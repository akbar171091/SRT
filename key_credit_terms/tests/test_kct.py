"""Tests for the Key Credit Terms populator.

    python -m unittest discover -s tests -v        (or: python -m pytest tests)

Tests that need the hackathon documents folder are skipped when it is not there.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from docx import Document  # noqa: E402

import populate_key_credit_terms as cli  # noqa: E402
from kct import config, llm, naming, pdftext, pipeline, records, rules, schema, template  # noqa: E402
from kct.fields import FIELD_IDS, FIELDS, guidance_text  # noqa: E402
from kct.rules import common  # noqa: E402
from kct.rules.blocks import find_blocks  # noqa: E402
from kct.textmodel import Doc, squash  # noqa: E402

HAVE_DOCS = config.DEFAULT_TEMPLATE.is_file()
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def sample_record() -> dict:
    rec = schema.new_record("Test Co", "Test Co 2026", "Test Co 2026 TS.pdf", "0" * 40, "rules")
    for i, f in enumerate(FIELDS):
        status = ("stated", "by_reference", "not_stated")[i % 3]
        rec["fields"][f.id] = {
            "lines": [f"{f.id} first “line” <= 3.50x & <b>", f"{f.id} second line"] if i % 2 == 0 else [f"{f.id} only line"],
            "status": status,
            "evidence": [] if status == "not_stated" else [{"quote": "a verbatim quote", "page": 2}],
            "note": "a note" if i % 7 == 0 else "",
        }
    return rec


def cell_lines(tc) -> list[str]:
    return ["".join(t.text or "" for t in p.iter(W + "t")) for p in tc.findall(W + "p")]


def table_rows(path: Path) -> list[list[list[str]]]:
    doc = Document(str(path))
    return [[cell_lines(tc) for tc in tr.tc_lst] for tr in doc.tables[0]._tbl.tr_lst]


class NamingTests(unittest.TestCase):
    def test_client_and_output_names(self):
        cases = {
            "Seadrill 2026 TS": ("Seadrill", "Key_Credit_Terms_Seadrill.docx"),
            "Honeywell 364day 2026 TS": ("Honeywell 364day", "Key_Credit_Terms_Honeywell_364day.docx"),
            "Honeywell 5yr TS": ("Honeywell 5yr", "Key_Credit_Terms_Honeywell_5yr.docx"),
            "Delta Airlines 2026 TS ": ("Delta Airlines", "Key_Credit_Terms_Delta_Airlines.docx"),
            "Accenture  2026 TS": ("Accenture", "Key_Credit_Terms_Accenture.docx"),
            "APi Group 2026 TS": ("APi Group", "Key_Credit_Terms_APi_Group.docx"),
            "Acme Term Sheet 2025": ("Acme", "Key_Credit_Terms_Acme.docx"),
        }
        for stem, (client, out) in cases.items():
            self.assertEqual(naming.client_name(stem), client)
            self.assertEqual(naming.output_name(naming.client_name(stem)), out)

    def test_is_term_sheet(self):
        self.assertTrue(naming.is_term_sheet(Path("Seadrill 2026 TS.pdf")))
        self.assertFalse(naming.is_term_sheet(Path("Seadrill 2026 CA.pdf")))
        self.assertFalse(naming.is_term_sheet(Path("Seadrill 2026 TS.docx")))
        self.assertFalse(naming.is_term_sheet(Path("Results 2026.pdf")))  # "TS" inside a word does not count

    def test_same_client_twice_keeps_the_year(self):
        files = naming.describe([Path("Acme 2025 TS.pdf"), Path("Acme 2026 TS.pdf"), Path("Beta 2026 TS.pdf")])
        self.assertEqual([f.output_name for f in files],
                         ["Key_Credit_Terms_Acme_2025.docx", "Key_Credit_Terms_Acme_2026.docx", "Key_Credit_Terms_Beta.docx"])

    def test_output_names_never_collide(self):
        files = naming.describe([Path("a/Acme 2026 TS.pdf"), Path("b/Acme 2026 TS.pdf")])
        self.assertEqual(len({f.output_name.lower() for f in files}), 2)


class TextTests(unittest.TestCase):
    PAGE = ("Assignments and           Lenders may assign all or a portion of their loans\n"
            "Participations:           and commitments with the consent of the Borrower – not\n"
            "                          to be unreasonably withheld – in a minimum amount of $5 ,000,000.\n")

    def test_exact_quote_ignores_spacing_case_and_quote_style(self):
        doc = Doc([self.PAGE])
        self.assertTrue(doc.has_quote("to be unreasonably withheld - in a minimum amount of $5,000,000", 1))
        self.assertFalse(doc.has_quote("in a minimum amount of $50,000,000", 1))
        self.assertFalse(doc.has_quote("to be unreasonably withheld", 2))

    def test_loose_quote_tolerates_the_label_column(self):
        doc = Doc([self.PAGE])
        quote = "Lenders may assign all or a portion of their loans and commitments with the consent of the Borrower"
        self.assertFalse(doc.has_quote(quote, 1))  # "Participations:" sits between the two lines
        self.assertTrue(doc.has_quote_loose(quote, 1))
        self.assertEqual(doc.locate(quote, 1)[0], "loose")
        self.assertFalse(doc.has_quote_loose("Lenders may assign their loans without the consent of the Agent or anyone else", 1))

    def test_locate_reports_other_page_and_missing(self):
        doc = Doc(["nothing here", self.PAGE])
        self.assertEqual(doc.locate("in a minimum amount of $5,000,000", 1), ("other_page", [2]))
        self.assertEqual(doc.locate("this sentence is not in the document at all", 1), ("missing", []))

    def test_squash(self):
        self.assertEqual(squash("“Net  Leverage” – 3.50x"), '"netleverage"-3.50x')


class SchemaTests(unittest.TestCase):
    def test_sample_record_is_valid(self):
        self.assertEqual(schema.validate(sample_record()), [])

    def test_validate_catches_problems(self):
        rec = sample_record()
        rec["fields"]["purpose"]["lines"] = []
        rec["fields"]["maturity"]["status"] = "maybe"
        rec["fields"]["security"] = {"lines": ["Unsecured"], "status": "stated", "evidence": [], "note": ""}
        rec["fields"]["ranking"]["evidence"] = [{"quote": "cut ... short", "page": 1}]
        del rec["fields"]["accordion"]
        problems = "\n".join(schema.validate(rec))
        for needle in ("purpose:", "maturity: status", "security: status stated needs", "ellipsis", "accordion: missing"):
            self.assertIn(needle, problems)

    def test_normalise_repairs_a_sloppy_record(self):
        rec = sample_record()
        rec["fields"]["purpose"] = {"lines": "one\n\n two  ", "status": "weird"}
        del rec["fields"]["accordion"]
        rec["fields"]["maturity"]["evidence"] = [{"quote": "  spaced   quote ", "page": "4"}, {"quote": "", "page": 1}, "junk"]
        clean = schema.normalise(rec)
        self.assertEqual(clean["fields"]["purpose"]["lines"], ["one", "two"])
        self.assertEqual(clean["fields"]["purpose"]["status"], "stated")
        self.assertEqual(clean["fields"]["accordion"]["status"], "not_stated")
        self.assertEqual(clean["fields"]["maturity"]["evidence"], [{"quote": "spaced quote", "page": 4}])
        self.assertEqual(set(clean["fields"]), set(FIELD_IDS))

    def test_extraction_schema_and_round_trip(self):
        js = schema.extraction_json_schema()
        item = js["properties"]["fields"]["items"]
        self.assertEqual(item["properties"]["id"]["enum"], FIELD_IDS)
        self.assertFalse(item["additionalProperties"])
        answer = {"doc": {"kind": "term_sheet", "title": "T", "date": "", "notes": ""},
                  "fields": [{"id": "purpose", "lines": ["General corporate purposes"], "status": "stated",
                              "evidence": [{"quote": "general corporate purposes", "page": 1}], "note": ""},
                             {"id": "not_a_field", "lines": ["x"], "status": "stated", "evidence": [], "note": ""}]}
        rec = schema.new_record("C", "C 2026", "C 2026 TS.pdf", "1" * 40, "claude-api")
        left_out = schema.from_extraction(answer, rec)
        self.assertEqual(rec["fields"]["purpose"]["lines"], ["General corporate purposes"])
        self.assertEqual(len(left_out), len(FIELD_IDS) - 1)
        self.assertNotIn("not_a_field", rec["fields"])

    def test_check_evidence_marks_quotes(self):
        rec = sample_record()
        rec["fields"]["purpose"] = {"lines": ["x"], "status": "stated", "note": "",
                                    "evidence": [{"quote": "general corporate purposes", "page": 1}, {"quote": "not there at all", "page": 1}]}
        for fid in FIELD_IDS:
            if fid != "purpose":
                rec["fields"][fid]["evidence"] = []
        tally = schema.check_evidence(rec, Doc(["Used for general corporate\npurposes of the Borrower."]))
        self.assertEqual((tally["total"], tally["exact"], tally["missing"]), (2, 1, 1))
        self.assertEqual([e["found"] for e in rec["fields"]["purpose"]["evidence"]], ["exact", "missing"])


class BriefTests(unittest.TestCase):
    def test_every_field_is_in_the_brief_and_unique(self):
        text = guidance_text()
        for f in FIELDS:
            self.assertIn(f"- {f.id} - ", text)
        self.assertEqual(len(set(FIELD_IDS)), len(FIELD_IDS))
        self.assertEqual(len({f.row for f in FIELDS}), len(FIELDS))

    def test_prompt_names_every_field_and_parses_fenced_json(self):
        prompt = llm.system_prompt()
        for fid in FIELD_IDS:
            self.assertIn(fid, prompt)
        self.assertEqual(llm._load('```json\n{"doc": {}, "fields": []}\n```'), {"doc": {}, "fields": []})
        with self.assertRaises(llm.ExtractionError):
            llm._load("sorry, I cannot")


@unittest.skipUnless(HAVE_DOCS, "Key_Credit_Terms.docx template not found")
class TemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.record = sample_record()
        cls.out = cls.dir / "out.docx"
        cls.report = template.render(copy.deepcopy(cls.record), config.DEFAULT_TEMPLATE, cls.out)
        cls.rows = table_rows(cls.out)
        cls.before = table_rows(config.DEFAULT_TEMPLATE)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_field_lands_in_its_row(self):
        self.assertEqual(len(self.rows), template.STOCK_ROW_COUNT)
        for f in FIELDS:
            self.assertEqual(self.rows[f.row][1], self.record["fields"][f.id]["lines"], f.id)

    def test_nothing_else_changes(self):
        filled = {f.row for f in FIELDS}
        for i, (old, new) in enumerate(zip(self.before, self.rows)):
            if i not in filled:
                self.assertEqual(old, new, f"row {i}")  # section headers and the pricing row
            elif i != 28:
                self.assertEqual(old[0], new[0], f"label of row {i}")
        self.assertEqual(self.rows[28][0], ["Other"])  # "[Other]" loses its brackets once it has content
        doc = Document(str(self.out))
        self.assertEqual(doc.paragraphs[0].text, Document(str(config.DEFAULT_TEMPLATE)).paragraphs[0].text)

    def test_no_placeholder_text_is_left_in_filled_rows(self):
        for f in FIELDS:
            text = " ".join(self.rows[f.row][1])
            for leftover in ("[add other", "[insert amount]", "[detail basket", "remove as applicable", "[Name(s)]", "[Country]"):
                self.assertNotIn(leftover, text)

    def test_formatting_is_kept_and_flags_are_highlighted(self):
        doc = Document(str(self.out))
        trs = doc.tables[0]._tbl.tr_lst
        facility_run = next(trs[0].tc_lst[1].iter(W + "r"))
        self.assertIsNotNone(facility_run.find(W + "rPr").find(W + "b"))  # the Facility value stays bold
        for f in FIELDS:
            highlighted = [r.find(W + "rPr") is not None and r.find(W + "rPr").find(W + "highlight") is not None
                           for r in trs[f.row].tc_lst[1].iter(W + "r") if r.find(W + "t") is not None]  # text runs only
            self.assertTrue(highlighted, f.id)
            expected = self.record["fields"][f.id]["status"] in ("not_stated", "by_reference")
            self.assertTrue(all(h == expected for h in highlighted), f.id)
        self.assertEqual(sorted(self.report["flagged"]), sorted(f.id for f in FIELDS if self.record["fields"][f.id]["status"] != "stated"))

    def test_comments_carry_the_evidence(self):
        with zipfile.ZipFile(self.out) as z:
            comments = z.read("word/comments.xml").decode("utf-8")
            document = z.read("word/document.xml").decode("utf-8")
        with_evidence = sum(1 for f in FIELDS if self.record["fields"][f.id]["evidence"] or self.record["fields"][f.id]["note"])
        self.assertEqual(self.report["comments"], with_evidence + 1)  # one per row with evidence, plus the covering comment
        self.assertEqual(comments.count("<w:comment "), with_evidence + 1)
        self.assertEqual(document.count("<w:commentRangeStart "), with_evidence + 1)
        self.assertIn("a verbatim quote", comments)
        self.assertIn("p.2", comments)

    def test_clean_copy_has_no_comments_or_highlight(self):
        out = self.dir / "clean.docx"
        report = template.render(copy.deepcopy(self.record), config.DEFAULT_TEMPLATE, out, evidence="none", highlight=False, appendix="7")
        self.assertEqual(report["comments"], 0)
        with zipfile.ZipFile(out) as z:
            self.assertNotIn("word/comments.xml", z.namelist())
            document = z.read("word/document.xml").decode("utf-8")
        self.assertNotIn('w:highlight w:val="yellow"', document)
        self.assertEqual(Document(str(out)).paragraphs[0].text.replace("  ", " "), "Appendix 7 - Key Credit Terms")
        self.assertEqual(table_rows(out)[5][1], self.record["fields"]["maturity"]["lines"])

    def test_references_table(self):
        out = self.dir / "table.docx"
        template.render(copy.deepcopy(self.record), config.DEFAULT_TEMPLATE, out, evidence="table")
        doc = Document(str(out))
        self.assertEqual(len(doc.tables), 2)
        self.assertIn("a verbatim quote", doc.tables[1].rows[1].cells[1].text)

    def test_reordered_template_rows_are_still_found(self):
        doc = Document(str(config.DEFAULT_TEMPLATE))
        tbl = doc.tables[0]._tbl
        trs = tbl.tr_lst
        purpose, maturity = trs[4], trs[5]
        maturity.addnext(purpose)  # swap Purpose and Maturity Date
        shuffled = self.dir / "shuffled_template.docx"
        doc.save(str(shuffled))
        out = self.dir / "shuffled.docx"
        template.render(copy.deepcopy(self.record), shuffled, out)
        rows = table_rows(out)
        self.assertEqual(rows[4][1], self.record["fields"]["maturity"]["lines"])
        self.assertEqual(rows[5][1], self.record["fields"]["purpose"]["lines"])

    def test_a_document_that_is_not_the_template_is_rejected(self):
        other = self.dir / "other.docx"
        d = Document()
        d.add_table(rows=2, cols=2)
        d.save(str(other))
        with self.assertRaises(template.TemplateError):
            template.render(copy.deepcopy(self.record), other, self.dir / "x.docx")


class RulesCoreTests(unittest.TestCase):
    TEXT = (
        "Borrower:                 Acme Holdings, Inc., a Delaware corporation\n"
        "                          (the “Borrower”).\n"
        "\n"
        "Assignments and           Lenders may assign their loans with the consent of the Borrower\n"
        "Participations:           (not to be unreasonably withheld) in a minimum amount of\n"
        "                          $5 ,000,000.\n"
        "\n"
        "Financial Covenant:       Maximum Total Net Leverage Ratio of 3.50 to 1.00, tested\n"
        "                          quarterly.\n"
        "\n"
        "Purpose:                  The proceeds will be used for general corporate purposes of\n"
        "                          the Borrower and its subsidiaries.\n"
    )

    def test_wrapped_label_is_one_block_whichever_line_matches(self):
        doc = Doc([self.TEXT])
        for pattern in (r"assignments(\s+and)?", r"participations?"):
            blocks = find_blocks(doc, pattern)
            self.assertEqual(len(blocks), 1, pattern)
            self.assertEqual(blocks[0].label, "Assignments and Participations")
            self.assertTrue(blocks[0].text.startswith("Lenders may assign"))
            self.assertTrue(blocks[0].text.endswith("$5 ,000,000."))

    def test_blocks_stop_at_the_next_label(self):
        doc = Doc([self.TEXT])
        self.assertEqual(find_blocks(doc, r"borrowers?")[0].text, "Acme Holdings, Inc., a Delaware corporation (the “Borrower”).")
        self.assertEqual(find_blocks(doc, r"purpose")[0].text,
                         "The proceeds will be used for general corporate purposes of the Borrower and its subsidiaries.")

    def test_quotes_are_verifiable_or_absent(self):
        ctx = common.Ctx([self.TEXT])
        block = ctx.first(r"financial\s+covenants?")
        quote = ctx.quote(block, r"3\.50\s+to\s+1\.00")
        self.assertIsNotNone(quote)
        self.assertEqual(quote["page"], 1)
        self.assertIn(ctx.raw.locate(quote["quote"], 1)[0], ("exact", "loose"))
        self.assertIsNone(ctx.quote(block, r"interest\s+coverage"))
        self.assertEqual(common.stated(["x"], None)["status"], "not_stated")  # no quote, no claim

    def test_money_and_ratio_formatting(self):
        self.assertEqual([a[1] for a in common.amounts("$1,250,000,000, $275mm, $10.0 billion, $150k, $5 ,000,000, EUR 500 million")],
                         ["$1.25bn", "$275m", "$10.0bn", "$150k", "$5m", "EUR 500m"])
        self.assertEqual(common.restyle_money("up to $1,000,000,000 in total"), "up to $1.0bn in total")
        self.assertEqual(common.fmt_ratio(3.5), "3.50x")

    def test_money_is_never_misread_or_rounded_to_another_figure(self):
        cases = {
            # the whole number is taken, however it is laid out
            "$500,000,000individually": "$500mindividually", "$1,325         ,000,000, including": "$1.325bn, including",
            "$165   million and": "$165m and", "greater of $165\n   million and 50%": "greater of $165m and 50%",
            # no rounding to a different figure; small amounts are written out
            "$3,500 fee": "$3,500 fee", "$325": "$325", "$999,999": "$999,999", "$1,255,000": "$1.255m", "$150,000": "$150k",
            # a unit letter counts only when nothing is glued to it; a new line starting with "K." is not a unit
            "$500 M&A": "$500 M&A", "$500\nK. Other": "$500\nK. Other", "$645                $470": "$645                $470",
            # other currencies keep their own sign or code; "A $1.0bn facility" is the article, not Australian dollars
            "C$100 million": "C$100m", "CHF 500 million": "CHF 500m", "£10m": "GBP 10m", "A $1,000,000,000 senior": "A $1.0bn senior",
            "A$500 million": "A$500m", "US$1bn": "$1.0bn", "USD 50 million": "$50m",
            # the space after an amount is left alone
            "$3,000,000,000 (and shall": "$3.0bn (and shall",
        }
        for source, want in cases.items():
            self.assertEqual(common.restyle_money(source), want, source)

    def test_rules_never_raise_and_always_return_every_field(self):
        for pages in ([""], ["just some words"], [self.TEXT], ["\x00\x0c" * 50], [self.TEXT] * 3):
            answer = rules.extract(pages)
            self.assertEqual(set(answer["fields"]), set(FIELD_IDS))
            rec = schema.new_record("C", "C", "C TS.pdf", "2" * 40, "rules")
            schema.from_extraction(answer, rec)
            rec = schema.normalise(rec)
            self.assertEqual(schema.validate(rec), [])
            tally = schema.check_evidence(rec, Doc(pages))
            self.assertEqual(tally["missing"] + tally["other_page"], 0)
            for entry in answer["fields"].values():
                self.assertFalse(entry.get("note", "").startswith("The rule for this row failed"), entry.get("note"))


class RecordsAndPipelineTests(unittest.TestCase):
    def test_find_current_and_stale(self):
        pool = [{"sha1": "a" * 40, "source_file": "Acme 2026 TS.pdf", "fields": {}}]
        self.assertEqual(records.find(pool, "a" * 40, "renamed.pdf")[1], "current")
        self.assertEqual(records.find(pool, "b" * 40, "acme 2026 ts.PDF")[1], "stale")
        self.assertEqual(records.find(pool, "b" * 40, "Other.pdf"), (None, None))

    def test_engine_choice(self):
        self.assertEqual(pipeline.choose_engine("auto", True), "audited")
        self.assertIn(pipeline.choose_engine("auto", False), ("rules", "claude-api"))
        self.assertEqual(pipeline.choose_engine("rules", True), "rules")
        self.assertIn(pipeline.choose_engine("claude", False), ("claude-api", "claude-cli"))

    def test_audited_records_on_disk_are_valid_and_match_their_pdf(self):
        pool, problems = records.load_all()
        self.assertEqual(problems, [])
        if not HAVE_DOCS or not pool:
            self.skipTest("no audited records or no documents folder")
        by_sha = {pdftext.sha1_of(p): p for p in naming.scan(config.DEFAULT_DOCS_DIR)}
        for rec in pool:
            pdf = by_sha.get(rec["sha1"])
            if pdf is None:
                continue  # the PDF this record was made from is no longer in the folder
            pages, _ = pdftext.extract_pages(pdf)
            clean = schema.normalise({k: v for k, v in rec.items() if not k.startswith("_")})
            tally = schema.check_evidence(clean, Doc(pages))
            self.assertEqual(tally["missing"] + tally["other_page"], 0, f"{pdf.name}: {tally['problems'][:3]}")

    @unittest.skipUnless(HAVE_DOCS, "documents folder not found")
    def test_end_to_end_with_the_rules_engine(self):
        pdfs = naming.scan(config.DEFAULT_DOCS_DIR)
        if not pdfs:
            self.skipTest("no term sheets")
        ts = naming.describe(pdfs)[0]
        with tempfile.TemporaryDirectory() as tmp:
            outcome = pipeline.process(ts, config.DEFAULT_TEMPLATE, Path(tmp), engine="rules", audited=[], save_json=True)
            self.assertTrue(outcome.ok, outcome.error)
            self.assertTrue(outcome.out_path.is_file())
            self.assertEqual(outcome.out_path.name, ts.output_name)
            self.assertEqual(outcome.quotes["missing"] + outcome.quotes["other_page"], 0)
            saved = json.loads(outcome.out_path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(schema.validate(saved), [])
            self.assertEqual(len(table_rows(outcome.out_path)), template.STOCK_ROW_COUNT)

    @unittest.skipUnless(HAVE_DOCS, "documents folder not found")
    def test_audited_engine_refuses_an_unknown_pdf(self):
        ts = naming.describe(naming.scan(config.DEFAULT_DOCS_DIR))[0]
        with tempfile.TemporaryDirectory() as tmp:
            outcome = pipeline.process(ts, config.DEFAULT_TEMPLATE, Path(tmp), engine="audited", audited=[])
            self.assertFalse(outcome.ok)
            self.assertIn("no audited record", outcome.error)


@unittest.skipUnless(HAVE_DOCS, "documents folder not found")
class CliTests(unittest.TestCase):
    def test_inputs_resolve_by_path_file_name_and_client(self):
        docs = config.DEFAULT_DOCS_DIR
        first = naming.scan(docs)[0]
        client = naming.client_name(first.stem)
        for typed in (str(first), first.name, first.stem, client, client.lower()):
            paths, problems = cli.resolve_inputs([typed], docs)
            self.assertEqual((paths, problems), ([first.resolve()], []), typed)
        paths, problems = cli.resolve_inputs([], docs)
        self.assertEqual(len(paths), len(naming.scan(docs)))
        paths, problems = cli.resolve_inputs(["No Such Client"], docs)
        self.assertEqual(paths, [])
        self.assertIn("No Such Client", problems[0])

    def test_credit_agreements_are_not_picked_up_by_default(self):
        paths, _ = cli.resolve_inputs([], config.DEFAULT_DOCS_DIR)
        self.assertTrue(all(naming.is_term_sheet(p) for p in paths))


if __name__ == "__main__":
    unittest.main()
