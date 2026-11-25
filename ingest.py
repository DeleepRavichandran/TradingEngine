"""Collect public/authorised XBRL instance filings, RSS/Atom headlines and calendar CSV."""
import argparse
import csv
import io
import json
import time
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

from fundamentals import EvidenceStore, UTC, event, instant

X = "{http://www.xbrl.org/2003/instance}"


def local(tag):
    return tag.split("}")[-1]


def xml(raw):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("unsupported XML declarations")
    return ET.fromstring(raw)


def payload(src):
    if src.startswith("https://"):
        with urlopen(Request(src, headers={"User-Agent": "TradingEngine/1.0"}), timeout=12) as r:
            if r.geturl().split(":")[0] != "https":
                raise ValueError("expected HTTPS")
            raw = r.read(16_000_001)
    else:
        with Path(src).open("rb") as f:
            raw = f.read(16_000_001)
    if len(raw) > 16_000_000:
        raise ValueError("oversize document")
    return raw


def filing(raw, spec):
    root = xml(raw)
    contexts = {c.get("id"): c for c in root.findall(X+"context")}
    rows = []
    signatures = []
    for key in ("current", "prior"):
        cid = spec[key]
        ctx = contexts[cid]
        entity = ctx.find(X+"entity/"+X+"identifier")
        start = date.fromisoformat(ctx.findtext(X+"period/"+X+"startDate"))
        end = date.fromisoformat(ctx.findtext(X+"period/"+X+"endDate"))
        if end < start or entity is None:
            raise ValueError("invalid duration or entity")
        if ctx.find(".//"+X+"segment") is not None or ctx.find(X+"scenario") is not None:
            raise ValueError("choose unsegmented comparable reporting contexts")
        values = []
        for metric in ("revenue_tag", "profit_tag"):
            facts = [f for f in root if f.get("contextRef") == cid and
                     (f.tag == spec[metric] or local(f.tag) == spec[metric])]
            if len(facts) != 1 or not facts[0].text:
                raise ValueError(f"expected one {metric} in context {cid}")
            values.append(float(facts[0].text))
            unit = [u for u in root.findall(X+"unit") if u.get("id") == facts[0].get("unitRef")]
            if len(unit) != 1 or (unit[0].findtext(X+"measure") or "").split(":")[-1] != "INR":
                raise ValueError("expected INR monetary facts")
        signatures.append((entity.get("scheme"), entity.text, (end-start).days, end))
        rows.append(values)
    a, b = signatures
    if a[:2] != b[:2] or abs(a[2]-b[2]) > 7 or not 350 <= (a[3]-b[3]).days <= 380:
        raise ValueError("contexts must compare the same issuer and year-over-year duration")
    return dict(period=a[3].isoformat(), revenue=rows[0][0], profit=rows[0][1],
                prior_revenue=rows[1][0], prior_profit=rows[1][1])


def entries(raw, spec, received):
    kind, source = spec["kind"], spec["source"]
    symbol = spec.get("symbol", "*")
    if kind == "filing":
        yield event(kind, symbol, source, spec["published"], spec["title"], filing(raw, spec), received)
    elif kind == "macro":
        for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
            yield event(kind, r.get("symbol") or symbol, source, r["published"], r["title"],
                        dict(scheduled=r["scheduled"], impact=r["impact"]), received)
    elif kind == "news":
        for item in xml(raw).iter():
            if local(item.tag) not in ("item", "entry"):
                continue
            fields = {local(el.tag): el for el in item}
            title = "".join(fields["title"].itertext()).strip()
            field = next((fields[k] for k in ("published","pubDate","updated") if k in fields), None)
            if field is None or not field.text:
                continue
            stamp = field.text.strip()
            try:
                pub = instant(stamp)
            except ValueError:
                pub = parsedate_to_datetime(stamp)
            if pub.tzinfo is None:
                raise ValueError("undated timezone in headline")
            if pub > instant(received):
                continue
            link = fields.get("link")
            url = (link.get("href") or link.text or "") if link is not None else ""
            yield event(kind, symbol, source, pub.isoformat(), title, dict(url=url), received)
    else:
        raise ValueError(f"unknown input kind {kind}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("config", type=Path)
    p.add_argument("--db", required=True)
    p.add_argument("--archived-receipt", help="replay only; actual historical collection timestamp")
    p.add_argument("--every", type=int, help="continuously refresh inputs at this interval in seconds")
    a = p.parse_args()
    if a.every is not None and (a.every < 30 or a.archived_receipt):
        p.error("continuous collection requires at least 30 seconds and live receipt timestamps")
    store = EvidenceStore(a.db, create=True)
    while True:
        failures = collect(a.config, a.archived_receipt, store)
        if failures:
            print("\n".join(failures), file=sys.stderr, flush=True)
        if not a.every:
            raise SystemExit(int(bool(failures)))
        time.sleep(a.every)


def collect(config, archive_receipt, store):
    failures = []
    for spec in json.loads(config.read_text()):
        try:
            loc = spec["input"]
            if not loc.startswith("https://"):
                loc = str(config.parent / loc)
            raw = payload(loc)
            received = archive_receipt or datetime.now(UTC).isoformat()
            evidence = list(entries(raw, spec, received))
            store.put(evidence, archived=bool(archive_receipt))
            print(f"{spec['source']}: scanned {len(evidence)} items")
        except (OSError, ValueError, KeyError, ET.ParseError, TypeError) as e:
            failures.append(f"{spec['source']}: {e}")
    return failures


if __name__ == "__main__":
    main()
