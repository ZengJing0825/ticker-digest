"""Persisted explainability: every run appends a record to ``state/audit/<date>.json``.

A record holds the thresholds and policy in force, every candidate with its
decision (including the ones that did not fire), the dedupe hits, what was
delivered and — when nothing was — why not.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .policy import Decision, summarize_reasons


def _decision_json(d: Decision) -> Dict[str, Any]:
    s = d.signal
    return {
        "subject": s.subject, "rule": s.rule, "voice": s.voice, "book": s.book, "fired": s.fired,
        "kept": d.kept, "decision": d.reason, "why": s.why, "severity": round(s.severity, 4),
        "grade": s.grade or None, "fingerprint": s.fingerprint, "source": s.source, "as_of": s.as_of.isoformat(),
    }


def why_no_push(decisions: List[Decision], delivered: bool, dry: bool, approved: Optional[int]) -> Optional[str]:
    """One sentence explaining an empty delivery; ``None`` when something was delivered."""
    if delivered:
        return None
    fired = [d for d in decisions if d.signal.fired]
    kept = [d for d in decisions if d.kept]
    if approved is not None and approved == 0:
        return "no item in the proposal file is marked approved"
    if not fired:
        return "no candidate crossed its threshold"
    if not kept:
        counts = summarize_reasons(fired)
        parts = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        return f"all {len(fired)} fired candidate(s) were suppressed ({parts})"
    if dry:
        return f"dry run: {len(kept)} kept candidate(s) rendered but not delivered"
    return "nothing delivered"


def build_record(*, command: str, kind: str, source: str, as_of: date, now: datetime, cfg: Config,
                 decisions: List[Decision], delivered_fps: List[str], output: Optional[str], dry: bool,
                 approved: Optional[int] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dedupe_hits = [_decision_json(d) for d in decisions if d.reason.startswith(("dedupe", "escalation"))]
    record = {
        "run_at": now.isoformat(timespec="seconds"),
        "command": command,
        "slice": kind,
        "source": source,
        "as_of": as_of.isoformat(),
        "dry": dry,
        "thresholds": asdict(cfg.thresholds),
        "policy": asdict(cfg.policy),
        "markets": dict(cfg.markets),
        "positions_updated_at": cfg.positions_updated_at.isoformat() if cfg.positions_updated_at else None,
        "counts": summarize_reasons(decisions),
        "decisions": [_decision_json(d) for d in decisions],
        "dedupe_hits": dedupe_hits,
        "delivered": delivered_fps,
        "output": output,
        "why_no_push": why_no_push(decisions, bool(delivered_fps), dry, approved),
    }
    if extra:
        record.update(extra)
    return record


def write(audit_dir: "Path | str", as_of: date, record: Dict[str, Any]) -> Path:
    """Append ``record`` to the day's audit file and return its path."""
    path = Path(audit_dir) / f"{as_of.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(path.read_text() or "{}") if path.exists() else {}
    runs = list(existing.get("runs", []))
    runs.append(record)
    path.write_text(json.dumps({"date": as_of.isoformat(), "runs": runs}, indent=2) + "\n")
    return path
