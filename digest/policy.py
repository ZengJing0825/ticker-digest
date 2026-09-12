"""Frequency caps and escalation-aware de-duplication.

Order of gates: threshold -> dedupe (identity + same-topic burst guard, both
with an escalation exception) -> per-group daily budget -> per-digest group
cap. Every candidate gets a ``Decision`` with a reason, so ``explain`` and
the audit file can show exactly why something was (not) delivered.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from .config import PolicyLimits
from .signals import Signal
from .slices import SliceContext, build_groups, group_keys


@dataclass(frozen=True)
class Decision:
    signal: Signal
    kept: bool
    reason: str


@dataclass(frozen=True)
class Entry:
    """One delivered fingerprint: when, how bad, and which group it was billed to."""

    at: datetime
    severity: float
    group: str

    def to_json(self) -> dict:
        return {"at": self.at.isoformat(timespec="minutes"), "severity": round(self.severity, 4), "group": self.group}

    @classmethod
    def from_json(cls, raw: Union[str, dict], fingerprint: str) -> "Entry":
        if isinstance(raw, str):  # legacy format: fingerprint -> YYYY-MM-DD
            return cls(datetime.combine(date.fromisoformat(raw), time.min), 0.0, fingerprint.split(":", 1)[0])
        return cls(datetime.fromisoformat(raw["at"]), float(raw.get("severity", 0.0)),
                   str(raw.get("group") or fingerprint.split(":", 1)[0]))


class SentState:
    """Persisted map of slice -> fingerprint -> ``Entry`` (``state/sent.json``).

    Each slice (ticker / person / book) is its own namespace: the three
    digests are separate deliveries, so a note delivered in the opinion
    digest is not "already sent" for the watchlist digest.
    """

    def __init__(self, path: "Path | str" = "state/sent.json", slice_kind: str = "ticker") -> None:
        self.path = Path(path)
        self.slice_kind = slice_kind
        self.data: Dict[str, Dict[str, Entry]] = {}

    # -- persistence -----------------------------------------------------
    def load(self) -> "SentState":
        if self.path.exists():
            raw = json.loads(self.path.read_text() or "{}")
            if raw and all(isinstance(v, str) for v in raw.values()):  # legacy flat file
                raw = {"ticker": raw}
            self.data = {k: {fp: Entry.from_json(e, fp) for fp, e in v.items()} for k, v in raw.items()}
        return self

    def save(self, keep_days: Optional[int] = None, today: Optional[date] = None) -> None:
        if keep_days is not None and today is not None:
            cutoff = datetime.combine(today - timedelta(days=keep_days), time.min)
            self.data = {k: {fp: e for fp, e in v.items() if e.at >= cutoff} for k, v in self.data.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: {fp: e.to_json() for fp, e in sorted(v.items())} for k, v in sorted(self.data.items())}
        self.path.write_text(json.dumps(payload, indent=2) + "\n")

    # -- queries ---------------------------------------------------------
    @property
    def sent(self) -> Dict[str, Entry]:
        return self.data.setdefault(self.slice_kind, {})

    def last_sent(self, fingerprint: str) -> Optional[Entry]:
        return self.sent.get(fingerprint)

    def last_topic(self, topic: str) -> Optional[Entry]:
        hits = [e for fp, e in self.sent.items() if ":".join(fp.split(":")[:2]) == topic]
        return max(hits, key=lambda e: e.at) if hits else None

    def sent_today(self, group: str, today: date) -> int:
        return sum(1 for e in self.sent.values() if e.at.date() == today and e.group == group)

    def record(self, signals: Iterable[Signal], now: Union[date, datetime], kind: Optional[str] = None,
               ctx: Optional[SliceContext] = None) -> None:
        if not isinstance(now, datetime):
            now = datetime.combine(now, time.min)
        kind = kind or self.slice_kind
        for s in signals:
            keys = group_keys(s, kind, ctx or SliceContext()) or [s.subject]
            self.sent[s.fingerprint] = Entry(now, s.severity, keys[0])


def _escalation(signal: Signal, prev: Entry, now: datetime, limits: PolicyLimits) -> "tuple[bool, str]":
    """Re-push only if the topic worsened by >= escalation_pp AND >= min_interval passed."""
    worsened = signal.severity - prev.severity
    elapsed = now - prev.at
    minutes = elapsed.total_seconds() / 60.0
    when = prev.at.isoformat(timespec="minutes")
    if worsened < limits.escalation_pp:
        return False, f"worsened {worsened:+.1f} < {limits.escalation_pp:.1f}pp since {when}"
    if minutes < limits.min_interval_minutes:
        return False, f"worsened {worsened:+.1f}pp but only {minutes:.0f} min since {when} < {limits.min_interval_minutes} min"
    return True, f"escalation: worsened {worsened:+.1f}pp >= {limits.escalation_pp:.1f}pp, {minutes:.0f} min since {when}"


def apply_policy(signals: List[Signal], state: SentState, limits: PolicyLimits, today: date,
                 now: Optional[datetime] = None, kind: str = "ticker",
                 ctx: Optional[SliceContext] = None) -> List[Decision]:
    now = now or datetime.combine(today, time.min)
    ctx = ctx or SliceContext()
    decisions: List[Decision] = []
    live: Dict[str, List[Signal]] = defaultdict(list)
    gate_reason: Dict[str, str] = {}  # fingerprint -> "kept" or the escalation note

    for s in signals:
        if not s.fired:
            decisions.append(Decision(s, False, "threshold not met"))
            continue
        keys = group_keys(s, kind, ctx)
        if not keys:
            decisions.append(Decision(s, False, f"not part of the {kind} slice"))
            continue
        prev = state.last_sent(s.fingerprint)
        if prev is not None and (now - prev.at) < timedelta(days=limits.dedupe_days):
            # Identity dedupe: same fingerprint inside dedupe_days, unless it escalated.
            ok, why = _escalation(s, prev, now, limits)
            if not ok:
                decisions.append(Decision(s, False, f"dedupe: identical signal delivered {prev.at.date()}; {why}"))
                continue
            gate_reason[s.fingerprint] = why
        else:
            # Same-topic burst guard: the topic (subject:rule) was pushed inside the window with another detail.
            topic = state.last_topic(s.topic)
            if topic is not None and (now - topic.at) < timedelta(hours=limits.escalation_window_hours):
                ok, why = _escalation(s, topic, now, limits)
                if not ok:
                    decisions.append(Decision(s, False, f"dedupe: same topic pushed within "
                                                        f"{limits.escalation_window_hours:g}h; {why}"))
                    continue
                gate_reason[s.fingerprint] = why
            else:
                gate_reason[s.fingerprint] = "kept"
        for key in keys:
            live[key].append(s)

    # Per-group daily budget: highest priority first, counting earlier runs today.
    ranked: Dict[str, List[Signal]] = {}
    cut: Dict[str, str] = {}
    for key, sigs in live.items():
        budget = max(0, limits.max_signals_per_ticker - state.sent_today(key, today))
        sigs.sort(key=lambda s: (-s.priority, s.rule))
        ranked[key] = sigs[:budget]
        for s in sigs[budget:]:
            cut.setdefault(s.fingerprint, f"cap: max {limits.max_signals_per_ticker} signals per {kind} per day")

    # Per-digest group cap: rank groups with the slice's own ranking (position-aware for books).
    groups = build_groups((s for sigs in ranked.values() for s in sigs), kind, ctx)
    allowed = [g.key for g in groups[:limits.max_tickers_per_digest]]
    for g in groups[limits.max_tickers_per_digest:]:
        for s in g.signals:
            cut.setdefault(s.fingerprint, f"cap: max {limits.max_tickers_per_digest} {kind}s per digest")

    # Emit in delivery order (group rank, then line rank), each fingerprint once.
    seen = set()
    for g in groups:
        if g.key not in allowed:
            continue
        for s in g.signals:
            if s.fingerprint not in seen:
                seen.add(s.fingerprint)
                decisions.append(Decision(s, True, gate_reason[s.fingerprint]))
    for sigs in live.values():
        for s in sigs:
            if s.fingerprint not in seen:
                seen.add(s.fingerprint)
                decisions.append(Decision(s, False, cut[s.fingerprint]))
    return decisions


def kept_signals(decisions: List[Decision]) -> List[Signal]:
    """Delivered signals, in the group-rank order produced by ``apply_policy``."""
    return [d.signal for d in decisions if d.kept]


def summarize_reasons(decisions: List[Decision]) -> Dict[str, int]:
    """Counts by decision family (kept / threshold / dedupe / cap / not in slice), for the audit."""
    out: Dict[str, int] = defaultdict(int)
    for d in decisions:
        if d.kept:
            out["kept"] += 1
        else:
            out[d.reason.split(":")[0].split(" ")[0]] += 1
    return dict(out)
