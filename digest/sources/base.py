"""Data-source interface shared by the offline fixture and online adapters.

A source answers three questions: "what did this ticker do each day?",
"which scheduled events are coming up?" and, optionally, "what did tracked
voices say?". Everything else (rules, slices, caps, rendering) is
source-agnostic, so adding a provider means implementing these methods and
nothing more.
"""
from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

LINK_NA = "link n/a"


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
class CalendarEvent:
    """A dated event: ``kind`` is ``earnings`` or a free-form catalyst label."""

    ticker: str
    date: date
    kind: str = "earnings"
    note: str = ""


EarningsEvent = CalendarEvent  # backwards-compatible alias


@dataclass(frozen=True)
class Note:
    """Something a tracked voice (a handle / person) said about a ticker."""

    date: date
    voice: str
    ticker: str
    headline: str
    link: Optional[str] = None  # URL when known; ``None`` renders as the literal "link n/a"


class DataSource(ABC):
    """Interface every source implements. ``name`` is what citations show."""

    name: str = "base"
    #: Name cited for calendar-derived signals (may differ from price data).
    calendar_name: str = "base"
    #: Name cited for voice notes.
    notes_name: str = "base"

    @abstractmethod
    def daily_bars(self, ticker: str, end: date) -> List[Bar]:
        """Return daily bars up to and including ``end``, oldest first.

        Return an empty list (never raise) when the ticker is unavailable so
        one bad symbol cannot take down the whole digest.
        """

    @abstractmethod
    def earnings_calendar(self) -> List[CalendarEvent]:
        """Return known upcoming (and past) earnings dates and catalysts."""

    def notes(self) -> List[Note]:
        """Return tracked-voice notes; sources without opinions return nothing."""
        return []


def _data_lines(text: str) -> List[str]:
    """Drop blank lines and '#' comment lines (used for synthetic-data headers)."""
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def parse_bars_csv(text: str) -> List[Bar]:
    """Parse a ``Date,Open,High,Low,Close,Volume`` CSV; malformed rows are skipped."""
    bars: List[Bar] = []
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


def parse_earnings_csv(text: str) -> List[CalendarEvent]:
    """Parse a ``ticker,date[,kind,note]`` CSV (``kind`` defaults to ``earnings``)."""
    events: List[CalendarEvent] = []
    for row in csv.DictReader(_data_lines(text)):
        try:
            kind = (row.get("kind") or "earnings").strip().lower() or "earnings"
            events.append(CalendarEvent(row["ticker"].strip().upper(), date.fromisoformat(row["date"].strip()),
                                        kind, (row.get("note") or "").strip()))
        except (KeyError, AttributeError, ValueError):
            continue
    return events


def parse_notes_csv(text: str) -> List[Note]:
    """Parse a ``date,voice,ticker,headline,link`` CSV; an empty or ``link n/a`` link becomes ``None``."""
    notes: List[Note] = []
    for row in csv.DictReader(_data_lines(text)):
        try:
            link = (row.get("link") or "").strip()
            notes.append(Note(date.fromisoformat(row["date"].strip()), row["voice"].strip(),
                              row["ticker"].strip().upper(), row["headline"].strip(),
                              link if link and link != LINK_NA else None))
        except (KeyError, AttributeError, ValueError):
            continue
    notes.sort(key=lambda n: n.date)
    return notes
