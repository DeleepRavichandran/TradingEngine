"""Synthetic development feed deliberately covering broad advances and reversals."""
import json
import math
import sys
from datetime import timedelta
from contest import SESSION, opening

day, symbol_text = sys.argv[1:]
symbols = symbol_text.split(",")
last = {s: 10000 + 2000 * i for i, s in enumerate(symbols)}
for k in range(SESSION):
    bars = {}
    for i, s in enumerate(symbols):
        o = last[s]
        c = round((10000 + 2000 * i) * (1 + 0.00038 * min(k, 175) - 0.0003 * max(0, k-175)
                  + 0.0025 * math.sin(k / 2 + i)))
        bars[s] = [o, max(o, c) + 4, min(o, c) - 4, c, 40000]
        last[s] = c
    print(json.dumps({"close": (opening(day) + timedelta(minutes=k+1)).isoformat(), "bars": bars}))
