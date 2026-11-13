"""Unit tests for the deterministic parts of the toolkit (no PDFs or API needed)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recon import inventory, quotes, rules, values as V  # noqa: E402


# ----------------------------------------------------------------- values
def keys(vals):
    return {v.key for v in vals}


def test_money_formats_normalise_to_same_value():
    a = V.parse_money("a $4,200,000,000 facility")
    b = V.parse_money("the $4.2 billion facility")
    c = V.parse_money("U.S. $4,200 million")
    d = V.parse_money("$4.2bn revolver")
    assert keys(a) == keys(b) == keys(c) == keys(d)


def test_money_currencies_and_small_amounts():
    eur = V.parse_money("€214,500,000 euro term loan")[0]
    assert eur.currency == "EUR" and eur.value == 214_500_000
    assert V.parse_money("$500 per day") == []  # below the noise floor


def test_blackline_abutting_figures_capture_inserted_amount():
    vals = [v.value for v in V.parse_money("Commitment is $1,500,000,0001,000,000,000.")]
    assert 1_500_000_000 in vals and 1_000_000_000 in vals


def test_percent_and_bps_share_a_scale():
    assert keys(V.parse_pct("0.125%")) == keys(V.parse_pct("12.5 bps")) == keys(V.parse_pct(".125%"))
    assert keys(V.parse_pct("50 basis points")) == keys(V.parse_pct("0.50%"))


def test_bare_bps_only_when_called():
    assert [v.value for v in V.parse_bare_bps("Level I 6.5 68.5 Level II 10.0")] == [6.5, 68.5, 10.0]


def test_ratios():
    for s in ("3.50 to 1.00", "3.50:1.00", "3.50x", "3.5 to 1"):
        assert [v.value for v in V.parse_ratio(s)] == [3.5], s


def test_dates():
    for s in ("March 16, 2030", "16 March 2030", "3/16/2030", "Mar. 16, 2030"):
        assert [v.value for v in V.parse_dates(s)] == ["2030-03-16"], s


# ----------------------------------------------------------------- inventory
def test_classify_variants():
    assert inventory.classify(Path("Delta Airlines 2026 CA .pdf")) == ("CA", "Delta Airlines 2026")
    assert inventory.classify(Path("Accenture  2026 TS.pdf")) == ("TS", "Accenture 2026")
    assert inventory.classify(Path("Acme Credit Agreement.pdf")) == ("CA", "Acme")
    assert inventory.classify(Path("Acme_term_sheet.pdf")) == ("TS", "Acme")
    assert inventory.classify(Path("random notes.pdf"))[0] is None


def test_scan_flags_missing_components(tmp_path):
    for name in ("Alpha 2026 CA.pdf", "Alpha 2026 TS.pdf", "Beta 2025 CA.pdf", "Gamma TS.pdf", "notes.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.4")
    deals, unclassified = inventory.scan([tmp_path])
    assert deals["Alpha 2026"].status == "complete"
    assert deals["Beta 2025"].status == "missing_ts" and deals["Beta 2025"].missing == ["Term sheet (TS)"]
    assert deals["Gamma"].status == "missing_ca"
    assert [p.name for p in unclassified] == ["notes.pdf"]


# ----------------------------------------------------------------- quotes
def test_quote_location_ignores_whitespace_and_typography():
    idx = quotes.QuoteIndex(["page one text", "the “Maturity Date”   means\nMarch 16, 2030 – subject to extension"])
    assert idx.locate('the "Maturity Date" means March 16, 2030 - subject') == (True, [2])
    assert idx.locate("Maturity Date means June 1, 2031")[0] is False
    assert idx.locate("")[0] is None


# ----------------------------------------------------------------- rules
TS_PAGE = """
Borrower:              Acme Holdings, Inc. (the "Borrower").
Administrative Agent:  Citibank, N.A. ("Citi").
Facility:              A $500 million senior unsecured revolving credit facility.
Maturity:              Five years after closing.
Letter of Credit       A $50 million sublimit for letters of credit.
Sublimit:
Financial Covenant:    Maximum Consolidated Leverage Ratio of 3.50 to 1.00.
Governing Law:         State of New York.
"""

CA_PAGES = [
    """
                       CREDIT AGREEMENT
                     ACME HOLDINGS, INC.,
                         as Borrower,
                       CITIBANK, N.A.,
                    as Administrative Agent
    """,
    """“Aggregate Commitments” means $500,000,000. “Letter of Credit Sublimit” means $50,000,000.
    “Maturity Date” means June 1, 2031.
    Section 7.11 Financial Covenants. The Borrower shall not permit the Consolidated Leverage Ratio to exceed 3.75 to 1.00.
    This Agreement shall be governed by, and construed in accordance with, the law of the State of New York.""",
]


def test_term_sheet_label_parsing():
    labels = [e[0] for e in rules.parse_term_sheet_entries([TS_PAGE])]
    assert "Borrower" in labels and "Facility" in labels
    assert "Letter of Credit Sublimit" in labels  # two-line label joined


def test_cover_roles():
    assert rules.cover_roles(CA_PAGES, r"(?:Administrative) Agent") == ["CITIBANK, N.A."]
    assert rules.cover_roles(CA_PAGES, r"(?:Borrowers?)") == ["ACME HOLDINGS, INC."]


def test_check_deal_flags_covenant_difference_and_matches_the_rest():
    rows = {r["id"]: r for r in rules.check_deal([TS_PAGE], CA_PAGES)}
    assert rows["R01"]["status"] == "match"       # $500m both sides
    assert rows["R03"]["status"] == "match"       # $50m LC sublimit
    assert rows["R09"]["status"] == "differs"     # 3.50x in TS vs 3.75x in CA
    assert "3.50x" in rows["R09"]["explanation"]
    assert rows["R10"]["status"] == "match"       # Citi -> Citibank alias
    assert rows["R11"]["status"] == "match"
    assert rows["R12"]["status"] == "match"       # New York
    assert rows["R13"]["status"] == "match"       # unsecured


def test_trace_figures_marks_missing_numbers():
    trace = rules.trace_figures([TS_PAGE], CA_PAGES)
    by_val = {t["normalised"]: t["found_in_ca"] for t in trace}
    assert by_val["$500m"] is True and by_val["3.50x"] is False


# ----------------------------------------------------------------- regressions from the code review
def test_toc_detection_keeps_covenant_sections_with_ratios():
    body = "Section 7.11 Financial Covenants. The Leverage Ratio shall not exceed 3.75 to 1.00; provided that following a Material Acquisition 4.25 to 1.00 (see Section 6.01(a))."
    toc = "7.11 Financial Covenants 147 7.12 Amendments 148 7.13 Notices 149 7.14 Waivers 150"
    assert not rules._looks_like_toc(body)
    assert rules._looks_like_toc(toc)
    assert rules._looks_like_toc("7.04 FINANCIAL COVENANT ............ 88 7.05 SANCTIONS")


def test_section_window_ignores_cross_references_and_stops_at_next_section():
    ca = rules.Doc(["See Section 7.11 Financial Covenants hereof for details. Section 7.11 Financial Covenants. The ratio shall not exceed "
                    "3.50 to 1.00. Section 7.12 Amendments. Lots of other text 9.99 to 1.00."])
    wins = rules.section_windows(ca, ["Financial Covenants?"])
    assert len(wins) == 1 and "3.50" in wins[0].text and "9.99" not in wins[0].text


def test_quote_check_rejects_number_prefixes():
    idx = quotes.QuoteIndex(["the Facility Amount is $1,000,000,000 in total"])
    assert idx.locate("Facility Amount is $1,000")[0] is False
    assert idx.locate("Facility Amount is $1,000,000,000")[0] is True


def test_classifier_needs_a_separator_before_ca_ts():
    assert inventory.classify(Path("Facts.pdf"))[0] is None
    assert inventory.classify(Path("Topics.pdf"))[0] is None
    assert inventory.classify(Path("Acme-TS.pdf")) == ("TS", "Acme")


def test_tenor_and_blackline_dates():
    assert [v.display() for v in V.parse_tenor("due on the date that is five (5) years after the Closing Date")] == ["5 yr"]
    assert [v.display() for v in V.parse_tenor("the fifth anniversary of the Effective Date")] == ["5 yr"]
    assert [v.value for v in V.parse_tenor("a 364-day revolving credit facility")] == [364.0]
    vals = {v.value for v in V.parse_dates("Maturity Date means March 1716, 20282030")}
    assert {"2030-03-16", "2028-03-17"} <= vals
    assert "2030-03-16" in {v.value for v in V.parse_dates("the 16th day of March, 2030")}


def test_fractional_and_comma_rates_and_ratio_spellings():
    assert {v.value for v in V.parse_pct("1/2 of 1%")} == {50.0}
    assert {v.value for v in V.parse_pct("1,250 basis points")} == {1250.0}
    assert {v.value for v in V.parse_pct("17.516.25 bps")} >= {17.5, 16.25}
    assert [v.value for v in V.parse_ratio("3.50× and")] == [3.5]


def test_ts_governing_law_ignores_incorporation_clauses():
    ts = rules.Doc(["Accenture plc, a company incorporated under the laws of Ireland. ... Governing Law: State of New York."])
    found, _q = rules._ts_law([], ts)
    assert found == {"New York"}


def test_security_class_uses_first_decisive_phrase():
    assert rules._security_class("A senior secured revolving facility; the Borrower's unsecured notes remain outstanding") == "secured"
    assert rules._security_class("A senior unsecured revolving credit facility") == "unsecured"


def test_both_absent_is_not_applicable():
    ts_page = "Borrower:              Acme Holdings, Inc.\nFacility:              A $500 million revolving credit facility.\nMaturity:              June 1, 2031.\nAgent:                 Citibank, N.A.\nPurpose:               General corporate purposes.\n"
    rows = {r["id"]: r for r in rules.check_deal([ts_page], CA_PAGES)}
    assert rows["R04"]["status"] == "not_applicable"   # no swingline anywhere
    assert rows["R03"]["status"] == "not_in_ts"         # CA has an LC sublimit, TS silent
