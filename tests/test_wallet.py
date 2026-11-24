import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from referee import Account, START
from solo import run_wallet


class WalletTests(unittest.TestCase):
    def test_loss_carries_once_and_duplicate_day_is_refused(self):
        syms = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        days = ["2026-11-25", "2026-11-26"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wallet = root / "wallet.sqlite"
            def session(day, feed):
                return run_wallet(io.StringIO(feed), wallet, root / (day + ".jsonl"), day, syms, "replay")
            raw = subprocess.check_output([sys.executable, "fixture.py", days[0], ",".join(syms)], text=True)
            frames = [json.loads(line) for line in raw.splitlines()]
            for frame in frames[60:]:
                for bar in frame["bars"].values():
                    bar[:4] = [p // 2 for p in bar[:4]]
            a = session(days[0], "\n".join(map(json.dumps, frames)))
            end = a["accounts"]["fundamental"]["closing_cash_paise"]
            self.assertLess(end, START)
            self.assertGreaterEqual(end, 0)
            with self.assertRaisesRegex(ValueError, "subsequent session"):
                session(days[0], "")
            with self.assertRaisesRegex(ValueError, "feed ended"):
                run_wallet(io.StringIO(""), wallet, root / "partial.jsonl", days[1], syms, "replay")
            # Simulate a crash between writing the complete journal and posting the close.
            with sqlite3.connect(wallet) as db:
                db.execute("UPDATE sessions SET balances=NULL WHERE day=?", (days[0],))
            b = session(days[1], raw.replace(days[0], days[1]))["accounts"]["fundamental"]
            self.assertEqual(end, b["opening_cash_paise"])
            self.assertEqual(b["closing_cash_paise"]-START, b["cumulative_net_paise"])
            print("Verified opening cash after losing session (paise):", end)

    def test_profits_do_not_increase_max_buying_budget(self):
        account = Account(start=2*START, capital_ceiling=START)
        bars = {s:[10000, 10000, 10000, 10000, 10**7] for s in "ABCDE"}
        account.submit(1, dict.fromkeys(bars, 100000), bars)
        fills, _ = account.step(3, bars)
        self.assertGreater(len(fills), 0)
        self.assertLessEqual(sum(account.positions.values())*10000, 0.8*START)
        self.assertLessEqual(max(account.positions.values())*10000, 0.2*START)
