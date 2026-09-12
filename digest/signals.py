"""Signal rules: each rule turns bars / calendar / notes / positions into a ``Signal`` candidate.

Every rule always returns a candidate, fired or not, with a one-line ``why``
so ``explain`` and the audit can show threshold checks that did *not*
trigger. Only fired candidates reach the policy layer.

A ``Signal`` is one cell of the signal matrix: it always names a ``subject``
(the ticker) and optionally a ``voice`` (the handle / person it came from)
and a ``book`` (the portfolio it belongs to). The same candidate set is later
sliced by any of the three axes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from statistics import median
from typing import Dict, List, Optional

from .config import Config, Position, Thresholds
from .markets import is_calendar_only
from .sources.base import Bar, CalendarEvent, DataSource, Note

RISK_RULES = ("pnl_cross", "concentration")     # "risk lines": ranked first when positions exist
PRICE_RULES = ("daily_move", "volume_spike", "week52_high", "week52_low")
CALENDAR_RULES = ("earnings_soon", "catalyst_soon")


@dataclass(frozen=True)
class Signal:
    subject: str      # ticker
    rule: str
    fired: bool
    why: str          # threshold check, e.g. "|+6.2%| >= 2.0 x 0.9% typical"
    headline: str     # the fact ("why" column of the rendered line; no citation, the renderer adds it)
    source: str       # cited data source
    as_of: date       # cited data date
    priority: int     # higher wins when caps apply and no positions are involved
    fingerprint: str  # identity for de-duplication ("SUBJECT:rule[:detail]")
    voice: Optional[str] = None      # handle / person for opinion signals
    book: Optional[str] = None       # portfolio id for position signals
    link: Optional[str] = None       # citation URL when known; rendered as "link n/a" otherwise
    severity: float = 0.0            # rule-specific magnitude used by escalation-aware dedupe
    judgment: str = ""               # short net read for the rendered line
    watch: str = ""                  # "what to watch" for the rendered line
    grade: str = ""                  # price-class signals: "material" / "unattributed"
    value: float = 0.0               # measured quantity (pct move, ratio, share...) for ranking

    @property
    def ticker(self) -> str:  # backwards-compatible name
        return self.subject

    @property
    def topic(self) -> str:
        """Fingerprint without its detail part: what "the same topic" means for the burst guard."""
        parts = self.fingerprint.split(":")
        return ":".join(parts[:2])


def _pct(now: float, base: float) -> float:
    return (now / base - 1.0) * 100.0


def typical_move(bars: List[Bar], window: int) -> Optional[float]:
    """Median absolute close-to-close move (%) over the trailing ``window`` sessions before the last bar."""
    closes = [b.close for b in bars[-1 - window:-1]]
    if len(closes) < window:
        return None
    moves = [abs(_pct(closes[i], closes[i - 1])) for i in range(1, len(closes))]
    return median(moves) if moves else None


def volume_ratio(bars: List[Bar], window: int) -> Optional[float]:
    prior = bars[-1 - window:-1]
    if len(prior) < window:
        return None
    avg = sum(b.volume for b in prior) / len(prior)
    return bars[-1].volume / avg if avg else 0.0


@dataclass(frozen=True)
class Reason:
    """An attributable reason for a price move: a note, a calendar event or a sector proxy."""

    kind: str   # "note" | "calendar" | "sector"
    text: str
    link: Optional[str] = None


def find_reason(ticker: str, as_of: date, pct: float, notes: List[Note], calendar: List[CalendarEvent],
                sectors: Dict[str, List[str]], moves: Dict[str, Optional[float]], th: Thresholds) -> Optional[Reason]:
    """News/catalyst first, then a sector proxy (a peer moved the same way by its own trigger)."""
    fresh = [n for n in notes if n.ticker == ticker and 0 <= (as_of - n.date).days <= th.reason_days]
    if fresh:
        n = fresh[-1]
        return Reason("note", f"{n.voice} note ({n.date.isoformat()})", n.link)
    near = [e for e in calendar if e.ticker == ticker and abs((e.date - as_of).days) <= th.reason_days]
    if near:
        e = near[0]
        return Reason("calendar", f"{e.kind} on {e.date.isoformat()}")
    for sector, members in sectors.items():
        if ticker not in members:
            continue
        for peer in members:
            peer_move = moves.get(peer)
            if peer == ticker or peer_move is None:
                continue
            if peer_move * pct > 0 and abs(peer_move) >= abs(pct) * 0.5:
                return Reason("sector", f"sector proxy {sector}: {peer} {peer_move:+.1f}%")
    return None


def rule_daily_move(ticker: str, bars: List[Bar], th: Thresholds, src: str,
                    reason: Optional[Reason] = None) -> Signal:
    """Relative trigger: |move| >= move_k x typical and volume >= volume_multiple x typical.

    Falls back to the absolute ``move_pct`` when fewer than ``typical_window``
    sessions exist. The signal is graded ``material`` only when move, volume
    and an attributable reason all hold; otherwise it is ``unattributed``.
    """
    prev, last = bars[-2], bars[-1]
    pct = _pct(last.close, prev.close)
    typical = typical_move(bars, th.typical_window)
    ratio = volume_ratio(bars, th.volume_window)
    vol_ok = ratio is None or ratio >= th.volume_multiple  # unknown volume history does not block
    vol_txt = f"volume {ratio:.1f}x" if ratio is not None else "volume history short"
    if typical is None:
        fired = abs(pct) >= th.move_pct
        why = f"|{pct:+.1f}%| {'>=' if fired else '<'} {th.move_pct:.1f}% (absolute fallback, history < {th.typical_window} sessions)"
    else:
        limit = th.move_k * typical
        move_ok = abs(pct) >= limit
        fired = move_ok and vol_ok
        why = (f"|{pct:+.1f}%| {'>=' if move_ok else '<'} {th.move_k:.1f} x {typical:.1f}% typical = {limit:.1f}%"
               f"; {vol_txt} {'>=' if vol_ok else '<'} {th.volume_multiple:.1f}x")
    material = fired and ratio is not None and ratio >= th.volume_multiple and reason is not None
    grade = "material" if material else "unattributed" if fired else ""
    headline = f"Closed {pct:+.1f}% at {last.close:,.2f} (previous close {prev.close:,.2f})"
    if ratio is not None:
        headline += f" on {ratio:.1f}x typical volume"
    if reason is not None:
        headline += f"; reason: {reason.text}"
    if material:
        judgment, watch = "material move: size, volume and a reason all line up", \
            "whether volume stays elevated next session and whether the reason is confirmed"
    else:
        judgment, watch = "move on volume, no attributable reason found", \
            "a reason surfacing (filing, news, sector); until then treat it as noise"
    return Signal(
        ticker, "daily_move", fired, why, headline, src, last.date, 5 if material else 4,
        f"{ticker}:daily_move:{last.date}", link=reason.link if reason else None, severity=abs(pct),
        judgment=judgment, watch=watch, grade=grade, value=pct,
    )


def rule_volume_spike(ticker: str, bars: List[Bar], th: Thresholds, src: str) -> Signal:
    last = bars[-1]
    ratio = volume_ratio(bars, th.volume_window)
    if ratio is None:
        have = len(bars[-1 - th.volume_window:-1])
        return Signal(ticker, "volume_spike", False, f"need {th.volume_window} prior sessions, have {have}",
                      "", src, last.date, 2, f"{ticker}:volume_spike:{last.date}")
    fired = ratio >= th.volume_multiple
    return Signal(
        ticker, "volume_spike", fired,
        f"{ratio:.1f}x {'>=' if fired else '<'} {th.volume_multiple:.1f}x {th.volume_window}-day average",
        f"Volume {last.volume:,.0f} was {ratio:.1f}x the {th.volume_window}-day average",
        src, last.date, 2, f"{ticker}:volume_spike:{last.date}", severity=ratio, value=ratio,
        judgment="volume spike without a matching price move", watch="whether price follows the volume",
    )


def rule_week52(ticker: str, bars: List[Bar], th: Thresholds, src: str) -> Signal:
    last = bars[-1]
    prior = [b.close for b in bars[-1 - th.week52_window:-1]]
    if len(prior) < 20:
        return Signal(ticker, "week52", False, f"insufficient history ({len(prior)} sessions)",
                      "", src, last.date, 3, f"{ticker}:week52")
    hi, lo = max(prior), min(prior)
    if last.close > hi:
        return Signal(ticker, "week52_high", True, f"close {last.close:,.2f} > prior high {hi:,.2f}",
                      f"New 52-week high: close {last.close:,.2f} vs prior high {hi:,.2f}",
                      src, last.date, 3, f"{ticker}:week52_high", severity=_pct(last.close, hi),
                      judgment="new 52-week high", watch="whether the close holds above the prior high",
                      value=_pct(last.close, hi))
    if last.close < lo:
        return Signal(ticker, "week52_low", True, f"close {last.close:,.2f} < prior low {lo:,.2f}",
                      f"New 52-week low: close {last.close:,.2f} vs prior low {lo:,.2f}",
                      src, last.date, 3, f"{ticker}:week52_low", severity=abs(_pct(last.close, lo)),
                      judgment="new 52-week low", watch="whether the close holds below the prior low",
                      value=_pct(last.close, lo))
    return Signal(ticker, "week52", False, f"close {last.close:,.2f} within [{lo:,.2f}, {hi:,.2f}]",
                  "", src, last.date, 3, f"{ticker}:week52")


def _upcoming(ticker: str, events: List[CalendarEvent], as_of: date, kind_is_earnings: bool) -> List[CalendarEvent]:
    return sorted((e for e in events if e.ticker == ticker and e.date >= as_of
                   and (e.kind == "earnings") == kind_is_earnings), key=lambda e: e.date)


def rule_earnings(ticker: str, events: List[CalendarEvent], as_of: date, th: Thresholds, src: str) -> Signal:
    upcoming = _upcoming(ticker, events, as_of, True)
    if not upcoming:
        return Signal(ticker, "earnings_soon", False, "no upcoming earnings on calendar",
                      "", src, as_of, 3, f"{ticker}:earnings_soon:none")
    nxt = upcoming[0].date
    days = (nxt - as_of).days
    fired = days <= th.earnings_days
    return Signal(
        ticker, "earnings_soon", fired,
        f"next earnings {nxt} in {days}d {'<=' if fired else '>'} {th.earnings_days}d",
        f"Earnings scheduled for {nxt} ({days} day{'s' if days != 1 else ''} away)",
        src, as_of, 3, f"{ticker}:earnings_soon:{nxt}", severity=0.0,
        judgment=f"earnings in {days} day{'s' if days != 1 else ''}",
        watch="the reported numbers and any change in guidance on the day", value=float(days),
    )


def rule_catalyst(ticker: str, events: List[CalendarEvent], as_of: date, th: Thresholds, src: str) -> Signal:
    upcoming = _upcoming(ticker, events, as_of, False)
    if not upcoming:
        return Signal(ticker, "catalyst_soon", False, "no upcoming catalyst on calendar",
                      "", src, as_of, 3, f"{ticker}:catalyst_soon:none")
    ev = upcoming[0]
    days = (ev.date - as_of).days
    fired = days <= th.earnings_days
    label = ev.note or ev.kind
    return Signal(
        ticker, "catalyst_soon", fired,
        f"next catalyst ({ev.kind}) {ev.date} in {days}d {'<=' if fired else '>'} {th.earnings_days}d",
        f"Catalyst on {ev.date}: {label} ({days} day{'s' if days != 1 else ''} away)",
        src, as_of, 3, f"{ticker}:catalyst_soon:{ev.kind}:{ev.date}", severity=0.0,
        judgment=f"scheduled catalyst in {days} day{'s' if days != 1 else ''}",
        watch="the outcome of the event and the first session after it", value=float(days),
    )


def rule_voice_note(note: Note, as_of: date, th: Thresholds, src: str,
                    move: Optional[float] = None) -> Signal:
    age = (as_of - note.date).days
    fired = 0 <= age <= th.note_days
    headline = f"{note.voice}: {note.headline}"
    if move is not None:
        headline += f" (price {move:+.1f}% on the latest session)"
    return Signal(
        note.ticker, "voice_take", fired,
        f"note dated {note.date} is {age}d old {'<=' if fired else '>'} {th.note_days}d",
        headline, src, note.date, 2, f"{note.ticker}:voice_take:{note.voice}:{note.date}",
        voice=note.voice, link=note.link, severity=0.0,
        judgment=f"opinion from {note.voice}, not data", watch="whether price and volume confirm it",
    )


def rule_pnl_cross(ticker: str, bars: List[Bar], pos: Position, th: Thresholds, src: str) -> Signal:
    prev, last = bars[-2], bars[-1]
    before, now = _pct(prev.close, pos.avg_cost), _pct(last.close, pos.avg_cost)
    side = "+" if now >= th.pnl_pct > before else "-" if now <= -th.pnl_pct < before else ""
    return Signal(
        ticker, "pnl_cross", bool(side),
        f"P&L {before:+.1f}% -> {now:+.1f}% {'crossed' if side else 'did not cross'} +/-{th.pnl_pct:.0f}%",
        f"Unrealized P&L crossed {side}{th.pnl_pct:.0f}%: now {now:+.1f}% vs avg cost {pos.avg_cost:,.2f}",
        src, last.date, 5, f"{ticker}:pnl_cross:{side}{th.pnl_pct:.0f}", book=pos.book, severity=abs(now),
        judgment=f"risk line: unrealized P&L crossed {side}{th.pnl_pct:.0f}%",
        watch="position size against the plan it was opened with", value=now,
    )


def rule_concentration(cfg: Config, bars_by_ticker: Dict[str, List[Bar]], src: str) -> List[Signal]:
    th = cfg.thresholds.concentration_pct
    out: List[Signal] = []
    for book, tickers in cfg.books().items():
        values = {t: cfg.positions[t].qty * bars_by_ticker[t][-1].close for t in tickers if bars_by_ticker.get(t)}
        total = sum(values.values())
        for t, value in values.items():
            share = value / total * 100.0 if total else 0.0
            single = len(values) < 2
            fired = share > th and not single
            why = (f"only position in book {book}; concentration not evaluated" if single
                   else f"{share:.0f}% {'>' if fired else '<='} {th:.0f}% of book {book}")
            out.append(Signal(
                t, "concentration", fired, why,
                f"Position is {share:.0f}% of book {book} (limit {th:.0f}%)",
                src, bars_by_ticker[t][-1].date, 1, f"{t}:concentration:{book}", book=book, severity=share,
                judgment=f"risk line: {share:.0f}% of book {book}", watch="whether the share keeps growing",
                value=share,
            ))
    return out


def evaluate(cfg: Config, source: DataSource, as_of: date) -> List[Signal]:
    """Run every rule for every ticker; returns fired and non-fired candidates.

    Calendar-tier markets skip the price rules entirely: no bars are fetched
    for them, only the calendar rules run.
    """
    realtime = [t for t in cfg.tickers if not is_calendar_only(t, cfg.markets)]
    bars_by_ticker = {t: source.daily_bars(t, as_of) for t in realtime}
    calendar = source.earnings_calendar()
    notes = source.notes()
    th, out = cfg.thresholds, []

    # First pass: the move of every realtime ticker (needed by the sector proxy).
    moves: Dict[str, Optional[float]] = {}
    for t, bars in bars_by_ticker.items():
        typical = typical_move(bars, th.typical_window) if len(bars) >= 2 else None
        if len(bars) < 2:
            moves[t] = None
            continue
        pct = _pct(bars[-1].close, bars[-2].close)
        limit = th.move_k * typical if typical is not None else th.move_pct
        moves[t] = pct if abs(pct) >= limit else None  # a peer only explains a move if it triggered too

    for ticker in cfg.tickers:
        calendar_rules = [rule_earnings(ticker, calendar, as_of, th, source.calendar_name),
                          rule_catalyst(ticker, calendar, as_of, th, source.calendar_name)]
        if ticker not in bars_by_ticker:
            out += calendar_rules
            continue
        bars = bars_by_ticker[ticker]
        if len(bars) < 2:
            out.append(Signal(ticker, "data", False, f"only {len(bars)} bar(s) available", "",
                              source.name, as_of, 0, f"{ticker}:data"))
            out += calendar_rules
            continue
        pct = _pct(bars[-1].close, bars[-2].close)
        reason = find_reason(ticker, as_of, pct, notes, calendar, cfg.sectors, moves, th)
        move = rule_daily_move(ticker, bars, th, source.name, reason)
        volume = rule_volume_spike(ticker, bars, th, source.name)
        if move.fired and volume.fired:  # the move line already carries the volume ratio
            volume = replace(volume, fired=False, why=volume.why + "; folded into daily_move (same session)")
        out += [move, volume, rule_week52(ticker, bars, th, source.name)]
        out += calendar_rules
        if ticker in cfg.positions:
            out.append(rule_pnl_cross(ticker, bars, cfg.positions[ticker], th, source.name))
    out += rule_concentration(cfg, bars_by_ticker, source.name)

    watch = set(cfg.tickers)
    for note in notes:
        if note.ticker not in watch:
            continue
        bars = bars_by_ticker.get(note.ticker) or []
        move = _pct(bars[-1].close, bars[-2].close) if len(bars) >= 2 else None
        out.append(rule_voice_note(note, as_of, th, source.notes_name, move))
    return out


def move_by_subject(candidates: List[Signal]) -> Dict[str, float]:
    """Latest close-to-close move (%) per ticker, from the daily_move candidates (fired or not)."""
    return {s.subject: s.value for s in candidates if s.rule == "daily_move"}


def weight_by_book(candidates: List[Signal]) -> Dict[str, Dict[str, float]]:
    """book -> ticker -> share of book value (0..1), from the concentration candidates."""
    out: Dict[str, Dict[str, float]] = {}
    for s in candidates:
        if s.rule == "concentration" and s.book:
            out.setdefault(s.book, {})[s.subject] = s.value / 100.0
    return out


def with_book(signal: Signal, book: str) -> Signal:
    return replace(signal, book=book)
