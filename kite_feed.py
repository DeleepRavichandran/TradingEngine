"""Read completed NSE equity minute candles through Kite Connect. No order endpoints."""
import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from contest import IST, SESSION, opening


def fetch(path):
    request = Request("https://api.kite.trade" + path, headers={
        "X-Kite-Version": "3",
        "Authorization": "token " + os.environ["KITE_API_KEY"] + ":" + os.environ["KITE_ACCESS_TOKEN"],
    })
    with urlopen(request, timeout=5) as response:
        return response.read().decode()


def candle(payload, start):
    if payload.get("status") != "success":
        raise ValueError("broker returned an unsuccessful response")
    for ts, o, h, l, c, vol, *_ in payload["data"]["candles"]:
        if datetime.fromisoformat(ts) == start:
            return [int(Decimal(str(x)) * 100) for x in (o, h, l, c)] + [int(vol)]
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", required=True)
    p.add_argument("--day", required=True)
    a = p.parse_args()
    symbols = a.symbols.split(",")
    start = opening(a.day)
    if datetime.now(IST).date() != start.date() or datetime.now(IST) >= start + timedelta(minutes=1):
        raise SystemExit("start the read-only feed on session day before the first candle closes")
    master = {r["tradingsymbol"]: r["instrument_token"] for r in csv.DictReader(io.StringIO(fetch("/instruments/NSE")))
              if r["instrument_type"] == "EQ" and r["segment"] == "NSE"}
    tokens = {s: master[s] for s in symbols}
    for minute in range(SESSION):
        bar_start = start + timedelta(minutes=minute)
        close = bar_start + timedelta(minutes=1)
        time.sleep(max(0, (close - datetime.now(IST)).total_seconds() + 1))
        bars = {}
        while len(bars) != len(tokens):
            for s, token in tokens.items():
                if s in bars:
                    continue
                if (datetime.now(IST) - close).total_seconds() >= 18:
                    raise SystemExit(f"missing fresh candle at {close}: {s}")
                query = urlencode({"from": bar_start.strftime("%Y-%m-%d %H:%M:%S"),
                                   "to": close.strftime("%Y-%m-%d %H:%M:%S")})
                data = json.loads(fetch(f"/instruments/historical/{token}/minute?" + query))
                value = candle(data, bar_start)
                if value is not None:
                    bars[s] = value
                time.sleep(0.36)
        print(json.dumps({"close": close.isoformat(), "bars": bars}), flush=True)


if __name__ == "__main__":
    main()
