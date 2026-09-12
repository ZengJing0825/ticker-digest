"""Offline source backed by the bundled synthetic CSVs under ``data/``."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .base import Bar, DataSource, EarningsEvent, parse_bars_csv, parse_earnings_csv


class FixtureSource(DataSource):
    name = "fixture"
    calendar_name = "fixture"

    def __init__(self, data_dir: Path | str = "data") -> None:
        self.data_dir = Path(data_dir)

    def daily_bars(self, ticker: str, end: date) -> list[Bar]:
        path = self.data_dir / "sample" / f"{ticker.upper()}.csv"
        if not path.exists():
            return []
        return [b for b in parse_bars_csv(path.read_text()) if b.date <= end]

    def earnings_calendar(self) -> list[EarningsEvent]:
        path = self.data_dir / "earnings_calendar.csv"
        return parse_earnings_csv(path.read_text()) if path.exists() else []
