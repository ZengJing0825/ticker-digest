"""Output contract: what a digest may and may not say.

1. Every bullet ends with one or more citations ``(source: <name>, YYYY-MM-DD, <url or "link n/a">)``.
2. No recommendations or promises (``FORBIDDEN_PHRASES``).
3. No technical-analysis jargon (``TA_JARGON``): the digest reports facts, not chart reads.
4. No fabricated links: every URL in the text must be one the signals actually carried.
5. The disclaimer footer is present verbatim.

The same validator runs on the template output and on any LLM rewrite, so
the model cannot smuggle advice, jargon or invented links, or drop citations.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

FORBIDDEN_PHRASES = [
    "price target", "buy", "sell", "should", "guaranteed", "guarantee",
    "risk-free", "can't lose", "will rise", "will fall", "will go up", "will go down",
    "take profit", "stop loss", "entry point", "exit point", "accumulate", "load up",
]
TA_JARGON = [
    "rsi", "macd", "golden cross", "death cross", "bollinger", "fibonacci", "ichimoku", "stochastic",
    "support level", "resistance level", "support and resistance", "breakout", "oversold", "overbought",
    "head and shoulders", "double top", "double bottom", "cup and handle", "moving average", "vwap",
    "candlestick", "doji", "divergence", "trendline", "trend line", "wedge", "pennant", "elliott wave",
    "momentum indicator", "relative strength",
]
DISCLAIMER = "Not investment advice. Automated summary of market data; verify before acting."
LINK_NA = "link n/a"
CITATION = r"\(source: [A-Za-z0-9_.@-]+, \d{4}-\d{2}-\d{2}, (?:https?://[^\s)]+|link n/a)\)"
CITATION_RE = re.compile(rf"(?:{CITATION}\s*)+$")
URL_RE = re.compile(r"https?://[^\s)\]>]+")


class ContractError(ValueError):
    pass


def validate(text: str, known_links: Optional[Iterable[str]] = None) -> List[str]:
    """Return a list of violations (empty means compliant).

    ``known_links`` is the set of URLs the signals carried; when given, any
    other URL in the text is a fabricated citation and is rejected.
    """
    problems: List[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")) and not CITATION_RE.search(stripped):
            problems.append(f"line {n}: bullet must end with '(source: <name>, YYYY-MM-DD, <url or link n/a>)'")
    for phrase in FORBIDDEN_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE):
            problems.append(f"forbidden phrase: '{phrase}'")
    for phrase in TA_JARGON:
        if re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE):
            problems.append(f"technical-analysis jargon: '{phrase}'")
    if known_links is not None:
        allowed = set(known_links)
        for url in URL_RE.findall(text):
            if url not in allowed:
                problems.append(f"unknown link (fabricated citation?): {url}")
    if DISCLAIMER not in text:
        problems.append("missing disclaimer footer")
    return problems


def check(text: str, known_links: Optional[Iterable[str]] = None) -> str:
    """Raise ``ContractError`` on violations; return the text unchanged otherwise."""
    problems = validate(text, known_links)
    if problems:
        raise ContractError("; ".join(problems))
    return text
