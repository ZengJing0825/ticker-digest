"""Command-line entry point: ``python -m digest {run,explain,propose,publish,reset-state}``."""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import List, Optional

from . import audit, llm
from .config import Config, load_config
from .markets import is_calendar_only
from .policy import Decision, SentState, apply_policy, kept_signals
from .proposals import approved_fingerprints, proposal_path, write_proposal
from .render import build_digest
from .signals import Signal, evaluate, move_by_subject, weight_by_book
from .slices import SLICES, SliceContext, build_groups
from .sources import DataSource, FixtureSource, StooqSource


def build_source(name: str, data_dir: Path) -> DataSource:
    if name == "fixture":
        return FixtureSource(data_dir)
    if name == "stooq":
        return StooqSource(data_dir / "earnings_calendar.csv")
    raise SystemExit(f"unknown source: {name}")


def parse_when(date_arg: Optional[str], now_arg: Optional[str]) -> "tuple[date, datetime]":
    """``--date`` is the run date; ``--now`` (YYYY-MM-DDTHH:MM) pins the wall clock for dedupe intervals."""
    if now_arg:
        now = datetime.fromisoformat(now_arg)
        return (date.fromisoformat(date_arg) if date_arg else now.date()), now
    if date_arg:
        as_of = date.fromisoformat(date_arg)
        return as_of, datetime.combine(as_of, datetime.now().time().replace(microsecond=0))
    now = datetime.now().replace(microsecond=0)
    return now.date(), now


def make_context(cfg: Config, candidates: List[Signal], source: DataSource, kind: str) -> SliceContext:
    ctx = SliceContext(books=cfg.books(), moves=move_by_subject(candidates), weights=weight_by_book(candidates),
                       calendar_only=[t for t in cfg.tickers if is_calendar_only(t, cfg.markets)])
    if kind == "ticker":
        ctx.universe = list(cfg.tickers)
    elif kind == "book":
        ctx.universe = [t for held in ctx.books.values() for t in held]
    else:
        seen: List[str] = []
        for n in source.notes():
            if n.voice not in seen and n.ticker in cfg.tickers:
                seen.append(n.voice)
        ctx.universe = seen
    return ctx


@dataclass
class Run:
    args: argparse.Namespace
    cfg: Config
    as_of: date
    now: datetime
    source: DataSource
    state: SentState
    candidates: List[Signal]
    ctx: SliceContext
    decisions: List[Decision]

    @property
    def kind(self) -> str:
        return self.args.slice

    def stale_days(self, delivered: List[Signal]) -> Optional[int]:
        """Age of the positions snapshot when a slice with positions uses it and it is too old."""
        updated = self.cfg.positions_updated_at
        if updated is None:
            return None
        uses_positions = self.kind == "book" or any(s.book for s in delivered)
        age = (self.as_of - updated).days
        return age if uses_positions and age > self.cfg.policy.positions_stale_days else None

    def digest(self, delivered: List[Signal]) -> str:
        groups = build_groups(delivered, self.kind, self.ctx)
        use_llm = llm.available() and not getattr(self.args, "no_llm", False)
        return build_digest(groups, self.as_of, self.kind, self.ctx, use_llm=use_llm,
                            max_lines=self.cfg.policy.max_lines_per_digest, stale_days=self.stale_days(delivered))

    def write_output(self, text: str) -> Path:
        stem = f"digest-{self.as_of.isoformat()}" + ("" if self.kind == "ticker" else f"-{self.kind}")
        out = Path(self.args.out) / f"{stem}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        n = 2
        while out.exists():  # a second run on the same day gets its own file
            out = out.with_name(f"{stem}-{n}.md")
            n += 1
        out.write_text(text)
        return out

    def deliver(self, delivered: List[Signal], text: str) -> Path:
        out = self.write_output(text)
        self.state.record(delivered, self.now, self.kind, self.ctx)
        self.state.save(keep_days=self.cfg.policy.dedupe_days, today=self.as_of)
        return out

    def audit(self, command: str, delivered: List[Signal], output: Optional[Path], dry: bool,
              approved: Optional[int] = None, **extra) -> Path:
        record = audit.build_record(command=command, kind=self.kind, source=self.args.source, as_of=self.as_of,
                                    now=self.now, cfg=self.cfg, decisions=self.decisions,
                                    delivered_fps=[s.fingerprint for s in delivered],
                                    output=str(output) if output else None, dry=dry, approved=approved, extra=extra)
        return audit.write(self.args.audit, self.as_of, record)


def prepare(args: argparse.Namespace) -> Run:
    cfg = load_config(args.config)
    as_of, now = parse_when(args.date, args.now)
    source = build_source(args.source, Path(args.data))
    state = SentState(args.state, args.slice).load()
    candidates = evaluate(cfg, source, as_of)
    ctx = make_context(cfg, candidates, source, args.slice)
    decisions = apply_policy(candidates, state, cfg.policy, as_of, now, args.slice, ctx)
    return Run(args, cfg, as_of, now, source, state, candidates, ctx, decisions)


def cmd_run(args: argparse.Namespace) -> int:
    run = prepare(args)
    kept = kept_signals(run.decisions)
    if not kept:
        print(f"No new events for {run.as_of} ({args.slice} slice); no digest written.")
        run.audit("run", [], None, dry=False)
        return 0
    text = run.digest(kept)
    out = run.deliver(kept, text)
    run.audit("run", kept, out, dry=False)
    print(text)
    mode = "llm" if llm.available() and not args.no_llm else "template"
    print(f"[written {out}; mode={mode}]", file=sys.stderr)
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    run = prepare(args)
    decisions = run.decisions
    fired = sum(1 for d in decisions if d.signal.fired)
    kept = sum(1 for d in decisions if d.kept)
    print(f"Candidates for {run.as_of} (source: {args.source}, slice: {args.slice}): "
          f"{len(decisions)} evaluated, {fired} fired, {kept} kept\n")
    print(f"{'SUBJECT':<9} {'RULE':<15} {'VOICE/BOOK':<18} {'FIRED':<6} WHY  ->  DECISION")
    for d in sorted(decisions, key=lambda d: (not d.kept, not d.signal.fired, d.signal.subject, d.signal.rule)):
        s = d.signal
        axis = s.voice or s.book or "-"
        print(f"{s.subject:<9} {s.rule:<15} {axis:<18} {'yes' if s.fired else 'no':<6} {s.why}  ->  {d.reason}")
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    run = prepare(args)
    path = write_proposal(args.out, run.as_of, run.decisions, args.slice)
    fired = sum(1 for d in run.decisions if d.signal.fired)
    run.audit("propose", [], None, dry=True, proposal=str(path))
    print(f"proposal written to {path}: {fired} candidate(s) to review")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    run = prepare(args)
    dry = not args.send
    approved_n: Optional[int] = None
    if args.approved:
        path = proposal_path(args.out, run.as_of)
        if not path.exists():
            print(f"no proposal file at {path}; run `propose` first", file=sys.stderr)
            return 2
        approved = approved_fingerprints(path.read_text())
        chosen = [s for s in run.candidates if s.fired and s.fingerprint in approved]
        approved_n = len(chosen)
        by_fp = {s.fingerprint: s for s in chosen}
        run.decisions = [Decision(d.signal, d.signal.fingerprint in by_fp,
                                  "approved" if d.signal.fingerprint in by_fp else
                                  ("not approved in proposal" if d.signal.fired else d.reason))
                         for d in run.decisions]
        chosen = [d.signal for d in run.decisions if d.kept]
    else:
        chosen = kept_signals(run.decisions)
    if not chosen:
        why = "nothing approved" if args.approved else "nothing kept by policy"
        print(f"No items to publish for {run.as_of} ({args.slice} slice): {why}.")
        run.audit("publish", [], None, dry=dry, approved=approved_n)
        return 0
    text = run.digest(chosen)
    if dry:
        print(text)
        print(f"[dry-run: {len(chosen)} item(s) rendered, nothing written, state untouched; pass --send to deliver]",
              file=sys.stderr)
        run.audit("publish", [], None, dry=True, approved=approved_n, rendered=[s.fingerprint for s in chosen])
        return 0
    out = run.deliver(chosen, text)
    run.audit("publish", chosen, out, dry=False, approved=approved_n)
    print(text)
    print(f"[published {out}]", file=sys.stderr)
    return 0


def cmd_reset_state(args: argparse.Namespace) -> int:
    path = Path(args.state)
    if path.exists():
        path.unlink()
        print(f"removed {path}")
    else:
        print(f"nothing to reset at {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="digest", description="Event-driven watchlist / opinion / portfolio digest.")
    parser.add_argument("--config", default="watchlist.yaml")
    parser.add_argument("--state", default="state/sent.json")
    parser.add_argument("--audit", default="state/audit", help="directory for per-date audit records")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("run", cmd_run), ("explain", cmd_explain), ("propose", cmd_propose), ("publish", cmd_publish)):
        p = sub.add_parser(name)
        p.add_argument("--date", help="YYYY-MM-DD (default: today)")
        p.add_argument("--now", help="YYYY-MM-DDTHH:MM wall clock for dedupe intervals (default: now)")
        p.add_argument("--slice", choices=list(SLICES), default="ticker",
                       help="ticker = watchlist digest, person = opinion digest, book = portfolio digest")
        p.add_argument("--source", choices=["fixture", "stooq"], default="fixture")
        p.add_argument("--data", default="data", help="directory with sample CSVs, calendar and voices")
        p.add_argument("--out", default="out")
        p.set_defaults(fn=fn)
    for name in ("run", "publish"):
        sub.choices[name].add_argument("--no-llm", action="store_true",
                                       help="force template mode even if ANTHROPIC_API_KEY is set")
    publish = sub.choices["publish"]
    publish.add_argument("--approved", action="store_true", help="send only items ticked in out/proposals/<date>.md")
    mode = publish.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", default=True, help="render only (default)")
    mode.add_argument("--send", action="store_true", help="actually deliver: write the digest and record state")
    sub.add_parser("reset-state").set_defaults(fn=cmd_reset_state)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    return args.fn(args)
