"""Cross-sectional momentum after a pullback in an advancing, liquid market."""
import json
import sys


def decide(state):
    history = state["history"]
    held = state["positions"]
    if len(history) < 32:
        return {}
    last = history[-1]
    breadth = sum(b[3] > history[0][s][0] for s, b in last.items()) / len(last)
    targets, candidates = {}, []
    for symbol, bar in last.items():
        rows = [frame[symbol] for frame in history[-31:]]
        price = bar[3]
        mean = sum(b[3] for b in rows[-20:]) / 20
        recent = sum(b[3] for b in rows[-5:]) / 5
        momentum = price / rows[0][3] - 1
        noise = sum((b[1] - b[2]) / b[3] for b in rows[-20:]) / 20
        if symbol in held:
            if price < mean or breadth < 0.45:
                targets[symbol] = 0
        elif (len(history) < 330 and breadth >= 0.60 and momentum > 0.004
              and recent > mean and rows[-2][3] <= recent < price
              and price * bar[4] >= 100_000_000):
            candidates.append((momentum / max(noise, 0.0005), symbol, price, noise))
    slots = max(0, 4 - len(held))
    for _, symbol, price, noise in sorted(candidates, reverse=True)[:slots]:
        budget = state["equity"] * min(0.18, 0.001 / max(noise * 2, 0.001))
        targets[symbol] = int(budget // price)
    return targets


if __name__ == "__main__":
    print(json.dumps(decide(json.load(sys.stdin))))
