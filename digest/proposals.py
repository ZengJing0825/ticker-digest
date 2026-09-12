"""Approval loop: ``propose`` writes a checklist, ``publish --approved`` sends only ticked items.

The proposal lists every candidate that crossed its threshold, with the
policy decision it would get, so a human can tick a box to approve it —
including items the caps or dedupe would have dropped (approval is the
explicit human override; threshold misses are not listed because there is
nothing to approve).
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import List, Set

from .policy import Decision

ITEM_RE = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*`(?P<fp>[^`]+)`")


def render_proposal(decisions: List[Decision], as_of: date, kind: str) -> str:
    fired = [d for d in decisions if d.signal.fired]
    lines = [
        f"# Proposal - {as_of.isoformat()} (slice: {kind})",
        "",
        "Tick `[x]` to approve an item, then run:",
        "",
        f"    python -m digest publish --date {as_of.isoformat()} --slice {kind} --approved --send",
        "",
        f"{len(fired)} candidate(s) crossed a threshold; `policy` shows what the automatic run would do.",
        "",
    ]
    for d in sorted(fired, key=lambda d: (not d.kept, d.signal.subject, d.signal.rule)):
        s = d.signal
        who = f" voice={s.voice}" if s.voice else ""
        book = f" book={s.book}" if s.book else ""
        lines.append(f"- [ ] `{s.fingerprint}` {s.subject} {s.rule}{who}{book} — policy: {d.reason} — {s.why} — {s.headline}")
    if not fired:
        lines.append("(nothing crossed a threshold; nothing to approve)")
    lines.append("")
    return "\n".join(lines)


def proposal_path(out_dir: "Path | str", as_of: date) -> Path:
    return Path(out_dir) / "proposals" / f"{as_of.isoformat()}.md"


def write_proposal(out_dir: "Path | str", as_of: date, decisions: List[Decision], kind: str) -> Path:
    path = proposal_path(out_dir, as_of)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_proposal(decisions, as_of, kind))
    return path


def approved_fingerprints(text: str) -> Set[str]:
    return {m.group("fp") for m in (ITEM_RE.match(ln) for ln in text.splitlines()) if m and m.group("mark") in "xX"}
