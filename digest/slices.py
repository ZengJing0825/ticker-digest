"""Slices: turn ONE candidate set into a watchlist, opinion or portfolio digest.

* ``ticker``  - group by subject: the watchlist digest.
* ``person``  - group by voice: the opinion digest (signals without a voice are dropped).
* ``book``    - group by portfolio: the portfolio digest (position signals carry their
                book; price/calendar signals join every book that holds the ticker).

Ranking inside a group is position-aware when the slice has positions: risk
lines (P&L crossing, concentration) come first, then ``weight x |move|``.
Without positions, subjects are ranked by event priority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .signals import RISK_RULES, Signal, with_book

SLICES = ("ticker", "person", "book")
TITLES = {"ticker": "Watchlist digest", "person": "Opinion digest", "book": "Portfolio digest"}
UNITS = {"ticker": "ticker", "person": "voice", "book": "ticker"}


@dataclass
class SliceContext:
    """Everything grouping/ranking needs beyond the signals themselves."""

    books: Dict[str, List[str]] = field(default_factory=dict)         # book -> held tickers
    moves: Dict[str, float] = field(default_factory=dict)             # ticker -> latest move (%)
    weights: Dict[str, Dict[str, float]] = field(default_factory=dict)  # book -> ticker -> share (0..1)
    calendar_only: List[str] = field(default_factory=list)            # tickers on calendar-tier markets
    universe: List[str] = field(default_factory=list)                 # all subjects the slice covers


@dataclass
class Line:
    subject: str
    signals: List[Signal]
    score: Tuple[float, ...]


@dataclass
class Group:
    key: str
    lines: List[Line]

    @property
    def signals(self) -> List[Signal]:
        return [s for line in self.lines for s in line.signals]

    @property
    def score(self) -> Tuple[float, ...]:
        """Best line first, then the total weight of everything in the group."""
        if not self.lines:
            return (0.0,)
        total = float(sum(s.priority for line in self.lines for s in line.signals))
        return max(line.score for line in self.lines) + (total,)


def group_keys(signal: Signal, kind: str, ctx: SliceContext) -> List[str]:
    """Which group(s) a signal belongs to under a slice; empty means it is not part of that digest."""
    if kind == "ticker":
        return [signal.subject]
    if kind == "person":
        return [signal.voice] if signal.voice else []
    if kind == "book":
        if signal.book:
            return [signal.book]
        return [b for b, held in ctx.books.items() if signal.subject in held]
    raise ValueError(f"unknown slice: {kind}")


def slice_signals(signals: Iterable[Signal], kind: str, ctx: SliceContext) -> List[Tuple[str, Signal]]:
    """(group key, signal) pairs; book-slice signals are stamped with the book they join."""
    out: List[Tuple[str, Signal]] = []
    for s in signals:
        for key in group_keys(s, kind, ctx):
            out.append((key, with_book(s, key) if kind == "book" and not s.book else s))
    return out


def line_score(subject: str, sigs: List[Signal], kind: str, key: str, ctx: SliceContext) -> Tuple[float, ...]:
    """Position-aware when the slice has positions, else event priority (then name, via the caller)."""
    priority = float(sum(s.priority for s in sigs))
    if kind == "book":
        risk = 1.0 if any(s.rule in RISK_RULES for s in sigs) else 0.0
        weight = ctx.weights.get(key, {}).get(subject, 0.0)
        move = abs(ctx.moves.get(subject, 0.0))
        return (risk, weight * move, priority)
    return (priority,)


def build_groups(signals: Iterable[Signal], kind: str, ctx: Optional[SliceContext] = None) -> List[Group]:
    """Group and rank kept signals. Order: groups by best line, lines by score, ties by name."""
    ctx = ctx or SliceContext()
    buckets: Dict[str, Dict[str, List[Signal]]] = {}
    for key, s in slice_signals(signals, kind, ctx):
        buckets.setdefault(key, {}).setdefault(s.subject, []).append(s)
    groups: List[Group] = []
    for key, by_subject in buckets.items():
        lines = [Line(subject, sorted(sigs, key=lambda s: (-s.priority, s.rule)),
                      line_score(subject, sigs, kind, key, ctx)) for subject, sigs in by_subject.items()]
        lines.sort(key=lambda ln: (tuple(-x for x in ln.score), ln.subject))
        groups.append(Group(key, lines))
    groups.sort(key=lambda g: (tuple(-x for x in g.score), g.key))
    return groups


def quiet_subjects(groups: List[Group], ctx: SliceContext, kind: str) -> List[str]:
    """Members of the slice universe that got no line (the "+N more quiet" tail)."""
    shown = {line.subject for g in groups for line in g.lines} if kind != "person" else {g.key for g in groups}
    return [u for u in ctx.universe if u not in shown]
