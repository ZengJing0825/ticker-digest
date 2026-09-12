import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from digest.config import PolicyLimits
from digest.policy import SentState, apply_policy, kept_signals, summarize_reasons
from digest.slices import SliceContext
from tests.helpers import AS_OF, signal

T0 = datetime(2026, 9, 12, 9, 0)


def reasons(decisions):
    return {(d.signal.subject, d.signal.rule): d.reason for d in decisions}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sent.json"
        self.state = SentState(self.path).load()

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
        self.assertEqual([s.subject for s in kept_signals(d)], ["D", "A", "B"])
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

    # -- escalation-aware dedupe ----------------------------------------
    def test_same_fingerprint_repushed_only_when_worsened_and_interval_passed(self):
        limits = PolicyLimits()
        self.state.record([signal("A", "concentration", severity=50.0)], T0)
        # 30 minutes later, +2pp worse: worsened enough but too soon.
        d = apply_policy([signal("A", "concentration", severity=52.0)], self.state, limits, AS_OF, T0 + timedelta(minutes=30))
        self.assertFalse(d[0].kept)
        self.assertIn("only 30 min", d[0].reason)
        # 60 minutes later, +1pp: interval passed but not worse enough.
        d = apply_policy([signal("A", "concentration", severity=51.0)], self.state, limits, AS_OF, T0 + timedelta(minutes=60))
        self.assertFalse(d[0].kept)
        self.assertIn("worsened +1.0 < 1.5pp", d[0].reason)
        # 60 minutes later, +2pp: re-pushed with an escalation note.
        d = apply_policy([signal("A", "concentration", severity=52.0)], self.state, limits, AS_OF, T0 + timedelta(minutes=60))
        self.assertTrue(d[0].kept)
        self.assertTrue(d[0].reason.startswith("escalation: worsened +2.0pp"))
        # Improving is never a reason to re-push.
        d = apply_policy([signal("A", "concentration", severity=40.0)], self.state, limits, AS_OF, T0 + timedelta(hours=5))
        self.assertFalse(d[0].kept)

    def test_same_topic_burst_guard_inside_the_window(self):
        limits = PolicyLimits(escalation_window_hours=1.0, min_interval_minutes=55, escalation_pp=1.5)
        self.state.record([signal("A", "daily_move", fingerprint="A:daily_move:2026-09-11", severity=3.0)], T0)
        fresh = signal("A", "daily_move", fingerprint="A:daily_move:2026-09-12", severity=3.5)
        d = apply_policy([fresh], self.state, limits, AS_OF, T0 + timedelta(minutes=20))
        self.assertFalse(d[0].kept)
        self.assertIn("same topic pushed within 1h", d[0].reason)
        worse = signal("A", "daily_move", fingerprint="A:daily_move:2026-09-12", severity=5.0)
        d = apply_policy([worse], self.state, limits, AS_OF, T0 + timedelta(minutes=56))
        self.assertTrue(d[0].kept)
        self.assertIn("escalation", d[0].reason)
        # Outside the window a new detail of the same topic is simply a new signal.
        d = apply_policy([fresh], self.state, limits, AS_OF, T0 + timedelta(hours=2))
        self.assertEqual(d[0].reason, "kept")

    def test_state_is_namespaced_per_slice_and_migrates_legacy_files(self):
        self.path.write_text('{"A:r": "2026-09-12"}\n')  # legacy flat format
        ticker = SentState(self.path, "ticker").load()
        self.assertEqual(set(ticker.sent), {"A:r"})
        self.assertEqual(ticker.sent["A:r"].at, datetime(2026, 9, 12, 0, 0))
        person = SentState(self.path, "person").load()
        self.assertEqual(person.sent, {})  # the opinion digest has its own namespace
        person.record([signal("A", "voice_take", voice="@owl")], T0)
        person.save()
        again = SentState(self.path, "ticker").load()
        self.assertEqual(set(again.sent), {"A:r"})
        self.assertEqual(set(SentState(self.path, "person").load().sent), {"A:voice_take"})
        self.assertEqual(SentState(self.path, "person").load().sent["A:voice_take"].group, "@owl")

    def test_person_slice_budget_is_per_voice(self):
        state = SentState(self.path, "person").load()
        sigs = [signal("A", "voice_take", 2, voice="@owl", fingerprint="A:voice_take:@owl"),
                signal("B", "voice_take", 2, voice="@owl", fingerprint="B:voice_take:@owl"),
                signal("C", "voice_take", 2, voice="@owl", fingerprint="C:voice_take:@owl"),
                signal("A", "daily_move", 4)]
        d = apply_policy(sigs, state, PolicyLimits(max_signals_per_ticker=2), AS_OF, T0, "person")
        r = reasons(d)
        self.assertEqual(r[("A", "daily_move")], "not part of the person slice")
        self.assertEqual(sum(1 for x in d if x.kept), 2)
        self.assertIn("cap: max 2 signals per person per day", r[("C", "voice_take")])

    def test_book_slice_cap_counts_books_not_tickers(self):
        ctx = SliceContext(books={"b1": ["A"], "b2": ["B"], "b3": ["C"], "b4": ["D"]})
        sigs = [signal(t, "daily_move", 4) for t in "ABCD"]
        d = apply_policy(sigs, SentState(self.path, "book").load(), PolicyLimits(max_tickers_per_digest=3), AS_OF, T0, "book", ctx)
        cut = [x for x in d if not x.kept]
        self.assertEqual(len(cut), 1)
        self.assertIn("max 3 books per digest", cut[0].reason)
        self.assertEqual(summarize_reasons(d), {"kept": 3, "cap": 1})


if __name__ == "__main__":
    unittest.main()
