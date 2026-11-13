"""Rules engine, text side: margins and fees stated in words, the credit spread adjustment, the floor, the opening level,
facilities, security and the document date. Synthetic text only; no PDF is needed.

Run from the ts_benchmark folder:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsbench import rules, values  # noqa: E402
from tsbench.textmodel import squash  # noqa: E402

HEAD = """
                                SUMMARY OF TERMS AND CONDITIONS

Borrower:                         Example Holdings, Inc. (the "Borrower").

Facility:                         A senior secured revolving credit facility in an aggregate principal
                                  amount of $750,000,000.
"""
TITLE = "\n                                SUMMARY OF TERMS AND CONDITIONS\n"
GRID = """
 Level    Leverage Ratio        Term SOFR Loans        Base Rate Loans          Commitment Fee
   I      >= 3.50:1.00               2.00%                  1.00%                   0.30%
   II     < 3.50:1.00                1.75%                  0.75%                   0.25%
   III    < 2.50:1.00                1.50%                  0.50%                   0.20%
"""
WRAP = "\n" + " " * 34  # a value that runs on to a second line of the value column


def extract(body: str, head: str = HEAD) -> dict:
    return rules.extract([head + body], "Example 2026", "Example 2026 TS.pdf")


def row(label: str, value: str) -> str:
    return f"\n{label + ':':<34}{value}\n"


def margins(rec: dict) -> list[list[float]]:
    return [[t["drawn_margin_bps"] for t in g["tiers"]] for g in rec["pricing"]["grids"]]


def opening(rec: dict) -> list[str]:
    return [t["level"] for g in rec["pricing"]["grids"] for t in g["tiers"] if t["is_opening"]]


def fees(rec: dict) -> list[tuple]:
    return [(f["type"], f["bps"], f["bps_low"], f["bps_high"]) for f in rec["pricing"]["fees"]]


def csa(rec: dict) -> tuple:
    return rec["pricing"]["csa"]["applies"], rec["pricing"]["csa"]["bps"]


def facilities(rec: dict) -> list[tuple]:
    return [(f["type"], f["amount_mm"], f["currency"], f["tenor_years"]) for f in rec["facilities"]]


def notes(rec: dict) -> str:
    return " | ".join(rec["_engine"]["notes"])


class Rates(unittest.TestCase):
    def test_percent_written_out(self):
        for text, bps in (("2.25 percent", 225.0), ("2.25 per cent", 225.0), ("0.375%", 37.5), ("25 bps", 25.0), ("20 basis points", 20.0)):
            m = values.RATE_RE.search("a rate of " + text + " per annum")
            self.assertEqual(values.rate_bps(m.group(1), m.group(2)), bps, text)
        self.assertIsNone(values.RATE_RE.search("fifty percent of the Lenders"))


class FlatMargin(unittest.TestCase):
    """A margin stated in words under a pricing label."""

    def test_credit_spread_adjustment_is_not_the_margin(self):
        for line in ("S + 10 bps CSA + 175 bps",
                     "SOFR + 10 bps CSA + 175 bps",
                     "Term SOFR + 0.10% credit spread adjustment + 1.75% per annum.",
                     "Adjusted Term SOFR (Term SOFR + 0.10%) + 1.75%",
                     "Term SOFR + 0.10% + 1.75%",
                     "Term SOFR + CSA of 10 bps + 175 bps",
                     "Term SOFR plus a credit spread adjustment of 0.10% plus 1.75%",
                     "S + CSA + 175 bps",
                     "S + 175 bps + 10 bps CSA",
                     "S + 175 bps"):
            rec = extract(row("Pricing", line))
            self.assertEqual(margins(rec), [[175.0]], line)
            self.assertEqual(opening(rec), ["Flat"], line)
            quote = rec["pricing"]["grids"][0]["tiers"][0]["quote"]
            self.assertTrue("175" in quote or "1.75" in quote, quote)  # the quote shows the margin, not only the adjustment
            self.assertIn(squash(quote), squash(line), line)

    def test_adjustment_is_still_read_as_the_adjustment(self):
        self.assertEqual(csa(extract(row("Pricing", "S + 10 bps CSA + 175 bps"))), (True, 10.0))
        self.assertEqual(csa(extract(row("Pricing", "S + 175 bps + 10 bps CSA"))), (True, 10.0))

    def test_sum_with_no_single_reading_gives_no_margin(self):
        for line in ("S + 10 bps CSA", "SOFR + 1.00% + 2.00%", "Term SOFR plus the Applicable Margin."):
            rec = extract(row("Pricing", line))
            self.assertEqual(margins(rec), [], line)
            self.assertIn("No pricing grid or flat margin", notes(rec), line)

    def test_from_a_to_b_takes_b(self):
        for line in ("The Applicable Margin will be reduced from SOFR + 2.50% to SOFR + 2.00%.",
                     "Reduced from S + 250 bps to S + 200 bps",
                     "Reduced from the current S + 250 bps to S + 200 bps",
                     "Decreased from SOFR + 2.50% to 2.00%"):
            rec = extract(row("Interest Rate", line))
            self.assertEqual(margins(rec), [[200.0]], line)
            self.assertEqual(rec["pricing"]["change_vs_existing"], "Drawn margin changed from 250 bps to 200 bps.", line)
        rec = extract(row("Interest Rate", "S + 200 bps (reduced from S + 250 bps)"))
        self.assertEqual(margins(rec), [[200.0]])

    def test_range_has_two_ends_and_no_opening_level(self):
        for line in ("Term SOFR + 1.50% to 2.00% per annum depending on the Leverage Ratio.",
                     "SOFR + 150 bps to SOFR + 200 bps based on leverage.",
                     "SOFR + 150 - 200 bps based on leverage.",
                     "SOFR + 150" + chr(0x2013) + "200 bps",
                     "Ranging from SOFR + 1.50% to SOFR + 2.00% by leverage.",
                     "From SOFR + 1.50% to SOFR + 2.00%, depending on leverage.",
                     "S + 2.00% to 1.50% depending on ratings"):
            rec = extract(row("Interest Rate", line))
            self.assertEqual(margins(rec), [[150.0, 200.0]], line)
            self.assertEqual(opening(rec), [], line)
            self.assertNotEqual(rec["pricing"]["basis"], "flat", line)
            self.assertIsNone(rec["pricing"]["change_vs_existing"], line)

    def test_second_figure_that_is_not_a_margin_is_no_range(self):
        self.assertEqual(margins(extract(row("Pricing", "S + 300 bps - 50 bps undrawn"))), [])
        self.assertEqual(margins(extract(row("Pricing", "S + 300 bps, 50 bps undrawn"))), [[300.0]])

    def test_range_beside_a_grid_adds_nothing(self):
        rec = extract(row("Interest Rate", "Term SOFR + 1.50% to 2.00% per annum, as set out in the grid below.") + GRID)
        self.assertEqual(margins(rec), [[200.0, 175.0, 150.0]])

    def test_libor_and_percent_in_words(self):
        for line, bench in (("LIBOR + 2.25% per annum.", "LIBOR"), ("Term SOFR plus 2.25 percent per annum.", "Term SOFR"),
                            ("Term SOFR plus 2.25 per cent per annum.", "Term SOFR"), ("Term SOFR plus 225 basis points.", "Term SOFR")):
            rec = extract(row("Interest Rate", line))
            self.assertEqual(margins(rec), [[225.0]], line)
            self.assertEqual(rec["pricing"]["benchmark"], bench, line)

    def test_margin_stated_for_term_sofr_loans(self):
        for line in ("2.25% per annum for Term SOFR Loans and 1.25% for Base Rate Loans.",
                     "2.25% for SOFR Loans; 1.25% for ABR Loans.",
                     "(a) 2.25% in the case of Term SOFR Loans and (b) 1.25% in the case of ABR Loans."):
            tier = extract(row("Applicable Margin", line))["pricing"]["grids"][0]["tiers"][0]
            self.assertEqual((tier["drawn_margin_bps"], tier["base_rate_margin_bps"], tier["is_opening"]), (225.0, 125.0, True), line)

    def test_other_rates_for_loans_are_not_the_margin(self):
        for label, line in (("Applicable Margin", "1.25% for Base Rate Loans."),
                            ("Applicable Margin", "The margin will increase by 0.25% for Term SOFR Loans after the first anniversary."),
                            ("Interest Rate", "Default interest of 2.00% for Term SOFR Loans above the applicable rate."),
                            ("Interest Rate", "The rate is subject to a floor of 0.75% for Term SOFR Loans and 1.75% for Base Rate Loans."),
                            ("Interest Rate", "Plus a credit spread adjustment of 0.10% for Term SOFR Loans."),
                            ("Commitment Fee", "0.25% for Term SOFR Loans"),
                            ("Applicable Margin", "2.25% per annum.")):
            self.assertEqual(margins(extract(row(label, line))), [], line)
        rec = extract(row("Interest Rate", "2.25% for Term SOFR Loans initially.") + GRID)
        self.assertEqual(margins(rec), [[200.0, 175.0, 150.0]])

    def test_adjustment_named_in_an_aside(self):
        for line in ('Term SOFR plus 0.10% (the "SOFR Adjustment") plus 1.75% per annum',
                     'Term SOFR plus 0.10% (the "Adjustment") plus 1.75% per annum',
                     "SOFR + CSA (10 bps) + 175 bps",
                     "S + 175 bps (plus 10 bps CSA)",
                     "S + 175 bps (incl. 10 bps CSA)"):
            self.assertEqual(margins(extract(row("Pricing", line))), [[175.0]], line)

    def test_range_after_the_adjustment(self):
        for line, ends in (("S + 0.10% CSA + 2.00% to 2.50%", [200.0, 250.0]),
                           ("Term SOFR + 0.10% credit spread adjustment + 1.75% to 2.25% per annum depending on leverage", [175.0, 225.0]),
                           ("S + 10 bps CSA + 150 - 200 bps", [150.0, 200.0])):
            rec = extract(row("Pricing", line))
            self.assertEqual((margins(rec), opening(rec)), ([ends], []), line)
        self.assertEqual(margins(extract(row("Pricing", "S + 175 bps + 10 - 25 bps"))), [])  # a range after a margin: no one reading

    def test_rate_that_moves_is_a_range_not_a_change(self):
        for line in ("Stepping down from SOFR + 2.50% to SOFR + 2.00% upon a ratings upgrade",
                     "Decreasing from SOFR + 2.50% to SOFR + 2.00% based on leverage",
                     "Increasing from SOFR + 2.00% to SOFR + 2.50% based on utilization",
                     "The margin will increase from SOFR + 2.00% to SOFR + 2.50% after the first anniversary",
                     "Moves from SOFR + 2.00% to SOFR + 2.50% after year one"):
            rec = extract(row("Interest Rate", line))
            self.assertEqual((margins(rec), opening(rec)), ([[200.0, 250.0]], []), line)
            self.assertIsNone(rec["pricing"]["change_vs_existing"], line)
        for line in ("Margin to be lowered from S + 250 bps to S + 200 bps", "The margin is being cut from SOFR + 2.50% to SOFR + 2.00%"):
            self.assertEqual(margins(extract(row("Interest Rate", line))), [[200.0]], line)

    def test_margin_in_force_before_the_change_is_not_the_margin(self):
        for line in ("Currently SOFR + 2.50%; proposed SOFR + 2.00%", "Existing: SOFR + 2.50%. Proposed: SOFR + 2.00%.",
                     "Current margin of SOFR + 2.50%, reduced to SOFR + 2.00%"):
            rec = extract(row("Interest Rate", line))
            self.assertEqual((margins(rec), opening(rec)), ([[200.0]], ["Flat"]), line)
            self.assertEqual(rec["pricing"]["change_vs_existing"], "Drawn margin changed from 250 bps to 200 bps.", line)
        for line in ("SOFR + 2.00% (currently SOFR + 2.50%)", "SOFR + 2.00% (was SOFR + 2.50%)"):
            self.assertEqual(margins(extract(row("Interest Rate", line))), [[200.0]], line)
        rec = extract(row("Interest Rate", "Currently SOFR + 2.50%; to be reduced"))
        self.assertEqual(margins(rec), [])
        self.assertIn("No pricing grid or flat margin", notes(rec))

    def test_between_two_ends_and_levels_in_a_row(self):
        for line in ("Between SOFR + 1.50% and SOFR + 2.00%", "SOFR + 1.50% / 1.75% / 2.00% based on leverage",
                     "SOFR + 2.00%, 1.75% and 1.50% based on leverage"):
            rec = extract(row("Interest Rate", line))
            self.assertEqual((margins(rec), opening(rec)), ([[150.0, 200.0]], []), line)
        for line, bps in (("S + 175 bps / 25 bps undrawn", 175.0), ("SOFR + 2.25% and 1.25% for Base Rate Loans", 225.0),
                          ("S + 2.25%, 0.50% and 0.25%", 225.0), ("S + 225 bps / 125 bps / 75 bps floor", 225.0)):
            self.assertEqual(margins(extract(row("Interest Rate", line))), [[bps]], line)

    def test_possessive_s_is_not_the_benchmark(self):
        self.assertEqual(margins(extract(row("Pricing", "The Borrower's plus 2.00% option"))), [])
        self.assertEqual(margins(extract(row("Pricing", "The Borrower" + chr(0x2019) + "s plus 2.00% option"))), [])

    def test_range_or_change_stated_for_term_sofr_loans(self):
        for line in ("2.25% - 2.75% for Term SOFR Loans", "From 2.25% to 2.75% for Term SOFR Loans depending on leverage",
                     "225 - 275 bps for Term SOFR Loans"):
            rec = extract(row("Applicable Margin", line))
            self.assertEqual((margins(rec), opening(rec)), ([[225.0, 275.0]], []), line)
        rec = extract(row("Applicable Margin", "Reduced from 2.50% to 2.00% for Term SOFR Loans"))
        self.assertEqual(margins(rec), [[200.0]])
        self.assertEqual(rec["pricing"]["change_vs_existing"], "Drawn margin changed from 250 bps to 200 bps.")
        self.assertEqual(margins(extract(row("Interest Rate", "Prepayment premium of 1.00% for Term SOFR Loans repaid in the first year"))), [])


class OpeningLevel(unittest.TestCase):
    PENALTY = ("If the Borrower fails to" + WRAP + "deliver a compliance certificate when due, Pricing Level I shall apply commencing"
               + WRAP + "on the first business day after the date on which it was required to be delivered.")
    AT_CLOSING = "From the Closing Date until delivery of the first compliance" + WRAP + "certificate, Pricing Level II shall apply."

    def read(self, text: str) -> dict:
        return extract(row("Applicable Margin", "Determined in accordance with the pricing grid below. " + text) + GRID)

    def test_penalty_level_is_not_the_opening_level(self):
        lsta = ("provided that if a Compliance" + WRAP + "Certificate is not delivered when due, then Pricing Level I shall apply as of the first"
                + WRAP + "Business Day after the date on which it was required and shall remain in effect until the"
                + WRAP + "first Business Day following its delivery.")
        for text in (self.PENALTY, lsta):
            rec = self.read(text)
            self.assertEqual(opening(rec), [], text)
            self.assertIn("no statement", rec["pricing"]["grids"][0]["opening_level_note"])

    def test_closing_date_sentence_wins_wherever_it_stands(self):
        for text in (self.PENALTY + WRAP + self.AT_CLOSING, self.AT_CLOSING + WRAP + self.PENALTY,
                     "The initial Pricing Level for reporting purposes shall be deemed Level I. " + WRAP + self.AT_CLOSING):
            self.assertEqual(opening(self.read(text)), ["II"], text)
        self.assertEqual(opening(self.read("Initially, pricing will be set at Level III.")), ["III"])

    def test_sentence_with_both_levels_is_left_alone(self):
        text = ("From the Closing Date until delivery of the first compliance" + WRAP + "certificate, Pricing Level II shall apply, provided that"
                + WRAP + "if the Borrower fails to deliver a certificate when due, Pricing Level I shall apply.")
        self.assertEqual(opening(self.read(text)), [])

    def test_initial_rate_must_be_a_margin(self):
        for body in (row("Extension Option", "The Borrower may extend the initial maturity date by one year subject to an" + WRAP
                         + "extension fee of 1.50% of the commitments."),
                     row("Default Rate", "Overdue amounts on the initial loans bear interest at the applicable rate plus 2.00%" + WRAP + "per annum."),
                     row("Amortization", "The Initial Term Loans will amortize in quarterly instalments of 1.75% of the" + WRAP + "original amount."),
                     row("Upfront Fee", "1.75% of each Lender's initial commitment.")):
            self.assertEqual(opening(extract(body + GRID)), [], body)
        for text in ("The initial Applicable Margin" + WRAP + "for Term SOFR Loans will be 1.75%.",
                     '"Applicable Rate" means, initially (i) with respect to Term Benchmark Loans, 1.75% and' + WRAP
                     + "(ii) with respect to ABR Loans, 0.75%."):
            self.assertEqual(opening(self.read(text)), ["II"], text)

    def test_level_that_applies_on_a_condition_is_not_the_opening_level(self):
        for text in ("If, after the Closing Date, the Borrower does not deliver a" + WRAP + "compliance certificate when due, Pricing Level I shall apply.",
                     "At any time after the Effective Date when the Borrower shall not have" + WRAP
                     + "delivered financial statements, Level I shall apply.",
                     "If the initial compliance certificate is not furnished on time, Level I shall apply.",
                     "In the absence of a compliance certificate after the Closing Date, Level I shall apply.",
                     "Level III shall apply if the initial public offering of the Borrower is completed."):
            self.assertEqual(opening(self.read(text)), [], text)
        self.assertEqual(opening(self.read("On the Closing Date, pricing will be set at Level III.")), ["III"])

    def test_initial_rate_of_the_benchmark_is_not_a_margin(self):
        for text in ("For the initial Interest Period, the Term SOFR rate will be deemed 1.75%.",
                     "Term SOFR shall initially be subject to a 1.50% minimum."):
            self.assertEqual(opening(self.read(text)), [], text)
        for text in ("Initially, Term SOFR plus 1.75%.", "Initial pricing of 1.75% over Term SOFR."):
            self.assertEqual(opening(self.read(text)), ["II"], text)


class CreditSpreadAdjustment(unittest.TestCase):
    RATE = row("Interest Rate", "Term SOFR plus 2.25%.")

    def test_own_row_is_read_and_not_the_row_above(self):
        for above, label, value, want in (
                ("Commitment Fee:                   0.25%", "Credit Spread Adjustment", "None", (False, None)),
                ("Commitment Fee:                   25 bps", "CSA", "N/A", (False, None)),
                ("Commitment Fee:                   25 bps", "CSA", "Not applicable.", (False, None)),
                ("Commitment Fee:                   25 bps", "CSA", "0 bps", (False, None)),
                ("Commitment Fee:                   25 bps", 'Credit Spread Adjustment ("CSA")', "None", (False, None)),
                ("Upfront Fee:                      0.20%", "SOFR Adjustment", "0.10%", (True, 10.0)),
                ("Commitment Fee:                   25 bps", "CSA", "10 bps", (True, 10.0)),
                ("SOFR Floor:                       0.00%", "Credit Spread Adjustment", "0.11448% (1-month), 0.26161% (3-month)", (True, 11.448)),
                ("Commitment Fee:                   25 bps", "Credit Spread Adjustment", "Removal of the 10 bps adjustment.", (False, None)),
                ("Commitment Fee:                   25 bps", "CSA", "TBD", (None, None)),
                ("Commitment Fee:                   25 bps", 'Credit Spread Adjustment ("CSA")', "TBD", (None, None))):
            rec = extract(self.RATE + "\n" + above + "\n" + row(label, value))
            self.assertEqual(csa(rec), want, (above, label, value))
            quote = rec["pricing"]["csa"]["quote"]
            self.assertTrue(want[0] is None or squash(label) in squash(quote), quote)

    def test_row_without_a_colon_and_row_placed_first(self):
        self.assertEqual(csa(extract(self.RATE + "\nFacility Fee                      0.25%\n\nCredit Spread Adjustment          None\n")), (False, None))
        self.assertEqual(csa(extract(self.RATE + "\nFacility Fee                      0.25%\n\nCredit Spread Adjustment          TBD\n")), (None, None))
        self.assertEqual(csa(extract(self.RATE + row("Credit Spread Adjustment", "None") + row("Commitment Fee", "25 bps"))), (False, None))
        self.assertEqual(csa(extract(self.RATE + row("Credit Spread Adjustment", "TBD") + row("Commitment Fee", "25 bps"))), (None, None))

    def test_prose_wording_still_reads(self):
        for line, want in (("Term SOFR plus 2.25%, plus a 10 bps credit spread adjustment.", (True, 10.0)),
                           ("Term SOFR plus 2.25%. Credit spread adjustment: 10 bps for all tenors.", (True, 10.0)),
                           ("Term SOFR plus 2.25%, with no credit spread adjustment.", (False, None)),
                           ("Term SOFR plus 2.25%.", (None, None))):
            self.assertEqual(csa(extract(row("Interest Rate", line) + row("Upfront Fee", "10 bps"))), want, line)

    def test_no_change_is_not_none(self):
        for value in ("No change from the existing 10 bps", "No change (0.10%)"):
            self.assertEqual(csa(extract(self.RATE + row("Credit Spread Adjustment", value) + row("Commitment Fee", "25 bps"))), (True, 10.0), value)
        self.assertEqual(csa(extract(self.RATE + row("CSA", "No CSA"))), (False, None))

    def test_unread_row_does_not_take_the_rate_of_the_row_below(self):
        for rows in ("\nCredit Spread Adjustment          TBD\n\nCommitment Fee                    25 bps\n",
                     "\nCredit Spread Adjustment          TBD\nCommitment Fee                    25 bps\n",
                     "\nCSA                               Included in margin\nUpfront Fee                       10 bps\n",
                     "\nCSA                               To be determined\nSOFR Floor                        0.50%\n"):
            self.assertEqual(csa(extract(self.RATE + rows)), (None, None), rows)

    def test_removal_stated_after_the_current_rate(self):
        self.assertEqual(csa(extract(self.RATE + row("CSA", "Currently 10 bps; to be removed"))), (False, None))
        self.assertEqual(csa(extract(self.RATE + row("CSA", "10 bps; may be removed with the consent of the Required Lenders"))), (True, 10.0))

    def test_rate_of_another_term_is_not_the_adjustment(self):
        for line, want in (("Term SOFR plus 2.25%, 25 bps upfront fee, CSA not applicable.", (None, None)),
                           ("Term SOFR plus CSA, commitment fee 25 bps.", (None, None)),
                           ("Term SOFR plus 2.25% plus a credit spread adjustment of 0.10% per annum.", (True, 10.0)),
                           ("Term SOFR plus 2.25% plus a CSA of 10bps.", (True, 10.0))):
            self.assertEqual(csa(extract(row("Interest Rate", line))), want, line)

    def test_adjustment_of_another_currency(self):
        self.assertEqual(csa(extract(self.RATE + row("Credit Spread Adjustment", "0.29547% for one-month Term CORRA"))), (None, None))
        self.assertEqual(csa(extract(self.RATE + row("Credit Spread Adjustment", "0.10% for Term SOFR; 0.29547% for Term CORRA"))), (True, 10.0))


class Floor(unittest.TestCase):
    def read(self, text: str) -> float | None:
        return extract(row("Amendments", text))["pricing"]["floor"]["pct"]

    def test_voting_and_prepayment_thresholds_are_not_a_floor(self):
        consent = "Changes to the Term SOFR margin require the consent of Lenders holding not less than 66.67%" + WRAP + "of the commitments."
        self.assertIsNone(self.read(consent))
        self.assertIsNone(self.read("Term SOFR Loans may be prepaid in an amount not less than 25% of the outstanding amount."))
        self.assertIsNone(self.read("Term SOFR will be subject to a floor of 5.25%."))
        self.assertEqual(self.read(consent + " Term SOFR shall not be less than 0.50%."), 0.5)

    def test_real_floors(self):
        self.assertEqual(self.read("Term SOFR shall not be less than 0.00%."), 0.0)
        self.assertEqual(self.read("Term SOFR will be subject to a floor of 0.75%."), 0.75)
        self.assertEqual(self.read("Term SOFR Loans bear interest at Term SOFR, which shall not be less than 0.50%."), 0.5)
        self.assertEqual(self.read("In no event shall Term SOFR for any Loans be less than 0.00%."), 0.0)

    def test_small_threshold_on_the_loans_is_not_a_floor(self):
        self.assertIsNone(self.read("Borrowings of Term SOFR Loans shall be in an amount of not less than 1% of the commitments."))
        self.assertIsNone(self.read("Term SOFR Loans may be prepaid subject to a premium of not less than 2%."))


class Fees(unittest.TestCase):
    RATE = row("Interest Rate", "SOFR + 2.25%.")

    def read(self, body: str) -> list[tuple]:
        return fees(extract(self.RATE + body))

    def test_step_down_to_a_level_and_step_down_by_an_amount(self):
        for value, want in (
                ("0.375% per annum on the unused commitments, with a step-down to 0.25% per annum" + WRAP + "when leverage is below 3.00x.", (37.5, 25.0, 37.5)),
                ("0.50% per annum, with one step-down to 0.375% at a First Lien Leverage Ratio of 3.50x.", (50.0, 37.5, 50.0)),
                ("0.375% per annum, with a reduction to 0.25% when leverage is below 3.00x.", (37.5, 25.0, 37.5)),
                ("0.375% per annum, stepping down to 0.25% when leverage is below 3.00x.", (37.5, 25.0, 37.5)),
                ("0.50% per annum, with step-downs to 0.375% and 0.25% based on leverage.", (50.0, 25.0, 50.0)),
                ("0.25% per annum, increasing to 0.375% if leverage exceeds 3.00x.", (25.0, 25.0, 37.5)),
                ("37.5 bps with a 12.5 bps step-down when leverage is below 3.00x.", (37.5, 25.0, 37.5)),
                ("37.5 bps with a 12.5 bps stepdown at First Lien Net Leverage of 2.75x or less", (37.5, 25.0, 37.5)),
                ("37.5 bps, with a step-down of 12.5 bps when leverage is below 3.00x.", (37.5, 25.0, 37.5)),
                ("0.375% per annum, reduced by 0.125% when leverage is below 3.00x.", (37.5, 25.0, 37.5))):
            self.assertEqual(self.read(row("Commitment Fee", value)), [("commitment_fee",) + want], value)

    def test_fractions_of_one_percent(self):
        body = row("Commitment Fee", "3/8 of 1% per annum on the average daily unused commitments.") \
            + row("Upfront Fee", "1/4 of 1% of each Lender's commitment.")
        self.assertEqual(self.read(body), [("commitment_fee", 37.5, None, None), ("upfront_fee", 25.0, None, None)])
        self.assertEqual(self.read(row("Commitment Fee", "1/2 of one percent per annum on the unused commitments.")), [("commitment_fee", 50.0, None, None)])
        self.assertEqual(self.read(row("Commitment Fee", "0.375% (3/8 of 1%) per annum on the unused commitments.")), [("commitment_fee", 37.5, None, None)])
        self.assertEqual(self.read(row("Commitment Fee", "0.25 percent per annum on the unused commitments.")), [("commitment_fee", 25.0, None, None)])

    def test_fee_on_the_facility_amount_is_kept_and_triggers_are_not_fees(self):
        self.assertEqual(self.read(row("Upfront Fee", "0.25% of the Facility amount.")), [("upfront_fee", 25.0, None, None)])
        self.assertEqual(self.read(row("Utilization Fee", "0.125% per annum if more than 50% of the Facility is drawn.")),
                         [("utilization_fee", 12.5, None, None)])
        self.assertEqual(self.read(row("Commitment Fee", "0.25% per annum. Baskets may not exceed 2.0% of Consolidated Total Assets.")),
                         [("commitment_fee", 25.0, None, None)])

    def test_from_a_to_b_takes_b(self):
        for value in ("Reduced from 0.375% to 0.25%.", "Reduced from 37.5 bps to 25 bps",
                      "To be reduced from 0.375% per annum to 0.25% per annum on the unused commitments.", "25 bps (reduced from 37.5 bps)"):
            rec = extract(self.RATE + row("Commitment Fee", value))
            self.assertEqual(fees(rec), [("commitment_fee", 25.0, None, None)], value)
            self.assertEqual(rec["pricing"]["change_vs_existing"], "Commitment fee changed from 37.5 bps to 25 bps.", value)
        self.assertEqual(self.read(row("Commitment Fee", "Reduced from 0.375%, as set out in the amendment.")), [])

    def test_range_is_not_a_change(self):
        for value in ("0.25% to 0.375% per annum depending on leverage.", "Ranging from 0.25% to 0.375% per annum depending on leverage.",
                      "From 0.25% to 0.375% per annum, depending on leverage."):
            rec = extract(self.RATE + row("Commitment Fee", value))
            self.assertEqual(fees(rec), [("commitment_fee", 25.0, 25.0, 37.5)], value)
            self.assertIsNone(rec["pricing"]["change_vs_existing"], value)

    def test_step_up_adds_to_the_fee(self):
        for value in ("0.25% per annum, with a step-up of 0.125% if leverage exceeds 4.0x.",
                      "0.25% per annum, with a 12.5 bps step-up if leverage exceeds 4.0x.",
                      "0.25% per annum, increased by 0.125% if leverage exceeds 4.0x.",
                      "0.25% per annum, with a step-up to 0.375% if leverage exceeds 4.0x.",
                      "0.25% increased to 0.375% during a Leverage Increase Period."):
            self.assertEqual(self.read(row("Commitment Fee", value)), [("commitment_fee", 25.0, 25.0, 37.5)], value)

    def test_size_of_a_change_alone_is_no_fee(self):
        for value in ("Reduced by 12.5 bps.", "12.5 bps reduction.", "A reduction of 12.5 bps from the existing fee.",
                      "Step-down of 12.5 bps to be added.", "Increase of 5 bps."):
            self.assertEqual(self.read(row("Commitment Fee", value)), [], value)
        self.assertEqual(self.read(row("Commitment Fee", "A reduction of 12.5 bps to 25 bps.")), [("commitment_fee", 25.0, None, None)])

    def test_fee_that_moves_is_a_range_not_a_change(self):
        for value, first in (("Stepping down from 0.375% to 0.25% based on leverage.", 37.5),
                             ("Step-down from 0.375% to 0.25% at 3.0x.", 37.5),
                             ("Decreasing from 0.375% to 0.25% as leverage falls.", 37.5),
                             ("Will decrease from 0.375% to 0.25% once leverage is below 3.0x.", 37.5),
                             ("Increasing from 0.25% to 0.375% if leverage exceeds 4.0x.", 25.0)):
            rec = extract(self.RATE + row("Commitment Fee", value))
            self.assertEqual(fees(rec), [("commitment_fee", first, 25.0, 37.5)], value)
            self.assertIsNone(rec["pricing"]["change_vs_existing"], value)

    def test_fee_in_force_before_the_change_is_not_the_fee(self):
        for value in ("0.25% (currently 0.375%)", "0.25% (previously 0.375%)", "Existing: 0.375%. Proposed: 0.25%."):
            rec = extract(self.RATE + row("Commitment Fee", value))
            self.assertEqual(fees(rec), [("commitment_fee", 25.0, None, None)], value)
            self.assertEqual(rec["pricing"]["change_vs_existing"], "Commitment fee changed from 37.5 bps to 25 bps.", value)
        self.assertEqual(self.read(row("Commitment Fee", "Currently 0.375%; proposed 0.25%")), [("commitment_fee", 25.0, None, None)])
        self.assertEqual(self.read(row("Commitment Fee", "Currently 0.375%")), [])
        self.assertEqual(self.read(row("Commitment Fee", "The existing Commitment Fee of 0.25% is unchanged.")), [("commitment_fee", 25.0, None, None)])
        for value in ("Reduced from 37.5 - 50 bps to 25 - 37.5 bps depending on leverage.", "Reduced from 0.375% - 0.50% to 0.25% - 0.375%."):
            rec = extract(self.RATE + row("Commitment Fee", value))
            self.assertEqual(fees(rec), [("commitment_fee", 25.0, 25.0, 37.5)], value)  # the old range is not mixed into the new one
            self.assertIsNone(rec["pricing"]["change_vs_existing"], value)

    def test_range_that_gives_its_unit_once(self):
        for value in ("25 - 37.5 bps", "25.0 to 37.5 bps based on the grid.", "Between 25 and 37.5 bps."):
            got = extract(self.RATE + row("Commitment Fee", value))["pricing"]["fees"]
            self.assertEqual([(f["bps"], f["bps_low"], f["bps_high"]) for f in got], [(25.0, 25.0, 37.5)], value)
        self.assertEqual(extract(self.RATE + row("Commitment Fee", "25 - 37.5 bps"))["pricing"]["fees"][0]["amount_text"], "25 - 37.5 bps")
        labels = self.read(row("Commitment Fee", "Tier 1 - 25 bps; Tier 2 - 37.5 bps"))  # a label and a rate, not a range from 1 bp
        self.assertEqual(labels, [("commitment_fee", 25.0, None, None), ("commitment_fee", 37.5, None, None)])
        self.assertEqual(self.read(row("Commitment Fee", "Levels 1 to 3 - 25 bps")), [("commitment_fee", 25.0, None, None)])

    def test_fractions_in_other_forms(self):
        for value, bps in (("1/2 of 1.00% per annum on the unused commitments.", 50.0), ("one-half of 1% per annum.", 50.0),
                           ("three-eighths of one percent per annum.", 37.5), ("0.375% (three-eighths of one percent) per annum.", 37.5)):
            self.assertEqual(self.read(row("Commitment Fee", value)), [("commitment_fee", bps, None, None)], value)
        for value in ("1 1/4% of the commitments.", "1-1/4% of the commitments."):  # a mixed number is not read as its fraction
            self.assertEqual(self.read(row("Upfront Fee", value)), [], value)
        self.assertEqual(self.read(row("Upfront Fee", "0.25% on a 50/50 basis.")), [("upfront_fee", 25.0, None, None)])

    def test_column_heads_over_a_row_of_rates_are_separate_fees(self):
        table = "\nUpfront Fees:                     Old Money                     New Money\n" + " " * 34 + "10 bps                        25 bps\n"
        got = extract(self.RATE + table)["pricing"]["fees"]
        self.assertEqual([(f["type"], f["bps"], f["bps_high"], f["description"], f["quote"]) for f in got],
                         [("upfront_fee", 10.0, None, "Old Money", "10 bps"), ("upfront_fee", 25.0, None, "New Money", "25 bps")])
        levels = "\nCommitment Fee:                   Level I                       Level II\n" + " " * 34 + "0.20%                         0.25%\n"
        self.assertEqual(self.read(levels), [("commitment_fee", 20.0, 20.0, 25.0)])  # one undrawn fee with a range, as before

    def test_term_out_fee_is_not_taken_from_the_section_next_to_it(self):
        term_out = row("Term-Out Option", "The Borrower may elect to convert the outstanding loans into a term loan maturing one" + WRAP
                       + "year after the Maturity Date, upon payment of a fee of 0.75% of the amount converted.")
        for facility_fee in ("The Borrower will pay a fee of 0.06% per annum on the daily amount of the commitments.",
                             "The Borrower will pay a fee of 0.06% per annum on the daily amount of the commitments",
                             "0.06% per annum on the daily amount of the commitments."):
            got = [(f["type"], f["bps"]) for f in extract(row("Facility Fee", facility_fee) + term_out)["pricing"]["fees"]]
            self.assertEqual(got, [("facility_fee", 6.0), ("term_out_fee", 75.0)], facility_fee)

    def test_term_out_fee_inside_another_section(self):
        body = row("Maturity", "364 days after the Closing Date. The Borrower may elect to convert the outstanding loans into a" + WRAP
                   + "term loan maturing one year later, upon payment of a fee equal to 75 basis points of the amount" + WRAP + "converted.")
        got = [(f["type"], f["bps"]) for f in extract(body + row("Facility Fee", "0.06% per annum on the commitments."))["pricing"]["fees"]]
        self.assertEqual(sorted(got), [("facility_fee", 6.0), ("term_out_fee", 75.0)])


class Facilities(unittest.TestCase):
    def read(self, body: str) -> list[tuple]:
        return facilities(extract(body, TITLE))

    def test_new_amount_and_not_the_one_being_refinanced(self):
        purpose = row("Purpose", "To refinance the Borrower's existing $400,000,000 revolving credit facility.")
        facility = row("Facility", "A senior unsecured revolving credit facility of $600,000,000, replacing the existing" + WRAP
                       + "three-year facility. Commitments terminate five years after the Closing Date.")
        self.assertEqual(self.read(purpose + facility), [("revolver", 600.0, "USD", 5.0)])
        self.assertEqual(self.read(facility + purpose), [("revolver", 600.0, "USD", 5.0)])
        repay = row("Purpose", "To repay in full the $400,000,000 three-year revolving credit facility dated 2021.")
        maturity = row("Maturity", "The fifth anniversary of the Closing Date, subject to two one-year extension options.")
        self.assertEqual(self.read(repay + row("Facility", "A senior unsecured revolving credit facility of $600,000,000.") + maturity),
                         [("revolver", 600.0, "USD", 5.0)])

    def test_amount_in_the_facility_section_is_preferred_to_one_in_the_background(self):
        body = row("Background", "The Company has a $400,000,000 revolving credit facility with a syndicate of banks.") \
            + row("Facility", "A senior unsecured revolving credit facility of $600,000,000.")
        self.assertEqual(self.read(body), [("revolver", 600.0, "USD", None)])
        curly = row("Purpose", "To refinance the Borrower" + chr(0x2019) + "s existing $400,000,000 revolving credit facility.") \
            + row("Facility", "A senior unsecured revolving credit facility of $600,000,000.")
        self.assertEqual(self.read(curly), [("revolver", 600.0, "USD", None)])

    def test_first_amount_stands_when_nothing_is_said_against_it(self):
        title = "\n          $1,000,000,000 SENIOR SECURED REVOLVING CREDIT FACILITY\n" + row("Borrower", "Example Holdings, Inc.")
        tranche = row("Facility", "The revolving credit facility includes a $300,000,000 tranche available in euros.")
        self.assertEqual(facilities(extract(tranche, title))[0][:2], ("revolver", 1000.0))
        proceeds = row("Use of Proceeds", "To refinance existing indebtedness and for working capital under the $600,000,000 revolving" + WRAP
                       + "credit facility. The revolving credit facility also has a $75,000,000 tranche for the UK Borrower.")
        self.assertEqual(self.read(proceeds)[0][:2], ("revolver", 600.0))
        only = row("Purpose", "To refinance the $400,000,000 revolving credit facility.")
        self.assertEqual(self.read(only)[0][:2], ("revolver", 400.0))  # the only amount there is

    def test_lengths_of_time_are_not_tenors(self):
        for text in ("Amend and extend the existing $400,000,000 revolving credit facility by one year.",
                     "A $600,000,000 senior unsecured revolving credit facility with two one-year extension options.",
                     "A $600,000,000 senior unsecured revolving credit facility. Letters of credit may have an expiry" + WRAP
                     + "date of up to one year after issuance.",
                     "A $600,000,000 senior unsecured revolving credit facility. The Borrower may terminate the" + WRAP
                     + "commitments after one year without premium."):
            self.assertIsNone(self.read(row("Facility", text))[0][3], text)
        self.assertEqual(self.read(row("Facility", "A $600,000,000 senior unsecured revolving credit facility maturing five years after closing."))[0][3], 5.0)

    def test_size_after_an_upsize(self):
        for text in ("The existing $400,000,000 revolving credit facility will be upsized to a" + WRAP + "$600,000,000 revolving credit facility.",
                     "The $400,000,000 revolving credit facility will be upsized to $600,000,000.",
                     "The existing $400,000,000 revolving credit facility will be increased to $600,000,000.",
                     "The Revolving Credit Facility will be increased from $400,000,000 to $600,000,000.",
                     "The Borrower will refinance and replace its existing $400,000,000 revolving credit facility" + WRAP
                     + "with a new $600,000,000 revolving credit facility."):
            self.assertEqual(self.read(row("Transaction", text))[0][:2], ("revolver", 600.0), text)

    def test_accordion_is_not_the_facility_size(self):
        text = "A $500,000,000 revolving credit facility, which may be increased to $750,000,000 at the" + WRAP \
            + "Borrower's request under the revolving credit facility accordion."
        self.assertEqual(self.read(row("Facility", text))[0][:2], ("revolver", 500.0))

    def test_existing_facility_is_kept_when_it_is_the_one_being_amended(self):
        self.assertEqual(self.read(row("Transaction", "Amendment and extension of the Borrower's existing $1,000 million Revolving Credit Facility.")),
                         [("revolver", 1000.0, "USD", None)])
        both = row("Transaction", "Amendment of the existing $1,000 million Revolving Credit Facility and a new" + WRAP + "$300 million Term Loan A Facility.")
        self.assertEqual([f[:2] for f in self.read(both)], [("revolver", 1000.0), ("term_loan_a", 300.0)])

    def test_facility_of_another_term_sheet_is_left_out(self):
        text = "The Borrower intends to borrow term loans on the Closing Date (as defined in the Term Loan" + WRAP \
            + "Facility Term Sheet) under a senior unsecured term loan facility in an aggregate principal" + WRAP \
            + "amount of $4,000,000,000 and seeks the $3,000,000,000 five-year revolving loan facility" + WRAP + "described herein."
        self.assertEqual(self.read(row("Transactions", text)), [("revolver", 3000.0, "USD", 5.0)])

    def test_tenor_belongs_to_its_own_facility(self):
        text = "(a) a $500,000,000 five-year revolving credit facility and (b) a $1,250,000,000" + WRAP + "seven-year term loan B facility."
        self.assertEqual(self.read(row("Facilities", text)), [("revolver", 500.0, "USD", 5.0), ("term_loan_b", 1250.0, "USD", 7.0)])
        text = "a five-year revolving credit facility of $500,000,000 and a seven-year term loan B" + WRAP + "facility of $1,250,000,000."
        self.assertEqual(self.read(row("Facilities", text)), [("revolver", 500.0, "USD", 5.0), ("term_loan_b", 1250.0, "USD", 7.0)])

    def test_tranches_with_different_tenors_give_no_tenor(self):
        text = "A senior unsecured revolving credit facility of $2,650,000,000 comprised of (i) a three-year" + WRAP \
            + "tranche in an aggregate amount of $1,325,000,000 and (ii) a five-year tranche in an" + WRAP + "aggregate amount of $1,325,000,000."
        rec = extract(row("Amounts", text), TITLE)
        self.assertEqual(facilities(rec), [("revolver", 2650.0, "USD", None)])
        self.assertIn("more than one tenor", notes(rec))

    def test_tenor_from_the_maturity_section(self):
        facility = row("Facility", "A senior secured revolving credit facility of $600,000,000.")
        for label, text in (("Maturity", "Five years after the Closing Date."),
                            ("Maturity Date", "The date that is five (5) years after the Closing Date."),
                            ("Availability and Maturity", "Available on a revolving basis until the fifth anniversary of the Closing Date.")):
            self.assertEqual(self.read(facility + row(label, text)), [("revolver", 600.0, "USD", 5.0)], text)

    def test_currency(self):
        for text, amount, currency in (("A C$500,000,000 senior unsecured revolving credit facility.", 500.0, "CAD"),
                                       ("A CAD $500,000,000 senior unsecured revolving credit facility.", 500.0, "CAD"),
                                       ("A$250 million senior unsecured revolving credit facility.", 250.0, "AUD"),
                                       ("A EUR 500,000,000 senior unsecured revolving credit facility.", 500.0, "EUR"),
                                       ("A " + chr(0x20AC) + "500 million senior unsecured revolving credit facility.", 500.0, "EUR"),
                                       ("GBP 250,000,000 revolving credit facility.", 250.0, "GBP"),
                                       ("A US$500,000,000 senior unsecured revolving credit facility.", 500.0, "USD"),
                                       ("A $250 million senior unsecured revolving credit facility.", 250.0, "USD"),
                                       ("A NEW $250 MILLION SENIOR UNSECURED REVOLVING CREDIT FACILITY.", 250.0, "USD")):
            self.assertEqual(self.read(row("Facility", text)), [("revolver", amount, currency, None)], text)
        mixed = row("Facilities", "(a) a $500,000,000 revolving credit facility and (b) a EUR 300,000,000 term loan A facility.")
        self.assertEqual([f[:3] for f in self.read(mixed)], [("revolver", 500.0, "USD"), ("term_loan_a", 300.0, "EUR")])
        labelled = row("Borrower", "Example plc") + row("Facility Amount", "EUR 500,000,000") + row("Interest", "Revolving loans bear interest at EURIBOR.")
        self.assertEqual(self.read(labelled), [("revolver", 500.0, "EUR", None)])
        for text, currency in (("A Cdn$500,000,000 senior unsecured revolving credit facility.", "CAD"),
                               ("A Can$500,000,000 senior unsecured revolving credit facility.", "CAD"),
                               ("A USD 500,000,000 senior unsecured revolving credit facility.", "USD"),
                               ("A U.S.$500,000,000 senior unsecured revolving credit facility.", "USD")):
            self.assertEqual(self.read(row("Facility", text)), [("revolver", 500.0, currency, None)], text)

    def test_span_of_amounts_is_not_a_change_of_size(self):
        facility = row("Facility", "A $750,000,000 senior secured revolving credit facility.")
        for label, text in (("Upfront Fee", "10 bps for commitments from $50 million to $100 million under the Revolving Credit Facility; 15 bps above."),
                            ("Allocation", "Lenders are invited to commit from $75 million to $150 million to the Revolving Credit Facility.")):
            self.assertEqual(self.read(facility + row(label, text)), [("revolver", 750.0, "USD", None)], text)
        self.assertEqual(self.read(row("Transaction", "An increase in the Revolving Credit Facility from $750 million to $1,000 million."))[0][:2],
                         ("revolver", 1000.0))

    def test_accordion_worded_with_can_is_not_the_facility_size(self):
        text = "A $500,000,000 revolving credit facility, which can be increased to $750,000,000 with lender consent."
        self.assertEqual(self.read(row("Facility", text))[0][:2], ("revolver", 500.0))

    def test_tenor_of_another_kind_of_facility_is_not_borrowed(self):
        text = "a $500,000,000 revolving credit facility and a seven-year term loan B facility of $1,250,000,000."
        self.assertEqual(self.read(row("Facilities", text)), [("revolver", 500.0, "USD", None), ("term_loan_b", 1250.0, "USD", 7.0)])
        text = "a five-year revolving credit facility of $500,000,000 and a $1,250,000,000 term loan B facility."
        self.assertEqual(self.read(row("Facilities", text)), [("revolver", 500.0, "USD", 5.0), ("term_loan_b", 1250.0, "USD", None)])

    def test_tenor_with_a_decimal_and_extension_wording(self):
        facility = row("Facility", "A senior secured revolving credit facility of $600,000,000.")
        for text, years in (("3.5 years after the Closing Date.", 3.5),
                            ("Five years from closing, which may be extended for one year on up to two occasions.", 5.0),
                            ("The Maturity Date may be extended for up to two successive one-year periods beyond the initial five-year term.", 5.0)):
            self.assertEqual(self.read(facility + row("Maturity", text)), [("revolver", 600.0, "USD", years)], text)


class Security(unittest.TestCase):
    PLAIN = HEAD.replace("senior secured ", "")
    LIEN = "A perfected first-priority security interest in substantially all assets of the Borrower" + WRAP + "and the Guarantors"

    def read(self, label: str, text: str) -> dict:
        return extract(row(label, text), self.PLAIN)["security"]

    def test_fall_away_does_not_make_the_facility_unsecured(self):
        sec = self.read("Collateral", self.LIEN + ". The Collateral will be released upon the Borrower obtaining an" + WRAP
                        + "investment grade rating, whereupon the Facility will be unsecured.")
        self.assertEqual(sec["value"], "secured")
        self.assertIn("released", sec["detail"])
        self.assertEqual(self.read("Collateral", self.LIEN + ", to be released if the Borrower's senior unsecured debt rating is" + WRAP
                                   + "BBB- / Baa3 or better.")["value"], "secured")
        self.assertEqual(self.read("Security", "First-priority liens on substantially all assets, ranking ahead of the Borrower's senior" + WRAP
                                   + "unsecured notes due 2029.")["value"], "secured")
        self.assertEqual(self.read("Security", "The Loans will rank senior to all unsecured debt of the Borrower. The Loans will be" + WRAP
                                   + "secured by a first-priority lien on substantially all assets.")["value"], "secured")

    def test_release_far_down_the_section_is_shown(self):
        text = ("The obligations will be secured by a perfected first-priority security interest in substantially" + WRAP
                + "all present and after-acquired assets of the Borrower and each Guarantor, including a pledge of" + WRAP
                + "the capital stock of each subsidiary, in each case subject to customary exceptions and limitations" + WRAP
                + "to be agreed in the definitive documentation. All of the Collateral shall be released, and the" + WRAP
                + "Facility shall become unsecured, on the first date on which the Borrower has an investment grade rating.")
        sec = self.read("Collateral", text)
        self.assertEqual(sec["value"], "secured")
        self.assertIn("shall be released", sec["detail"])

    def test_sections_that_say_there_is_no_collateral(self):
        for label, text in (("Collateral", "None. The Facility will be unsecured."), ("Security", "The Facility will be unsecured."),
                            ("Security", "Unsecured."), ("Security", "The Facilities will not be secured by any collateral."),
                            ("Security", "The Facility will be unsecured; provided that if the Borrower's rating falls below BBB- / Baa3" + WRAP
                             + "the obligations shall be secured by a first-priority lien on substantially all assets.")):
            self.assertEqual(self.read(label, text)["value"], "unsecured", text)

    def test_unsecured_is_not_read_as_secured(self):
        for label, text in (("Security", "The Facility will constitute senior unsecured obligations of the Borrower."),
                            ("Security", "Senior unsecured."), ("Collateral", "No collateral."), ("Collateral", "N/A"), ("Security", "Not applicable."),
                            ("Security", "The Facility ranks pari passu with all other senior debt. The Facility is unsecured.")):
            self.assertEqual(self.read(label, text)["value"], "unsecured", text)

    def test_section_that_lists_the_assets_is_secured(self):
        for text in ("All assets of the Borrower and the Guarantors.",
                     "Substantially all assets of the Loan Parties. Unsecured hedging obligations are excluded.",
                     "So long as the Borrower's senior unsecured rating is below BBB-, the Facility will be secured by" + WRAP
                     + "first-priority liens on substantially all assets."):
            self.assertEqual(self.read("Collateral", text)["value"], "secured", text)


class DocumentDate(unittest.TestCase):
    BODY = row("Borrower", "Example Holdings, Inc.") + row("Facility", "A senior secured revolving credit facility of $750,000,000.")
    T = "                                SUMMARY OF TERMS AND CONDITIONS\n"

    def read(self, head: str, body: str = "") -> str | None:
        return rules.extract([head + self.BODY + body], "Example 2026", "Example 2026 TS.pdf")["doc"]["date"]

    def test_stamp_or_date_alone_in_the_title_area(self):
        for head, want in ((self.T + "                                        March 5, 2026\n", "2026-03-05"),
                           ("                                        March 5, 2026\n" + self.T, "2026-03-05"),
                           (self.T + "                                   Dated March 5, 2026\n", "2026-03-05"),
                           (self.T + "\nDate:\nMarch 5, 2026\n", "2026-03-05"),
                           ("[Draft 03/ 26/2026]\n" + self.T, "2026-03-26"),
                           ("[CS&M Draft" + chr(0x2014) + "03/   26/2026]\n" + self.T, "2026-03-26"),
                           ("Draft of March 26, 2026\n" + self.T, "2026-03-26"),
                           ("Posting Version 3/25  /26\n" + self.T, "2026-03-25")):
            self.assertEqual(self.read(head), want, head)
        self.assertEqual(self.read(self.T, "\n\n                                                     Draft 6/5/2026\n"), "2026-06-05")

    def test_dates_that_are_not_the_documents_own(self):
        for head in (self.T,
                     self.T + "                                        March 2026\n",
                     "Draft of March 26, 2099\n" + self.T,
                     "Draft 13/45/2026\n" + self.T,
                     self.T + "\nThe Facility is currently scheduled to mature on March 16, 2025. It will be extended.\n",
                     self.T + "\nThis term sheet amends that certain Credit Agreement, dated as of August 1, 2019 (as amended).\n",
                     self.T + "\nThis term sheet amends that certain Credit Agreement, dated as of\nAugust 1, 2019\n(as amended).\n",
                     self.T + "\nSigning of the Existing Credit Agreement took place on or about\nAugust 1, 2019\n",
                     self.T + "\nthat certain Commitment Letter, dated as of May 6, 2025, between the Borrower and the Arrangers.\n",
                     self.T + "\nMaturity Date:\nMarch 16, 2025\n",
                     self.T + "\nMaturity Date                     March 16, 2025\n",
                     self.T + "\nScheduled Maturity\nAugust 1, 2025\n",
                     self.T + "\nExpected Closing\nMarch 16, 2026\n",
                     self.T + "\nThe amended version dated August 1, 2019 of the Existing Credit Agreement governs.\n",
                     self.T + "\nThe terms set out below follow the draft dated August 1, 2019\n"):
            self.assertIsNone(self.read(head), head)

    def test_presentation_may_carry_the_date_on_its_second_page(self):
        cover = "Lender Presentation\nApril 2026\n" + "\n".join(f"Slide text line {i} of the lender presentation" for i in range(10))
        letter = "Company Authorization Letter\nApril 30, 2026\nCitibank N.A.\nLadies and Gentlemen:\nWe refer to the proposed amendment.\n"
        deck = rules.extract([cover, letter, self.BODY, self.BODY], "Example 2026", "Example 2026 TS.pdf")
        self.assertEqual((deck["doc"]["kind"], deck["doc"]["date"]), ("lender_presentation", "2026-04-30"))
        sheet = rules.extract([self.T + self.BODY, letter, self.BODY, self.BODY], "Example 2026", "Example 2026 TS.pdf")
        self.assertEqual((sheet["doc"]["kind"], sheet["doc"]["date"]), ("term_sheet", None))


class ExistingAndProposedColumns(unittest.TestCase):
    """The existing column's table stands for the deal only where the proposed column leaves it unchanged."""

    PAGE = """
                                   Existing                               Proposed
Borrower                           Example Holdings, Inc.                 Same as existing
Facility                           $500 million revolving credit facility $750 million revolving credit facility
Drawn margin                       S + 250 bps                            {margin}
Undrawn fee                        37.5 bps                               {fee}
Maturity                           June 30, 2027                          Five years from closing
"""

    def read(self, margin: str, fee: str) -> tuple[list, list, str]:
        rec = rules.extract([self.PAGE.format(margin=margin, fee=fee)], "Example 2026", "Example 2026 TS.pdf")
        undrawn = [t["undrawn_fee_bps"] for g in rec["pricing"]["grids"] for t in g["tiers"]] + [f["bps"] for f in rec["pricing"]["fees"]]
        return margins(rec), [u for u in undrawn if u is not None], notes(rec)

    def test_proposed_figures_are_read(self):
        self.assertEqual(self.read("S + 200 bps", "25 bps")[:2], ([[200.0]], [25.0]))

    def test_unchanged_cells_fall_back_to_the_existing_table(self):
        for margin, fee in (("Same as existing", "Same as existing"), ("No change", "Unchanged"), ("", "")):
            got = self.read(margin, fee)
            self.assertEqual(got[:2], ([[250.0]], [37.5]), (margin, fee))
            self.assertNotIn("left out", got[2])

    def test_other_proposed_text_keeps_the_existing_table_out(self):
        got = self.read("To be agreed", "To be agreed")
        self.assertEqual(got[:2], ([], []))
        self.assertIn("existing-terms column was left out", got[2])
        self.assertIn("No pricing grid or flat margin", got[2])

    def test_one_changed_cell(self):
        got = self.read("Same as existing", "25 bps")
        self.assertEqual(got[:2], ([[250.0]], [25.0]))
        got = self.read("S + 200 bps", "Same as existing")
        self.assertEqual(got[:2], ([[200.0]], [37.5]))

    def test_proposed_cells_that_only_give_the_size_of_the_change(self):
        got = self.read("Reduced by 50 bps", "Reduced by 12.5 bps")  # neither the existing terms nor the reductions are the new terms
        self.assertEqual(got[:2], ([], []))
        self.assertIn("existing-terms column was left out", got[2])


if __name__ == "__main__":
    unittest.main()
