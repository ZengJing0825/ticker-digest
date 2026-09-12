# ticker-digest

An event-driven **watchlist daily digest** agent. Give it a watchlist (and,
optionally, your positions); it detects events worth telling you about,
applies frequency caps and de-duplication, enforces an output contract with
citations, and renders a Markdown digest — optionally polished by an LLM.

The default demo runs fully offline on bundled synthetic data.

> Not investment advice. The sample data is synthetic and the tool only
> reports rule-triggered facts about price, volume and calendar data.

## Design principles

**No event, no message.** A digest is written only when at least one rule
fires *and* survives the policy layer. A quiet day produces no file and a
single line on stdout. Push channels stay valuable only if silence is the
default.

**Frequency caps.** Attention is the scarce resource, so delivery is
budgeted at two levels: at most `max_signals_per_ticker` signals per ticker
per day (earlier runs the same day count) and at most
`max_tickers_per_digest` tickers per digest. When a cap binds, higher
priority rules win (P&L crossing > daily move > 52-week / earnings > volume
> concentration) and tickers are ranked by the weight of what survived.
Signals cut by the ticker cap are simply delivered in the next run; signals
cut by the daily budget wait for the next day.

**De-duplication.** Every signal has a *fingerprint* that defines what
"the same signal" means for that rule: a daily move is keyed by its data
date, a 52-week high or a concentration warning is keyed by ticker only, an
earnings reminder by the event date. Fingerprints of delivered signals are
persisted in `state/sent.json` and suppressed for `dedupe_days`. Running the
agent twice on a Saturday, or every day of a week while a stock sits at a
52-week high, does not repeat itself.

**Output contract.** `digest/contract.py` validates every digest before it
is written: each bullet ends with `(source: <name>, YYYY-MM-DD)`, a list of
forbidden phrases (price targets, buy/sell/should, guarantees) is rejected,
and the disclaimer footer must be present verbatim. The template renderer
always passes; an LLM rewrite is validated with the *same* function and
discarded on any violation, so the model can polish wording but cannot add
advice or drop citations.

**Position-aware.** With `positions` configured, two extra rules run:
unrealized P&L crossing `+/-pnl_pct` (a crossing, not a level, so it fires
once) and a single position exceeding `concentration_pct` of tracked
portfolio value.

**Pluggable sources.** A source implements two methods — daily bars for a
ticker and an events calendar. Rules, policy and rendering never touch a
provider directly.

## Quickstart

Requires Python 3.10+, `PyYAML` and `requests` (the `anthropic` package is
optional).

```bash
pip install -e .              # or: pip install pyyaml requests
python -m digest run --date 2026-09-12 --source fixture   # writes out/digest-2026-09-12.md
python -m digest run --date 2026-09-12 --source fixture   # second run: dedupe kicks in
python -m digest explain --date 2026-09-12 --source fixture
python -m digest reset-state
python -m unittest discover -s tests
```

`run` prints the digest and writes `out/digest-<date>.md` (a repeat run on
the same day gets a `-2`, `-3` … suffix). `explain` prints every evaluated
candidate with its threshold check and the policy decision (`kept`,
`threshold not met`, `dedupe: …`, `cap: …`) and never touches state.
`--date` is the run date; each ticker's latest bar on or before that date is
used, so a Saturday run digests Friday's close and cites Friday's date.

Online mode fetches daily CSVs from stooq.com (free, no key):

```bash
python -m digest run --source stooq
```

Stooq has no earnings endpoint, so calendar events still come from
`data/earnings_calendar.csv` and are cited as `local-calendar`. Any network
or payload problem degrades to "no data for that ticker" with a warning
(`-v` shows them) rather than an exception. Stooq sometimes serves a
JavaScript browser-verification page to scripted clients; the adapter sends
an honest `User-Agent`, detects that page and reports it — it does not try
to work around the check, so online mode may legitimately produce no data.

LLM polish is enabled automatically when `ANTHROPIC_API_KEY` is set and the
`anthropic` package is installed (`pip install -e ".[llm]"`); model
`claude-sonnet-5`. Pass `--no-llm` to force template mode. The rewrite is
re-validated by the contract and falls back to the template on API errors
or violations.

## Configuration (`watchlist.yaml`)

```yaml
tickers: [AAPL, NVDA, TSLA, MSFT, AMD, BTC-USD]
positions:                       # optional
  NVDA: {qty: 40, avg_cost: 100.0}
thresholds:                      # all optional; defaults shown
  move_pct: 5.0                  # abs daily close-to-close move, %
  volume_multiple: 2.0           # volume vs trailing average
  volume_window: 20              # sessions in that average
  week52_window: 252             # sessions defining the 52-week range
  earnings_days: 7               # look-ahead for scheduled earnings, calendar days
  pnl_pct: 20.0                  # unrealized P&L crossing, +/- %
  concentration_pct: 40.0        # single position share of tracked value, %
policy:                          # all optional; defaults shown
  max_signals_per_ticker: 2      # per ticker per day
  max_tickers_per_digest: 3
  dedupe_days: 7
```

Unknown keys raise a `ConfigError` so typos do not silently disable a rule.
CLI flags: `--config`, `--state` (default `state/sent.json`), `--data`
(default `data`), `--out` (default `out`), `-v`.

## Sample data (synthetic)

`data/sample/*.csv` holds 300 sessions per ticker (weekdays for equities,
ending Fri 2026-09-11; every day for BTC-USD, ending Sat 2026-09-12),
generated by `scripts/make_sample_data.py` from a fixed seed. Each file
starts with a comment marking it as synthetic. The last session is
engineered so that a run dated 2026-09-12 produces seven candidates across
four tickers: AAPL +6.2% on 3.2x volume; NVDA at a new 52-week high with a
position P&L crossing +20% and 66% concentration; AMD and MSFT earnings
within 7 days. That is enough for both caps and the dedupe to visibly
trigger. The generator re-runs the package's own rules and asserts this
scenario, so regenerating cannot silently drift.

## Adding a source

Subclass `digest.sources.base.DataSource`, set `name` (and `calendar_name`
if calendar data comes from elsewhere), and implement:

```python
def daily_bars(self, ticker: str, end: date) -> list[Bar]: ...   # oldest first, <= end
def earnings_calendar(self) -> list[EarningsEvent]: ...
```

Return an empty list on failure instead of raising. Register the source in
`build_source()` in `digest/cli.py`. `parse_bars_csv` handles the common
`Date,Open,High,Low,Close,Volume` layout.

## Adding a rule

Write a function in `digest/signals.py` that returns a `Signal` for both the
fired and the non-fired case (`fired`, plus a one-line `why` for `explain`),
choose a `priority` and a `fingerprint` that captures what "identical"
means for the rule, and call it from `evaluate()`. Headlines must not
contain the citation (the renderer appends it) or any phrase in
`contract.FORBIDDEN_PHRASES`; the contract check will refuse to render
otherwise.

## Layout

```
digest/           config, signals, policy, contract, render, llm, cli
digest/sources/   base (interface + CSV parsers), fixture (offline), stooq (online)
data/             synthetic sample CSVs and earnings calendar
scripts/          deterministic sample-data generator
tests/            unittest suite
```

## License

MIT — see `LICENSE`.
