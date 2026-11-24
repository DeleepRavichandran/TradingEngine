# TradingEngine
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
