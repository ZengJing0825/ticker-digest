import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from digest.config import PolicyLimits
from digest.policy import SentState, apply_policy, kept_signals
from tests.helpers import AS_OF, signal


def reasons(decisions):
    return {(d.signal.ticker, d.signal.rule): d.reason for d in decisions}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = SentState(Path(self.tmp.name) / "sent.json").load()

    def tearDown(self):
        self.tmp.cleanup()

    def test_per_ticker_cap_keeps_highest_priority(self):
        sigs = [signal("A", "low", 1), signal("A", "high", 5), signal("A", "mid", 3)]
        d = apply_policy(sigs, self.state, PolicyLimits(max_signals_per_ticker=2), AS_OF)
        self.assertEqual([s.rule for s in kept_signals(d)], ["high", "mid"])
        self.assertIn("cap: max 2 signals per ticker", reasons(d)[("A", "low")])

    def test_ticker_cap_ranks_by_weight_then_name(self):
        sigs = [signal("C", "r", 1), signal("B", "r", 1), signal("A", "r", 5), signal("D", "r", 9)]
        d = apply_policy(sigs, self.state, PolicyLimits(max_tickers_per_digest=3), AS_OF)
        self.assertEqual([s.ticker for s in kept_signals(d)], ["D", "A", "B"])
        self.assertIn("cap: max 3 tickers per digest", reasons(d)[("C", "r")])

    def test_non_fired_signals_are_never_kept(self):
        d = apply_policy([signal("A", "r", fired=False)], self.state, PolicyLimits(), AS_OF)
        self.assertEqual(kept_signals(d), [])
        self.assertEqual(d[0].reason, "threshold not met")

    def test_dedupe_across_two_consecutive_runs(self):
        limits = PolicyLimits(dedupe_days=7)
        first = apply_policy([signal("A", "r")], self.state, limits, AS_OF)
        self.state.record(kept_signals(first), AS_OF)
        self.state.save()
        # Second run the next day reloads state from disk and suppresses the same fingerprint.
        reloaded = SentState(self.state.path).load()
        second = apply_policy([signal("A", "r")], reloaded, limits, AS_OF + timedelta(days=1))
        self.assertEqual(kept_signals(second), [])
        self.assertIn("dedupe", second[0].reason)
        # Once the window has passed, the signal is deliverable again.
        third = apply_policy([signal("A", "r")], reloaded, limits, AS_OF + timedelta(days=7))
        self.assertEqual(len(kept_signals(third)), 1)

    def test_daily_budget_counts_earlier_runs_today(self):
        limits = PolicyLimits(max_signals_per_ticker=2)
        self.state.record([signal("A", "x", fingerprint="A:x"), signal("A", "y", fingerprint="A:y")], AS_OF)
        d = apply_policy([signal("A", "z", fingerprint="A:z")], self.state, limits, AS_OF)
        self.assertEqual(kept_signals(d), [])
        self.assertIn("cap: max 2 signals per ticker per day", d[0].reason)

    def test_save_prunes_old_entries(self):
        self.state.record([signal("A", "old")], AS_OF - timedelta(days=30))
        self.state.record([signal("A", "new")], AS_OF)
        self.state.save(keep_days=7, today=AS_OF)
        self.assertEqual(set(SentState(self.state.path).load().sent), {"A:new"})


if __name__ == "__main__":
    unittest.main()
