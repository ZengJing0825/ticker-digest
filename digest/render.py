"""Render delivered signals as a Markdown digest that satisfies the contract.

Template:  title -> one-line net read -> name-major lines (one per subject:
judgment - why - what to watch - source) -> at most ``max_lines`` lines, then
``+N more quiet`` -> optional positions footer -> disclaimer.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import List, Optional

from . import contract, llm
from .signals import Signal
from .slices import TITLES, UNITS, Group, Line, SliceContext, quiet_subjects

log = logging.getLogger(__name__)

CALENDAR_BADGE = "[calendar-only]"


def citation(s: Signal) -> str:
    return f"(source: {s.source}, {s.as_of.isoformat()}, {s.link or contract.LINK_NA})"


def render_line(line: Line, badge: bool = False) -> str:
    """One name-major line: **SUBJECT** · judgment · why · watch: ... · citations."""
    lead = line.signals[0]
    why = "; ".join(s.headline for s in line.signals)
    cites: List[str] = []
    for s in line.signals:
        c = citation(s)
        if c not in cites:
            cites.append(c)
    name = f"**{line.subject}**" + (f" {CALENDAR_BADGE}" if badge else "")
    judgment = lead.judgment or lead.rule.replace("_", " ")
    watch = lead.watch or "the next session"
    return f"- {name} · {judgment} · {why} · watch: {watch} · " + " ".join(cites)


def net_read(groups: List[Group], kind: str, ctx: SliceContext, as_of: date, shown: int, quiet: int) -> str:
    unit = UNITS[kind]
    if not groups:
        return f"Net read: nothing crossed a threshold for {as_of.isoformat()}."
    lead_group = groups[0]
    lead_line = lead_group.lines[0]
    lead = lead_line.subject if kind != "person" else f"{lead_group.key} on {lead_line.subject}"
    total = shown + quiet
    return (f"Net read: {shown} of {total} {unit}{'s' if total != 1 else ''} have something real for "
            f"{as_of.isoformat()}; {lead} leads ({lead_line.signals[0].judgment or lead_line.signals[0].rule}); "
            f"{quiet} quiet.")


def render_markdown(groups: List[Group], as_of: date, kind: str = "ticker", ctx: Optional[SliceContext] = None,
                    max_lines: int = 8, stale_days: Optional[int] = None) -> str:
    """Template renderer. Groups and lines keep the order chosen by the policy layer."""
    ctx = ctx or SliceContext()
    all_lines = [(g, ln) for g in groups for ln in g.lines]
    shown, overflow = all_lines[:max_lines], all_lines[max_lines:]
    quiet = [ln.subject if kind != "person" else g.key for g, ln in overflow]
    quiet += [q for q in quiet_subjects([Group(g.key, [ln]) for g, ln in shown], ctx, kind) if q not in quiet]
    out = [f"# {TITLES[kind]} - {as_of.isoformat()}", "",
           net_read(groups, kind, ctx, as_of, len(shown), len(quiet)), ""]
    current = None
    for g, ln in shown:
        if kind != "ticker" and g.key != current:
            if current is not None:
                out.append("")
            out.append(f"## {g.key}")
            current = g.key
        out.append(render_line(ln, badge=ln.subject in ctx.calendar_only))
    if quiet:
        out += ["", f"+{len(quiet)} more quiet: {', '.join(quiet)}"]
    if stale_days is not None:
        out += ["", f"positions last updated {stale_days} days ago — reconnect or re-enter"]
    out += ["", "---", contract.DISCLAIMER, ""]
    return "\n".join(out)


def known_links(groups: List[Group]) -> List[str]:
    return sorted({s.link for g in groups for s in g.signals if s.link})


def build_digest(groups: List[Group], as_of: date, kind: str = "ticker", ctx: Optional[SliceContext] = None,
                 use_llm: bool = False, max_lines: int = 8, stale_days: Optional[int] = None) -> str:
    """Template output (always contract-checked), optionally polished by an LLM.

    The rewrite is validated by the *same* contract, with the template's
    links as the only allowed URLs; any violation falls back to the template.
    """
    links = known_links(groups)
    text = contract.check(render_markdown(groups, as_of, kind, ctx, max_lines, stale_days), links)
    if not use_llm:
        return text
    polished = llm.polish(text)
    if polished is None:
        return text
    problems = contract.validate(polished, links)
    if problems:
        log.warning("llm: rewrite rejected by contract (%s); using template output", "; ".join(problems))
        return text
    return polished
