"""Deterministic long-only NSE intraday paper accounts. All money is in paise."""
from dataclasses import dataclass, field

START = 10_000_000
SESSION = 375
FLATTEN = 360  # at 15:15 IST, cancel buys and start liquidating on subsequent opens


def ceildiv(n, d):
    return (n + d - 1) // d


def charges(value, buy):
    # Per IOC fill. Round each modelled charge upwards to a paisa.
    brokerage = min(2000, ceildiv(value * 3, 10000))
    exchange = ceildiv(value * 307, 10_000_000)
    sebi = ceildiv(value, 1_000_000)
    gst = ceildiv((brokerage + exchange + sebi) * 18, 100)
    duty = ceildiv(value * 3, 100000) if buy else ceildiv(value, 4000)
    return brokerage + exchange + sebi + gst + duty


def validate(bars, symbols):
    if set(bars) != set(symbols):
        raise ValueError("incomplete watchlist")
    for bar in bars.values():
        if len(bar) != 5 or any(type(x) is not int for x in bar):
            raise ValueError("expected integer open, high, low, close (paise), volume")
        o, h, l, c, v = bar
        if not (0 < l <= min(o, c) <= max(o, c) <= h and v >= 0):
            raise ValueError("invalid OHLCV")


@dataclass
class Account:
    start: int = START
    positions: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    halted: bool = False

    def __post_init__(self):
        self.cash = self.start

    def equity(self, marks):
        return self.cash + sum(q * marks[s] for s, q in self.positions.items())

    def check_loss(self, marks):
        if 100 * self.equity(marks) <= 98 * self.start:
            self.halted = True

    def step(self, minute, bars):
        opens = {s: b[0] for s, b in bars.items()}
        closes = {s: b[3] for s, b in bars.items()}
        self.check_loss(opens)
        forced = self.halted or minute > FLATTEN
        orders = {s: 0 for s in self.positions} if forced else self.pending.pop(minute, {})
        if forced:
            self.pending.clear()
        fills = []
        # Sell first, then allocate scarce cash in stable symbol order.
        order_keys = sorted(orders, key=lambda s: (orders[s] >= self.positions.get(s, 0), s))
        for s in order_keys:
            held = self.positions.get(s, 0)
            delta = orders[s] - held
            qty = min(abs(delta), bars[s][4] // 100)  # 1% of minute volume, IOC
            if not qty:
                continue
            buy = delta > 0
            px = ceildiv(opens[s] * 10005, 10000) if buy else max(1, opens[s] * 9995 // 10000)
            if buy:
                self.check_loss(opens)
                if self.halted:
                    continue
                equity = self.equity(opens)
                gross = equity - self.cash
                # Recheck after each fill, including its fees and slippage.
                lo, hi = 0, qty
                while lo < hi:
                    n = (lo + hi + 1) // 2
                    cost = charges(n * px, True)
                    post = equity - n * (px - opens[s]) - cost
                    if (n * px + cost <= self.cash and (held + n) * opens[s] * 5 <= post
                            and (gross + n * opens[s]) * 5 <= post * 4):
                        lo = n
                    else:
                        hi = n - 1
                qty = lo
            if qty:
                fee = charges(qty * px, buy)
                signed = qty if buy else -qty
                self.cash -= signed * px + fee
                self.positions[s] = held + signed
                if not self.positions[s]:
                    del self.positions[s]
                fills.append(dict(symbol=s, shares=signed, price=px, fees=fee))
        self.check_loss(closes)
        return fills, self.equity(closes)

    def submit(self, minute, targets, symbols):
        if not isinstance(targets, dict) or any(
            s not in symbols or type(q) is not int or not 0 <= q <= 10**7 for s, q in targets.items()
        ):
            raise ValueError("invalid target shares")
        if not self.halted and minute < FLATTEN:
            # The immediate next bar opens at the close just observed. A decision
            # made after that close first gets a genuinely future open two bars on.
            self.pending[minute + 2] = targets.copy()
