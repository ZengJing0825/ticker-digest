"""Small builders shared by the test modules."""
from __future__ import annotations

from datetime import date, timedelta

from digest.config import Config, PolicyLimits, Position, Thresholds
from digest.signals import Signal
from digest.sources.base import Bar, DataSource, EarningsEvent

AS_OF = date(2026, 9, 12)


def bars(closes: list[float], volumes: list[float] | None = None, end: date = AS_OF) -> list[Bar]:
    """Build consecutive calendar-day bars ending on ``end`` from a list of closes."""
    volumes = volumes or [1_000_000.0] * len(closes)
    start = end - timedelta(days=len(closes) - 1)
    return [Bar(start + timedelta(days=i), c, c, c, c, v) for i, (c, v) in enumerate(zip(closes, volumes))]


def signal(ticker: str, rule: str, priority: int = 1, fired: bool = True, fingerprint: str | None = None) -> Signal:
    return Signal(ticker, rule, fired, "why", f"{ticker} {rule}", "test", AS_OF, priority,
                  fingerprint or f"{ticker}:{rule}")


class MemorySource(DataSource):
    name = "memsource"
    calendar_name = "memcal"

    def __init__(self, series: dict[str, list[Bar]], events: list[EarningsEvent] | None = None) -> None:
        self.series, self.events = series, events or []

    def daily_bars(self, ticker: str, end: date) -> list[Bar]:
        return [b for b in self.series.get(ticker, []) if b.date <= end]

    def earnings_calendar(self) -> list[EarningsEvent]:
        return self.events


def config(tickers: list[str], positions: dict[str, Position] | None = None, **limits) -> Config:
    return Config(tickers=tickers, positions=positions or {}, thresholds=Thresholds(), policy=PolicyLimits(**limits))
