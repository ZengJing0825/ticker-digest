"""Market tiers: which rules a ticker's market is allowed to run.

``realtime`` markets run every rule (price, volume, range, positions).
``calendar`` markets run only the earnings / catalyst calendar rules and their
lines carry a ``[calendar-only]`` badge. The split is a data-source *cost*
decision, not a capability limit: daily bars for US equities and crypto are
free, while licensed intraday/daily feeds for other exchanges are not. Move a
market to ``realtime`` in ``watchlist.yaml`` once a source for it exists.
"""
from __future__ import annotations

from typing import Dict

REALTIME, CALENDAR = "realtime", "calendar"

#: Suffix conventions used to infer a ticker's market. Anything else is US.
SUFFIXES = {
    ".HK": "HK",
    ".T": "JP",
    ".JP": "JP",
    ".KS": "KR",
    ".KQ": "KR",
    ".KR": "KR",
    "-USD": "CRYPTO",
}


def market_of(ticker: str) -> str:
    upper = ticker.upper()
    for suffix, market in SUFFIXES.items():
        if upper.endswith(suffix):
            return market
    return "US"


def tier_of(ticker: str, markets: Dict[str, str]) -> str:
    """Tier for a ticker; markets not listed in the config default to ``realtime``."""
    return markets.get(market_of(ticker), REALTIME)


def is_calendar_only(ticker: str, markets: Dict[str, str]) -> bool:
    return tier_of(ticker, markets) == CALENDAR
