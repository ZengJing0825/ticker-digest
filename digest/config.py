"""Load ``watchlist.yaml`` into typed config objects with sane defaults."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

DEFAULT_BOOK = "default"
TIERS = ("realtime", "calendar")


@dataclass(frozen=True)
class Position:
    qty: float
    avg_cost: float
    book: str = DEFAULT_BOOK  # portfolio id this position belongs to


@dataclass(frozen=True)
class Thresholds:
    move_pct: float = 5.0            # absolute fallback for the daily move when history is short
    move_k: float = 2.0              # relative trigger: |move| >= move_k x typical 30-day move
    typical_window: int = 30         # sessions defining "typical" daily move
    volume_multiple: float = 2.0     # volume vs trailing average
    volume_window: int = 20          # sessions in the volume average
    week52_window: int = 252         # sessions defining the "52-week" range
    earnings_days: int = 7           # look-ahead for scheduled earnings / catalysts
    pnl_pct: float = 20.0            # unrealized P&L crossing (+/-)
    concentration_pct: float = 40.0  # single position share of its book
    note_days: int = 2               # a voice note counts while it is at most this many days old
    reason_days: int = 2             # a calendar event within +/- N days explains a move


@dataclass(frozen=True)
class PolicyLimits:
    max_signals_per_ticker: int = 2   # per subject (ticker / voice / book) per day, earlier runs count
    max_tickers_per_digest: int = 3   # groups per digest
    max_lines_per_digest: int = 8     # rendered name-major lines; the rest is "+N more quiet"
    dedupe_days: int = 7              # identical fingerprint is not repeated inside this window
    escalation_pp: float = 1.5        # ... unless severity worsened by at least this many points
    min_interval_minutes: int = 55    # ... and at least this long passed since the last push
    escalation_window_hours: float = 1.0  # same-topic burst guard: applies to any push inside this window
    positions_stale_days: int = 14    # older positions snapshot -> footer reminder


@dataclass(frozen=True)
class Config:
    tickers: List[str]
    positions: Dict[str, Position] = field(default_factory=dict)
    positions_updated_at: Optional[date] = None
    thresholds: Thresholds = Thresholds()
    policy: PolicyLimits = PolicyLimits()
    markets: Dict[str, str] = field(default_factory=dict)       # market -> "realtime" | "calendar"
    sectors: Dict[str, List[str]] = field(default_factory=dict)  # sector -> tickers (proxy attribution)

    def books(self) -> Dict[str, List[str]]:
        """Portfolio id -> tickers held in it (insertion order)."""
        out: Dict[str, List[str]] = {}
        for t, p in self.positions.items():
            out.setdefault(p.book, []).append(t)
        return out


class ConfigError(ValueError):
    pass


def _build(cls: type, raw: Optional[Dict[str, Any]], section: str):
    raw = raw or {}
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{section}: unknown key(s) {sorted(unknown)}; expected {sorted(known)}")
    return cls(**raw)


def _parse_positions(raw: Any) -> "tuple[Dict[str, Position], Optional[date]]":
    """``positions`` is a ticker -> {qty, avg_cost[, book]} map plus an optional ``updated_at``."""
    raw = dict(raw or {})
    updated_at = raw.pop("updated_at", None)
    if updated_at is not None:
        if isinstance(updated_at, date):
            updated = updated_at
        else:
            try:
                updated = date.fromisoformat(str(updated_at))
            except ValueError:
                raise ConfigError(f"positions.updated_at: expected YYYY-MM-DD, got {updated_at!r}")
    else:
        updated = None
    positions = {str(t).upper(): _build(Position, p, f"positions.{t}") for t, p in raw.items()}
    return positions, updated


def _parse_markets(raw: Any) -> Dict[str, str]:
    markets: Dict[str, str] = {}
    for market, tier in (raw or {}).items():
        if tier not in TIERS:
            raise ConfigError(f"markets.{market}: tier must be one of {list(TIERS)}, got {tier!r}")
        markets[str(market).upper()] = tier
    return markets


def load_config(path: "Path | str" = "watchlist.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    known = {"tickers", "positions", "thresholds", "policy", "markets", "sectors"}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"unknown top-level key(s) {sorted(unknown)}; expected {sorted(known)}")
    tickers = [str(t).upper() for t in raw.get("tickers") or []]
    if not tickers:
        raise ConfigError("watchlist.yaml must list at least one ticker")
    positions, updated_at = _parse_positions(raw.get("positions"))
    unknown_pos = set(positions) - set(tickers)
    if unknown_pos:
        raise ConfigError(f"positions for tickers not on the watchlist: {sorted(unknown_pos)}")
    sectors = {str(k): [str(t).upper() for t in v or []] for k, v in (raw.get("sectors") or {}).items()}
    return Config(
        tickers=tickers,
        positions=positions,
        positions_updated_at=updated_at,
        thresholds=_build(Thresholds, raw.get("thresholds"), "thresholds"),
        policy=_build(PolicyLimits, raw.get("policy"), "policy"),
        markets=_parse_markets(raw.get("markets")),
        sectors=sectors,
    )
