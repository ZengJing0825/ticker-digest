"""Small builders shared by the test modules."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

from digest.config import Config, PolicyLimits, Position, Thresholds
from digest.signals import Signal
from digest.sources.base import Bar, CalendarEvent, DataSource, Note

AS_OF = date(2026, 9, 12)


def bars(closes: List[float], volumes: Optional[List[float]] = None, end: date = AS_OF) -> List[Bar]:
    """Build consecutive calendar-day bars ending on ``end`` from a list of closes."""
    volumes = volumes or [1_000_000.0] * len(closes)
    start = end - timedelta(days=len(closes) - 1)
    return [Bar(start + timedelta(days=i), c, c, c, c, v) for i, (c, v) in enumerate(zip(closes, volumes))]


def signal(ticker: str, rule: str, priority: int = 1, fired: bool = True, fingerprint: Optional[str] = None,
           **extra) -> Signal:
    return Signal(ticker, rule, fired, "why", f"{ticker} {rule}", "test", AS_OF, priority,
                  fingerprint or f"{ticker}:{rule}", **extra)


class MemorySource(DataSource):
    name = "memsource"
    calendar_name = "memcal"
    notes_name = "memnotes"

    def __init__(self, series: Dict[str, List[Bar]], events: Optional[List[CalendarEvent]] = None,
                 notes: Optional[List[Note]] = None) -> None:
        self.series, self.events, self._notes = series, events or [], notes or []

    def daily_bars(self, ticker: str, end: date) -> List[Bar]:
        return [b for b in self.series.get(ticker, []) if b.date <= end]

    def earnings_calendar(self) -> List[CalendarEvent]:
        return self.events

    def notes(self) -> List[Note]:
        return self._notes


def config(tickers: List[str], positions: Optional[Dict[str, Position]] = None, thresholds: Optional[Thresholds] = None,
           markets: Optional[Dict[str, str]] = None, sectors: Optional[Dict[str, List[str]]] = None,
           updated_at: Optional[date] = None, **limits) -> Config:
    return Config(tickers=tickers, positions=positions or {}, positions_updated_at=updated_at,
                 thresholds=thresholds or Thresholds(), policy=PolicyLimits(**limits),
                 markets=markets or {}, sectors=sectors or {})
