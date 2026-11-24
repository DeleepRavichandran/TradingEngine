import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fundamentals import EvidenceStore, assess, behavior, event, instant
from ingest import collect, entries, filing
from solo import run

SOURCES = Path(__file__).resolve().parents[1] / "examples/fundamentals"
RECEIVED = "2026-11-25T09:40:00+05:30"
SYMBOLS = "RELIANCE,HDFCBANK,INFY,ICICIBANK,TCS"
DAY = "2026-11-25"


class AnalysisTests(unittest.TestCase):
    def test_filing_context_and_receipt(self):
        spec = json.loads((SOURCES/"sources.json").read_text())[0]
        raw = (SOURCES/"quarter.xml").read_bytes()
        e, = entries(raw, spec, RECEIVED)
        history = [{"INFY":[100,100,100,100,50]}]
        self.assertEqual(1, assess([e], instant("2026-11-25T09:39:59+05:30"), history)["INFY"]["entry_multiplier"])
        result = assess([e], instant(RECEIVED), history)["INFY"]
        self.assertEqual(0, result["entry_multiplier"])
        self.assertAlmostEqual(-0.12, result["facts"]["revenue_growth"])
        with self.assertRaises(ValueError):
            filing(raw.replace(b"2025-07-01", b"2025-04-01"), spec)
        with self.assertRaises(ValueError):
            filing(raw.replace(b":INR", b":USD"), spec)

    def test_archive_and_live_are_independent(self):
        spec = json.loads((SOURCES/"sources.json").read_text())[0]
        raw = (SOURCES/"quarter.xml").read_bytes()
        with tempfile.TemporaryDirectory() as d:
            store = EvidenceStore(Path(d)/"data.db", create=True)
            for archived, when in [(True,RECEIVED),(False,"2026-11-25T10:30:00+05:30")]:
                store.put(entries(raw,spec,when), archived)
            self.assertFalse(store.read(instant(RECEIVED), live=True))
            self.assertEqual(1, len(store.read(instant(RECEIVED))))
            end = instant("2026-11-25T11:00:00+05:30")
            self.assertEqual(1, len(store.read(end)))
            self.assertEqual(1, len(store.read(end, live=True)))

    def test_macro_window_and_behavior_proxies(self):
        t = instant(RECEIVED)
        e = event("macro","*","calendar",RECEIVED,"Policy release",
                  {"impact":"high","scheduled":"2026-11-25T09:55:00+05:30"}, RECEIVED)
        normal = {"A":[100,100,100,100,100]}
        hist = [normal]*20
        self.assertEqual(0, assess([e],t,hist)["A"]["entry_multiplier"])
        self.assertEqual(1, assess([e],instant("2026-11-25T10:11:00+05:30"),hist)["A"]["entry_multiplier"])
        for px,label in [(98,"selling_pressure"),(102,"crowded_advance")]:
            self.assertEqual(label,behavior(hist+[{"A":[px,px,px,px,250]}],"A")["label"])

    def test_full_session_with_late_evidence_and_counterfactual(self):
        frames = subprocess.check_output([sys.executable,"fixture.py",DAY,SYMBOLS],text=True)
        with tempfile.TemporaryDirectory() as d:
            store = EvidenceStore(Path(d)/"data.db",create=True)
            self.assertEqual([],collect(SOURCES/"sources.json",RECEIVED,store))
            journal = io.StringIO()
            result = run(io.StringIO(frames),journal,DAY,SYMBOLS.split(","),"replay",store)
            self.assertGreater(result["decisions_changed"],0)
            rows = [json.loads(line) for line in journal.getvalue().splitlines()][1:-1]
            self.assertEqual(375,len(rows))
            self.assertFalse(rows[23]["evidence_added"])
            self.assertEqual(3,len(rows[24]["evidence_added"]))
            changed = next(r for r in rows if "INFY" in r["chart_targets_same_account"]
                           and "INFY" not in r["fundamental"]["targets"])
            self.assertIn("declining_sales_and_margin",changed["analysis"]["INFY"]["reasons"])
            self.assertEqual(127, changed["chart_targets_same_account"]["INFY"])
