import unittest

from digest import contract

GOOD = ("# Digest\n\nNet read: one thing.\n\n- **AAPL** · material move · Closed +6.2% at 232.15 · watch: volume · "
        "(source: fixture, 2026-09-11, link n/a)\n\n---\n" + contract.DISCLAIMER + "\n")


class ContractTests(unittest.TestCase):
    def test_compliant_text_passes(self):
        self.assertEqual(contract.validate(GOOD), [])
        self.assertEqual(contract.check(GOOD), GOOD)

    def test_rejects_forbidden_phrases(self):
        for phrase in ("This is a strong BUY.", "You should sell here.", "Price target: 300.", "Returns are guaranteed.",
                       "Time to take profit."):
            problems = contract.validate(GOOD + phrase + "\n")
            self.assertTrue(any(p.startswith("forbidden phrase") for p in problems), phrase)
        # Whole-word matching: "buyback" and "resell" are not recommendations.
        self.assertEqual(contract.validate(GOOD.replace("Closed", "Buyback announced, resell limits lifted; closed")), [])

    def test_rejects_technical_analysis_jargon(self):
        for phrase in ("RSI is at 80", "a golden cross formed", "stock is oversold", "broke the resistance level",
                       "above the 50-day moving average", "clean breakout"):
            problems = contract.validate(GOOD + phrase + "\n")
            self.assertTrue(any(p.startswith("technical-analysis jargon") for p in problems), phrase)
        self.assertEqual(contract.validate(GOOD.replace("Closed", "Average volume; closed")), [])  # "average" alone is fine

    def test_rejects_missing_citation(self):
        text = GOOD.replace(" (source: fixture, 2026-09-11, link n/a)", "")
        self.assertTrue(any("citation" in p or "source" in p for p in contract.validate(text)))
        with self.assertRaises(contract.ContractError):
            contract.check(text)
        # The old two-part citation is no longer enough: a link or the literal "link n/a" is required.
        self.assertTrue(contract.validate(GOOD.replace(", link n/a)", ")")))

    def test_citation_accepts_url_or_literal_link_na_only(self):
        with_url = GOOD.replace("link n/a", "https://example.com/note/1")
        self.assertEqual(contract.validate(with_url, known_links=["https://example.com/note/1"]), [])
        self.assertEqual(contract.validate(with_url), [])  # no allow-list given: any URL is syntactically fine
        self.assertTrue(contract.validate(GOOD.replace("link n/a", "no link")))
        # Several citations may trail one line (one per fact the line folds together).
        two = GOOD.replace("link n/a)", "link n/a) (source: cal, 2026-09-12, link n/a)")
        self.assertEqual(contract.validate(two), [])

    def test_rejects_fabricated_links(self):
        fabricated = GOOD.replace("link n/a", "https://example.com/made-up")
        problems = contract.validate(fabricated, known_links=[])
        self.assertTrue(any("fabricated" in p for p in problems))
        problems = contract.validate(GOOD + "See https://example.com/elsewhere for more.\n", known_links=[])
        self.assertTrue(any("fabricated" in p for p in problems))

    def test_rejects_missing_disclaimer(self):
        self.assertIn("missing disclaimer footer", contract.validate(GOOD.replace(contract.DISCLAIMER, "")))


if __name__ == "__main__":
    unittest.main()
