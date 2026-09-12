import unittest

from digest.markets import is_calendar_only, market_of, tier_of


class MarketTests(unittest.TestCase):
    def test_market_inferred_from_suffix(self):
        self.assertEqual(market_of("AAPL"), "US")
        self.assertEqual(market_of("BTC-USD"), "CRYPTO")
        self.assertEqual(market_of("0700.hk"), "HK")
        self.assertEqual(market_of("7203.T"), "JP")
        self.assertEqual(market_of("005930.KS"), "KR")

    def test_tier_defaults_to_realtime_when_market_not_configured(self):
        markets = {"HK": "calendar", "US": "realtime"}
        self.assertEqual(tier_of("0700.HK", markets), "calendar")
        self.assertEqual(tier_of("7203.T", markets), "realtime")
        self.assertTrue(is_calendar_only("0700.HK", markets))
        self.assertFalse(is_calendar_only("AAPL", markets))
        self.assertFalse(is_calendar_only("0700.HK", {}))


if __name__ == "__main__":
    unittest.main()
