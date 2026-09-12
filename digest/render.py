"""Render delivered signals as a Markdown digest that satisfies the contract."""
from __future__ import annotations

import logging
from datetime import date

from . import contract, llm
from .signals import Signal

log = logging.getLogger(__name__)


def render_markdown(signals: list[Signal], as_of: date) -> str:
    """Template renderer. Tickers keep the order chosen by the policy layer."""
    tickers: list[str] = []
    for s in signals:
        if s.ticker not in tickers:
            tickers.append(s.ticker)
    lines = [
        f"# Watchlist digest - {as_of.isoformat()}",
        "",
        f"{len(signals)} signal(s) across {len(tickers)} ticker(s). Only rule-triggered, "
        "not-recently-reported events are listed; quiet tickers are omitted.",
        "",
    ]
    for ticker in tickers:
        lines.append(f"## {ticker}")
        for s in signals:
            if s.ticker == ticker:
                lines.append(f"- {s.headline} (source: {s.source}, {s.as_of.isoformat()})")
        lines.append("")
    lines += ["---", contract.DISCLAIMER, ""]
    return "\n".join(lines)


def build_digest(signals: list[Signal], as_of: date, use_llm: bool = False) -> str:
    """Template output (always contract-checked), optionally polished by an LLM."""
    text = contract.check(render_markdown(signals, as_of))
    if not use_llm:
        return text
    polished = llm.polish(text)
    if polished is None:
        return text
    problems = contract.validate(polished)
    if problems:
        log.warning("llm: rewrite rejected by contract (%s); using template output", "; ".join(problems))
        return text
    return polished
