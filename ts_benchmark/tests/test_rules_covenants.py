"""Rules engine, covenant side: the level of each financial covenant, step-ups, dated schedules, incurrence tests that are
not covenants, the springing flag, test types and the section labels that are read. Synthetic text only; no PDF is needed.

Run from the ts_benchmark folder:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsbench import blocks, covenants, rules, schema, values  # noqa: E402
from tsbench.textmodel import Doc, squash  # noqa: E402

HEAD = """
                                SUMMARY OF TERMS AND CONDITIONS

Borrower:                         Example Holdings, Inc. (the "Borrower").

Facility:                         A senior secured revolving credit facility in an aggregate principal
                                  amount of $750,000,000.
"""
# enough two-column rows for the page to count as one with columns, whatever is added below
COLS = HEAD + """
Purpose:                          The proceeds of the Facility will be used to refinance existing indebtedness,
                                  to pay fees and expenses and for working capital and general corporate
                                  purposes of the Borrower and its subsidiaries, including permitted
                                  acquisitions and capital expenditures in the ordinary course of
                                  business.
"""
PLAIN = """
SUMMARY OF TERMS AND CONDITIONS
Borrower: Example Holdings, Inc.
Facility: A senior secured revolving credit facility in an aggregate principal amount of $750,000,000.
Interest Rate: SOFR + 2.25%.
"""
NEGATIVE = [
    "(a) indebtedness, with an exception for unsecured debt so long as the Total Leverage Ratio does not exceed 6.00:1.00;",
    "(b) restricted payments, permitted so long as the Total Leverage Ratio does not exceed 3.25:1.00;",
    "(c) permitted acquisitions, subject to a Total Leverage Ratio of 5.00:1.00.",
]
WRAP = "\n" + " " * 34  # a value that runs on to a second line of the value column
DEFAULTS = "\nEvents of Default:                Customary.\n"
MATURITY = "\nMaturity:                         Five years.\n"
TOT, NET, SEC, FL = "max_total_leverage", "max_net_leverage", "max_secured_leverage", "max_first_lien_leverage"
ICR, CAP, LIQ, FCC = "min_interest_coverage", "max_debt_to_capitalization", "min_liquidity", "min_fixed_charge_coverage"
LE, BULLET = chr(0x2264), chr(0x2022)


def extract(body: str | list[str], head: str = HEAD) -> dict:
    pages = [head + body] if isinstance(body, str) else body
    return rules.extract(pages, "Example 2026", "Example 2026 TS.pdf")


def sheet(text: str, label: str = "Financial Covenants") -> str:
    """One row of a term sheet: the label, and the text wrapped over the value column."""
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > 84:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    return f"\n{label + ':':<34}" + WRAP.join(lines + [cur]) + "\n\nEvents of Default:                Customary.\n"


def cov(ctype: str, level: float, schedule: tuple = (), step: float | None = None, springing: bool = False) -> tuple:
    return ctype, level, list(schedule), step, springing


def read(body: str | list[str], head: str = HEAD) -> list[tuple]:
    """(type, level, schedule levels, step-up level, springing) of each covenant the engine returns."""
    return [(c["type"], c["threshold"], [row["threshold"] for row in c["schedule"]], c["step_up"]["threshold"], c["springing"]["is_springing"])
            for c in extract(body, head)["financial_covenants"]]


def notes(body: str, head: str = HEAD) -> str:
    return " | ".join(extract(body, head)["_engine"]["notes"])


def levels(text: str, unit: str = "x") -> list[float]:
    return [v for v, _, _ in values.thresholds(text, unit)]


class RatioForms(unittest.TestCase):
    def test_brackets_of_a_draft_are_read_through(self):
        self.assertEqual(levels("of [4.00]:1.00 (with a step-up to [4.50] to 1.00)"), [4.0, 4.5])
        self.assertEqual(levels("of [4.00:1.00] and [3.50]x"), [4.0, 3.5])
        self.assertEqual(levels("not to exceed [65]%", "pct"), [65.0])
        self.assertEqual(levels("not to exceed [TBD]:1.00 or [__]x"), [])

    def test_times(self):
        self.assertEqual(levels("shall not exceed 3.5 times, increasing to 4.00x"), [3.5, 4.0])
        self.assertEqual(levels("of 3.25 times."), [3.25])
        # whole numbers of times count occasions
        self.assertEqual(levels("may be cured no more than 2 times in any year and 5 times in total"), [])

    def test_ratio_written_with_x_on_both_sides(self):
        self.assertEqual(levels("of 3.00x to 1.00x and 2.50x:1.0x"), [3.0, 2.5])
        self.assertEqual(levels("reduced from 2.00x to 1.00x"), [2.0, 1.0])  # two levels, not one ratio
        self.assertEqual(levels("between 3.00x to 1.50x"), [3.0, 1.5])

    def test_other_spellings(self):
        self.assertEqual(levels("3.50-to-1.00, 4.0 x; 3.0X and 2.50 : 1.00"), [3.5, 4.0, 3.0, 2.5])
        self.assertEqual(levels("Net Leverage " + LE + " 3.00x"), [3.0])
        self.assertEqual(levels("shall not exceed 65 percent", "pct"), [65.0])
        self.assertEqual(levels("of 0.65 to 1.00", "pct"), [65.0])

    def test_what_is_not_a_ratio(self):
        self.assertEqual(levels("3.50 to 1.25, $3.5x, 3.5xx and Section 6.05(a)(ix)"), [])


class HeadlineLevel(unittest.TestCase):
    """The level of a test is the figure its sentence sets as the limit, not the first figure after its name."""

    def test_step_up_is_not_the_level(self):
        for text in ("The Total Leverage Ratio shall not exceed 3.5 times, increasing to 4.00x for the four fiscal quarters following a Material Acquisition.",
                     "Maximum Total Leverage Ratio of 3.50 to 1.0, stepping up to 4.00 to 1.0 following a Material Acquisition.",
                     "Maximum Total Leverage Ratio of [3.50]:1.00 (with a step-up to 4.00:1.00 after a Qualified Acquisition).",
                     "Maximum Total Leverage Ratio of [3.50]x, stepping up to [4.00]x after a Qualified Acquisition.",
                     "Total Leverage Ratio not to exceed 3.50x (4.00x following a Material Acquisition).",
                     "Total Leverage Ratio: 3.50x (4.00x during an Acquisition Holiday)."):
            self.assertEqual(read(sheet(text)), [cov(TOT, 3.5, step=4.0)], text)

    def test_step_up_stated_ahead_of_the_level(self):
        for text in ("Following a Qualified Acquisition, the Total Leverage Ratio shall not exceed 4.50 to 1.00 for four quarters; at all other times it "
                     "shall not exceed 4.00 to 1.00.",
                     "Following a Material Acquisition, the Total Leverage Ratio shall not exceed 4.50x for four fiscal quarters. At all other times the "
                     "Total Leverage Ratio shall not exceed 4.00x."):
            self.assertEqual(read(sheet(text)), [cov(TOT, 4.0, step=4.5)], text)

    def test_only_a_step_up_gives_no_covenant_and_a_note(self):
        for text in ("Maximum Total Leverage Ratio of [TBD]:1.00 (with a step-up to 4.50:1.00 after a Qualified Acquisition).",
                     "The Total Leverage Ratio shall not exceed 4 times, increasing to 4.50x following a Material Acquisition.",
                     "Following a Material Acquisition, the Total Leverage Ratio shall not exceed 4.50x for four fiscal quarters."):
            self.assertEqual(read(sheet(text)), [], text)
            self.assertIn("Total Leverage Ratio: only a step-up level (4.50", notes(sheet(text)), text)

    def test_level_after_the_acquisition_being_financed_is_a_level(self):
        text = "Following the Acquisition, the Borrower shall maintain a Total Leverage Ratio of not more than 4.50x."
        self.assertEqual(read(sheet(text)), [cov(TOT, 4.5)])

    def test_figure_inside_a_definition_is_not_the_level(self):
        for text, expected in (
            ("Total Net Leverage Ratio (with cash netting capped at 1.0x of EBITDA) not to exceed 4.25x.", cov(NET, 4.25)),
            ("Total Net Leverage Ratio, with cash netting capped at 1.0x of EBITDA, not to exceed 4.25x.", cov(NET, 4.25)),
            ("Total Net Leverage Ratio not to exceed 4.25x (with cash netting capped at 1.0x of EBITDA).", cov(NET, 4.25)),
            ("Total Net Leverage Ratio (netting up to $250 million of unrestricted cash) not to exceed 4.25x.", cov(NET, 4.25)),
            ("The ratio of Debt to Capitalization (excluding up to 15% of hybrid securities) shall not exceed 65%.", cov(CAP, 65.0)),
            ("The ratio of Debt to Capitalization, excluding up to 15% of hybrid securities, shall not exceed 65%.", cov(CAP, 65.0)),
            ("Minimum Liquidity (unrestricted cash plus availability, excluding cash collateral in excess of $50 million) of $150 million.", cov(LIQ, 150.0)),
        ):
            self.assertEqual(read(sheet(text)), [expected], text)

    def test_level_that_stands_in_brackets_alone_is_still_the_level(self):
        self.assertEqual(read(sheet("Total Leverage Ratio (maximum 3.50x), tested quarterly.")), [cov(TOT, 3.5)])

    def test_levels_written_in_other_forms(self):
        self.assertEqual(read(sheet("The Total Leverage Ratio shall not exceed 3.5 times.")), [cov(TOT, 3.5)])
        self.assertEqual(read(sheet("Maximum Total Leverage Ratio of [4.00]:1.00.")), [cov(TOT, 4.0)])
        self.assertEqual(read(sheet("Debt to Capitalization shall not exceed 65 percent.")), [cov(CAP, 65.0)])

    def test_count_of_equity_cures_is_not_a_level(self):
        text = ("Maximum Total Leverage Ratio of 4.50x. The Leverage Ratio covenant may be cured with equity no more than 2 times in any four fiscal "
                "quarters ending in 2026 and 5 times in total.")
        self.assertEqual(read(sheet(text)), [cov(TOT, 4.5)])

    def test_section_that_names_a_test_without_a_readable_level_says_so(self):
        text = sheet("Maximum Total Leverage Ratio of [TBD]:1.00.")
        self.assertEqual(read(text), [])
        self.assertIn("Total Leverage Ratio (page 1): the financial covenant section names this test, but no level could be read", notes(text))


class FurtherFigures(unittest.TestCase):
    """A second figure in the sentence is a schedule row only with period wording, and a step-up only with step-up wording."""

    def test_small_step_is_an_increment(self):
        for text in ("Maximum Total Leverage Ratio of 4.00x, with a 0.50x step-up for the four fiscal quarters following a Material Acquisition.",
                     "Maximum Total Leverage Ratio of 4.00x, with a step-up of 0.50x for the four fiscal quarters following a Material Acquisition.",
                     "Maximum Total Leverage Ratio of 4.00x, which may be increased by 0.50x for four fiscal quarters following a Material Acquisition.",
                     "Maximum Total Leverage Ratio of 4.00:1.00, with an increase of 0.50:1.00 following a Material Acquisition.",
                     "Maximum Total Leverage Ratio of 4.00x with one 0.50x step-up."):
            self.assertEqual(read(sheet(text)), [cov(TOT, 4.0, step=4.5)], text)

    def test_level_today_and_actual_ratio_are_left_out(self):
        for text in ("Maximum Total Leverage Ratio of 4.50x (currently 4.00x).",
                     "Maximum Total Leverage Ratio: 4.50x (existing: 4.00x).",
                     "Total Leverage Ratio (currently 1.80x) not to exceed 4.50x.",
                     "Maximum Total Leverage Ratio of 4.50x (1.80x as of December 31, 2025).",
                     "Maximum Total Leverage Ratio of 4.50x. As of December 31, 2025 the Borrower's Total Leverage Ratio was 1.80x.",
                     "Maximum Total Leverage Ratio of 4.50x. As of December 31, 2025, the Total Leverage Ratio is 1.80x.",
                     "Maximum Total Leverage Ratio of 4.50x. The Total Leverage Ratio as of December 31, 2025 stood at 1.80x."):
            self.assertEqual(read(sheet(text)), [cov(TOT, 4.5)], text)
        self.assertEqual(read(sheet("As of December 31, 2025 the Borrower's Total Leverage Ratio was 1.80x.")), [])

    def test_dated_level_with_limit_wording_is_a_level(self):
        self.assertEqual(read(sheet("As of December 31, 2026, the Total Leverage Ratio shall not exceed 4.75x.")), [cov(TOT, 4.75)])
        self.assertEqual(read(sheet("Maximum Total Leverage Ratio as of June 30, 2026 of 4.50x.")), [cov(TOT, 4.5)])
        self.assertEqual(read(sheet("Total Leverage Ratio - same as existing: 4.00x.")), [cov(TOT, 4.0)])

    def test_amount_of_another_measure_is_no_schedule(self):
        for text, level in (("Minimum Liquidity of $150,000,000; minimum Consolidated EBITDA of $75,000,000.", 150.0),
                            ("Minimum Liquidity of $250 million at all times. Capital expenditures shall not exceed $400 million in fiscal year 2026.", 250.0)):
            self.assertEqual(read(sheet(text)), [cov(LIQ, level)], text)

    def test_figure_without_period_or_step_up_wording_is_left_out(self):
        for text in ("Maximum Total Leverage Ratio of 4.50x, with EBITDA add-backs for cost savings not to exceed 0.5x.",
                     "Maximum Total Leverage Ratio of 4.50x to 1.00x."):
            self.assertEqual(read(sheet(text)), [cov(TOT, 4.5)], text)

    def test_dated_schedules_still_read(self):
        for text, expected in (
            ("Maximum Total Leverage Ratio of 4.50x, stepping down to 4.00x after December 31, 2027.", cov(TOT, 4.5, (4.5, 4.0))),
            ("Maximum Total Net Leverage Ratio of 5.00x, stepping down to 4.50x on June 30, 2027 and 4.00x on June 30, 2028.", cov(NET, 5.0, (5.0, 4.5, 4.0))),
            ("Consolidated Total Leverage Ratio not to exceed 4.75 to 1.00 through December 31, 2026 and 4.50 to 1.00 thereafter.",
             cov(TOT, 4.75, (4.75, 4.5))),
            ("Maximum Total Leverage Ratio of 4.75x, 4.50x and 4.25x for fiscal years 2025, 2026 and 2027, respectively.", cov(TOT, 4.75, (4.75, 4.5, 4.25))),
            ("Net Leverage Ratio covenant of 4.0x, stepping down to 3.5x after 18 months.", cov(NET, 4.0, (4.0, 3.5))),
            ("Maximum Total Leverage Ratio of 4.75x as of December 31, 2026 and 4.50x as of December 31, 2027.", cov(TOT, 4.75, (4.75, 4.5))),
            ("Total Leverage Ratio: 4.50x, 4.25x as of June 30, 2027 and 4.00x as of June 30, 2028.", cov(TOT, 4.5, (4.5, 4.25, 4.0))),
            ("Minimum Liquidity of $150 million through December 31, 2025 and $100 million thereafter.", cov(LIQ, 150.0, (150.0, 100.0))),
        ):
            self.assertEqual(read(sheet(text)), [expected], text)

    def test_schedule_and_step_up_together(self):
        text = ("Total Leverage Ratio not to exceed 4.75 to 1.00 through December 31, 2026 and 4.50 to 1.00 thereafter, in each case with a "
                "step-up of 0.50x following a Material Acquisition.")
        self.assertEqual(read(sheet(text)), [cov(TOT, 4.75, (4.75, 4.5), step=5.25)])

    def test_two_tests_in_one_sentence(self):
        text = ("(a) Consolidated Total Net Leverage Ratio not to exceed 4.00 to 1.00, which may be increased to 4.50 to 1.00 for four fiscal quarters "
                "following a Material Acquisition; and (b) Consolidated Interest Coverage Ratio of not less than 3.00 to 1.00.")
        self.assertEqual(read(sheet(text)), [cov(NET, 4.0, step=4.5), cov(ICR, 3.0)])
        text = "Maximum Total Leverage Ratio of 4.00x to 1.00x and minimum Interest Coverage Ratio of 3.00x to 1.00x."
        self.assertEqual(read(sheet(text)), [cov(TOT, 4.0), cov(ICR, 3.0)])

    def test_coverage_test_loosens_downwards(self):
        text = "Minimum Interest Coverage Ratio of 3.00x, stepping down to 2.50x following a Material Acquisition."
        self.assertEqual(read(sheet(text)), [cov(ICR, 3.0, step=2.5)])

    def test_bracket_with_another_level_is_not_the_scope_of_the_test(self):
        rec = extract(sheet("Maximum Total Leverage Ratio of 4.50x (currently 4.00x)."))
        self.assertEqual(rec["financial_covenants"][0]["applies_to"], "")


class AmendedLevels(unittest.TestCase):
    """ "from A to B": B is the level, unless the wording makes the increase a step-up or dates it."""

    def test_amendment_takes_the_new_level(self):
        for text, expected, old in (
            ("The maximum Total Leverage Ratio will be increased from 4.00:1.00 to 4.50:1.00.", cov(TOT, 4.5), "4.00:1.00"),
            ("Maximum Total Leverage Ratio increased from 4.00x to 4.50x.", cov(TOT, 4.5), "4.00x"),
            ("Total Leverage Ratio covenant to be reset from 4.00x to 4.50x.", cov(TOT, 4.5), "4.00x"),
            ("Maximum Total Leverage Ratio of 4.50x (increased from 4.00x).", cov(TOT, 4.5), "4.00x"),
            ("Minimum Interest Coverage Ratio reduced from 3.00x to 2.50x.", cov(ICR, 2.5), "3.00x"),
            ("Minimum Interest Coverage Ratio reduced from 2.00x to 1.00x.", cov(ICR, 1.0), "2.00x"),
            ("Minimum Liquidity reduced from $150 million to $100 million.", cov(LIQ, 100.0), "$150 million"),
        ):
            rec = extract(sheet(text))
            self.assertEqual(read(sheet(text)), [expected], text)
            self.assertEqual(rec["financial_covenants"][0]["change_vs_existing"], f"Existing level: {old}.", text)
            self.assertIn(squash(rec["financial_covenants"][0]["threshold_text"]), squash(rec["financial_covenants"][0]["quote"]), text)

    def test_conditional_or_temporary_increase_is_a_step_up(self):
        for text in ("The Total Leverage Ratio shall not exceed 3.50 to 1.00; provided that it may be increased from 3.50 to 1.00 to 4.00 to 1.00 for four "
                     "fiscal quarters following a Material Acquisition.",
                     "The Total Leverage Ratio shall be increased from 3.50 to 1.00 to 4.00 to 1.00 following a Material Acquisition.",
                     "The Total Leverage Ratio will be temporarily increased from 3.50x to 4.00x.",
                     "During a Covenant Holiday the Total Leverage Ratio is increased from 3.50x to 4.00x.",
                     "The maximum Total Leverage Ratio may, at the Borrower's election, be increased from 3.50:1.00 to 4.00:1.00 for four consecutive "
                     "fiscal quarters."):
            rec = extract(sheet(text))
            self.assertEqual(read(sheet(text)), [cov(TOT, 3.5, step=4.0)], text)
            self.assertIsNone(rec["financial_covenants"][0]["change_vs_existing"], text)

    def test_dated_change_is_a_schedule(self):
        text = "Maximum Total Leverage Ratio of 4.50x, stepping down from 4.50x to 4.00x on June 30, 2027."
        self.assertEqual(read(sheet(text)), [cov(TOT, 4.5, (4.5, 4.0))])


class LeverageTests(unittest.TestCase):
    """A leverage test that says which leverage it is keeps its own type."""

    def test_second_test_keeps_its_type(self):
        for text, expected in (
            ("(a) First Lien Net Leverage Ratio not to exceed 4.50:1.00 and (b) Total Leverage Ratio not to exceed 6.00:1.00.", [cov(FL, 4.5), cov(TOT, 6.0)]),
            ("(a) Total Net Leverage Ratio not to exceed 4.00:1.00 and (b) Total Leverage Ratio not to exceed 5.00:1.00.", [cov(NET, 4.0), cov(TOT, 5.0)]),
            ("(a) Senior Secured Leverage Ratio not to exceed 3.00:1.00 and (b) Total Leverage Ratio not to exceed 5.00:1.00.", [cov(SEC, 3.0), cov(TOT, 5.0)]),
            ("(a) Total Leverage Ratio not to exceed 5.00:1.00 and (b) Senior Secured Leverage Ratio not to exceed 3.00:1.00.", [cov(TOT, 5.0), cov(SEC, 3.0)]),
            ("First Lien Leverage Ratio not to exceed 3.00x and Senior Leverage Ratio not to exceed 4.50x.", [cov(FL, 3.0), cov(TOT, 4.5)]),
        ):
            self.assertEqual(read(sheet(text)), expected, text)

    def test_test_named_without_a_level_does_not_rename_the_next_one(self):
        for second, ctype in (("Total Net Leverage Ratio", NET), ("Total Leverage Ratio", TOT)):
            text = f"(a) Senior Secured Net Leverage Ratio not to exceed [TBD]:1.00 and (b) {second} not to exceed 5.00:1.00."
            rec = extract(sheet(text))
            self.assertEqual(read(sheet(text)), [cov(ctype, 5.0)], text)
            self.assertEqual(rec["financial_covenants"][0]["name"], second)

    def test_loose_reference_still_takes_the_type_of_the_test_it_refers_to(self):
        rec = extract(sheet("Consolidated Net Leverage Ratio: the Leverage Ratio shall not exceed 3.50:1.00."))
        self.assertEqual([(c["type"], c["name"], c["threshold"]) for c in rec["financial_covenants"]], [(NET, "Consolidated Net Leverage Ratio", 3.5)])
        text = ("Consolidated Net Leverage Ratio. The Borrower will maintain a ratio of Total Funded Debt to Consolidated EBITDA of not more than 3.50 to "
                "1.00, and following a Material Acquisition the Leverage Ratio may be increased to 4.00 to 1.00.")
        self.assertEqual(read(sheet(text)), [cov(NET, 3.5, step=4.0)])


class IncurrenceTests(unittest.TestCase):
    """A ratio that another term is conditional on is not a maintenance covenant."""

    def test_section_ends_at_the_next_numbered_or_bulleted_label(self):
        rows = ["Borrower: Example Holdings, Inc.", "Facility: A $750,000,000 revolving credit facility.", "Interest Rate: SOFR + 2.25%.",
                "Financial Covenants: Maximum Total Leverage Ratio of 4.50:1.00, tested quarterly.",
                "Negative Covenants: Customary for facilities of this type, including limitations on:\n" + "\n".join(NEGATIVE),
                "Events of Default: Customary."]
        for lead in ("{}. ", "{}) ", BULLET + " ", "- ", ""):
            page = "\nSUMMARY OF TERMS AND CONDITIONS\n" + "\n".join(lead.format(i + 1) + row for i, row in enumerate(rows)) + "\n"
            self.assertEqual(read(page, ""), [cov(TOT, 4.5)], lead)

    def test_lettered_labels(self):
        page = ("\nSUMMARY OF TERMS AND CONDITIONS\nA. Borrower: Example Holdings, Inc.\nB. Facility: A $750,000,000 revolving credit facility.\n"
                "C. Financial Covenants: Maximum Total Leverage Ratio of 4.50:1.00, tested quarterly.\n"
                "D. Negative Covenants: Customary for facilities of this type, including limitations on:\n" + "\n".join(NEGATIVE)
                + "\nE. Events of Default: Customary.\n")
        self.assertEqual(read(page, ""), [cov(TOT, 4.5)])

    def test_numbered_items_under_an_unnumbered_label_stay_in_its_section(self):
        page = PLAIN + "Financial Covenants:\n1. Minimum Interest Coverage Ratio: 3.00x\n2. Maximum Leverage Ratio: 3.50x\nEvents of Default: Customary.\n"
        self.assertEqual(read(page, ""), [cov(ICR, 3.0), cov(TOT, 3.5)])
        page = ("\nSUMMARY OF TERMS AND CONDITIONS\n1. Borrower: Example Holdings, Inc.\n7. Financial Covenants:\n"
                "(a) Maximum Total Leverage Ratio of 4.50:1.00;\n"
                "(b) Minimum Interest Coverage Ratio of 3.00:1.00.\n8. Negative Covenants: Unsecured debt up to a Total Leverage Ratio of 6.00:1.00.\n")
        self.assertEqual(read(page, ""), [cov(TOT, 4.5), cov(ICR, 3.0)])

    def test_condition_inside_the_covenant_section(self):
        for text in ("Maximum Total Leverage Ratio of 4.50:1.00, tested quarterly. Restricted payments are permitted so long as the Total Leverage Ratio is "
                     "less than 3.00:1.00.",
                     "Maximum Total Leverage Ratio of 4.50:1.00, tested quarterly. For the avoidance of doubt, the Borrower may make unlimited restricted "
                     "payments so long as the Total Leverage Ratio is less than 3.00:1.00.",
                     "Maximum Total Leverage Ratio of 4.50:1.00, tested quarterly, and restricted payments permitted so long as the Total Leverage Ratio "
                     "is below 3.00x.",
                     "Maximum Total Leverage Ratio of 4.50x. Restricted payments permitted so long as the Total Leverage Ratio as of the last day of the "
                     "most recently ended fiscal quarter is less than 3.00x.",
                     "Maximum Total Leverage Ratio of 4.50x. Dividends are permitted so long as the Total Leverage Ratio does not exceed 3.00:1.00 "
                     "through December 31, 2027 and 2.75:1.00 thereafter.",
                     "Maximum Total Leverage Ratio of 4.50x. Permitted acquisitions are subject to pro forma compliance with a Total Leverage Ratio "
                     "of 5.00x.",
                     "Total Leverage Ratio not to exceed 4.50x; unlimited restricted payments if the Total Leverage Ratio is below 3.00x.",
                     "Maximum Total Leverage Ratio of 4.50x. The Applicable Margin increases by 0.25% whenever the Total Leverage Ratio exceeds "
                     "3.50x."):
            self.assertEqual(read(sheet(text)), [cov(TOT, 4.5)], text)
            self.assertIn("it reads as a condition for another term", notes(sheet(text)), text)

    def test_condition_alone_gives_no_covenant_and_a_note(self):
        text = sheet("None. Restricted payments are permitted so long as the Total Leverage Ratio is less than 3.00:1.00.")
        self.assertEqual(read(text), [])
        self.assertIn("Total Leverage Ratio of 3.00:1.00: the text does not say that this level is maintained or tested", notes(text))

    def test_run_of_conditions_after_a_covenant(self):
        text = "Maximum Total Leverage Ratio of 4.50:1.00, tested quarterly. Negative Covenants: Customary, including limitations on: " + " ".join(NEGATIVE)
        self.assertEqual([(f.kind, f.value) for f in covenants._scan(text)], [("level", 4.5), ("condition", 6.0), ("condition", 3.25), ("condition", 5.0)])

    def test_maintenance_wording_keeps_the_covenant(self):
        for text, expected in (
            ("The Borrower shall maintain, on a pro forma basis, a Total Leverage Ratio not exceeding 4.00x.", [cov(TOT, 4.0)]),
            ("The Facility will be subject to a maximum Total Leverage Ratio of 4.50x.", [cov(TOT, 4.5)]),
            ("The Borrower will be subject to the following financial covenants: (a) Total Leverage Ratio not to exceed 4.50x and (b) Interest "
             "Coverage Ratio of at least 3.00x.", [cov(TOT, 4.5), cov(ICR, 3.0)]),
            ("Subject to the Documentation Principles, a Total Net Leverage Ratio of no greater than 4.00:1.00.", [cov(NET, 4.0)]),
        ):
            self.assertEqual(read(sheet(text)), expected, text)

    def test_step_up_wording_is_not_a_condition(self):
        for text, step in (("Total Leverage Ratio not to exceed 3.75 to 1.00; provided that for four fiscal quarters following a Permitted Acquisition, "
                            "the Leverage Ratio shall not exceed 4.25 to 1.00.", 4.25),
                           ("Maximum Total Leverage Ratio of 3.75:1.00 (subject to a step-up to 4.25x following a Material Acquisition).", 4.25),
                           ("Total Leverage Ratio not to exceed 3.75x, increasing to 4.25x if a Material Acquisition has occurred.", 4.25),
                           ("Maximum Total Leverage Ratio of 3.75x. If a Material Acquisition occurs, the Total Leverage Ratio may be increased to "
                            "4.25x.", 4.25)):
            self.assertEqual(read(sheet(text)), [cov(TOT, 3.75, step=step)], text)


class SpringingAndTypes(unittest.TestCase):
    def test_qualifier_inside_a_definition_does_not_make_the_test_springing(self):
        for text in ("Total Net Leverage Ratio (netting unrestricted cash only to the extent held in the United States) not to exceed 4.00:1.00.",
                     "Total Net Leverage Ratio (netting unrestricted cash solely to the extent held in the United States) not to exceed 4.00:1.00.",
                     "Total Net Leverage Ratio (calculated net of cash only to the extent such cash is unrestricted) not to exceed 4.00x.",
                     "Total Net Leverage Ratio not to exceed 4.00:1.00, with unrestricted cash netted only to the extent held in deposit accounts in "
                     "the United States."):
            self.assertEqual(read(sheet(text)), [cov(NET, 4.0)], text)

    def test_springing_tests_are_still_flagged(self):
        for text, expected in (
            ("Term Loan B: None. Revolving Facility: a springing First Lien Net Leverage Ratio of 7.75:1.00, tested only if utilization exceeds 35% "
             "of the Revolving commitments.", cov(FL, 7.75, springing=True)),
            ("Total Leverage Ratio not to exceed 7.75x, applicable only when more than 35% of the Revolving Facility is drawn.",
             cov(TOT, 7.75, springing=True)),
            ("First Lien Leverage Ratio (tested only when Revolving Loans are outstanding) not to exceed 6.50x.", cov(FL, 6.5, springing=True)),
            ("Solely to the extent the Revolving Facility is more than 35% drawn, First Lien Leverage Ratio not to exceed 6.50x.",
             cov(FL, 6.5, springing=True)),
            ("Net First Lien Leverage Ratio of 3.75x, only to be tested quarterly when 30% of facility is drawn.", cov(FL, 3.75, springing=True)),
        ):
            self.assertEqual(read(sheet(text)), [expected], text)

    def test_debt_service_coverage_is_not_interest_coverage(self):
        rec = extract(sheet("Minimum Debt Service Coverage Ratio of 1.20x and minimum Interest Coverage Ratio of 3.00x."))
        got = [(c["type"], c["name"], c["direction"], c["threshold"]) for c in rec["financial_covenants"]]
        self.assertEqual(got, [("other", "Debt Service Coverage Ratio", "min", 1.2), (ICR, "Interest Coverage Ratio", "min", 3.0)])
        rec = extract(sheet("Minimum Debt Service Coverage Ratio of 1.20x."))
        metrics = schema.derive({k: v for k, v in rec.items() if not k.startswith("_")})["metrics"]
        self.assertIsNone(metrics["coverage"])  # kept out of the interest coverage benchmark
        self.assertEqual(read(sheet("Minimum Fixed Charge Coverage Ratio of 1.10x.")), [cov(FCC, 1.1)])


class Labels(unittest.TestCase):
    """The headings under which covenants are looked for."""

    def test_leading_word(self):
        for label in ("Financial Covenants", "Financial Covenant", "Key Financial Covenants", "Principal Financial Covenants", "FINANCIAL COVENANTS"):
            self.assertEqual(read(sheet("Total Net Leverage Ratio not to exceed 4.25x.", label)), [cov(NET, 4.25)], label)

    def test_label_wrapped_over_two_lines(self):
        for page in (
            "\nFinancial                         Maximum Total Leverage Ratio of 4.00x.\nCovenants:\n\nEvents of Default:                Customary.\n",
            "\nFINANCIAL\nCOVENANTS:                        Maximum Total Leverage Ratio of 4.00x.\n\nEvents of Default:                Customary.\n",
            "\nFinancial                         Maximum Total Leverage Ratio of 4.00x, tested\nCovenants:                        quarterly.\n\n"
            "Events of Default:                Customary.\n",
            "\nMaximum Total                     4.00 to 1.00, tested quarterly.\nLeverage Ratio:\n\nEvents of Default:                Customary.\n",
        ):
            rec = extract(page)
            self.assertEqual(read(page), [cov(TOT, 4.0)], page)
            self.assertTrue(rec["financial_covenants"][0]["quote"], page)  # still tied to the page, if only by the level
        page = ("\n         Financial                    Total Net Leverage Ratio not to exceed 4.25x and Interest\n"
                "         Covenants:                   Coverage Ratio of at least 3.00x.\n\n         Events of Default:           Customary.\n")
        self.assertEqual(read(page), [cov(NET, 4.25), cov(ICR, 3.0)])
        self.assertEqual(read(PLAIN + "Financial\nCovenants:\nMaximum Total Leverage Ratio of 3.5x\nEvents of Default: Customary.\n", ""), [cov(TOT, 3.5)])

    def test_what_is_not_a_wrapped_covenant_label(self):
        page = ("\nNegative                          Limitations on indebtedness, with a maximum Total Leverage Ratio of 5.00x for\n"
                "Covenants:                        ratio debt, and on liens.\n\nEvents of Default:                Customary.\n")
        self.assertEqual(read(page), [])
        page = "\nCovenants and Events of Default\nFinancial Covenants:              Maximum Total Leverage Ratio of 4.00x.\n" + DEFAULTS
        self.assertEqual(read(page), [cov(TOT, 4.0)])
        page = "\nFinancial                         Maximum Total Leverage Ratio of 4.00x.\nMaintenance\nCovenants:\n" + DEFAULTS
        self.assertEqual(read(page), [])  # a label over three lines is not joined

    def test_general_covenants_heading_is_read_for_maintenance_tests_only(self):
        for text, expected in (
            ("Maximum Total Leverage Ratio of 4.00x; Minimum Interest Coverage of 3.00x.", [cov(TOT, 4.0), cov(ICR, 3.0)]),
            ("Total Leverage Ratio not to exceed 4.00x and Interest Coverage Ratio of at least 3.00x, each tested quarterly.", [cov(TOT, 4.0), cov(ICR, 3.0)]),
            ("Usual and customary for facilities of this type, including a Total Leverage Ratio of 4.00x.", []),
            ("Customary affirmative and negative covenants, including a limitation on restricted payments, which are permitted subject to a maximum "
             "pro forma Total Net Leverage Ratio of 2.50x.", []),
        ):
            self.assertEqual(read(sheet(text, "Covenants")), expected, text)
        self.assertIn("is not listed as a financial covenant", notes(sheet("Usual and customary, including a Total Leverage Ratio of 4.00x.", "Covenants")))

    def test_baskets_of_a_general_section_are_not_covenants(self):
        baskets = ("(i) indebtedness (with exceptions for ratio debt subject to a pro forma Total Net Leverage Ratio of 4.50x); (ii) liens (including "
                   "liens securing debt so long as the Secured Net Leverage Ratio does not exceed 3.00x); (iii) restricted payments (unlimited if the "
                   "Total Net Leverage Ratio is less than 2.50x); (iv) investments, with a maximum Total Net Leverage Ratio of 3.25x for unlimited "
                   "investments")
        page = sheet("Usual and customary for facilities of this type, including limitations on: " + baskets + ".", "Covenants")
        self.assertEqual(read(page), [])
        self.assertEqual(notes(page).count("is not listed as a financial covenant"), 3)  # three notes say enough
        page = sheet("Usual and customary, including: (a) Negative Covenants - limitations on: " + baskets + "; (b) Financial Covenant - Maximum Total "
                     "Net Leverage Ratio of 4.00x, tested quarterly.", "Covenants")
        self.assertEqual(read(page), [cov(NET, 4.0)])
        page = (sheet("Maximum Total Leverage Ratio of 4.00x, tested quarterly.").split("\n\nEvents")[0]
                + sheet("Customary, including permitted acquisitions with a Total Leverage Ratio of up to 4.50x.", "Covenants"))
        self.assertEqual(read(page), [cov(TOT, 4.0)])  # no step-up taken from the general section

    def test_covenants_stated_under_a_general_heading(self):
        for text, expected in (
            ("Usual and customary for investment grade facilities of this type, including a maximum Consolidated Leverage Ratio of 3.50:1.00 and a "
             "minimum Interest Coverage Ratio of 3.00:1.00.", [cov(TOT, 3.5), cov(ICR, 3.0)]),
            ("Financial covenant limited to a maximum Debt to Capitalization Ratio of 65%.", [cov(CAP, 65.0)]),
            ("Customary limitations on liens, mergers and sale of assets. The Borrower shall maintain a ratio of Total Debt to EBITDA of not more "
             "than 3.50 to 1.00.", [cov(TOT, 3.5)]),
        ):
            self.assertEqual(read(sheet(text, "Covenants")), expected, text)

    def test_test_under_its_own_sub_heading_inside_a_general_section_is_read_once(self):
        page = ("\nCovenants:                        Usual and customary, including, with respect to the financial covenants:\n\n"
                "                                            Maximum Leverage Ratio: The Company shall not permit, as of the last\n"
                "                                            day of any fiscal quarter, the Leverage Ratio to exceed 3.75 to 1.00;\n"
                "                                            provided, however, that following a permitted acquisition the Leverage\n"
                "                                            Ratio as of the last day of such fiscal quarter shall not exceed 4.25 to 1.00.\n\n"
                "                                  In addition, a basket for liens securing permitted acquisitions.\n\n"
                "Events of Default:                Customary.\n")
        rec = extract(page)
        self.assertEqual(read(page), [cov(TOT, 3.75, step=4.25)])
        self.assertNotIn("basket", rec["financial_covenants"][0]["step_up"]["detail"])  # read from the sub-heading, not from the section around it
        self.assertEqual(notes(page).count("financial covenant"), 0)

    def test_heading_on_its_own_line(self):
        page = ("\nFinancial Covenants:\nMaximum Total Leverage Ratio of 4.00x, tested quarterly.\nMinimum Liquidity of $150 million\n\n"
                "Events of Default:\nCustomary.\n")
        self.assertEqual(read(page, COLS), [cov(TOT, 4.0), cov(LIQ, 150.0)])
        page = ("\n   Financial Covenants:\n\n   Total Net Leverage Ratio not to exceed 4.25x.\n   Events of Default:\n"
                "   Customary; cross-default above $50 million.\n")
        self.assertEqual(read(page, COLS), [cov(NET, 4.25)])

    def test_heading_style_section_ends_at_the_next_heading(self):
        for following in ("Negative Covenants:\nLimitation on debt, with ratio debt permitted up to a Total Leverage Ratio of 5.00x.\n",
                          "NEGATIVE COVENANTS\nLimitations on debt (ratio debt up to a Total Leverage Ratio of 5.00x), liens and restricted payments.\n"):
            page = "\nFinancial Covenants:\nMaximum Total Leverage Ratio of 4.00x.\n\n" + following
            self.assertEqual(read(page, COLS), [cov(TOT, 4.0)], following)
        page = "\nFinancial Covenants:\nEvents of Default:\nCustomary, with a Total Leverage Ratio of 9.00x mentioned here.\n"
        self.assertEqual(read(page, COLS), [])
        page = "\nFinancial Covenants\nMaximum Total Leverage Ratio of 4.00x.\n\nEvents of Default:\nCustomary.\n"
        self.assertEqual(read(page, COLS), [])  # a heading without a colon is left alone, as before


class Blocks(unittest.TestCase):
    """blocks.find_blocks, which rules.py also uses for fees, security and facilities."""

    def test_wrapped_label_is_one_block(self):
        doc = Doc([HEAD + "\nCommitment                        0.25% per annum on the unused\nFee:                              commitments.\n" + MATURITY])
        found = blocks.find_blocks(doc, r"commitment\s+fees?")
        self.assertEqual([(b.label, b.text, len(b.lines)) for b in found], [("Commitment Fee", "0.25% per annum on the unused commitments.", 2)])
        self.assertEqual(found[0].line.text.strip()[:10], "Commitment")
        doc = Doc([HEAD + "\nLETTER OF\nCREDIT FEES:                      0.125% per annum on the face amount.\n" + MATURITY])
        self.assertEqual([b.text for b in blocks.find_blocks(doc, r"letters?\s+of\s+credit\s+fees?")], ["0.125% per annum on the face amount."])

    def test_lines_that_do_not_make_one_label_are_not_joined(self):
        doc = Doc([HEAD + "\nCommitment Fee:                   0.25% per annum.\nFee:                              0.50% upfront.\n"])
        self.assertEqual([b.text for b in blocks.find_blocks(doc, r"commitment\s+fees?")], ["0.25% per annum."])
        doc = Doc([HEAD + "\nCommitment                        0.25% per annum.\n\nFee:                              0.50% upfront.\n"])
        self.assertEqual(blocks.find_blocks(doc, r"commitment\s+fees?"), [])  # a blank line between them: two rows

    def test_second_line_of_a_longer_label_is_marked(self):
        doc = Doc([HEAD + "\nNegative                          Limitations on debt.\nCovenants:                        And on liens.\n\n"
                   "Covenants:                        Customary.\n"])
        self.assertEqual([b.continues for b in blocks.find_blocks(doc, r"covenants?")], [True, False])

    def test_heading_on_its_own_line_owns_the_text_below_it(self):
        doc = Doc([COLS + "\nCommitment Fee:\n0.25% per annum on the unused commitments.\npayable quarterly in arrears.\n\nMaturity:\nFive years.\n"])
        self.assertEqual([b.text for b in blocks.find_blocks(doc, r"commitment\s+fees?")],
                         ["0.25% per annum on the unused commitments. payable quarterly in arrears."])
        doc = Doc([COLS + "\nCommitment Fee\n0.25% per annum on the unused commitments.\n"])
        self.assertEqual([b.text for b in blocks.find_blocks(doc, r"commitment\s+fees?")], [""])  # no colon: a heading, as before

    def test_plain_page_section_ends_at_a_label_marked_like_its_own(self):
        page = "\nTERMS\n1. Fees: 0.25% per annum.\n(a) Upfront Fee: 10 bps.\n2. Maturity: Five years.\n3. Other: None.\n"
        self.assertEqual([b.text for b in blocks.find_blocks(Doc([page]), r"fees")], ["0.25% per annum. (a) Upfront Fee: 10 bps."])
        page = "\nTERMS\nFees: 0.25% per annum.\n1. Upfront Fee: 10 bps.\n2. Agency Fee: To be agreed.\nMaturity: Five years.\n"
        self.assertEqual([b.text for b in blocks.find_blocks(Doc([page]), r"fees")], ["0.25% per annum. 1. Upfront Fee: 10 bps. 2. Agency Fee: To be agreed."])


if __name__ == "__main__":
    unittest.main()
