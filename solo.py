"""Run the Codex fundamental strategy on one complete session of minute bars."""
import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from bots.codex import decide
from fundamentals import EvidenceStore, assess, encoded, instant
from referee import Account, SESSION, START, validate

IST = timezone(timedelta(hours=5, minutes=30))


def run(stream, log, day, symbols, mode, store=None, clock=lambda: datetime.now(IST)):
    opening = datetime.combine(date.fromisoformat(day), time(9, 15), IST)
    if not symbols or len(set(symbols)) != len(symbols) or any(not s for s in symbols):
        raise ValueError("invalid symbol list")
    if mode == "forward" and clock().date() != opening.date():
        raise ValueError("forward feed must run on its session date")
    accounts = {key: Account() for key in ("fundamental", "chart_only")}
    stats = {key: dict(fills=0, fees_paise=0, peak=START, max_drawdown=0.0) for key in accounts}
    history, evidence, seen = [], [], set()
    archive = store.read(opening + timedelta(days=1)) if store and mode == "replay" else []
    changes = 0
    sources = ("solo.py", "fundamentals.py", "bots/codex.py", "referee.py")
    base = Path(__file__).resolve().parent
    versions = {s: hashlib.sha256((base / s).read_bytes()).hexdigest() for s in sources}

    def write(obj):
        log.write(encoded(obj) + "\n")
        log.flush()
        if mode == "forward":
            os.fsync(log.fileno())

    write(dict(type="session", day=day, symbols=symbols, mode=mode, code=versions,
               store=store.identity if store else None, replay_input_hash=hashlib.sha256(encoded(archive).encode()).hexdigest()))
    for minute in range(1, SESSION + 1):
        line = stream.readline()
        received = clock()
        if not line:
            raise ValueError(f"feed ended before minute {minute}")
        frame = json.loads(line)
        close = opening + timedelta(minutes=minute)
        if instant(frame["close"]) != close:
            raise ValueError(f"wrong candle timestamp for minute {minute}")
        if mode == "forward" and not 0 <= (received-close).total_seconds() <= 20:
            raise ValueError("late or premature forward frame")
        bars = frame["bars"]
        validate(bars, symbols)
        history.append(bars)
        available = store.read(close, live=True) if store and mode == "forward" else archive
        added = [e for e in available if e["id"] not in seen and e["symbol"] in (*symbols, "*")
                 and instant(e["received"]) <= close]
        seen.update(e["id"] for e in added)
        evidence.extend(added)
        analysis = assess(evidence, close, history)
        row = dict(type="minute", minute=minute, close=close.isoformat(), received=received.isoformat(),
                   bars=bars, evidence_added=added, analysis=analysis)
        for key, acc in accounts.items():
            fills, equity = acc.step(minute, bars)
            state = dict(history=history, positions=acc.positions, equity=equity, cash=acc.cash)
            chart = decide(state)
            targets = decide(dict(state, analysis=analysis)) if key == "fundamental" else chart
            if mode == "forward" and clock() >= close + timedelta(minutes=1):
                raise ValueError("missed eligible open")
            acc.submit(minute, targets, symbols)
            if key == "fundamental":
                # Same portfolio isolates the immediate decision effect even after account paths diverge.
                row["chart_targets_same_account"] = chart
                changes += int(chart != targets)
            row[key] = dict(targets=targets, equity=equity, cash=acc.cash, positions=dict(acc.positions), fills=fills)
            st = stats[key]
            st["fills"] += len(fills)
            st["fees_paise"] += sum(f["fees"] for f in fills)
            st["peak"] = max(st["peak"], equity)
            st["max_drawdown"] = max(st["max_drawdown"], 1-equity/st["peak"])
        write(row)
    if any(acc.positions for acc in accounts.values()):
        raise ValueError("outstanding intraday positions")
    for key, acc in accounts.items():
        stats[key]["net_paise"] = acc.cash - START
        del stats[key]["peak"]
    summary = dict(type="complete", mode=mode, decisions_changed=changes, accounts=stats,
                   incremental_net_paise=accounts["fundamental"].cash-accounts["chart_only"].cash)
    write(summary)
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["replay","forward"], required=True)
    p.add_argument("--symbols", required=True)
    p.add_argument("--day", required=True)
    p.add_argument("--db", type=Path)
    p.add_argument("--journal", required=True, type=Path)
    a = p.parse_args()
    db = EvidenceStore(a.db) if a.db else None
    a.journal.parent.mkdir(parents=True, exist_ok=True)
    with a.journal.open("x") as log:
        print(json.dumps(run(sys.stdin, log, a.day, a.symbols.split(","), a.mode, db), indent=2))
