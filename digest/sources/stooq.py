"""Online source: free daily CSVs from stooq.com (no API key required).

Stooq has no earnings endpoint, so calendar events still come from the
local ``data/earnings_calendar.csv`` (cited as ``local-calendar``) and voice
notes from ``data/voices.csv`` next to it (cited as ``local-notes``).
Every network failure degrades to "no data for this ticker" rather than an
exception, so a flaky connection yields a smaller digest, not a crash.

Stooq sometimes answers scripted clients with a JavaScript browser-verification
page instead of the CSV. The adapter identifies itself honestly, detects that
page and reports it; it deliberately does not try to get around the check.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import List, Optional

import requests

from .base import Bar, CalendarEvent, DataSource, Note, parse_bars_csv, parse_earnings_csv, parse_notes_csv

log = logging.getLogger(__name__)

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
USER_AGENT = "ticker-digest/0.1 (open-source watchlist digest; daily CSV fetch)"


def stooq_symbol(ticker: str) -> str:
    """Map a watchlist ticker to stooq's symbol convention."""
    t = ticker.lower()
    if t.endswith("-usd"):  # crypto pairs such as BTC-USD -> btcusd
        return t[:-4] + "usd"
    return t + ".us"


class StooqSource(DataSource):
    name = "stooq"
    calendar_name = "local-calendar"
    notes_name = "local-notes"

    def __init__(self, calendar_path: "Path | str" = "data/earnings_calendar.csv",
                 timeout: float = 10.0, session: Optional[requests.Session] = None) -> None:
        self.calendar_path = Path(calendar_path)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)

    def daily_bars(self, ticker: str, end: date) -> List[Bar]:
        url = STOOQ_URL.format(symbol=stooq_symbol(ticker))
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("stooq: %s unavailable (%s)", ticker, exc)
            return []
        text = resp.text.strip()
        if "verify your browser" in text.lower():
            log.warning("stooq: %s blocked by a browser-verification page; endpoint not usable from scripts right now", ticker)
            return []
        if not text.startswith("Date,"):
            # Stooq answers unknown symbols and rate limits with an HTML/notice body.
            log.warning("stooq: unexpected payload for %s (unknown symbol or rate limited)", ticker)
            return []
        return [b for b in parse_bars_csv(text) if b.date <= end]

    def earnings_calendar(self) -> List[CalendarEvent]:
        if not self.calendar_path.exists():
            return []
        return parse_earnings_csv(self.calendar_path.read_text())

    def notes(self) -> List[Note]:
        path = self.calendar_path.with_name("voices.csv")
        return parse_notes_csv(path.read_text()) if path.exists() else []
