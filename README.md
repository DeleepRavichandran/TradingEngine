# TradingEngine

### Standalone Codex Fundamental Analysis Agent

Run `solo.py` to use the Codex strategy by itself. It receives completed candles,
financial disclosures, calendar events and headlines. It runs a second copy of
the same chart strategy with the overlay disabled and records both ledgers.
The shared contest runner is not involved.

**Try the complete example** (Python 3.10+, from this checkout). All company
figures, headlines, event times and prices in this example are invented.

```sh
mkdir -p runs/fundamental-demo
python ingest.py examples/fundamentals/sources.json --db runs/fundamental-demo/data.db --archived-receipt 2026-11-25T09:40:00+05:30
SYMBOLS=RELIANCE,HDFCBANK,INFY,ICICIBANK,TCS
python fixture.py 2026-11-25 "$SYMBOLS" | python solo.py --mode replay --day 2026-11-25 --symbols "$SYMBOLS" --db runs/fundamental-demo/data.db --wallet runs/fundamental-demo/wallet.sqlite --journal runs/fundamental-demo/session.jsonl
python -m unittest discover -s tests -v
```

**Supply your own sources.** Each entry in the JSON configuration has a source
label, an HTTPS URL or local file under `input`, and a kind. File paths are relative
to the config. Use a fresh journal filename for every session.

| Kind | Input | Effect on new entries |
|---|---|---|
| Filing | XBRL instance with two unsegmented INR duration contexts for the same issuer: current and prior-year comparable period. Configure the issuer symbol, actual public release time, title, both context IDs and the revenue and profit element names. | Veto when revenue falls more than 5% and net margin falls more than two percentage points. Reports expire after 125 days. |
| Macro | CSV with symbol (or *), title, published, scheduled, impact. Supply actual schedule-announcement timestamps, including a UTC offset. | Pause entries from 15 minutes before through 15 minutes after a known high-impact event. |
| News | RSS or Atom with timezone-aware publication timestamps. Use a company-specific feed for a company symbol or * for market-wide coverage. | A negative balance of matched English headline phrases in the last 24 hours halves entry sizing. Unmatched headlines carry zero directional weight. |
| Behaviour | Five-minute price movement with latest volume relative to the preceding 20-minute median. | Halve entry sizing during a high-volume selloff or crowded advance. These are observable proxies; the program cannot measure an investor's emotions. |

These initial thresholds are research assumptions. Existing risk limits and exit
rules still apply. Empty external coverage leaves the external component neutral.
The journal records new source events, publication and receipt times, reasons,
financial ratios, target shares and fills. Each minute also records the chart-only
target on the fundamental account's **same holdings** to isolate the immediate decision.
Source configuration, comparable periods and issuer mapping are operator supplied.
Current support covers numeric XBRL instance facts, dated headline text and calendar
CSV. PDF/OCR, inline XBRL, automated filing discovery, and full-text sentiment models
are outside this version.

**Forward collection:** change the config to your authorised sources and run
`python ingest.py sources.json --db runs/live.db --every 120`. A working public
headline source is included in `examples/fundamentals/public-news.json`.
The collector commits each source independently and reports feed errors to stderr.
Backfilled observations entered with `--archived-receipt` are available only in
replay. Forward collection uses the local UTC receipt time. The agent includes an
event only once both publication and receipt are at or before the candle close.
Use an accurate system clock. Run the existing licensed minute feed with the same
symbols, piping it into `python solo.py --mode forward --day YYYY-MM-DD --symbols
"$SYMBOLS" --db runs/live.db --journal runs/SESSION.jsonl`. The solo trader starts with ₹1,00,000 once. Run from the same checkout or pass
the same absolute `--wallet` path each day (default `runs/solo-wallet.sqlite`).
Completed sessions carry cash after fees into the next date. Replay and forward
balances are separate. The chart-only ledger is a hypothetical comparison and
adds no buying power. Profits stay on the ledger; new orders are sized against
the lower of current equity and ₹1 lakh. The existing 80% gross and 20% per-stock
limits also apply. The daily loss halt uses that session's opening balance.
A wallet starts a new series and does not import older single-day demo journals. A late or incomplete feed leaves a partial journal without a
completion record. This release does not send broker orders.


An independent, long-only NSE intraday paper trader and a common referee for a
Codex vs Claude forward contest. Python 3.10+; standard library only.

### Run the synthetic demonstration

From the Git checkout, use Bash or an equivalent shell. Each freeze needs a new directory.

```sh
export SYMBOLS=RELIANCE,HDFCBANK,INFY,ICICIBANK,TCS
python -m unittest discover -s tests -v
python contest.py freeze --mode replay --days 2026-11-25 --symbols "$SYMBOLS" --dir runs/demo --claude-file bots/cash.py
python fixture.py 2026-11-25 "$SYMBOLS" | python contest.py session --day 2026-11-25 --dir runs/demo
python contest.py score --dir runs/demo
```

The demo uses artificial prices and a cash control. Replay always reports a null weekly winner.
For licensed historical minute data, stream the same JSON-lines format into a replay session.

### Freeze the weekly contest before its first market open

Both entrants provide **one trusted, standalone standard-library Python strategy file** in a Git
checkout. Replace the Claude checkout path, revision and file below with the actual entry. Both
sides review the referee and archive the printed manifest before starting. The referee freezes
the Git revisions, exact submitted source bytes, watchlist, ordered dates and engine hashes.

```sh
python contest.py freeze --mode forward --dir runs/week --days 2026-11-25,2026-11-26,2026-11-27 --symbols "$SYMBOLS" --claude-repo ../ClaudeEngine --claude-rev HEAD --claude-file bots/contest_entry.py
```

On **each** frozen date, start the pipeline before 09:15 IST with a currently authorised
Kite Connect market-data session. Supply KITE_API_KEY and KITE_ACCESS_TOKEN locally.
The code calls only GET instrument-master and historical-minute endpoints. Actual broker
access, candle availability and network latency depend on the operator's subscription.
Use a small watchlist for sequential polling. Confirm the two opponents have the same input.

```sh
DAY=2026-11-25   # set to today's frozen session
set -o pipefail
python kite_feed.py --day "$DAY" --symbols "$SYMBOLS" | python contest.py session --day "$DAY" --dir runs/week
python contest.py score --dir runs/week
```

A different authorised provider can pipe the same feed. Each line is one complete minute,
end-stamped in IST, with every frozen symbol. Each bar is [open, high, low, close, volume];
prices are **integer paise** and volume is shares. First close 09:16, last close 15:30.

```json
{"close":"2026-11-25T09:16:00+05:30","bars":{"RELIANCE":[10000,10010,9990,10005,25000]}}
```

### Strategy contract and referee rules

- Each decision runs in a fresh Python interpreter. Read one JSON object from stdin with
  close, history (list of complete symbol-to-bar maps), cash, equity, positions and halted.
  Print one JSON map of symbol to **target shares**. An omitted symbol has no new instruction.
  A zero target requests an exit. Strategy files are trusted participant code, not sandboxed.
  Use an isolated operator account with no writable shared contest files for untrusted code;
  this version is for cooperative entrants.
- The Codex entry looks for a pullback and recovery in a rising stock when at least 60%
  of the watchlist trades above its opening price. It ranks momentum relative to recent
  candle ranges, sizes down in volatility, and exits on deteriorating breadth or trend.
  It can stay entirely in cash. The strategy parameters have no verified real-market edge.
- ₹1 lakh each, capital carried between days, only whole shares, 20% per stock and 80%
  gross exposure checked when increasing risk. Exits have priority. All entrants get
  their own identical 1% volume allowance. Orders are immediate-or-cancel at their
  eligible bar. Spread/slippage is modelled at 5 bps per side, rounded adversely to
  one paisa. This is a contest execution price, not an exchange tick-level fill.
- Both decide after a completed candle. For a 09:16 close received at 09:16:02, the first
  eligible open is **09:17**, represented by the 09:18 end-stamped bar. The intervening
  open at 09:16 has already passed. Every forward frame must arrive within 20 seconds.
  A decision that misses its eligible open invalidates the session. Each bot gets 3 seconds.
- Fees model intraday brokerage (0.03%, capped at ₹20 per executed IOC), sell-side STT,
  NSE transaction charges, GST, SEBI fees and buy-side stamp duty. Rates in referee.py
  are frozen contest assumptions. Charges are rounded up to paise per component and
  exclude broker-specific extras. [Reference schedule](https://zerodha.com/charges/).
- At a 2% opening-equity loss measured at candle opens or closes, cancel entries and
  liquidate at available volume. Slippage or gaps can take the realised loss beyond 2%.
  Forced liquidation starts at 15:15, with retries every bar. A residual holding at
  15:30 makes a session incomplete. No overnight liquidation price is invented.
- The referee journals received bars, wall-clock receipt and decision times, orders,
  fills, costs, holdings and cash. Scoring independently replays the recorded decisions
  through the referee and reconciles each minute. Exclusive daily files prevent overwrite.
  A missing minute, invalid response, bot crash, timeout, or interrupted run leaves an
  incomplete session. This version does not resume interrupted forward days or declare
  a winner from a selectively shortened week.
- Score all frozen sessions. Highest positive net P&L wins, then lower maximum drawdown
  on minute-close equity. Identical results tie. If neither earns a positive net result,
  cash wins. The score is a weekly paper result. Monetary output fields end in _paise.

[Kite minute candle documentation](https://kite.trade/docs/connect/v3/historical/)

### Trade dashboard

The dashboard opens on the competition's starting allocation of ₹1,00,000 on 25 November 2026. The opening page is a dated snapshot. Select **Open journal** to inspect a complete or partial standalone `solo.py` paper session, including minute equity, cash, positions and fees. All dates and fill times use IST. **Show demo** opens the synthetic replay generated by `fixture.py` with the example disclosures.

To watch an ongoing paper run, start the viewer on the runner's machine in a second terminal. Use the same journal path you passed to `solo.py`.

```bash
python dashboard.py --journal runs/my-session.jsonl
```

Open the URL printed by the command. The local viewer reads the latest fully written minute every ten seconds and stops refreshing when the engine records its close. Run `python dashboard.py` without a journal for the competition opening view. Imported files are snapshots. The hosted viewer has no connection to a local runner.
