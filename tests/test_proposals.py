import unittest

from digest.policy import Decision
from digest.proposals import approved_fingerprints, render_proposal
from tests.helpers import AS_OF, signal


class ProposalTests(unittest.TestCase):
    def test_lists_fired_candidates_with_policy_reason_and_parses_ticks(self):
        decisions = [Decision(signal("A", "daily_move", 4, fingerprint="A:daily_move:2026-09-11"), True, "kept"),
                     Decision(signal("B", "earnings_soon", 3, fingerprint="B:earnings_soon:2026-09-15"), False, "cap: max 3 tickers per digest"),
                     Decision(signal("C", "week52", fired=False), False, "threshold not met")]
        text = render_proposal(decisions, AS_OF, "ticker")
        self.assertIn("# Proposal - 2026-09-12 (slice: ticker)", text)
        self.assertIn("- [ ] `A:daily_move:2026-09-11` A daily_move — policy: kept", text)
        self.assertIn("- [ ] `B:earnings_soon:2026-09-15` B earnings_soon — policy: cap: max 3 tickers per digest", text)
        self.assertNotIn("C week52", text)  # threshold misses are not up for approval
        self.assertEqual(approved_fingerprints(text), set())
        ticked = text.replace("- [ ] `B:", "- [x] `B:")
        self.assertEqual(approved_fingerprints(ticked), {"B:earnings_soon:2026-09-15"})
        self.assertEqual(approved_fingerprints(ticked.replace("[x]", "[X]")), {"B:earnings_soon:2026-09-15"})

    def test_empty_proposal(self):
        self.assertIn("nothing to approve", render_proposal([], AS_OF, "book"))


if __name__ == "__main__":
    unittest.main()
