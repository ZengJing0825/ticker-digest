"""Data-source interface shared by the offline fixture and online adapters.

A source answers two questions: "what did this ticker do each day?" and
"which scheduled events are coming up?". Everything else (rules, caps,
rendering) is source-agnostic, so adding a provider means implementing
these two methods and nothing more.
"""
from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Bar:
    """One daily OHLCV bar."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class EarningsEvent:
    ticker: str
    date: date


class DataSource(ABC):
    """Interface every source implements. ``name`` is what citations show."""

    name: str = "base"
    #: Name cited for calendar-derived signals (may differ from price data).
    calendar_name: str = "base"

    @abstractmethod
    def daily_bars(self, ticker: str, end: date) -> list[Bar]:
        """Return daily bars up to and including ``end``, oldest first.

        Return an empty list (never raise) when the ticker is unavailable so
        one bad symbol cannot take down the whole digest.
        """

    @abstractmethod
    def earnings_calendar(self) -> list[EarningsEvent]:
        """Return known upcoming (and past) earnings dates."""


def _data_lines(text: str) -> list[str]:
    """Drop blank lines and '#' comment lines (used for synthetic-data headers)."""
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def parse_bars_csv(text: str) -> list[Bar]:
    """Parse a ``Date,Open,High,Low,Close,Volume`` CSV; malformed rows are skipped."""
    bars: list[Bar] = []
    for row in csv.DictReader(_data_lines(text)):
        try:
            bars.append(
                Bar(
                    date.fromisoformat(row["Date"]),
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    float(row.get("Volume") or 0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b.date)
    return bars


def parse_earnings_csv(text: str) -> list[EarningsEvent]:
    """Parse a ``ticker,date`` CSV."""
    events: list[EarningsEvent] = []
    for row in csv.DictReader(_data_lines(text)):
        try:
            events.append(EarningsEvent(row["ticker"].strip().upper(), date.fromisoformat(row["date"].strip())))
        except (KeyError, AttributeError, ValueError):
            continue
    return events
