import unittest

from digest import contract

GOOD = "# Digest\n\n## AAPL\n- Closed +6.2% at 232.15 (source: fixture, 2026-09-11)\n\n---\n" + contract.DISCLAIMER + "\n"


class ContractTests(unittest.TestCase):
    def test_compliant_text_passes(self):
        self.assertEqual(contract.validate(GOOD), [])
        self.assertEqual(contract.check(GOOD), GOOD)

    def test_rejects_forbidden_phrases(self):
        for phrase in ("This is a strong BUY.", "You should sell here.", "Price target: 300.", "Returns are guaranteed."):
            problems = contract.validate(GOOD + phrase + "\n")
            self.assertTrue(any(p.startswith("forbidden phrase") for p in problems), phrase)
        # Whole-word matching: "buyback" and "oversold" are not recommendations.
        self.assertEqual(contract.validate(GOOD.replace("Closed", "Buyback announced, stock oversold; closed")), [])

    def test_rejects_missing_citation(self):
        text = GOOD.replace(" (source: fixture, 2026-09-11)", "")
        self.assertTrue(any("citation" in p or "source" in p for p in contract.validate(text)))
        with self.assertRaises(contract.ContractError):
            contract.check(text)

    def test_rejects_missing_disclaimer(self):
        self.assertIn("missing disclaimer footer", contract.validate(GOOD.replace(contract.DISCLAIMER, "")))


if __name__ == "__main__":
    unittest.main()
