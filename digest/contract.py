"""Output contract: what a digest may and may not say.

1. Every bullet cites its source and data date: ``(source: <name>, YYYY-MM-DD)``.
2. No recommendations or promises (see ``FORBIDDEN_PHRASES``).
3. The disclaimer footer is present verbatim.

The same validator runs on the template output and on any LLM rewrite, so
the model cannot smuggle advice or drop citations.
"""
from __future__ import annotations

import re

FORBIDDEN_PHRASES = [
    "price target", "buy", "sell", "should", "guaranteed", "guarantee",
    "risk-free", "can't lose", "will rise", "will fall", "will go up", "will go down",
]
DISCLAIMER = "Not investment advice. Automated summary of market data; verify before acting."
CITATION_RE = re.compile(r"\(source: [A-Za-z0-9_.-]+, \d{4}-\d{2}-\d{2}\)\s*$")


class ContractError(ValueError):
    pass


def validate(text: str) -> list[str]:
    """Return a list of violations (empty means compliant)."""
    problems: list[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")) and not CITATION_RE.search(stripped):
            problems.append(f"line {n}: bullet must end with '(source: <name>, YYYY-MM-DD)'")
    for phrase in FORBIDDEN_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE):
            problems.append(f"forbidden phrase: '{phrase}'")
    if DISCLAIMER not in text:
        problems.append("missing disclaimer footer")
    return problems


def check(text: str) -> str:
    """Raise ``ContractError`` on violations; return the text unchanged otherwise."""
    problems = validate(text)
    if problems:
        raise ContractError("; ".join(problems))
    return text
