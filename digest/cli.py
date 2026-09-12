"""Command-line entry point: ``python -m digest {run,explain,reset-state}``."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from . import llm
from .config import load_config
from .policy import Decision, SentState, apply_policy, kept_signals
from .render import build_digest
from .signals import evaluate
from .sources import DataSource, FixtureSource, StooqSource


def build_source(name: str, data_dir: Path) -> DataSource:
    if name == "fixture":
        return FixtureSource(data_dir)
    if name == "stooq":
        return StooqSource(data_dir / "earnings_calendar.csv")
    raise SystemExit(f"unknown source: {name}")


def _decide(args: argparse.Namespace) -> tuple[list[Decision], SentState, date]:
    cfg = load_config(args.config)
    as_of = date.fromisoformat(args.date) if args.date else date.today()
    source = build_source(args.source, Path(args.data))
    state = SentState(args.state).load()
    signals = evaluate(cfg, source, as_of)
    return apply_policy(signals, state, cfg.policy, as_of), state, as_of


def cmd_run(args: argparse.Namespace) -> int:
    decisions, state, as_of = _decide(args)
    kept = kept_signals(decisions)
    if not kept:
        print(f"No new events for {as_of}; no digest written.")
        return 0
    use_llm = llm.available() and not args.no_llm
    text = build_digest(kept, as_of, use_llm=use_llm)
    out = Path(args.out) / f"digest-{as_of.isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 2
    while out.exists():  # a second run on the same day gets its own file
        out = out.with_name(f"digest-{as_of.isoformat()}-{n}.md")
        n += 1
    out.write_text(text)
    state.record(kept, as_of)
    state.save(keep_days=load_config(args.config).policy.dedupe_days, today=as_of)
    print(text)
    print(f"[written {out}; mode={'llm' if use_llm else 'template'}]", file=sys.stderr)
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    decisions, _, as_of = _decide(args)
    fired = sum(1 for d in decisions if d.signal.fired)
    kept = sum(1 for d in decisions if d.kept)
    print(f"Candidates for {as_of} (source: {args.source}): {len(decisions)} evaluated, {fired} fired, {kept} kept\n")
    print(f"{'TICKER':<8} {'RULE':<14} {'FIRED':<6} {'DECISION':<44} WHY")
    for d in sorted(decisions, key=lambda d: (not d.kept, not d.signal.fired, d.signal.ticker, d.signal.rule)):
        print(f"{d.signal.ticker:<8} {d.signal.rule:<14} {'yes' if d.signal.fired else 'no':<6} "
              f"{d.reason:<44} {d.signal.why}")
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
    parser = argparse.ArgumentParser(prog="digest", description="Event-driven watchlist digest.")
    parser.add_argument("--config", default="watchlist.yaml")
    parser.add_argument("--state", default="state/sent.json")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("run", cmd_run), ("explain", cmd_explain)):
        p = sub.add_parser(name)
        p.add_argument("--date", help="YYYY-MM-DD (default: today)")
        p.add_argument("--source", choices=["fixture", "stooq"], default="fixture")
        p.add_argument("--data", default="data", help="directory with sample CSVs and earnings calendar")
        p.set_defaults(fn=fn)
    run = sub.choices["run"]
    run.add_argument("--out", default="out")
    run.add_argument("--no-llm", action="store_true", help="force template mode even if ANTHROPIC_API_KEY is set")
    sub.add_parser("reset-state").set_defaults(fn=cmd_reset_state)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    return args.fn(args)
