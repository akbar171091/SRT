"""Regression tests. Run from the ts_benchmark folder:  python -m unittest discover -s tests -v

The document tests need the term sheet PDFs (default folder, or TSBENCH_DOCS) and skip without them.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsbench import benchmark, compare, dataset, exports, inventory, rules, schema, server, tables, values  # noqa: E402
from tsbench.config import DEFAULT_DOCS_DIR  # noqa: E402
from tsbench.textmodel import Doc, squash  # noqa: E402

DOCS = Path(os.environ.get("TSBENCH_DOCS", DEFAULT_DOCS_DIR))
HAVE_DOCS = DOCS.is_dir() and any(inventory.is_term_sheet(p) for p in DOCS.iterdir())

GRID = """
                                    Pricing Grid

 Level    Leverage Ratio         Applicable Margin for      Applicable Margin for      Commitment
                                   Term SOFR Loans            Base Rate Loans               Fee
   I      > 3.50:1.00                   2.00%                      1.00%                  0.30%
   II     <= 3.50:1.00 but              1.75%                      0.75%                  0.25%
          > 2.50:1.00
   III    <= 2.50:1.00                  1.50%                      0.50%                  0.20%
"""

TERM_SHEET = """
                                SUMMARY OF TERMS AND CONDITIONS

Borrower:                         Example Holdings, Inc. (the "Borrower").

Facility:                         A senior secured revolving credit facility in an aggregate principal
                                  amount of $750,000,000.

Maturity:                         Five years after the Closing Date.

Collateral:                       A perfected first-priority security interest in substantially all assets.

Interest Rates:                   Term SOFR plus the Applicable Margin. Term SOFR shall be subject to a floor
                                  of 0.00%. The interest rates shall not include a credit spread adjustment.

Commitment Fee:                   As per the pricing grid set forth below.

Upfront Fees:                     Existing commitments: 10 basis points; New commitments: 25 basis points.

Financial Covenants:              (a) Consolidated Total Net Leverage Ratio not to exceed 4.00 to 1.00, which
                                  may be increased to 4.50 to 1.00 for four fiscal quarters following a Material
                                  Acquisition; and (b) Consolidated Interest Coverage Ratio of not less than
                                  3.00 to 1.00.

Events of Default:                Customary for facilities of this type.
""" + GRID


class Values(unittest.TestCase):
    def test_ratio_at_end_of_sentence(self):
        self.assertEqual([v for v, _, _ in values.thresholds("not less than 3.00 to 1.00.", "x")], [3.0])
        self.assertEqual([v for v, _, _ in values.thresholds("no less than 3.00:1.000. The", "x")], [3.0])
        self.assertEqual([v for v, _, _ in values.thresholds("Net Leverage ≤ 3.00x", "x")], [3.0])

    def test_percent_and_amount(self):
        self.assertEqual([v for v, _, _ in values.thresholds("to exceed 65.0% ; and", "pct")], [65.0])
        self.assertEqual([v for v, _, _ in values.thresholds("Debt to Capitalization of 0.65 to 1.00", "pct")], [65.0])
        self.assertEqual([v for v, _, _ in values.thresholds("Minimum Liquidity of $150 million", "usd_mm")], [150.0])
        self.assertEqual([v for v, _, _ in values.thresholds("at least $1.25 billion", "usd_mm")], [1250.0])


class Grids(unittest.TestCase):
    def test_wrapped_rows_and_columns(self):
        grids = tables.find_grids(Doc([GRID]))
        self.assertEqual(len(grids), 1)
        g = grids[0]
        self.assertEqual([t.level for t in g.tiers], ["I", "II", "III"])
        self.assertEqual([t.values["drawn"] for t in g.tiers], [200.0, 175.0, 150.0])
        self.assertEqual([t.values["base"] for t in g.tiers], [100.0, 75.0, 50.0])
        self.assertEqual([t.values["commitment_fee"] for t in g.tiers], [30.0, 25.0, 20.0])
        self.assertIn("> 2.50:1.00", g.tiers[1].criteria)  # the wrapped half of the criteria cell
        self.assertEqual(g.undrawn_fee_type, "commitment_fee")

    def test_sideways_grid(self):
        text = """
                              LEVEL I        LEVEL II       LEVEL III

 Commitment Fee                0.04%          0.05%          0.065%

 Applicable
 Margin                        0.50%          0.625%         0.75%
"""
        g = tables.find_grids(Doc([text]))[0]
        self.assertTrue(g.transposed)
        self.assertEqual([(t.level, t.values["drawn"], t.values["commitment_fee"]) for t in g.tiers],
                         [("I", 50.0, 4.0), ("II", 62.5, 5.0), ("III", 75.0, 6.5)])

    def test_prose_is_not_a_grid(self):
        prose = "The Base Rate is the highest of the prime rate, the federal funds rate plus 0.50% and\nTerm SOFR plus 1.00%, and shall not be less than 1.00%.\n"
        self.assertEqual(tables.find_grids(Doc([prose])), [])


class RulesEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rec = rules.extract([TERM_SHEET], "Example 2026", "Example 2026 TS.pdf")

    def test_pricing(self):
        p = self.rec["pricing"]
        self.assertEqual(p["basis"], "leverage_grid")
        self.assertEqual([t["drawn_margin_bps"] for t in p["grids"][0]["tiers"]], [200.0, 175.0, 150.0])
        self.assertEqual(p["floor"]["pct"], 0.0)
        self.assertIs(p["csa"]["applies"], False)
        self.assertEqual(sorted(f["bps"] for f in p["fees"] if f["type"] == "upfront_fee"), [10.0, 25.0])

    def test_covenants(self):
        covs = {c["type"]: c for c in self.rec["financial_covenants"]}
        self.assertEqual(set(covs), {"max_net_leverage", "min_interest_coverage"})
        self.assertEqual(covs["max_net_leverage"]["threshold"], 4.0)
        self.assertEqual(covs["max_net_leverage"]["step_up"]["threshold"], 4.5)
        self.assertEqual(covs["min_interest_coverage"]["threshold"], 3.0)

    def test_deal_terms(self):
        self.assertEqual(self.rec["security"]["value"], "secured")
        self.assertEqual(self.rec["credit_profile"]["value"], "leveraged")
        self.assertEqual((self.rec["facilities"][0]["type"], self.rec["facilities"][0]["amount_mm"]), ("revolver", 750.0))
        self.assertEqual(self.rec["borrower"]["name"], "Example Holdings, Inc.")

    def test_every_quote_is_verbatim(self):
        doc = Doc([TERM_SHEET])
        page_text = squash(TERM_SHEET)
        for label, holder, page in __import__("tsbench.verified", fromlist=["_items"])._items(self.rec):
            if holder.get("quote"):
                self.assertIn(squash(holder["quote"]), page_text, label)
                self.assertTrue(doc.has_quote(holder["quote"], page), label)

    def test_derived_figures(self):
        d = schema.derive(self.rec)
        m = d["metrics"]
        self.assertEqual((m["margin_min"], m["margin_max"], m["undrawn_min"], m["undrawn_max"]), (150.0, 200.0, 20.0, 30.0))
        self.assertEqual((m["all_in_min"], m["all_in_max"]), (150.0, 200.0))  # commitment fee: all-in is the margin
        self.assertEqual((m["leverage"], m["leverage_step_up"], m["coverage"]), (4.0, 4.5, 3.0))
        self.assertEqual(m["csa"], 0.0)


class Derive(unittest.TestCase):
    def test_facility_fee_arithmetic(self):
        self.assertEqual(schema.tier_figures({"drawn_margin_bps": 87.5, "undrawn_fee_bps": 12.5, "all_in_drawn_bps": None}, "facility_fee"),
                         {"margin": 87.5, "undrawn": 12.5, "all_in": 100.0, "computed": ["all_in"]})
        self.assertEqual(schema.tier_figures({"drawn_margin_bps": None, "undrawn_fee_bps": 22.5, "all_in_drawn_bps": 150.0}, "facility_fee"),
                         {"margin": 127.5, "undrawn": 22.5, "all_in": 150.0, "computed": ["margin"]})
        self.assertEqual(schema.tier_figures({"drawn_margin_bps": 125.0, "undrawn_fee_bps": 15.0, "all_in_drawn_bps": None}, "commitment_fee")["all_in"], 125.0)


class Benchmark(unittest.TestCase):
    def test_statistics(self):
        self.assertEqual(benchmark.stats([4.0, 1.0, 3.0, 2.0]), {"n": 4, "min": 1.0, "p25": 1.75, "median": 2.5, "mean": 2.5, "p75": 3.25, "max": 4.0})
        self.assertIsNone(benchmark.stats([]))

    def test_rank_and_ties(self):
        deals = [{"id": i, "derived": {"metrics": {k: None for k in benchmark.METRIC_IDS} | {"margin_max": v}}}
                 for i, v in (("a", 100.0), ("b", 150.0), ("c", 150.0), ("d", None))]
        out = benchmark.benchmark(deals)["metrics"]["margin_max"]
        self.assertEqual(out["stats"]["n"], 3)
        self.assertEqual((out["deals"]["a"]["rank"], out["deals"]["b"]["rank"], out["deals"]["c"]["rank"]), (1, 2, 2))
        self.assertEqual(out["deals"]["a"]["vs_median"], -50.0)
        self.assertNotIn("d", out["deals"])


@unittest.skipUnless(HAVE_DOCS, f"term sheet PDFs not found in {DOCS}")
class Documents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = dataset.build(DOCS)

    def test_every_term_sheet_is_read(self):
        self.assertEqual(self.data["meta"]["n_deals"], len(inventory.scan(DOCS)))
        for d in self.data["deals"]:
            self.assertTrue(d["record"]["pricing"]["grids"], d["deal"])

    def test_every_quote_is_found_in_its_pdf(self):
        for d in self.data["deals"]:
            self.assertEqual(d["evidence"]["missing"], [], d["deal"])
            self.assertGreater(d["evidence"]["total"], 0, d["deal"])

    def test_rules_engine_reads_every_grid_figure_of_the_audited_records(self):
        """Each margin and undrawn fee in each audited grid is reproduced by the rules engine."""
        wrong = []
        for d in self.data["deals"]:
            for c in (d["qa"] or {}).get("checks", []):
                if c["status"] != "match" and any(k in c["field"] for k in ("drawn margin", "undrawn fee", "all-in drawn", "number of tiers")):
                    wrong.append((d["deal"], c["field"], c["verified"], c["rules"]))
        self.assertEqual(wrong, [])

    def test_rules_engine_agreement_does_not_regress(self):
        if self.data["qa"]["documents"]:
            self.assertGreaterEqual(self.data["qa"]["agreement"], 0.97)

    def test_exports(self):
        for name, make in exports.CSV_EXPORTS.items():
            text = make(self.data)
            self.assertGreater(len(text.splitlines()), 1, name)
        html = exports.static_html(self.data)
        self.assertIn('id="embedded-dataset"', html)
        embedded = html.split('<script id="embedded-dataset" type="application/json">', 1)[1].split("</script>", 1)[0]
        self.assertTrue(json.loads(embedded)["meta"]["static"])

    def test_server(self):
        app = server.App(DOCS)
        app.data = json.loads(json.dumps(self.data))
        for d in app.data["deals"]:
            d["pdf_url"] = f"/pdf/{d['id']}"
        httpd = server.serve(app, 8790)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            def get(path, host=None):
                req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": host} if host else {})
                with urllib.request.urlopen(req, timeout=20) as res:
                    return res.status, res.headers.get("Content-Type"), res.read()

            self.assertIn(b"Term sheet benchmark", get("/")[2])
            self.assertEqual(json.loads(get("/api/dataset")[2])["meta"]["n_deals"], self.data["meta"]["n_deals"])
            first = self.data["deals"][0]["id"]
            status, ctype, body = get(f"/pdf/{first}")
            self.assertEqual((status, ctype, body[:5]), (200, "application/pdf", b"%PDF-"))
            two = ",".join(d["id"] for d in self.data["deals"][:2])
            self.assertEqual(json.loads(get(f"/api/benchmark?ids={two},not_a_deal")[2])["n"], 2)
            def refused(path, host=None):
                try:
                    get(path, host)
                except urllib.error.HTTPError as err:
                    with err:
                        return err.code
                return 200

            for path in ("/pdf/../run.py", "/pdf/%2e%2e%2frun.py", "/tsbench/config.py", "/export/nothing.csv"):
                self.assertEqual(refused(path), 404, path)
            self.assertEqual(refused("/api/dataset", host="evil.example"), 403)
        finally:
            httpd.shutdown()
            httpd.server_close()


class Compare(unittest.TestCase):
    def test_identical_records_agree(self):
        rec = rules.extract([TERM_SHEET], "Example 2026", "Example 2026 TS.pdf")
        result = compare.compare(rec, rec)
        self.assertEqual(result["summary"]["agreement"], 1.0)
        self.assertEqual(result["summary"]["mismatch"] + result["summary"]["missed"] + result["summary"]["extra"], 0)


if __name__ == "__main__":
    unittest.main()
