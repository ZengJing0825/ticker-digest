import tempfile
import unittest
from datetime import date
from pathlib import Path

import requests

from digest.config import ConfigError, load_config
from digest.sources import FixtureSource, StooqSource
from digest.sources.base import parse_earnings_csv, parse_notes_csv
from digest.sources.stooq import stooq_symbol

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text, self.status = text, status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise requests.HTTPError(f"status {self.status}")


class FakeSession:
    def __init__(self, response=None, exc=None) -> None:
        self.response, self.exc, self.headers = response, exc, {}

    def get(self, url, timeout):
        if self.exc:
            raise self.exc
        return self.response


class SourceTests(unittest.TestCase):
    def test_fixture_reads_bundled_synthetic_data(self):
        src = FixtureSource(ROOT / "data")
        bars = src.daily_bars("AAPL", date(2026, 9, 12))
        self.assertEqual(len(bars), 300)  # well over the 30 sessions the relative threshold needs
        self.assertEqual(bars[-1].date, date(2026, 9, 11))
        self.assertEqual(src.daily_bars("ZZZZ", date(2026, 9, 12)), [])
        self.assertTrue(any(e.ticker == "AMD" and e.kind == "earnings" for e in src.earnings_calendar()))
        self.assertTrue(any(e.ticker == "BTC-USD" and e.kind == "protocol" for e in src.earnings_calendar()))
        notes = src.notes()
        self.assertTrue(notes)
        self.assertTrue(all(n.voice.startswith("@") for n in notes))
        self.assertIn("https://example.com/notes/quiet-compounder/2026-09-10", {n.link for n in notes})

    def test_notes_and_calendar_parsers(self):
        notes = parse_notes_csv("# synthetic\ndate,voice,ticker,headline,link\n"
                                "2026-09-11,@owl,aapl,Hello,link n/a\n2026-09-10,@fox,MSFT,Hi,https://example.com/x\nbad,row\n")
        self.assertEqual([(n.voice, n.ticker, n.link) for n in notes],
                         [("@fox", "MSFT", "https://example.com/x"), ("@owl", "AAPL", None)])
        events = parse_earnings_csv("ticker,date\nAMD,2026-09-16\n")  # legacy two-column layout still works
        self.assertEqual((events[0].kind, events[0].note), ("earnings", ""))

    def test_stooq_symbol_mapping(self):
        self.assertEqual(stooq_symbol("AAPL"), "aapl.us")
        self.assertEqual(stooq_symbol("BTC-USD"), "btcusd")

    def test_stooq_fails_gracefully(self):
        cal = ROOT / "data" / "earnings_calendar.csv"
        self.assertEqual(StooqSource(cal, session=FakeSession(exc=requests.ConnectionError("down"))).daily_bars("AAPL", date.today()), [])
        self.assertEqual(StooqSource(cal, session=FakeSession(FakeResponse("<html>limit</html>"))).daily_bars("AAPL", date.today()), [])
        self.assertEqual(StooqSource(cal, session=FakeSession(FakeResponse("", 503))).daily_bars("AAPL", date.today()), [])
        challenge = "<html><noscript>This site requires JavaScript to verify your browser.</noscript></html>"
        self.assertEqual(StooqSource(cal, session=FakeSession(FakeResponse(challenge))).daily_bars("AAPL", date.today()), [])
        good = FakeSession(FakeResponse("Date,Open,High,Low,Close,Volume\n2026-09-10,1,2,0.5,1.5,100\n2026-09-11,1.5,2,1,1.8,120\n"))
        src = StooqSource(cal, session=good)
        bars = src.daily_bars("AAPL", date(2026, 9, 10))
        self.assertEqual([b.close for b in bars], [1.5])  # respects the ``end`` cutoff
        self.assertTrue(src.notes())  # voices.csv next to the calendar
        self.assertEqual(src.notes_name, "local-notes")

    def test_config_defaults_and_validation(self):
        cfg = load_config(ROOT / "watchlist.yaml")
        self.assertIn("BTC-USD", cfg.tickers)
        self.assertEqual(cfg.positions["NVDA"].avg_cost, 100.0)
        self.assertEqual(cfg.positions["NVDA"].book, "core")
        self.assertEqual(cfg.books(), {"core": ["NVDA", "TSLA"], "crypto": ["BTC-USD"]})
        self.assertEqual(cfg.positions_updated_at, date(2026, 8, 20))
        self.assertEqual(cfg.markets["HK"], "calendar")
        self.assertEqual(cfg.sectors["semis"], ["NVDA", "AMD"])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "w.yaml"
            p.write_text("tickers: [aapl]\n")
            cfg = load_config(p)
            self.assertEqual(cfg.tickers, ["AAPL"])
            self.assertEqual(cfg.policy.dedupe_days, 7)
            self.assertEqual(cfg.policy.escalation_pp, 1.5)
            self.assertEqual(cfg.thresholds.move_k, 2.0)
            self.assertIsNone(cfg.positions_updated_at)
            self.assertEqual(cfg.markets, {})
            p.write_text("tickers: [AAPL]\npositions: {AAPL: {qty: 1, avg_cost: 1}}\n")  # legacy flat positions
            self.assertEqual(load_config(p).positions["AAPL"].book, "default")
            for bad in ("tickers: [AAPL]\nthresholds: {mov_pct: 3}\n",
                        "tickers: [AAPL]\nmarkets: {HK: intraday}\n",
                        "tickers: [AAPL]\npositions: {updated_at: soon}\n",
                        "tickers: [AAPL]\nsector: {}\n"):
                p.write_text(bad)
                with self.assertRaises(ConfigError, msg=bad):
                    load_config(p)


if __name__ == "__main__":
    unittest.main()
