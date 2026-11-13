"""Tests for the figures the benchmark derives, the exports and the local server.

Run from the ts_benchmark folder:  python -m unittest discover -s tests -v
The classes marked as needing documents use the term sheet PDFs (default folder, or TSBENCH_DOCS) and skip without them.
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsbench import benchmark, compare, dataset, exports, inventory, schema, server, textmodel, values  # noqa: E402
from tsbench.config import DEFAULT_DOCS_DIR  # noqa: E402

DOCS = Path(os.environ.get("TSBENCH_DOCS", DEFAULT_DOCS_DIR))
HAVE_DOCS = DOCS.is_dir() and any(inventory.is_term_sheet(p) for p in DOCS.iterdir())
BOM = chr(0xFEFF)


def record(facilities=(), grids=(), fees=(), covenants=()) -> dict:
    rec = dataset._empty_record("X 2026", "X 2026 TS.pdf", "")
    rec["facilities"] = list(facilities)
    rec["pricing"]["grids"] = list(grids)
    rec["pricing"]["fees"] = list(fees)
    rec["financial_covenants"] = list(covenants)
    return rec


def facility(n: int, ftype: str, amount, tenor=5.0, currency="USD") -> dict:
    return {"id": f"F{n}", "name": f"Facility {n} (described at length)", "type": ftype, "amount_mm": amount, "currency": currency,
            "tenor_text": "", "tenor_years": tenor, "maturity_text": "", "quote": "", "page": None}


def grid(name: str, tiers, fee_type="commitment_fee", ids=None) -> dict:
    return {"name": name, "facility_ids": ids or [], "metric": "", "undrawn_fee_type": fee_type, "page": 1, "opening_level_note": "", "notes": "",
            "tiers": [{"level": str(i + 1), "criteria": "", "drawn_margin_bps": margin, "base_rate_margin_bps": None, "undrawn_fee_bps": undrawn,
                       "all_in_drawn_bps": None, "lc_fee_bps": None, "is_opening": False, "quote": ""} for i, (margin, undrawn) in enumerate(tiers)]}


def fee(ftype: str, bps, low=None, high=None) -> dict:
    return {"type": ftype, "facility_ids": [], "description": "", "bps": bps, "bps_low": low, "bps_high": high, "amount_text": "", "quote": "", "page": None}


def covenant(ctype: str, threshold, unit="x", applies_to="", schedule=()) -> dict:
    return {"type": ctype, "name": ctype, "direction": None, "threshold": threshold, "unit": unit, "threshold_text": "", "schedule": list(schedule),
            "step_up": {"present": False, "threshold": None, "detail": ""}, "springing": {"is_springing": False, "trigger": ""},
            "applies_to": applies_to, "test_frequency": "", "definition_notes": "", "change_vs_existing": None, "quote": "", "page": None}


def rows_of(text: str) -> tuple[list[str], list[dict]]:
    table = list(csv.reader(io.StringIO(text.lstrip(BOM))))
    return table[0], [dict(zip(table[0], row)) for row in table[1:]]


class FacilitySize(unittest.TestCase):
    def test_a_total_needs_every_facility_sized(self):
        d = schema.derive(record([facility(1, "term_loan_a", 550), facility(2, "term_loan_a", 250), facility(3, "revolver", None)]))
        self.assertIsNone(d["metrics"]["facility_mm"])  # 800 would read as the size of a deal that is twice as large
        self.assertEqual((d["size"]["total_mm"], d["size"]["partial_mm"]), (None, 800))
        self.assertIn("Facility 3", d["size"]["note"])
        self.assertNotIn("described at length", d["size"]["note"])

    def test_a_tranche_of_zero_is_a_stated_amount(self):
        d = schema.derive(record([facility(1, "revolver", 1325), facility(2, "revolver", 1325), facility(3, "lc_facility", 0)]))
        self.assertEqual((d["metrics"]["facility_mm"], d["size"]["partial_mm"]), (2650, None))

    def test_currencies_are_not_added_together(self):
        d = schema.derive(record([facility(1, "revolver", 500), facility(2, "term_loan_a", 300, currency="EUR")]))
        self.assertIsNone(d["metrics"]["facility_mm"])
        self.assertIn("EUR and USD", d["size"]["note"])

    def test_tenor_range_of_the_headline_tranches(self):
        d = schema.derive(record([facility(1, "revolver", 1325, tenor=3.0), facility(2, "revolver", 1325, tenor=5.0)],
                                 [grid("Pricing Grid", [(100, 10)], ids=["F1", "F2"])]))
        self.assertEqual((d["metrics"]["tenor"], d["tenor_range"]), (5.0, [3.0, 5.0]))


class AllInDrawn(unittest.TestCase):
    def test_facility_fee_stated_outside_the_grid_is_added(self):
        d = schema.derive(record([facility(1, "revolver", 1000)], [grid("Flat pricing", [(100, None)], "facility_fee")], [fee("facility_fee", 10)]))
        m, line = d["metrics"], d["lines"][0]
        self.assertEqual((m["margin_max"], m["undrawn_max"], m["all_in_min"], m["all_in_max"]), (100, 10, 110, 110))
        self.assertEqual(line["computed"], ["all_in"])

    def test_fee_type_settled_by_the_separate_fee(self):
        d = schema.derive(record([facility(1, "revolver", 1000)], [grid("Flat pricing", [(100, None)], "not_stated")], [fee("facility_fee", 10)]))
        self.assertEqual(d["metrics"]["all_in_max"], 110)
        d = schema.derive(record([facility(1, "revolver", 1000)], [grid("Flat pricing", [(100, None)], "not_stated")], [fee("commitment_fee", 25)]))
        self.assertEqual((d["metrics"]["all_in_max"], d["lines"][0]["computed"]), (100, []))

    def test_unknown_facility_fee_leaves_all_in_empty(self):
        # a stepped fee, or a tier with no fee, has no single all-in cost: empty is right, the bare margin would understate it
        d = schema.derive(record([facility(1, "revolver", 1000)], [grid("Flat pricing", [(100, None)], "facility_fee")], [fee("facility_fee", 10, 6, 10)]))
        self.assertIsNone(d["metrics"]["all_in_max"])
        d = schema.derive(record([facility(1, "revolver", 1000)], [grid("Grid", [(70, 5), (80, None)], "facility_fee")]))
        self.assertEqual((d["metrics"]["all_in_min"], d["metrics"]["all_in_max"]), (75, 75))
        self.assertEqual([f["all_in"] for f in d["lines"][0]["tier_figures"]], [75, None])


class Headline(unittest.TestCase):
    def test_existing_terms_never_stand_for_the_deal(self):
        proposed = grid("Pricing (Proposed)", [(250, 50), (300, 50)])
        existing = grid("Pricing (Existing)", [(300, 50), (350, 50), (425, 50)])
        for grids in ([proposed, existing], [existing, proposed]):
            d = schema.derive(record([facility(1, "revolver", 275)], grids))
            self.assertEqual(d["lines"][d["headline"]]["name"], "Pricing (Proposed)")
            self.assertEqual((d["metrics"]["margin_min"], d["metrics"]["margin_max"]), (250, 300))
            self.assertEqual(d["headline_rivals"], [])

    def test_a_second_grid_for_the_same_facility_is_reported(self):
        d = schema.derive(record([facility(1, "revolver", 275)], [grid("Grid A", [(100, 10)]), grid("Grid B", [(150, 10), (175, 10)])]))
        self.assertEqual((d["headline"], d["headline_rivals"]), (1, [0]))


class Covenants(unittest.TestCase):
    def test_fixed_charge_coverage_is_not_interest_coverage(self):
        d = schema.derive(record(covenants=[covenant("min_fixed_charge_coverage", 1.25)]))
        self.assertIsNone(d["metrics"]["coverage"])
        self.assertEqual(d["covenants"][0]["family"], "fixed_charge")
        d = schema.derive(record(covenants=[covenant("min_interest_coverage", 3.0)]))
        self.assertEqual(d["metrics"]["coverage"], 3.0)

    def test_second_level_of_the_same_test_is_reported(self):
        d = schema.derive(record(covenants=[covenant("max_debt_to_capitalization", 65.0, "pct", "subsidiaries"),
                                            covenant("max_debt_to_capitalization", 70.0, "pct", "parent")]))
        self.assertEqual((d["metrics"]["debt_cap"], d["primary_alternates"]["capitalization"]), (65.0, [1]))

    def test_schedule_end_level(self):
        steps = [{"period": "to 30 Nov 2025", "threshold": 2.5}, {"period": "from 28 Feb 2026", "threshold": 3.0}]
        c = schema.derive(record(covenants=[covenant("min_interest_coverage", 2.5, schedule=steps)]))["covenants"][0]
        self.assertEqual((c["threshold"], c["final"], c["has_schedule"]), (2.5, 3.0, True))

    def test_comparison_pairs_coverage_tests_and_tolerates_unknown_types(self):
        a = record([facility(1, "revolver", None), facility(2, "revolver", 500)], covenants=[covenant("min_interest_coverage", 3.0)])
        b = record([facility(1, "revolver", 500)], covenants=[covenant("min_fixed_charge_coverage", 3.0), covenant("max_capex", 50.0)])
        checks = {c["field"]: c["status"] for c in compare.compare(a, b)["checks"]}
        self.assertEqual(checks["Interest coverage: level"], "match")
        self.assertEqual(checks["Interest coverage: test type"], "mismatch")
        self.assertEqual(checks["Other"], "extra")


class PeerGroups(unittest.TestCase):
    def test_unreadable_documents_are_never_peers(self):
        blank = {k: None for k in benchmark.METRIC_IDS}
        deals = [{"id": "a", "readable": True, "derived": {"metrics": blank | {"margin_max": 100.0}}},
                 {"id": "b", "readable": False, "derived": {"metrics": dict(blank)}}]
        out = benchmark.benchmark(deals)
        self.assertEqual((out["peer_ids"], out["n"]), (["a"], 1))
        self.assertEqual(benchmark.custom(deals, ["a", "b"])["peer_ids"], ["a"])


class Robustness(unittest.TestCase):
    def test_footer_test_does_not_stall_on_a_long_indent(self):
        start = time.perf_counter()
        self.assertFalse(textmodel.is_footer(" " * 20000 + "not a footer"))
        self.assertLess(time.perf_counter() - start, 0.5)
        self.assertTrue(textmodel.is_footer("          - 12 -"))
        self.assertTrue(textmodel.is_footer("Page 3 of 14"))
        self.assertTrue(textmodel.is_footer(" " * 70 + "Fee"))  # a stray short word far to the right
        self.assertFalse(textmodel.is_page_furniture(" " * 70 + "Fee"))  # but not page furniture by its words

    def test_absurd_amount_is_not_a_number_to_benchmark(self):
        self.assertEqual(values.thresholds("a facility of $" + "9" * 400 + " million", "usd_mm"), [])
        self.assertEqual(values.thresholds("a facility of $750,000,000", "usd_mm")[0][0], 750.0)

    def test_non_finite_values_are_dropped_before_serialising(self):
        dropped = [0]
        clean = dataset._finite({"a": float("inf"), "b": [1.0, float("nan")], "c": "x"}, dropped)
        self.assertEqual((clean, dropped[0]), ({"a": None, "b": [1.0, None], "c": "x"}, 2))
        with self.assertRaises(ValueError):
            exports.embed_json({"a": float("inf")})

    def test_embedded_json_survives_markup_in_the_text(self):
        data = {"name": "Arrow <!-- Holdings </script><script>alert(1)</script> " + chr(0x2028) + " Inc."}
        text = exports.embed_json(data)
        self.assertNotIn("<", text)
        self.assertEqual(json.loads(text), data)

    def test_csv_cells_cannot_be_formulas(self):
        self.assertEqual(exports._cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(exports._cell("-2.5"), "'-2.5")
        self.assertEqual(exports._cell(-2.5), -2.5)

    def test_file_names_never_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = ["Acme TS.pdf", "Acme Term Sheet.pdf", "Acme-TS.pdf", chr(0x4E2D) + chr(0x56FD) + " TS.pdf", chr(0x65E5) + chr(0x672C) + " TS.pdf", "Notes.pdf"]
            for name in names:
                (Path(tmp) / name).write_bytes(b"")
            found = inventory.scan(Path(tmp))
            self.assertEqual(len(found), 5)
            self.assertEqual(len({f.slug for f in found}), 5)
            self.assertTrue(all(f.slug for f in found))


@unittest.skipUnless(HAVE_DOCS, f"term sheet PDFs not found in {DOCS}")
class Exports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = dataset.build(DOCS)

    def test_pricing_extract_follows_the_peer_group(self):
        group = self.data["benchmarks"]["investment_grade"]
        header, rows = rows_of(exports.pricing_csv(self.data, group))
        self.assertEqual(len(rows), group["n"])
        self.assertEqual({r["Peer group"] for r in rows}, {f"Investment-grade style ({group['n']})"})
        for r in rows:
            deal = next(d for d in self.data["deals"] if d["deal"] == r["Deal"])
            place = group["metrics"]["margin_max"]["deals"][deal["id"]]
            self.assertEqual(float(r["Margin max vs peer group median (bps)"]), place["vs_median"])
            self.assertEqual(int(r["Margin max rank in peer group (1 = lowest)"]), place["rank"])
        _, everyone = rows_of(exports.pricing_csv(self.data))
        self.assertEqual(len(everyone), self.data["benchmarks"]["all"]["n"])

    def test_custom_group_appears_in_the_statistics_extract(self):
        ids = [d["id"] for d in self.data["deals"][:3]]
        _, rows = rows_of(exports.peer_stats_csv(self.data, benchmark.custom(self.data["deals"], ids)))
        self.assertIn("Custom selection", {r["Peer group"] for r in rows})
        _, rows = rows_of(exports.peer_stats_csv(self.data))
        self.assertNotIn("Custom selection", {r["Peer group"] for r in rows})

    def test_covenant_extract_columns(self):
        header, rows = rows_of(exports.covenants_csv(self.data))
        self.assertEqual(len(header), len(set(header)))
        for r in rows:
            deal = next(d for d in self.data["deals"] if d["deal"] == r["Deal"])
            if not deal["record"]["financial_covenants"]:
                self.assertEqual((r["Covenant"], r["Springing trigger"]), ("None stated" if deal["source"] == "verified" else "None found by the rules engine", ""))
                self.assertEqual(r["Note"], deal["record"].get("no_financial_covenant_note") or "")
        deferred = [(d, c) for d in self.data["deals"] for c in d["derived"]["covenants"] if c["deferred"]]
        for d, c in deferred:
            row = next(r for r in rows if r["Deal"] == d["deal"] and r["Covenant"] == c["label"])
            self.assertNotEqual(row["Level applies from"], "closing")

    def test_saved_report_carries_no_local_path(self):
        html = exports.static_html(self.data)
        embedded = html.split('<script id="embedded-dataset" type="application/json">', 1)[1].split("</script>", 1)[0]
        data = json.loads(embedded)
        self.assertEqual(data["meta"]["docs_dir"], DOCS.name)
        self.assertNotIn(json.dumps(str(DOCS.parent))[1:-1], embedded)
        self.assertTrue(all("path" not in d and d["pdf_url"] is None for d in data["deals"]))


@unittest.skipUnless(HAVE_DOCS, f"term sheet PDFs not found in {DOCS}")
class Folder(unittest.TestCase):
    """A folder with a changed file, a copy, a damaged file and a name outside Latin-1."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        sheets = sorted(inventory.scan(DOCS), key=lambda t: t.path.stat().st_size)
        cls.kept, cls.changed, cls.renamed = sheets[0], sheets[1], sheets[2]
        shutil.copyfile(cls.kept.path, folder / cls.kept.name)
        shutil.copyfile(cls.kept.path, folder / (cls.kept.path.stem + " (1).pdf"))
        shutil.copyfile(cls.changed.path, folder / cls.changed.name)
        with open(folder / cls.changed.name, "ab") as f:
            f.write(b"\n%changed")
        (folder / "Broken 2026 TS.pdf").write_bytes(cls.kept.path.read_bytes()[:2000])
        cls.odd_name = chr(0x160) + "koda 2026 TS.pdf"
        shutil.copyfile(cls.renamed.path, folder / cls.odd_name)
        cls.folder = folder
        cls.data = dataset.build(folder)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def deal(self, file_name: str) -> dict:
        return next(d for d in self.data["deals"] if d["file"] == file_name)

    def test_identical_copy_is_counted_once(self):
        self.assertEqual(sum(1 for d in self.data["deals"] if d["sha1"] == self.deal(self.kept.name)["sha1"]), 1)
        self.assertTrue(any("identical copy" in p for p in self.data["meta"]["problems"]))

    def test_changed_pdf_falls_back_to_the_rules_engine(self):
        d = self.deal(self.changed.name)
        self.assertEqual((d["source"], d["verified_status"]), ("rules", "stale"))
        self.assertEqual(self.deal(self.kept.name)["source"], "verified")

    def test_damaged_pdf_is_listed_but_not_benchmarked(self):
        d = self.deal("Broken 2026 TS.pdf")
        self.assertFalse(d["readable"])
        self.assertEqual(self.data["meta"]["n_unreadable"], 1)
        self.assertNotIn(d["id"], self.data["benchmarks"]["all"]["peer_ids"])
        self.assertNotIn(str(self.folder), " ".join(d["notes"]))  # the reason is given without the local path

    def test_unusable_audited_record_does_not_stop_the_build(self):
        original = compare.compare
        compare.compare = lambda *_: (_ for _ in ()).throw(KeyError("csa"))
        try:
            data = dataset.build(self.folder)
        finally:
            compare.compare = original
        d = next(x for x in data["deals"] if x["file"] == self.kept.name)
        self.assertEqual((d["source"], d["verified_status"]), ("rules", "unusable"))
        self.assertTrue(any("could not be used" in p for p in data["meta"]["problems"]))

    def test_pdf_with_a_name_outside_latin_1_is_served(self):
        app = server.App(self.folder)
        app.data = self.data
        httpd = server.serve(app, 8796)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/pdf/{self.deal(self.odd_name)['id']}", timeout=20) as res:
                self.assertEqual((res.status, res.headers.get("Content-Type")), (200, "application/pdf"))
                self.assertEqual(res.read()[:5], b"%PDF-")
        finally:
            httpd.shutdown()
            httpd.server_close()


@unittest.skipUnless(HAVE_DOCS, f"term sheet PDFs not found in {DOCS}")
class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = server.App(DOCS)
        cls.app.build()
        cls.httpd = server.serve(cls.app, 8797)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path: str, headers: dict | None = None, method: str = "GET"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.status, res.headers, res.read()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.headers, err.read()

    def test_page_headers(self):
        status, headers, _ = self.call("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_other_sites_cannot_use_the_server(self):
        first = self.app.data["deals"][0]["id"]
        cross = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "object"}
        self.assertEqual(self.call(f"/pdf/{first}", cross)[0], 403)
        self.assertEqual(self.call("/api/dataset", {"Sec-Fetch-Site": "same-site"})[0], 403)
        self.assertEqual(self.call("/api/dataset", {"Sec-Fetch-Site": "same-origin"})[0], 200)
        # a link to the front page may be followed from anywhere
        self.assertEqual(self.call("/", {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})[0], 200)
        self.assertEqual(self.call("/", {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe"})[0], 403)

    def test_rescan_is_refused_from_another_origin(self):
        generated = self.app.data["meta"]["generated"]
        for origin in ("https://evil.example", "http://localhost:8501", "null"):
            self.assertEqual(self.call("/api/refresh", {"Origin": origin}, "POST")[0], 403, origin)
        self.assertEqual(self.call("/api/refresh", {"Sec-Fetch-Site": "cross-site"}, "POST")[0], 403)
        self.assertEqual(self.app.data["meta"]["generated"], generated)

    def test_malformed_request_target_gets_an_answer(self):
        self.assertEqual(self.call("/export/pricing_benchmark.csv?group=nonsense")[0], 200)  # unknown group: all term sheets
        self.assertEqual(self.call("/api/benchmark?ids=__proto__,constructor")[0], 200)

    def test_export_follows_the_group_in_the_link(self):
        group = self.app.data["benchmarks"]["leveraged"]
        _, rows = rows_of(self.call("/export/pricing_benchmark.csv?group=leveraged")[2].decode("utf-8"))
        self.assertEqual((len(rows), rows[0]["Peer group"]), (group["n"], f"Leveraged style ({group['n']})"))
        ids = ",".join(d["id"] for d in self.app.data["deals"][:2])
        _, rows = rows_of(self.call(f"/export/pricing_benchmark.csv?ids={ids}")[2].decode("utf-8"))
        self.assertEqual((len(rows), rows[0]["Peer group"]), (2, "Custom selection (2)"))

    def test_second_copy_takes_the_next_port(self):
        other = server.serve(self.app, self.port)
        try:
            self.assertNotEqual(other.server_address[1], self.port)
        finally:
            other.server_close()


if __name__ == "__main__":
    unittest.main()
