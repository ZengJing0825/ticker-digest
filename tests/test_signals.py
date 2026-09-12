import unittest
from datetime import date

from digest.config import Position, Thresholds
from digest.signals import (evaluate, rule_concentration, rule_daily_move, rule_earnings, rule_pnl_cross,
                            rule_volume_spike, rule_week52)
from digest.sources.base import EarningsEvent
from tests.helpers import AS_OF, MemorySource, bars, config

TH = Thresholds()


class SignalRuleTests(unittest.TestCase):
    def test_daily_move_fires_on_threshold(self):
        self.assertTrue(rule_daily_move("X", bars([100, 105]), TH, "t").fired)
        self.assertTrue(rule_daily_move("X", bars([100, 94]), TH, "t").fired)
        self.assertFalse(rule_daily_move("X", bars([100, 104.9]), TH, "t").fired)

    def test_volume_spike_uses_trailing_average(self):
        vols = [100.0] * 20 + [200.0]
        self.assertTrue(rule_volume_spike("X", bars([1.0] * 21, vols), TH, "t").fired)
        vols[-1] = 199.0
        self.assertFalse(rule_volume_spike("X", bars([1.0] * 21, vols), TH, "t").fired)
        self.assertFalse(rule_volume_spike("X", bars([1.0] * 5, [1.0] * 5), TH, "t").fired)  # too little history

    def test_week52_high_and_low(self):
        closes = [50.0] * 30 + [60.0]
        self.assertEqual(rule_week52("X", bars(closes), TH, "t").rule, "week52_high")
        closes[-1] = 40.0
        self.assertEqual(rule_week52("X", bars(closes), TH, "t").rule, "week52_low")
        closes[-1] = 50.0
        self.assertFalse(rule_week52("X", bars(closes), TH, "t").fired)

    def test_earnings_within_window(self):
        events = [EarningsEvent("X", date(2026, 9, 18)), EarningsEvent("X", date(2026, 9, 1))]
        s = rule_earnings("X", events, AS_OF, TH, "cal")
        self.assertTrue(s.fired)
        self.assertIn("2026-09-18", s.fingerprint)
        self.assertFalse(rule_earnings("X", [EarningsEvent("X", date(2026, 9, 20))], AS_OF, TH, "cal").fired)
        self.assertFalse(rule_earnings("Y", events, AS_OF, TH, "cal").fired)

    def test_pnl_cross_only_on_crossing(self):
        pos = Position(qty=1, avg_cost=100.0)
        self.assertTrue(rule_pnl_cross("X", bars([119.0, 121.0]), pos, TH, "t").fired)
        self.assertTrue(rule_pnl_cross("X", bars([81.0, 79.0]), pos, TH, "t").fired)
        self.assertFalse(rule_pnl_cross("X", bars([121.0, 125.0]), pos, TH, "t").fired)  # already above
        self.assertFalse(rule_pnl_cross("X", bars([110.0, 115.0]), pos, TH, "t").fired)

    def test_concentration_share_of_portfolio(self):
        cfg = config(["A", "B"], {"A": Position(10, 1), "B": Position(1, 1)})
        series = {"A": bars([10.0, 10.0]), "B": bars([10.0, 10.0])}
        by_ticker = {s.ticker: s for s in rule_concentration(cfg, series, "t")}
        self.assertTrue(by_ticker["A"].fired)
        self.assertFalse(by_ticker["B"].fired)

    def test_evaluate_returns_candidates_for_every_rule(self):
        cfg = config(["A", "B"], {"A": Position(1, 100.0)})
        src = MemorySource({"A": bars([100.0] * 21 + [110.0]), "B": bars([1.0])})
        sigs = evaluate(cfg, src, AS_OF)
        rules_a = {s.rule for s in sigs if s.ticker == "A"}
        self.assertEqual(rules_a, {"daily_move", "volume_spike", "week52_high", "earnings_soon", "pnl_cross", "concentration"})
        self.assertEqual([s.rule for s in sigs if s.ticker == "B"], ["data"])  # too few bars
        self.assertEqual({s.source for s in sigs if s.rule == "earnings_soon"}, {"memcal"})


if __name__ == "__main__":
    unittest.main()
