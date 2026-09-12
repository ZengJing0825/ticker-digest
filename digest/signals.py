"""Signal rules: each rule turns bars/positions into a ``Signal`` candidate.

Every rule always returns a candidate, fired or not, with a one-line ``why``
so ``explain`` can show threshold checks that did *not* trigger. Only fired
candidates reach the policy layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .config import Config, Position, Thresholds
from .sources.base import Bar, DataSource, EarningsEvent


@dataclass(frozen=True)
class Signal:
    ticker: str
    rule: str
    fired: bool
    why: str          # threshold check, e.g. "|+6.2%| >= 5.0%"
    headline: str     # digest text (without citation; the renderer adds it)
    source: str       # cited data source
    as_of: date       # cited data date
    priority: int     # higher wins when caps apply
    fingerprint: str  # identity for de-duplication


def _pct(now: float, base: float) -> float:
    return (now / base - 1.0) * 100.0


def rule_daily_move(ticker: str, bars: list[Bar], th: Thresholds, src: str) -> Signal:
    prev, last = bars[-2], bars[-1]
    pct = _pct(last.close, prev.close)
    fired = abs(pct) >= th.move_pct
    return Signal(
        ticker, "daily_move", fired,
        f"|{pct:+.1f}%| {'>=' if fired else '<'} {th.move_pct:.1f}%",
        f"Closed {pct:+.1f}% at {last.close:,.2f} (previous close {prev.close:,.2f})",
        src, last.date, 4, f"{ticker}:daily_move:{last.date}",
    )


def rule_volume_spike(ticker: str, bars: list[Bar], th: Thresholds, src: str) -> Signal:
    last = bars[-1]
    window = bars[-1 - th.volume_window:-1]
    if len(window) < th.volume_window:
        return Signal(ticker, "volume_spike", False, f"need {th.volume_window} prior sessions, have {len(window)}",
                      "", src, last.date, 2, f"{ticker}:volume_spike:{last.date}")
    avg = sum(b.volume for b in window) / len(window)
    ratio = last.volume / avg if avg else 0.0
    fired = ratio >= th.volume_multiple
    return Signal(
        ticker, "volume_spike", fired,
        f"{ratio:.1f}x {'>=' if fired else '<'} {th.volume_multiple:.1f}x {th.volume_window}-day average",
        f"Volume {last.volume:,.0f} was {ratio:.1f}x the {th.volume_window}-day average",
        src, last.date, 2, f"{ticker}:volume_spike:{last.date}",
    )


def rule_week52(ticker: str, bars: list[Bar], th: Thresholds, src: str) -> Signal:
    last = bars[-1]
    prior = [b.close for b in bars[-1 - th.week52_window:-1]]
    if len(prior) < 20:
        return Signal(ticker, "week52", False, f"insufficient history ({len(prior)} sessions)",
                      "", src, last.date, 3, f"{ticker}:week52")
    hi, lo = max(prior), min(prior)
    if last.close > hi:
        return Signal(ticker, "week52_high", True, f"close {last.close:,.2f} > prior high {hi:,.2f}",
                      f"New 52-week high: close {last.close:,.2f} vs prior high {hi:,.2f}",
                      src, last.date, 3, f"{ticker}:week52_high")
    if last.close < lo:
        return Signal(ticker, "week52_low", True, f"close {last.close:,.2f} < prior low {lo:,.2f}",
                      f"New 52-week low: close {last.close:,.2f} vs prior low {lo:,.2f}",
                      src, last.date, 3, f"{ticker}:week52_low")
    return Signal(ticker, "week52", False, f"close {last.close:,.2f} within [{lo:,.2f}, {hi:,.2f}]",
                  "", src, last.date, 3, f"{ticker}:week52")


def rule_earnings(ticker: str, events: list[EarningsEvent], as_of: date, th: Thresholds, src: str) -> Signal:
    upcoming = sorted(e.date for e in events if e.ticker == ticker and e.date >= as_of)
    if not upcoming:
        return Signal(ticker, "earnings_soon", False, "no upcoming earnings on calendar",
                      "", src, as_of, 3, f"{ticker}:earnings_soon:none")
    nxt = upcoming[0]
    days = (nxt - as_of).days
    fired = days <= th.earnings_days
    return Signal(
        ticker, "earnings_soon", fired,
        f"next earnings {nxt} in {days}d {'<=' if fired else '>'} {th.earnings_days}d",
        f"Earnings scheduled for {nxt} ({days} day{'s' if days != 1 else ''} away)",
        src, as_of, 3, f"{ticker}:earnings_soon:{nxt}",
    )


def rule_pnl_cross(ticker: str, bars: list[Bar], pos: Position, th: Thresholds, src: str) -> Signal:
    prev, last = bars[-2], bars[-1]
    before, now = _pct(prev.close, pos.avg_cost), _pct(last.close, pos.avg_cost)
    side = "+" if now >= th.pnl_pct > before else "-" if now <= -th.pnl_pct < before else ""
    return Signal(
        ticker, "pnl_cross", bool(side),
        f"P&L {before:+.1f}% -> {now:+.1f}% {'crossed' if side else 'did not cross'} +/-{th.pnl_pct:.0f}%",
        f"Unrealized P&L crossed {side}{th.pnl_pct:.0f}%: now {now:+.1f}% vs avg cost {pos.avg_cost:,.2f}",
        src, last.date, 5, f"{ticker}:pnl_cross:{side}{th.pnl_pct:.0f}",
    )


def rule_concentration(cfg: Config, bars_by_ticker: dict[str, list[Bar]], src: str) -> list[Signal]:
    values = {t: p.qty * bars_by_ticker[t][-1].close for t, p in cfg.positions.items() if bars_by_ticker.get(t)}
    total = sum(values.values())
    th = cfg.thresholds.concentration_pct
    out = []
    for t, value in values.items():
        share = value / total * 100.0 if total else 0.0
        fired = share > th
        out.append(Signal(
            t, "concentration", fired, f"{share:.0f}% {'>' if fired else '<='} {th:.0f}% of portfolio",
            f"Position is {share:.0f}% of tracked portfolio value (limit {th:.0f}%)",
            src, bars_by_ticker[t][-1].date, 1, f"{t}:concentration",
        ))
    return out


def evaluate(cfg: Config, source: DataSource, as_of: date) -> list[Signal]:
    """Run every rule for every ticker; returns fired and non-fired candidates."""
    bars_by_ticker = {t: source.daily_bars(t, as_of) for t in cfg.tickers}
    calendar = source.earnings_calendar()
    th, out = cfg.thresholds, []
    for ticker, bars in bars_by_ticker.items():
        if len(bars) < 2:
            out.append(Signal(ticker, "data", False, f"only {len(bars)} bar(s) available", "",
                              source.name, as_of, 0, f"{ticker}:data"))
            continue
        out += [rule_daily_move(ticker, bars, th, source.name),
                rule_volume_spike(ticker, bars, th, source.name),
                rule_week52(ticker, bars, th, source.name),
                rule_earnings(ticker, calendar, as_of, th, source.calendar_name)]
        if ticker in cfg.positions:
            out.append(rule_pnl_cross(ticker, bars, cfg.positions[ticker], th, source.name))
    out += rule_concentration(cfg, bars_by_ticker, source.name)
    return out
