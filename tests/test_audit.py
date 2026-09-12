import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from digest import audit
from digest.policy import Decision
from tests.helpers import AS_OF, config, signal

NOW = datetime(2026, 9, 12, 9, 0)


class AuditTests(unittest.TestCase):
    def test_why_no_push_explains_each_empty_outcome(self):
        none_fired = [Decision(signal("A", "r", fired=False), False, "threshold not met")]
        self.assertEqual(audit.why_no_push(none_fired, False, False, None), "no candidate crossed its threshold")
        suppressed = [Decision(signal("A", "r"), False, "dedupe: identical signal delivered 2026-09-11; x"),
                      Decision(signal("B", "r"), False, "cap: max 3 tickers per digest")]
        self.assertEqual(audit.why_no_push(suppressed, False, False, None),
                         "all 2 fired candidate(s) were suppressed (cap 1, dedupe 1)")
        kept = [Decision(signal("A", "r"), True, "kept")]
        self.assertIn("dry run", audit.why_no_push(kept, False, True, None))
        self.assertIn("proposal", audit.why_no_push(kept, False, True, 0))
        self.assertIsNone(audit.why_no_push(kept, True, False, None))

    def test_record_carries_thresholds_decisions_and_dedupe_hits_and_appends(self):
        cfg = config(["A"])
        decisions = [Decision(signal("A", "r", severity=2.0), False, "dedupe: identical signal delivered 2026-09-11; x"),
                     Decision(signal("A", "s", fired=False), False, "threshold not met")]
        record = audit.build_record(command="run", kind="ticker", source="fixture", as_of=AS_OF, now=NOW, cfg=cfg,
                                    decisions=decisions, delivered_fps=[], output=None, dry=False)
        self.assertEqual(record["thresholds"]["move_k"], 2.0)
        self.assertEqual(record["policy"]["escalation_pp"], 1.5)
        self.assertEqual(len(record["decisions"]), 2)
        self.assertEqual([h["fingerprint"] for h in record["dedupe_hits"]], ["A:r"])
        self.assertEqual(record["counts"], {"dedupe": 1, "threshold": 1})
        self.assertTrue(record["why_no_push"].startswith("all 1 fired"))
        with tempfile.TemporaryDirectory() as tmp:
            path = audit.write(tmp, AS_OF, record)
            audit.write(tmp, AS_OF, dict(record, command="publish"))
            self.assertEqual(path, Path(tmp) / "2026-09-12.json")
            data = json.loads(path.read_text())
            self.assertEqual([r["command"] for r in data["runs"]], ["run", "publish"])


if __name__ == "__main__":
    unittest.main()
