"""Frequency caps and de-duplication.

Order of gates: threshold -> dedupe -> per-ticker daily budget -> per-digest
ticker cap. Every candidate gets a ``Decision`` with a reason, so the
``explain`` command can show exactly why something was (not) delivered.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .config import PolicyLimits
from .signals import Signal


@dataclass(frozen=True)
class Decision:
    signal: Signal
    kept: bool
    reason: str


class SentState:
    """Persisted map of fingerprint -> date last delivered (``state/sent.json``)."""

    def __init__(self, path: Path | str = "state/sent.json") -> None:
        self.path = Path(path)
        self.sent: dict[str, date] = {}

    def load(self) -> "SentState":
        if self.path.exists():
            raw = json.loads(self.path.read_text() or "{}")
            self.sent = {k: date.fromisoformat(v) for k, v in raw.items()}
        return self

    def save(self, keep_days: int | None = None, today: date | None = None) -> None:
        if keep_days is not None and today is not None:
            cutoff = today - timedelta(days=keep_days)
            self.sent = {k: v for k, v in self.sent.items() if v >= cutoff}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({k: v.isoformat() for k, v in sorted(self.sent.items())}, indent=2) + "\n")

    def last_sent(self, fingerprint: str) -> date | None:
        return self.sent.get(fingerprint)

    def sent_today(self, ticker: str, today: date) -> int:
        return sum(1 for fp, d in self.sent.items() if d == today and fp.split(":", 1)[0] == ticker)

    def record(self, signals: list[Signal], today: date) -> None:
        for s in signals:
            self.sent[s.fingerprint] = today


def apply_policy(signals: list[Signal], state: SentState, limits: PolicyLimits, today: date) -> list[Decision]:
    decisions: list[Decision] = []
    live: dict[str, list[Signal]] = defaultdict(list)

    for s in signals:
        if not s.fired:
            decisions.append(Decision(s, False, "threshold not met"))
            continue
        last = state.last_sent(s.fingerprint)
        if last is not None and (today - last).days < limits.dedupe_days:
            decisions.append(Decision(s, False, f"dedupe: identical signal delivered {last}"))
            continue
        live[s.ticker].append(s)

    # Per-ticker daily budget: highest priority first, counting earlier runs today.
    ranked: dict[str, list[Signal]] = {}
    for ticker, sigs in live.items():
        budget = max(0, limits.max_signals_per_ticker - state.sent_today(ticker, today))
        sigs.sort(key=lambda s: (-s.priority, s.rule))
        ranked[ticker] = sigs[:budget]
        for s in sigs[budget:]:
            decisions.append(Decision(s, False, f"cap: max {limits.max_signals_per_ticker} signals per ticker per day"))

    # Per-digest ticker cap: rank tickers by the weight of what survived.
    order = sorted((t for t in ranked if ranked[t]), key=lambda t: (-sum(s.priority for s in ranked[t]), t))
    for i, ticker in enumerate(order):
        for s in ranked[ticker]:
            if i < limits.max_tickers_per_digest:
                decisions.append(Decision(s, True, "kept"))
            else:
                decisions.append(Decision(s, False, f"cap: max {limits.max_tickers_per_digest} tickers per digest"))
    return decisions


def kept_signals(decisions: list[Decision]) -> list[Signal]:
    """Delivered signals, in the ticker-rank order produced by ``apply_policy``."""
    return [d.signal for d in decisions if d.kept]
