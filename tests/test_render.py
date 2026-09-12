import unittest
from unittest import mock

from digest import contract, llm, render
from tests.helpers import AS_OF, signal


class RenderTests(unittest.TestCase):
    def test_template_output_passes_contract(self):
        text = render.render_markdown([signal("NVDA", "week52_high"), signal("AAPL", "daily_move")], AS_OF)
        self.assertEqual(contract.validate(text), [])
        self.assertLess(text.index("## NVDA"), text.index("## AAPL"))  # policy order is preserved
        self.assertIn("(source: test, 2026-09-12)", text)

    def test_build_digest_falls_back_when_llm_breaks_contract(self):
        sigs = [signal("AAPL", "daily_move")]
        template = render.render_markdown(sigs, AS_OF)
        with mock.patch.object(llm, "polish", return_value="You should buy AAPL."):
            self.assertEqual(render.build_digest(sigs, AS_OF, use_llm=True), template)
        with mock.patch.object(llm, "polish", return_value=None):  # API failure
            self.assertEqual(render.build_digest(sigs, AS_OF, use_llm=True), template)
        polished = template.replace("AAPL daily_move", "AAPL had a notable daily move")
        with mock.patch.object(llm, "polish", return_value=polished):
            self.assertEqual(render.build_digest(sigs, AS_OF, use_llm=True), polished)


if __name__ == "__main__":
    unittest.main()
