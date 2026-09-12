import unittest
from datetime import date

from digest.config import Position, Thresholds
from digest.signals import (Reason, evaluate, find_reason, move_by_subject, rule_catalyst, rule_concentration,
                            rule_daily_move, rule_earnings, rule_pnl_cross, rule_voice_note, rule_volume_spike,
                            rule_week52, typical_move, weight_by_book)
from digest.sources.base import CalendarEvent, EarningsEvent, Note
from tests.helpers import AS_OF, MemorySource, bars, config

TH = Thresholds()


def steady(n: int, step: float = 1.0, base: float = 100.0):
    """Alternating +/-step% closes: a series whose typical (median) move is exactly ``step``%."""
    closes, level = [], base
    for i in range(n):
        closes.append(level)
        level = level * (1 + step / 100) if i % 2 == 0 else level / (1 + step / 100)
    return closes


class SignalRuleTests(unittest.TestCase):
    def test_daily_move_absolute_fallback_with_short_history(self):
        self.assertTrue(rule_daily_move("X", bars([100, 105]), TH, "t").fired)
        self.assertTrue(rule_daily_move("X", bars([100, 94]), TH, "t").fired)
        s = rule_daily_move("X", bars([100, 104.9]), TH, "t")
        self.assertFalse(s.fired)
        self.assertIn("absolute fallback", s.why)

    def test_typical_move_is_the_median_abs_move(self):
        closes = steady(31)
        self.assertAlmostEqual(typical_move(bars(closes), 30), 1.0, places=6)
        self.assertIsNone(typical_move(bars(closes[:20]), 30))

    def test_daily_move_relative_trigger_needs_move_and_volume(self):
        closes = steady(31) + [0.0]
        closes[-1] = closes[-2] * 1.025  # +2.5% >= 2 x 1.0% typical
        vols = [100.0] * 31 + [250.0]     # 2.5x the 20-day average
        s = rule_daily_move("X", bars(closes, vols), TH, "t")
        self.assertTrue(s.fired)
        self.assertEqual(s.grade, "unattributed")  # no reason -> not material
        self.assertEqual(s.priority, 4)
        self.assertAlmostEqual(s.severity, 2.5, places=6)
        vols[-1] = 150.0                  # volume below 2x: the move alone does not trigger
        s = rule_daily_move("X", bars(closes, vols), TH, "t")
        self.assertFalse(s.fired)
        self.assertIn("volume 1.5x < 2.0x", s.why)
        closes[-1] = closes[-2] * 1.015  # +1.5% < 2 x 1.0%
        self.assertFalse(rule_daily_move("X", bars(closes, [100.0] * 31 + [250.0]), TH, "t").fired)

    def test_daily_move_material_only_with_a_reason(self):
        closes = steady(31) + [0.0]
        closes[-1] = closes[-2] * 1.03
        vols = [100.0] * 31 + [300.0]
        s = rule_daily_move("X", bars(closes, vols), TH, "t", Reason("note", "@owl note", "https://example.com/n"))
        self.assertEqual(s.grade, "material")
        self.assertEqual(s.priority, 5)
        self.assertEqual(s.link, "https://example.com/n")
        self.assertIn("reason: @owl note", s.headline)
        self.assertIn("material move", s.judgment)

    def test_find_reason_prefers_note_then_calendar_then_sector(self):
        note = Note(date(2026, 9, 11), "@owl", "X", "something", None)
        cal = [CalendarEvent("X", date(2026, 9, 13), "earnings")]
        self.assertEqual(find_reason("X", AS_OF, 3.0, [note], cal, {}, {}, TH).kind, "note")
        self.assertEqual(find_reason("X", AS_OF, 3.0, [], cal, {}, {}, TH).kind, "calendar")
        sectors = {"semis": ["X", "Y"]}
        self.assertEqual(find_reason("X", AS_OF, 3.0, [], [], sectors, {"Y": 2.0}, TH).kind, "sector")
        self.assertIsNone(find_reason("X", AS_OF, 3.0, [], [], sectors, {"Y": -2.0}, TH))  # opposite direction
        self.assertIsNone(find_reason("X", AS_OF, 3.0, [], [], sectors, {"Y": None}, TH))  # peer did not trigger
        old = Note(date(2026, 9, 1), "@owl", "X", "stale", None)
        self.assertIsNone(find_reason("X", AS_OF, 3.0, [old], [], {}, {}, TH))

    def test_volume_spike_uses_trailing_average(self):
        vols = [100.0] * 20 + [200.0]
        self.assertTrue(rule_volume_spike("X", bars([1.0] * 21, vols), TH, "t").fired)
        vols[-1] = 199.0
        self.assertFalse(rule_volume_spike("X", bars([1.0] * 21, vols), TH, "t").fired)
        self.assertFalse(rule_volume_spike("X", bars([1.0] * 5, [1.0] * 5), TH, "t").fired)  # too little history

    def test_week52_high_and_low(self):
        closes = [50.0] * 30 + [60.0]
        s = rule_week52("X", bars(closes), TH, "t")
        self.assertEqual(s.rule, "week52_high")
        self.assertAlmostEqual(s.severity, 20.0)
        closes[-1] = 40.0
        self.assertEqual(rule_week52("X", bars(closes), TH, "t").rule, "week52_low")
        closes[-1] = 50.0
        self.assertFalse(rule_week52("X", bars(closes), TH, "t").fired)

    def test_earnings_within_window(self):
        events = [EarningsEvent("X", date(2026, 9, 18)), EarningsEvent("X", date(2026, 9, 1))]
        s = rule_earnings("X", events, AS_OF, TH, "cal")
        self.assertTrue(s.fired)
        self.assertIn("2026-09-18", s.fingerprint)
        self.assertEqual(s.severity, 0.0)  # calendar events never "worsen"
        self.assertFalse(rule_earnings("X", [EarningsEvent("X", date(2026, 9, 20))], AS_OF, TH, "cal").fired)
        self.assertFalse(rule_earnings("Y", events, AS_OF, TH, "cal").fired)

    def test_catalyst_is_separate_from_earnings(self):
        events = [CalendarEvent("X", date(2026, 9, 15), "protocol", "network upgrade")]
        self.assertFalse(rule_earnings("X", events, AS_OF, TH, "cal").fired)
        s = rule_catalyst("X", events, AS_OF, TH, "cal")
        self.assertTrue(s.fired)
        self.assertIn("network upgrade", s.headline)
        self.assertEqual(s.fingerprint, "X:catalyst_soon:protocol:2026-09-15")

    def test_voice_note_fires_while_fresh(self):
        note = Note(date(2026, 9, 11), "@owl", "X", "a note", "https://example.com/1")
        s = rule_voice_note(note, AS_OF, TH, "notes", move=2.0)
        self.assertTrue(s.fired)
        self.assertEqual((s.voice, s.link, s.subject), ("@owl", "https://example.com/1", "X"))
        self.assertIn("+2.0%", s.headline)
        self.assertFalse(rule_voice_note(Note(date(2026, 9, 9), "@owl", "X", "old", None), AS_OF, TH, "notes").fired)
        self.assertFalse(rule_voice_note(Note(date(2026, 9, 13), "@owl", "X", "future", None), AS_OF, TH, "notes").fired)

    def test_pnl_cross_only_on_crossing(self):
        pos = Position(qty=1, avg_cost=100.0, book="core")
        s = rule_pnl_cross("X", bars([119.0, 121.0]), pos, TH, "t")
        self.assertTrue(s.fired)
        self.assertEqual(s.book, "core")
        self.assertTrue(rule_pnl_cross("X", bars([81.0, 79.0]), pos, TH, "t").fired)
        self.assertFalse(rule_pnl_cross("X", bars([121.0, 125.0]), pos, TH, "t").fired)  # already above
        self.assertFalse(rule_pnl_cross("X", bars([110.0, 115.0]), pos, TH, "t").fired)

    def test_concentration_is_per_book_and_skips_single_position_books(self):
        cfg = config(["A", "B", "C"], {"A": Position(10, 1, "core"), "B": Position(1, 1, "core"), "C": Position(1, 1, "solo")})
        series = {"A": bars([10.0, 10.0]), "B": bars([10.0, 10.0]), "C": bars([10.0, 10.0])}
        by_ticker = {s.subject: s for s in rule_concentration(cfg, series, "t")}
        self.assertTrue(by_ticker["A"].fired)
        self.assertEqual(by_ticker["A"].book, "core")
        self.assertAlmostEqual(by_ticker["A"].value, 100 * 100 / 110)
        self.assertFalse(by_ticker["B"].fired)
        self.assertFalse(by_ticker["C"].fired)
        self.assertIn("only position in book solo", by_ticker["C"].why)
        self.assertEqual(weight_by_book(list(by_ticker.values()))["solo"]["C"], 1.0)

    def test_evaluate_returns_candidates_for_every_rule(self):
        cfg = config(["A", "B"], {"A": Position(1, 100.0)})
        src = MemorySource({"A": bars([100.0] * 21 + [110.0]), "B": bars([1.0])})
        sigs = evaluate(cfg, src, AS_OF)
        rules_a = {s.rule for s in sigs if s.subject == "A"}
        self.assertEqual(rules_a, {"daily_move", "volume_spike", "week52_high", "earnings_soon", "catalyst_soon",
                                   "pnl_cross", "concentration"})
        self.assertEqual([s.rule for s in sigs if s.subject == "B"], ["data", "earnings_soon", "catalyst_soon"])
        self.assertEqual({s.source for s in sigs if s.rule == "earnings_soon"}, {"memcal"})
        self.assertAlmostEqual(move_by_subject(sigs)["A"], 10.0)

    def test_evaluate_folds_volume_into_a_fired_move(self):
        closes = steady(31) + [0.0]
        closes[-1] = closes[-2] * 1.03
        vols = [100.0] * 31 + [300.0]
        sigs = {s.rule: s for s in evaluate(config(["A"]), MemorySource({"A": bars(closes, vols)}), AS_OF)}
        self.assertTrue(sigs["daily_move"].fired)
        self.assertFalse(sigs["volume_spike"].fired)
        self.assertIn("folded into daily_move", sigs["volume_spike"].why)

    def test_evaluate_attaches_voice_notes_and_sector_reasons(self):
        closes = steady(31) + [0.0]
        closes[-1] = closes[-2] * 1.03
        vols = [100.0] * 31 + [300.0]
        series = {"A": bars(closes, vols), "B": bars(closes, vols)}
        notes = [Note(date(2026, 9, 11), "@owl", "A", "note on A", None), Note(date(2026, 9, 11), "@owl", "ZZZ", "off list", None)]
        sigs = evaluate(config(["A", "B"], sectors={"s": ["A", "B"]}), MemorySource(series, notes=notes), AS_OF)
        by = {(s.subject, s.rule): s for s in sigs}
        self.assertEqual(by[("A", "daily_move")].grade, "material")   # note is the reason
        self.assertIn("@owl note", by[("A", "daily_move")].headline)
        self.assertEqual(by[("B", "daily_move")].grade, "material")   # sector proxy: A moved the same way
        self.assertIn("sector proxy s: A", by[("B", "daily_move")].headline)
        self.assertTrue(by[("A", "voice_take")].fired)
        self.assertEqual(by[("A", "voice_take")].voice, "@owl")
        self.assertNotIn(("ZZZ", "voice_take"), by)  # notes about tickers off the watchlist are ignored

    def test_calendar_only_markets_skip_price_rules(self):
        cfg = config(["A", "1234.HK"], markets={"HK": "calendar", "US": "realtime"})
        src = MemorySource({"A": bars([100.0] * 21 + [110.0]), "1234.HK": bars([1.0, 2.0])},
                           [CalendarEvent("1234.HK", date(2026, 9, 15))])
        sigs = evaluate(cfg, src, AS_OF)
        hk = {s.rule for s in sigs if s.subject == "1234.HK"}
        self.assertEqual(hk, {"earnings_soon", "catalyst_soon"})
        self.assertTrue(any(s.subject == "1234.HK" and s.fired for s in sigs))
        self.assertIn("daily_move", {s.rule for s in sigs if s.subject == "A"})


if __name__ == "__main__":
    unittest.main()
