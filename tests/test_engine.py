import unittest
from datetime import datetime
from referee import Account, charges, validate
from kite_feed import candle


def frame(px=10000, volume=10**7):
    return {"A": [px, px, px, px, volume]}


class RefereeTests(unittest.TestCase):
    def test_causal_fill_and_real_cost(self):
        a = Account()
        a.submit(1, {"A": 100}, ["A"])
        self.assertEqual([], a.step(2, frame())[0])
        fills, _ = a.step(3, frame())
        self.assertEqual(10005, fills[0]["price"])
        self.assertEqual(a.cash, a.start - 100 * 10005 - charges(100 * 10005, True))
        self.assertFalse(a.step(4, frame())[0])

    def test_gap_and_aggregate_limits(self):
        a = Account()
        bars = {s: frame(31000)["A"] for s in "ABCDEFG"}
        for minute in (1, 2):
            a.submit(minute, {s: 50000 for s in bars}, bars)
        for minute in (3, 4):
            _, equity = a.step(minute, bars)
            self.assertGreaterEqual(a.cash, 0)
            self.assertTrue(all(q * 31000 * 5 <= equity + 10000 for q in a.positions.values()))
            self.assertLessEqual(sum(a.positions.values()) * 31000 * 5, equity * 4)
        self.assertGreater(len(a.positions), 1)

    def test_halt_cancels_pending_and_allows_exits(self):
        a = Account()
        a.positions["A"] = 50
        a.cash -= 500000
        a.submit(1, {"A": 80}, ["A"])
        a.halted = True
        fills, _ = a.step(3, frame(volume=100))
        self.assertEqual(-1, fills[0]["shares"])
        self.assertFalse(a.pending)
        a.step(4, frame())
        self.assertFalse(a.positions)

    def test_daily_loss_and_session_close(self):
        for minute, px in [(50, 8500), (361, 10000)]:
            a = Account()
            a.cash -= 2000000
            a.positions["A"] = 200
            fills, _ = a.step(minute, frame(px))
            self.assertEqual(-200, fills[0]["shares"])
            self.assertFalse(a.positions)
            self.assertEqual(minute == 50, a.halted)

    def test_independent_liquidity(self):
        for a in (Account(), Account()):
            a.submit(5, {"A": 100}, ["A"])
            self.assertEqual(10, a.step(7, frame(volume=1000))[0][0]["shares"])

    def test_validation_and_candle_time(self):
        with self.assertRaises(ValueError):
            validate(frame(), ["A", "B"])
        with self.assertRaises(ValueError):
            Account().submit(1, {"A": -1}, ["A"])
        t = datetime.fromisoformat("2026-11-25T09:15:00+05:30")
        self.assertEqual([10000]*4+[200], candle({"status":"success","data":{"candles":[
            [t.isoformat(),100,100,100,100,200]]}}, t))


if __name__ == "__main__":
    unittest.main()
