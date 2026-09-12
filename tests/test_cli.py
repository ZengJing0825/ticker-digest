"""End-to-end runs of the CLI against the bundled synthetic data, in a temporary out/state."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from digest import contract
from digest.cli import main

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out, self.state, self.audit = self.dir / "out", self.dir / "state" / "sent.json", self.dir / "state" / "audit"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = main(["--config", str(ROOT / "watchlist.yaml"), "--state", str(self.state), "--audit", str(self.audit),
                         *argv])
        return code, buf.getvalue(), err.getvalue()

    def common(self, cmd, date, clock="09:00", *extra):
        return [cmd, "--date", date, "--now", f"{date}T{clock}", "--data", str(ROOT / "data"), "--out", str(self.out), *extra]

    def test_three_slices_from_one_candidate_set(self):
        code, ticker, _ = self.run_cli(*self.common("run", "2026-09-12", "09:00", "--no-llm"))
        self.assertEqual(code, 0)
        self.assertIn("# Watchlist digest - 2026-09-12", ticker)
        self.assertIn("Net read:", ticker)
        self.assertIn("- **NVDA** · risk line", ticker)
        self.assertIn("- **AAPL** · material move", ticker)
        self.assertIn("reason: @ledger_owl note", ticker)
        self.assertIn("+5 more quiet:", ticker)
        self.assertIn("positions last updated 23 days ago — reconnect or re-enter", ticker)
        self.assertEqual(contract.validate(ticker.split("[written")[0]), [])
        _, person, _ = self.run_cli(*self.common("run", "2026-09-12", "09:00", "--slice", "person", "--no-llm"))
        self.assertIn("# Opinion digest", person)
        self.assertIn("## @ledger_owl", person)
        self.assertIn("https://example.com/notes/quiet-compounder/2026-09-10", person)
        self.assertNotIn("positions last updated", person)
        _, book, _ = self.run_cli(*self.common("run", "2026-09-12", "09:00", "--slice", "book", "--no-llm"))
        self.assertIn("# Portfolio digest", book)
        self.assertIn("## core", book)
        self.assertIn("## crypto", book)
        self.assertIn("+1 more quiet: TSLA", book)
        self.assertTrue((self.out / "digest-2026-09-12.md").exists())
        self.assertTrue((self.out / "digest-2026-09-12-person.md").exists())
        self.assertTrue((self.out / "digest-2026-09-12-book.md").exists())
        state = json.loads(self.state.read_text())
        self.assertEqual(set(state), {"ticker", "person", "book"})

    def test_quiet_day_dedupe_leftovers_and_calendar_badge(self):
        _, first, _ = self.run_cli(*self.common("run", "2026-09-02", "09:00", "--no-llm"))
        self.assertIn("- **NVDA** · risk line: 65% of book core", first)
        code, quiet, _ = self.run_cli(*self.common("run", "2026-09-03", "09:00", "--no-llm"))
        self.assertEqual(code, 0)
        self.assertEqual(quiet.strip(), "No new events for 2026-09-03 (ticker slice); no digest written.")
        self.assertFalse((self.out / "digest-2026-09-03.md").exists())
        record = json.loads((self.audit / "2026-09-03.json").read_text())["runs"][-1]
        self.assertTrue(record["why_no_push"].startswith("all 1 fired candidate(s) were suppressed (dedupe 1)"))
        self.assertEqual(len(record["dedupe_hits"]), 1)
        # The eventful day: three tickers kept; a same-day re-run delivers the capped leftovers, badge included.
        _, second, _ = self.run_cli(*self.common("run", "2026-09-12", "09:00", "--no-llm"))
        _, rerun, _ = self.run_cli(*self.common("run", "2026-09-12", "09:30", "--no-llm"))
        self.assertIn("- **0700.HK** [calendar-only] · earnings in 3 days", rerun)
        self.assertNotIn("**NVDA**", rerun.split("+5 more quiet")[0])
        self.assertTrue((self.out / "digest-2026-09-12-2.md").exists())

    def test_propose_then_publish_approved_is_dry_by_default(self):
        code, out, _ = self.run_cli(*self.common("propose", "2026-09-12"))
        self.assertEqual(code, 0)
        proposal = self.out / "proposals" / "2026-09-12.md"
        self.assertTrue(proposal.exists())
        text = proposal.read_text()
        self.assertIn("`AMD:earnings_soon:2026-09-16` AMD earnings_soon — policy: cap: max 3 tickers per digest", text)
        # Nothing approved yet.
        code, out, err = self.run_cli(*self.common("publish", "2026-09-12", "09:00", "--approved"))
        self.assertEqual(code, 0)
        self.assertIn("nothing approved", out)
        # Approve a capped item: the human override wins, but publish stays dry by default.
        proposal.write_text(text.replace("- [ ] `AMD:earnings_soon:2026-09-16`", "- [x] `AMD:earnings_soon:2026-09-16`"))
        code, out, err = self.run_cli(*self.common("publish", "2026-09-12", "09:00", "--approved", "--no-llm"))
        self.assertEqual(code, 0)
        self.assertIn("- **AMD** · earnings in 4 days", out)
        self.assertNotIn("**NVDA**", out)
        self.assertIn("dry-run", err)
        self.assertFalse(self.state.exists())
        self.assertFalse((self.out / "digest-2026-09-12.md").exists())
        # --send delivers: file written, state recorded, audit says so.
        code, out, err = self.run_cli(*self.common("publish", "2026-09-12", "09:00", "--approved", "--send", "--no-llm"))
        self.assertIn("published", err)
        self.assertTrue((self.out / "digest-2026-09-12.md").exists())
        self.assertIn("AMD:earnings_soon:2026-09-16", json.loads(self.state.read_text())["ticker"])
        runs = json.loads((self.audit / "2026-09-12.json").read_text())["runs"]
        self.assertEqual([r["command"] for r in runs], ["propose", "publish", "publish", "publish"])
        self.assertEqual(runs[-1]["delivered"], ["AMD:earnings_soon:2026-09-16"])
        self.assertIsNone(runs[-1]["why_no_push"])
        self.assertTrue(runs[-2]["dry"])
        self.assertEqual(runs[1]["why_no_push"], "no item in the proposal file is marked approved")

    def test_publish_without_approved_uses_policy_and_explain_never_touches_state(self):
        code, out, err = self.run_cli(*self.common("publish", "2026-09-12", "09:00", "--no-llm"))
        self.assertEqual(code, 0)
        self.assertIn("# Watchlist digest", out)
        self.assertIn("dry-run", err)
        code, out, _ = self.run_cli(*self.common("explain", "2026-09-12"))
        self.assertIn("slice: ticker", out)
        self.assertIn("folded into daily_move", out)
        self.assertFalse(self.state.exists())
        record = json.loads((self.audit / "2026-09-12.json").read_text())["runs"][0]
        self.assertEqual(record["thresholds"]["typical_window"], 30)
        self.assertIn("rendered", record)
        self.assertEqual(record["markets"]["HK"], "calendar")

    def test_missing_proposal_is_an_error(self):
        code, _, err = self.run_cli(*self.common("publish", "2026-09-12", "09:00", "--approved"))
        self.assertEqual(code, 2)
        self.assertIn("run `propose` first", err)


if __name__ == "__main__":
    unittest.main()
