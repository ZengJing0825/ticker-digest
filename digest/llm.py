"""Optional LLM polish via the Anthropic SDK. Never required for the demo.

Enabled only when ``ANTHROPIC_API_KEY`` is set *and* the ``anthropic``
package is installed. The rewrite is re-validated by ``contract.py``; on any
API error or contract violation the caller falls back to the template.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
SYSTEM_PROMPT = (
    "You edit a Markdown market digest for readability only. Keep the one-line net read, keep one "
    "bullet per name, and keep every trailing citation '(source: ..., YYYY-MM-DD, <url or link n/a>)' "
    "verbatim at the end of its bullet. Keep the final disclaimer line verbatim. Do not add facts, "
    "numbers, links, opinions, forecasts or recommendations. Never use the words buy, sell, should, "
    "guaranteed or price target, and never use technical-analysis jargon (RSI, MACD, support, "
    "resistance, breakout, oversold, moving average and the like). Return only the Markdown document."
)


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and importlib.util.find_spec("anthropic") is not None


def polish(markdown: str) -> Optional[str]:
    """Return the rewritten digest, or ``None`` if the call failed."""
    import anthropic  # imported lazily so the package stays optional

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": markdown}],
        )
    except anthropic.RateLimitError:
        log.warning("llm: rate limited; using template output")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("llm: API error %s; using template output", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("llm: connection error; using template output")
        return None
    if response.stop_reason != "end_turn":
        log.warning("llm: stop_reason=%s; using template output", response.stop_reason)
        return None
    return "".join(block.text for block in response.content if block.type == "text").strip()
