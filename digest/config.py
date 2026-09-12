"""Load ``watchlist.yaml`` into typed config objects with sane defaults."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Position:
    qty: float
    avg_cost: float


@dataclass(frozen=True)
class Thresholds:
    move_pct: float = 5.0            # abs daily close-to-close move
    volume_multiple: float = 2.0     # volume vs trailing average
    volume_window: int = 20          # sessions in the volume average
    week52_window: int = 252         # sessions defining the "52-week" range
    earnings_days: int = 7           # look-ahead for scheduled earnings
    pnl_pct: float = 20.0            # unrealized P&L crossing (+/-)
    concentration_pct: float = 40.0  # single position share of portfolio


@dataclass(frozen=True)
class PolicyLimits:
    max_signals_per_ticker: int = 2  # per ticker per day (counts earlier runs today)
    max_tickers_per_digest: int = 3
    dedupe_days: int = 7


@dataclass(frozen=True)
class Config:
    tickers: list[str]
    positions: dict[str, Position] = field(default_factory=dict)
    thresholds: Thresholds = Thresholds()
    policy: PolicyLimits = PolicyLimits()


class ConfigError(ValueError):
    pass


def _build(cls: type, raw: dict[str, Any] | None, section: str):
    raw = raw or {}
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{section}: unknown key(s) {sorted(unknown)}; expected {sorted(known)}")
    return cls(**raw)


def load_config(path: Path | str = "watchlist.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    tickers = [str(t).upper() for t in raw.get("tickers") or []]
    if not tickers:
        raise ConfigError("watchlist.yaml must list at least one ticker")
    positions = {
        str(t).upper(): _build(Position, p, f"positions.{t}") for t, p in (raw.get("positions") or {}).items()
    }
    unknown_pos = set(positions) - set(tickers)
    if unknown_pos:
        raise ConfigError(f"positions for tickers not on the watchlist: {sorted(unknown_pos)}")
    return Config(
        tickers=tickers,
        positions=positions,
        thresholds=_build(Thresholds, raw.get("thresholds"), "thresholds"),
        policy=_build(PolicyLimits, raw.get("policy"), "policy"),
    )
