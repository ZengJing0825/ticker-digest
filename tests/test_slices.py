import unittest

from digest.slices import SliceContext, build_groups, group_keys, quiet_subjects
from tests.helpers import signal


class SliceTests(unittest.TestCase):
    def setUp(self):
        self.ctx = SliceContext(books={"core": ["A", "B"], "crypto": ["C"]},
                                moves={"A": 1.0, "B": -4.0, "C": 0.5},
                                weights={"core": {"A": 0.7, "B": 0.3}, "crypto": {"C": 1.0}},
                                universe=["A", "B", "C", "D"])

    def test_group_keys_per_slice(self):
        price = signal("A", "daily_move", 4)
        note = signal("A", "voice_take", 2, voice="@owl")
        pos = signal("B", "pnl_cross", 5, book="core")
        self.assertEqual(group_keys(price, "ticker", self.ctx), ["A"])
        self.assertEqual(group_keys(price, "person", self.ctx), [])
        self.assertEqual(group_keys(note, "person", self.ctx), ["@owl"])
        self.assertEqual(group_keys(price, "book", self.ctx), ["core"])   # joins the book that holds A
        self.assertEqual(group_keys(pos, "book", self.ctx), ["core"])
        self.assertEqual(group_keys(signal("D", "daily_move"), "book", self.ctx), [])  # not held anywhere

    def test_ticker_slice_ranks_by_event_priority_then_name(self):
        groups = build_groups([signal("B", "r", 1), signal("A", "r", 1), signal("C", "r", 5)], "ticker", self.ctx)
        self.assertEqual([g.key for g in groups], ["C", "A", "B"])

    def test_book_slice_ranks_risk_lines_first_then_weight_times_move(self):
        sigs = [signal("A", "daily_move", 4), signal("B", "daily_move", 4), signal("C", "daily_move", 4)]
        groups = build_groups(sigs, "book", self.ctx)
        core = next(g for g in groups if g.key == "core")
        # A: 0.7 x 1.0 = 0.7 < B: 0.3 x 4.0 = 1.2 -> B first, despite equal priority and later name.
        self.assertEqual([ln.subject for ln in core.lines], ["B", "A"])
        self.assertEqual(core.lines[0].score, (0.0, 1.2, 4.0))
        # Add a risk line for A: risk lines outrank weight x move.
        groups = build_groups(sigs + [signal("A", "concentration", 1, book="core")], "book", self.ctx)
        core = next(g for g in groups if g.key == "core")
        self.assertEqual([ln.subject for ln in core.lines], ["A", "B"])
        self.assertEqual(core.lines[0].score[0], 1.0)
        # Price signals joining a book are stamped with it.
        self.assertTrue(all(s.book == "core" for s in core.signals))

    def test_person_slice_groups_by_voice(self):
        sigs = [signal("A", "voice_take", 2, voice="@owl"), signal("B", "voice_take", 2, voice="@owl"),
                signal("A", "voice_take", 2, voice="@fox"), signal("A", "daily_move", 4)]
        groups = build_groups(sigs, "person", self.ctx)
        self.assertEqual([g.key for g in groups], ["@owl", "@fox"])  # @owl has more weight
        self.assertEqual([ln.subject for ln in groups[0].lines], ["A", "B"])
        self.assertEqual(sum(len(g.signals) for g in groups), 3)  # the price signal is not an opinion

    def test_quiet_subjects_are_the_universe_minus_shown(self):
        groups = build_groups([signal("A", "r"), signal("C", "r")], "ticker", self.ctx)
        self.assertEqual(quiet_subjects(groups, self.ctx, "ticker"), ["B", "D"])
        ctx = SliceContext(universe=["@owl", "@fox"])
        groups = build_groups([signal("A", "voice_take", voice="@owl")], "person", ctx)
        self.assertEqual(quiet_subjects(groups, ctx, "person"), ["@fox"])


if __name__ == "__main__":
    unittest.main()
