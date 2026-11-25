"""Point-in-time external evidence and observable market-behaviour measures."""
import hashlib
import json
import math
import re
import sqlite3
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
DAY = 86400
POSITIVE = ("raises guidance", "profit rises", "beats estimates", "record profit", "rate cut")
NEGATIVE = ("cuts guidance", "profit falls", "misses estimates", "defaults on", "rate hike", "panic selling")


def instant(s):
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("supply a timezone-aware timestamp")
    return t.astimezone(UTC)


def encoded(x):
    return json.dumps(x, sort_keys=True, allow_nan=False, separators=(",", ":"))


def number(x):
    if type(x) not in (float, int) or not math.isfinite(x):
        raise ValueError("expected a finite number")
    return x


def event(kind, symbol, source, published, title, data, received):
    published, received = instant(published), instant(received)
    if published > received or not symbol or not source or not title:
        raise ValueError("invalid evidence identity or publication after receipt")
    if kind == "filing":
        for k in ("revenue", "prior_revenue", "profit", "prior_profit"):
            number(data[k])
        if min(data["revenue"], data["prior_revenue"]) <= 0 or symbol == "*":
            raise ValueError("filing needs a company and positive comparable sales")
        period = datetime.strptime(data["period"], "%Y-%m-%d").date()
        if period > published.date():
            raise ValueError("reported period ends after publication")
    elif kind == "macro":
        instant(data["scheduled"])
        if data["impact"] not in ("high", "normal"):
            raise ValueError("unknown event importance")
    elif kind != "news":
        raise ValueError("unknown event kind")
    e = dict(kind=kind, symbol=symbol, source=source, published=published.isoformat(),
             title=title, data=data)
    e["id"] = hashlib.sha256(encoded(e).encode()).hexdigest()
    e["received"] = received.isoformat()
    return e


class EvidenceStore:
    def __init__(self, path, create=False):
        p = Path(path).resolve()
        self.db = sqlite3.connect(p.as_uri() + ("?mode=rwc" if create else "?mode=ro"), uri=True)
        if create:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY, uuid TEXT);
                CREATE TABLE IF NOT EXISTS evidence (id TEXT, received TEXT, payload TEXT, archived INTEGER, PRIMARY KEY(id,archived));
                CREATE INDEX IF NOT EXISTS receipt ON evidence(received);
            """)
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES(1,?)", (str(uuid.uuid4()),))
            self.db.commit()
        self.identity = self.db.execute("SELECT uuid FROM metadata WHERE id=1").fetchone()[0]

    def put(self, events, archived=False):
        with self.db:
            for e in events:
                self.db.execute("INSERT OR IGNORE INTO evidence VALUES(?,?,?,?)",
                                (e["id"], e["received"], encoded(e), int(archived)))

    def read(self, through, live=False, after=""):
        rows = self.db.execute("SELECT payload FROM evidence WHERE received>? AND received<=? "
                               "AND (?=0 OR archived=0) ORDER BY received,id",
                               (after, through.astimezone(UTC).isoformat(), int(live)))
        # A licensed archive and a live collector may independently observe the same event.
        first = {}
        for (raw,) in rows:
            item = json.loads(raw)
            first.setdefault(item["id"], item)
        return list(first.values())


def behavior(history, symbol):
    if len(history) < 21:
        return {"label": "insufficient_history"}
    bars = [f[symbol] for f in history[-21:]]
    vol = statistics.median(b[4] for b in bars[:-1])
    if vol <= 0:
        return {"label": "insufficient_volume"}
    ret = bars[-1][3] / bars[-6][3] - 1
    ratio = bars[-1][4] / vol
    label = "neutral"
    if ratio >= 2 and ret <= -0.012:
        label = "selling_pressure"
    elif ratio >= 2 and ret >= 0.018:
        label = "crowded_advance"
    return dict(label=label, return_5m=round(ret, 6), relative_volume=round(ratio, 3))


def assess(events, close, history):
    visible = [e for e in events if max(instant(e["published"]), instant(e["received"])) <= close]
    result = {}
    for s in history[-1]:
        items = [e for e in visible if e["symbol"] in (s, "*")]
        reasons, ids = [], []
        factor = 1.0
        facts = {}
        filings = [e for e in items if e["kind"] == "filing" and (close - instant(e["published"])).days < 125]
        if filings:
            f = max(filings, key=lambda e: (e["data"]["period"], e["published"], e["received"], e["id"]))
            d = f["data"]
            growth = d["revenue"] / d["prior_revenue"] - 1
            margin_change = d["profit"]/d["revenue"] - d["prior_profit"]/d["prior_revenue"]
            facts.update(revenue_growth=round(growth, 5), net_margin_change=round(margin_change, 5))
            ids.append(f["id"])
            if growth < -0.05 and margin_change < -0.02:
                reasons.append("declining_sales_and_margin")
                factor = 0.0
        news = [e for e in items if e["kind"] == "news" and (close - instant(e["published"])).total_seconds() < DAY]
        tones = []
        for e in news:
            title = re.sub(r"\s+", " ", e["title"].casefold())
            tone = int(any(p in title for p in POSITIVE)) - int(any(p in title for p in NEGATIVE))
            if tone:
                tones.append(tone)
                ids.append(e["id"])
        facts.update(news_count=len(news), headline_balance=sum(tones))
        if sum(tones) < 0:
            reasons.append("negative_headlines")
            factor = min(factor, 0.5)
        for e in items:
            if e["kind"] == "macro" and e["data"]["impact"] == "high":
                delta = (close - instant(e["data"]["scheduled"])).total_seconds()
                if -900 <= delta <= 900:
                    reasons.append("scheduled_high_impact_event")
                    ids.append(e["id"])
                    factor = 0.0
        proxy = behavior(history, s)
        if proxy["label"] in ("selling_pressure", "crowded_advance"):
            reasons.append(proxy["label"])
            factor = min(factor, 0.5)
        result[s] = dict(entry_multiplier=factor, reasons=sorted(set(reasons)),
                         evidence=sorted(set(ids)), behavior=proxy, facts=facts)
    return result
