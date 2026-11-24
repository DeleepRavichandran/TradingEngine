"""Freeze opponents, consume shared candles and score complete paper sessions."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from referee import Account, SESSION, START, validate

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parent
NAMES = ("codex", "claude")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args])


def opening(day):
    return datetime.combine(date.fromisoformat(day), time(9, 15), IST)


def engine_hash():
    return {s: digest((ROOT / s).read_bytes()) for s in ("contest.py", "referee.py", "kite_feed.py")}


def freeze(a):
    days = a.days.split(",")
    symbols = a.symbols.split(",")
    if days != sorted(set(days)) or any(opening(d).weekday() >= 5 for d in days):
        raise ValueError("supply unique scheduled exchange dates in ascending order")
    if a.mode == "forward" and datetime.now(IST) >= opening(days[0]):
        raise ValueError("freeze before the first session opens")
    if len(set(symbols)) != len(symbols) or any(not s or s.strip() != s for s in symbols):
        raise ValueError("invalid watchlist")
    bots, sources = {}, {}
    for name in NAMES:
        repo = getattr(a, name + "_repo")
        rev = git(repo, "rev-parse", "--verify", getattr(a, name + "_rev") + "^{commit}").decode().strip()
        path = getattr(a, name + "_file")
        src = git(repo, "show", rev + ":" + path)
        compile(src, path, "exec")
        bots[name] = dict(commit=rev, path=path, sha256=digest(src))
        sources[name] = src
    if a.mode == "forward" and any(digest(s) == digest((ROOT / "bots/cash.py").read_bytes()) for s in sources.values()):
        raise ValueError("the bundled demo control cannot enter a forward match")
    manifest = dict(mode=a.mode, days=days, symbols=symbols, bots=bots, engine=engine_hash(),
                    frozen_at=datetime.now(IST).isoformat(), start_paise=START)
    a.dir.mkdir(parents=True, exist_ok=False)
    for name, src in sources.items():
        (a.dir / (name + ".py")).write_bytes(src)
    (a.dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


def manifest(root):
    m = json.loads((root / "manifest.json").read_text())
    if m["engine"] != engine_hash() or any(
        digest((root / (n + ".py")).read_bytes()) != m["bots"][n]["sha256"] for n in NAMES
    ):
        raise ValueError("frozen referee or bot differs")
    return m


def decision(root, name, state):
    with tempfile.TemporaryDirectory() as work:
        p = subprocess.run([sys.executable, "-I", str((root / (name + ".py")).resolve())],
                           input=json.dumps(state), capture_output=True, text=True, timeout=3,
                           cwd=work, env={"PATH": os.defpath}, check=True)
    return json.loads(p.stdout)


def totals(root, day):
    path = root / (day + ".jsonl")
    with path.open() as f:
        rows = [json.loads(line) for line in f]
    if len(rows) != SESSION or [r["minute"] for r in rows] != list(range(1, SESSION + 1)):
        raise ValueError(f"incomplete session {day}")
    if any(rows[-1][n]["positions"] for n in NAMES):
        raise ValueError(f"unclosed intraday position on {day}")
    return rows


def session(a):
    m = manifest(a.dir)
    index = m["days"].index(a.day)
    start = {n: START for n in NAMES}
    if index:
        prev = totals(a.dir, m["days"][index - 1])[-1]
        start = {n: prev[n]["equity"] for n in NAMES}
    forward = m["mode"] == "forward"
    if forward and datetime.now(IST).date().isoformat() != a.day:
        raise ValueError("forward session must run on its declared date")
    accounts = {n: Account(start[n]) for n in NAMES}
    history = []
    path = a.dir / (a.day + ".jsonl")
    # Exclusive journal prevents a second session or overwriting a partial result.
    with path.open("x") as log:
        for minute in range(1, SESSION + 1):
            line = sys.stdin.readline()
            received = datetime.now(IST)
            if not line:
                raise ValueError(f"feed ended before minute {minute}")
            frame = json.loads(line)
            close = opening(a.day) + timedelta(minutes=minute)
            stamp = datetime.fromisoformat(frame["close"])
            if stamp.tzinfo is None or stamp != close:
                raise ValueError(f"expected timezone-aware close {close.isoformat()}")
            if forward and not 0 <= (received - close).total_seconds() <= 20:
                raise ValueError(f"stale or premature forward frame at {close}")
            bars = frame["bars"]
            validate(bars, m["symbols"])
            history.append(bars)
            row = dict(minute=minute, close=close.isoformat(), received=received.isoformat(), bars=bars)
            for name, acc in accounts.items():
                fills, equity = acc.step(minute, bars)
                state = dict(close=row["close"], history=history, cash=acc.cash,
                             equity=equity, positions=acc.positions, halted=acc.halted)
                targets = decision(a.dir, name, state)
                decided = datetime.now(IST)
                if forward and decided >= close + timedelta(minutes=1):
                    raise ValueError("decision missed its eligible open")
                acc.submit(minute, targets, m["symbols"])
                row[name] = dict(equity=equity, cash=acc.cash, fills=fills, halted=acc.halted,
                                 positions=dict(acc.positions), targets=targets, decided=decided.isoformat())
            log.write(json.dumps(row, separators=(",", ":")) + "\n")
            log.flush()
            os.fsync(log.fileno())
    totals(a.dir, a.day)
    print(f"Completed {m['mode']} session {a.day}")


def score(root):
    m = manifest(root)
    records = []
    missing = []
    for d in m["days"]:
        try:
            rows = totals(root, d)
            replay = {n: Account(records[-1][n]["equity"] if records else START) for n in NAMES}
            for row in rows:
                minute = row["minute"]
                close = opening(d) + timedelta(minutes=minute)
                if datetime.fromisoformat(row["close"]) != close:
                    raise ValueError("ledger timestamp mismatch")
                validate(row["bars"], m["symbols"])
                received = datetime.fromisoformat(row["received"])
                for n, account in replay.items():
                    actual = row[n]
                    decided = datetime.fromisoformat(actual["decided"])
                    if m["mode"] == "forward" and not (
                        close <= received <= close + timedelta(seconds=20)
                        and received <= decided < close + timedelta(minutes=1)
                    ):
                        raise ValueError("forward timing mismatch")
                    fills, equity = account.step(minute, row["bars"])
                    if (fills, equity, account.cash, account.positions, account.halted) != (
                        actual["fills"], actual["equity"], actual["cash"], actual["positions"], actual["halted"]
                    ):
                        raise ValueError("ledger reconciliation failed")
                    account.submit(minute, actual["targets"], m["symbols"])
            records.extend(rows)
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            missing.append(d)
    summary = {}
    for n in NAMES:
        peak, dd, equity, fees, fills = START, 0.0, START, 0, 0
        for r in records:
            equity = r[n]["equity"]
            peak = max(peak, equity)
            dd = max(dd, 1 - equity / peak)
            fees += sum(f["fees"] for f in r[n]["fills"])
            fills += len(r[n]["fills"])
        summary[n] = dict(net_paise=equity - START, max_drawdown=dd, fees_paise=fees, fills=fills)
    winners = sorted(NAMES, key=lambda n: (-summary[n]["net_paise"], summary[n]["max_drawdown"]))
    first, second = (summary[n] for n in winners)
    winner = winners[0]
    if first["net_paise"] <= 0:
        winner = "cash"
    elif (first["net_paise"], first["max_drawdown"]) == (second["net_paise"], second["max_drawdown"]):
        winner = "tie"
    return dict(mode=m["mode"], incomplete_dates=missing, accounts=summary,
                weekly_winner=winner if not missing and m["mode"] == "forward" else None)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="cmd", required=True)
    f = subs.add_parser("freeze")
    f.add_argument("--mode", choices=["replay", "forward"], required=True)
    f.add_argument("--days", required=True)
    f.add_argument("--symbols", required=True)
    for name in NAMES:
        f.add_argument("--" + name + "-repo", default=str(ROOT))
        f.add_argument("--" + name + "-rev", default="HEAD")
        f.add_argument("--" + name + "-file", default="bots/codex.py" if name == "codex" else None,
                       required=name == "claude")
    s = subs.add_parser("session")
    s.add_argument("--day", required=True)
    for sub in (f, s, subs.add_parser("score")):
        sub.add_argument("--dir", required=True, type=Path)
    a = p.parse_args()
    if a.cmd == "freeze":
        freeze(a)
    elif a.cmd == "session":
        session(a)
    else:
        print(json.dumps(score(a.dir), indent=2))


if __name__ == "__main__":
    main()
