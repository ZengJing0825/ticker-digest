import unittest
from unittest import mock

from digest import contract, llm, render
from digest.slices import SliceContext, build_groups
from tests.helpers import AS_OF, signal


def groups(*sigs, kind="ticker", ctx=None):
    return build_groups(list(sigs), kind, ctx)


class RenderTests(unittest.TestCase):
    def test_template_output_passes_contract_and_keeps_policy_order(self):
        ctx = SliceContext(universe=["NVDA", "AAPL", "TSLA"])
        text = render.render_markdown(groups(signal("NVDA", "week52_high", 3), signal("AAPL", "daily_move", 4)), AS_OF, "ticker", ctx)
        self.assertEqual(contract.validate(text), [])
        self.assertLess(text.index("**AAPL**"), text.index("**NVDA**"))  # slice ranking: higher priority first
        self.assertIn("(source: test, 2026-09-12, link n/a)", text)
        self.assertIn("# Watchlist digest - 2026-09-12", text)
        self.assertIn("+1 more quiet: TSLA", text)

    def test_one_line_per_subject_with_judgment_why_watch_source(self):
        a = signal("AAPL", "daily_move", 5, judgment="material move", watch="volume next session",
                   link="https://example.com/a")
        b = signal("AAPL", "voice_take", 2, voice="@owl", judgment="opinion", watch="confirmation")
        text = render.render_markdown(groups(a, b), AS_OF)
        lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertTrue(line.startswith("- **AAPL** · material move · AAPL daily_move; AAPL voice_take · watch: volume next session · "))
        self.assertIn("(source: test, 2026-09-12, https://example.com/a)", line)
        self.assertIn("(source: test, 2026-09-12, link n/a)", line)  # a second citation for the second fact
        self.assertEqual(contract.validate(text, ["https://example.com/a"]), [])

    def test_net_read_and_quiet_tail(self):
        ctx = SliceContext(universe=["A", "B", "C"])
        text = render.render_markdown(groups(signal("A", "daily_move", 4, judgment="material move")), AS_OF, "ticker", ctx)
        self.assertIn("Net read: 1 of 3 tickers have something real for 2026-09-12; A leads (material move); 2 quiet.", text)
        self.assertIn("+2 more quiet: B, C", text)
        empty = render.render_markdown([], AS_OF, "ticker", ctx)
        self.assertIn("Net read: nothing crossed a threshold", empty)

    def test_top_lines_cap_and_overflow_counted_as_quiet(self):
        sigs = [signal(f"T{i:02d}", "daily_move", 10 - i) for i in range(10)]
        ctx = SliceContext(universe=[s.subject for s in sigs] + ["Z"])
        text = render.render_markdown(groups(*sigs), AS_OF, "ticker", ctx, max_lines=8)
        self.assertEqual(sum(1 for ln in text.splitlines() if ln.startswith("- ")), 8)
        self.assertIn("+3 more quiet: T08, T09, Z", text)

    def test_calendar_badge_group_headers_and_stale_footer(self):
        ctx = SliceContext(books={"core": ["NVDA", "TSLA"]}, calendar_only=["1234.HK"], universe=["NVDA", "TSLA"])
        sigs = [signal("NVDA", "pnl_cross", 5, book="core"), signal("1234.HK", "earnings_soon", 3, book="core")]
        text = render.render_markdown(groups(*sigs, kind="book", ctx=ctx), AS_OF, "book", ctx, stale_days=23)
        self.assertIn("# Portfolio digest", text)
        self.assertIn("## core", text)
        self.assertIn("- **1234.HK** [calendar-only] ·", text)
        self.assertIn("positions last updated 23 days ago — reconnect or re-enter", text)
        self.assertEqual(contract.validate(text), [])
        person = render.render_markdown(groups(signal("A", "voice_take", 2, voice="@owl"), kind="person"), AS_OF, "person",
                                        SliceContext(universe=["@owl", "@fox"]))
        self.assertIn("# Opinion digest", person)
        self.assertIn("## @owl", person)
        self.assertIn("@owl on A leads", person)
        self.assertIn("+1 more quiet: @fox", person)

    def test_build_digest_falls_back_when_llm_breaks_contract(self):
        g = groups(signal("AAPL", "daily_move", link="https://example.com/a"))
        template = render.render_markdown(g, AS_OF)
        with mock.patch.object(llm, "polish", return_value="You should buy AAPL."):
            self.assertEqual(render.build_digest(g, AS_OF, use_llm=True), template)
        with mock.patch.object(llm, "polish", return_value=None):  # API failure
            self.assertEqual(render.build_digest(g, AS_OF, use_llm=True), template)
        jargon = template.replace("AAPL daily_move", "AAPL had a clean breakout")
        with mock.patch.object(llm, "polish", return_value=jargon):
            self.assertEqual(render.build_digest(g, AS_OF, use_llm=True), template)
        invented = template.replace("https://example.com/a", "https://example.com/not-in-the-data")
        with mock.patch.object(llm, "polish", return_value=invented):
            self.assertEqual(render.build_digest(g, AS_OF, use_llm=True), template)
        polished = template.replace("AAPL daily_move", "AAPL had a notable daily move")
        with mock.patch.object(llm, "polish", return_value=polished):
            self.assertEqual(render.build_digest(g, AS_OF, use_llm=True), polished)


if __name__ == "__main__":
    unittest.main()
