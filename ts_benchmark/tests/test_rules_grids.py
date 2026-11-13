"""Pricing grid and existing-versus-proposed layout tests on synthetic page text (no PDFs needed).

Run from the ts_benchmark folder:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsbench import tables, views  # noqa: E402
from tsbench.textmodel import Doc  # noqa: E402

BULLET = chr(0x2022)
GRID = """
 Level    Leverage Ratio        Term SOFR Loans        Base Rate Loans          Commitment Fee
   I      >= 3.50:1.00               2.00%                  1.00%                   0.30%
   II     < 3.50:1.00                1.75%                  0.75%                   0.25%
   III    < 2.50:1.00                1.50%                  0.50%                   0.20%
"""
ROWS = GRID.split("\n", 2)[2]  # the three rows without their header
NEXT_ROWS = ("   IV     < 2.00:1.00                1.25%                  0.25%                   0.15%\n"
             "   V      < 1.50:1.00                1.00%                  0.00%                   0.10%\n")
CRITERIA_GRID = GRID.replace(" Level ", "       ").replace("   I  ", "      ").replace("   II ", "      ").replace("   III", "      ")
PAGE_NUMBER = "\n\n" + " " * 52 + "9\n"
COMPARISON = """
                                   Existing                               Proposed
Borrower                           Example Holdings, Inc.                 Same as existing
Facility                           $500 million revolving credit facility $750 million revolving credit facility
Drawn margin                       S + 250 bps                            S + 200 bps
Undrawn fee                        37.5 bps                               25 bps
Maturity                           June 30, 2027                          Five years from closing
"""
SECTIONS = """
Commitment Fee:                   0.375% per annum on the unused commitments.

Financial Covenants:              Maximum Total Leverage Ratio of 4.50:1.00 and minimum Interest Coverage Ratio of
                                  3.00:1.00, each tested quarterly.
"""


def regrid(a: str, b: str, c: str, grid: str = GRID) -> str:
    """The grid with other SOFR margins."""
    return grid.replace("2.00%", a).replace("1.75%", b).replace("1.50%", c)


def find(pages: str | list[str], notes: list[str] | None = None) -> list[tables.Grid]:
    return tables.find_grids(Doc(pages if isinstance(pages, list) else [pages]), notes)


def rates(grid: tables.Grid, key: str = "drawn") -> list[float | None]:
    return [t.values.get(key) for t in grid.tiers]


def levels(grid: tables.Grid) -> list[str]:
    return [t.level for t in grid.tiers]


class SplitPageLabels(unittest.TestCase):
    """R00: on an existing-versus-proposed page the row label sits in the label column, left of the proposed cell."""

    def proposed(self, text: str) -> tuple[Doc, list[tables.Grid]]:
        raw = Doc([text])
        view = views.split_views(raw)[0]
        return raw, tables.find_grids(view)

    def test_named_rows_are_read_from_the_proposed_column(self):
        raw, grids = self.proposed(COMPARISON)
        self.assertEqual(len(grids), 1)
        self.assertEqual(grids[0].tiers[0].values, {"drawn": 200.0, "commitment_fee": 25.0})
        self.assertTrue(grids[0].transposed)
        self.assertEqual(grids[0].tiers[0].quote, "S + 200 bps")  # the quote stays inside the proposed cell
        self.assertTrue(raw.has_quote(grids[0].tiers[0].quote, 1))

    def test_other_row_names_and_rate_styles(self):
        text = COMPARISON.replace("Drawn margin     ", "Applicable Margin").replace("Undrawn fee   ", "Commitment Fee").replace(
            "S + 250 bps ", "SOFR + 2.50%").replace("S + 200 bps", "SOFR + 2.00%").replace("37.5 bps", "0.375%  ").replace("25 bps", "0.25%")
        _, grids = self.proposed(text)
        self.assertEqual([t.values for g in grids for t in g.tiers], [{"drawn": 200.0, "commitment_fee": 25.0}])

    def test_levels_in_the_label_column(self):
        _, grids = self.proposed("""
                                   Existing                               Proposed
Level I                            S + 250 bps                            S + 200 bps
Level II                           S + 225 bps                            S + 175 bps
Level III                          S + 200 bps                            S + 150 bps
""")
        self.assertEqual(len(grids), 1)
        self.assertEqual(levels(grids[0]), ["I", "II", "III"])
        self.assertEqual(rates(grids[0]), [200.0, 175.0, 150.0])

    def test_section_label_is_not_mixed_into_a_grid_s_own_criteria(self):
        _, grids = self.proposed("""
                                   Existing                               Proposed
Borrower                           Example Holdings, Inc.                 Same as existing
                                   Ratings        SOFR margin             Ratings        SOFR margin
                                   BB / Ba2         2.750%                BB / Ba2         2.500%
Applicable Margin                  BB- / Ba3        3.000%                BB- / Ba3        2.750%
                                   B+ / B1          3.250%                B+ / B1          3.000%
Commitment fee                     0.50%                                  0.375%
""")
        self.assertEqual(len(grids), 1)
        self.assertEqual([t.criteria for t in grids[0].tiers], ["BB / Ba2", "BB- / Ba3", "B+ / B1"])
        self.assertEqual(rates(grids[0]), [250.0, 275.0, 300.0])


class FeeLinesBesideGrid(unittest.TestCase):
    """R03: a labelled rate of its own next to a grid is a term of the deal, never a tier."""

    def assert_three_tiers(self, text: str):
        grids = find(text)
        self.assertEqual(len(grids), 1, text)
        self.assertEqual(rates(grids[0]), [200.0, 175.0, 150.0])
        self.assertEqual(levels(grids[0]), ["I", "II", "III"])
        self.assertEqual([t.criteria for t in grids[0].tiers], [">= 3.50:1.00", "< 3.50:1.00", "< 2.50:1.00"])
        self.assertEqual(grids[0].metric, "Leverage Ratio")
        self.assertEqual(grids[0].undrawn_fee_type, "commitment_fee")

    def test_fee_line_below_the_grid(self):
        self.assert_three_tiers(GRID + "\nUpfront Fee:                      0.10%\n")
        self.assert_three_tiers(GRID + "\nUpfront Fee:                      10 bps\n")

    def test_fee_lines_above_the_grid(self):
        self.assert_three_tiers("\nUpfront Fee:                      0.20%\n\nSOFR Adjustment:                  0.10%\n" + GRID)
        self.assert_three_tiers("\nUpfront Fee:                      0.10%\n" + GRID)

    def test_fee_lines_below_an_indented_grid(self):
        wide = GRID.replace("\n ", "\n" + " " * 34)
        self.assert_three_tiers(wide + "\nFronting Fee:                     0.125%\n\nUpfront Fee:                      0.10%\n")

    def test_fee_line_without_a_colon(self):
        self.assert_three_tiers(GRID + "\nUpfront Fee                       0.10%\n")

    def test_single_rate_in_a_column_of_its_own(self):
        self.assert_three_tiers(GRID + "\nMFN protection                              50 bps\n")

    def test_fee_line_beside_a_one_column_grid(self):
        grid = """
                    Leverage           Pricing
                    >= 3.50x           S + 200 bps
 Pricing:           < 3.50x            S + 175 bps
                    < 2.50x            S + 150 bps
"""
        for text in (grid + "\n Undrawn Fee:                          37.5 bps\n", "\n Commitment fee                        50 bps" + grid):
            grids = find(text)
            self.assertEqual(len(grids), 1)
            self.assertEqual(rates(grids[0]), [200.0, 175.0, 150.0])

    def test_labelled_rows_alone_are_still_a_sideways_table(self):
        grids = find("\nPricing:\nDrawn:               S + 300 bps\nUndrawn: 50 bps\nLC:                        3.00%\n")
        self.assertEqual([t.values for g in grids for t in g.tiers], [{"drawn": 300.0, "commitment_fee": 50.0, "lc": 300.0}])
        grids = find("\nDrawn                S + 300 bps\nUndrawn              50 bps\nLC Fee:              3.00%\n")
        self.assertEqual([t.values for g in grids for t in g.tiers], [{"drawn": 300.0, "commitment_fee": 50.0, "lc": 300.0}])

    def test_relative_label_stays_a_tier(self):
        grids = find("""
 Applicable Margin:      Months 1-6:           2.00%
                         Months 7-12:          2.25%
                         Thereafter:           2.50%
""")
        self.assertEqual([rates(g) for g in grids], [[200.0, 225.0, 250.0]])

    def test_level_rows_written_with_colons_stay_tiers(self):
        grids = find("\n Pricing Grid\n Level I:           2.00%        0.30%\n Level II:          1.75%        0.25%\n"
                     " Level III:         1.50%        0.20%\n")
        self.assertEqual([levels(g) for g in grids], [["I", "II", "III"]])

    def test_row_wrapped_over_two_rate_lines_stays_one_tier(self):
        grids = find("""
                                         Commitment     Term Benchmark      ABR Loans      Letters of Credit
 Level   Rating                             Fee              Loans
    I      A3/A-/A- or better           0.08%                1.00%                   0%                     0.875%
   II      Baa1/BBB+/BBB+                                                                                    1.00%
           or better                    0.10%               1.125%                0.125%
   III     Baa2/BBB/BBB                0.125%                1.25%                 0.25%                    1.125%
""")
        self.assertEqual(len(grids), 1)
        self.assertEqual(grids[0].tiers[1].values, {"commitment_fee": 10.0, "drawn": 112.5, "base": 12.5, "lc": 100.0})
        self.assertEqual(grids[0].tiers[1].criteria, "Baa1/BBB+/BBB+ or better")

    def test_label_that_reads_as_criteria_stays_a_tier(self):
        grids = find("\n" + " " * 25 + "Rating                    Margin\n" + " " * 25 + "A- / A3 or better:        1.00%\n"
                     + " " * 25 + "BBB+ / Baa1:              1.125%\n" + " " * 25 + "Lower or unrated:         1.50%\n")
        self.assertEqual([rates(g) for g in grids], [[100.0, 112.5, 150.0]])

    def test_tier_with_one_rate_out_of_line_stays_and_the_named_rate_beside_it_goes(self):
        text = GRID.replace("1.50%                  0.50%                   0.20%", "         1.50%") + " MFN protection" + " " * 31 + "50 bps\n"
        grids = find(text)
        self.assertEqual([rates(g) for g in grids], [[200.0, 175.0, 150.0]])  # four tiers before, the last one at 50 bps

    def test_default_rate_line_under_a_one_column_grid(self):
        grids = find("\n" + " " * 20 + "Leverage           Margin\n" + " " * 20 + ">= 3.50x           2.00%\n"
                     + " " * 20 + "< 3.50x            1.75%\n"
                     + " " * 20 + "< 2.50x            1.50%\n Default Rate:" + " " * 25 + "2.00%\n")
        self.assertEqual([rates(g) for g in grids], [[200.0, 175.0, 150.0]])  # no grid at all before: 2.00% broke the order

    def test_named_terms_without_a_colon_under_a_one_column_grid(self):
        grid = "\n" + " " * 20 + "Leverage           Margin\n" + " " * 20 + ">= 3.50x           2.00%\n" + " " * 20 + "< 3.50x            1.75%\n" \
               + " " * 20 + "< 2.50x            1.50%\n"
        for line in (" MFN protection" + " " * 24 + "0.50%", " MFN protection" + " " * 12 + "0.50%", " Default rate" + " " * 26 + "0.75%",
                     " Amortisation" + " " * 26 + "1.00%"):
            self.assertEqual([rates(g) for g in find(grid + line + "\n")], [[200.0, 175.0, 150.0]], line)  # a fourth tier before

    def test_lines_of_percentages_are_not_sorted_into_a_grid(self):
        # none of these rows is a tier, so "Gross margin" and "EBITDA margin" are not taken out to make a table of their own
        self.assertEqual(find("\n Net revenues      13.7%\n Gross margin      6.7%\n Segment earnings  16.5%\n EBITDA margin     9.7%\n"), [])

    def test_flat_pair_after_a_grid_is_a_table_of_its_own(self):
        grids = find(GRID + "\nTerm Loan B\nDrawn:                            S + 300 bps\nUndrawn:                          50 bps\n")
        self.assertEqual([len(g.tiers) for g in grids], [3, 1])
        self.assertEqual(grids[1].tiers[0].values, {"drawn": 300.0, "commitment_fee": 50.0})


class TableBoundaries(unittest.TestCase):
    """R05: two grids on one page are two tables; a grid cut by a page break is one."""

    def test_existing_grid_printed_above_the_proposed_one(self):
        old, new = "\n" + " " * 36 + "Existing Pricing Grid\n", "\n" + " " * 36 + "Proposed Pricing Grid\n"
        for text in (old + regrid("2.75%", "2.50%", "2.25%") + new + GRID,  # merged before: one grid of six tiers, 150-275
                     old + regrid("2.25%", "2.00%", "1.75%") + new + GRID,  # not in order before: no grid at all
                     new + GRID + old + regrid("2.75%", "2.50%", "2.25%"),
                     old + regrid("2.75%", "2.50%", "2.25%") + "\n" * 8 + new + GRID):
            grids = find(text)
            self.assertEqual(len(grids), 1)
            self.assertEqual(rates(grids[0]), [200.0, 175.0, 150.0])
            self.assertEqual(grids[0].heading, "Proposed Pricing Grid")
            self.assertIn("Existing Pricing Grid", " ".join(grids[0].notes))

    def test_existing_grid_alone_is_kept(self):
        grids = find("\n" + " " * 36 + "Existing Pricing Grid\n" + GRID)
        self.assertEqual([rates(g) for g in grids], [[200.0, 175.0, 150.0]])

    def test_existing_grid_for_another_facility_is_kept(self):
        grids = find("\n   Existing Revolver Pricing\n" + GRID + "\n   New Term Loan B Pricing\n" + regrid("3.00%", "2.75%", "2.50%"))
        self.assertEqual([rates(g) for g in grids], [[200.0, 175.0, 150.0], [300.0, 275.0, 250.0]])

    def test_two_facilities_on_one_page(self):
        text = "\n" + " " * 36 + "Revolving Facility\n" + GRID + "\n" + " " * 36 + "Term Loan B Facility\n" + regrid("3.25%", "3.00%", "2.75%")
        grids = find(text)
        self.assertEqual([rates(g) for g in grids], [[200.0, 175.0, 150.0], [325.0, 300.0, 275.0]])
        self.assertIn("Revolving Facility", grids[0].context)
        self.assertNotIn("Revolving Facility", grids[1].context)  # the heading of the table above is not this table's

    def test_header_row_alone_separates_criteria_only_grids(self):
        grids = find(regrid("2.75%", "2.50%", "2.25%", CRITERIA_GRID) + CRITERIA_GRID)
        self.assertEqual([rates(g) for g in grids], [[275.0, 250.0, 225.0], [200.0, 175.0, 150.0]])

    def test_restarted_levels_separate_tables_and_unread_rows_are_noted(self):
        grids = find("\n" + " " * 25 + "Pricing Grid\n" + GRID + "\n Term Loan Facility\n" + regrid("3.00%", "2.75%", "2.50%", ROWS))
        self.assertEqual([rates(g) for g in grids], [[200.0, 175.0, 150.0]])  # the rows below have no header of their own
        self.assertIn("3 rate rows below this table were not read", " ".join(grids[0].notes))

    def test_tables_run_together_are_reported_not_read(self):
        notes: list[str] = []
        text = CRITERIA_GRID + "\n Term Loan Facility\n" + regrid("3.00%", "2.75%", "2.50%", CRITERIA_GRID.split("\n", 2)[2])
        self.assertEqual(find(text, notes), [])
        self.assertEqual(len(notes), 1)
        self.assertIn("Page 1: a pricing table of 6 rows was not read", notes[0])

    def test_unheaded_percentages_are_not_reported(self):
        notes: list[str] = []
        self.assertEqual(find("\n Net revenues      13.7%\n Gross margin      6.7%\n Segment earnings  16.5%\n EBITDA margin     9.7%\n", notes), [])
        self.assertEqual(notes, [])

    def test_wrapped_criteria_do_not_end_a_table(self):
        grids = find("""
                       Public Debt Rating                                    Applicable
                          S&P/Moody's                                          Margin
                             Level 1                                            0.50  %
                      AA- or Aa3 or above
                             Level 2                                           0.625  %
               Lower than Level 1 but at least A+ or A1
                             Level 3                                            0.75  %
               Lower than Level 2 but at least A or A2 by each of the two rating agencies
""")
        self.assertEqual([rates(g) for g in grids], [[50.0, 62.5, 75.0]])
        grids = find(GRID.replace("\n   II ", "\n" + " " * 82 + "(waived)\n   II "))  # a word under one of three rate columns
        self.assertEqual([rates(g) for g in grids], [[200.0, 175.0, 150.0]])

    def test_page_read_without_layout_is_not_split_on_position(self):
        text = ("Existing Terms Proposed Terms\nFacility: $500 million Senior Secured Revolving Credit Facility\nSame as existing\nPricing:\n"
                "Drawn: S + 300 bps\nSame as existing\nUndrawn: 50 bps\nSame as existing\nLC: 3.00%\nSame as existing\nConsent Fee: 10 bps\n")
        grids = find(text)  # every line starts at the left edge: "Same as existing" is above nothing
        self.assertEqual([t.values for g in grids for t in g.tiers], [{"drawn": 300.0, "commitment_fee": 50.0, "lc": 300.0}])
        self.assertEqual(grids[0].notes, [])  # the consent fee is a fee with a name of its own, not an unnamed row

    def test_descending_level_numbers_are_one_table(self):
        grids = find(GRID.replace("   I  ", "   3  ").replace("   II ", "   2  ").replace("   III", "   1  "))
        self.assertEqual([levels(g) for g in grids], [["3", "2", "1"]])

    def test_grid_carried_over_a_page_break(self):
        page_1 = "\nPricing Grid\n" + GRID.replace("Commitment Fee", "Facility Fee  ") + PAGE_NUMBER
        for page_2 in ("\n" + NEXT_ROWS + "\nEvents of Default:                Customary.\n",
                       "Example Holdings, Inc. - Summary of Terms\n\n" + NEXT_ROWS,  # a running header
                       "\n" + GRID.split("\n")[1].replace("Commitment Fee", "Facility Fee  ") + "\n" + NEXT_ROWS,  # header repeated
                       "\n" + NEXT_ROWS.replace("       ", "    ")):  # another character grid on the next page
            grids = find([page_1, page_2])
            self.assertEqual(len(grids), 1, page_2)
            self.assertEqual(levels(grids[0]), ["I", "II", "III", "IV", "V"])
            self.assertEqual(rates(grids[0]), [200.0, 175.0, 150.0, 125.0, 100.0])
            self.assertEqual(rates(grids[0], "facility_fee"), [30.0, 25.0, 20.0, 15.0, 10.0])  # the first page's header names it
            self.assertEqual(grids[0].page, 1)
            self.assertIn("runs on to page 2: 2 tiers", " ".join(grids[0].notes))

    def test_single_tier_and_unlevelled_rows_on_the_next_page(self):
        grids = find(["\nPricing Grid\n" + GRID + PAGE_NUMBER, "\n" + NEXT_ROWS.split("\n")[0] + "\n"])
        self.assertEqual(rates(grids[0]), [200.0, 175.0, 150.0, 125.0])
        self.assertIn("1 tier read", " ".join(grids[0].notes))
        grids = find([CRITERIA_GRID + PAGE_NUMBER, "\n" + NEXT_ROWS.replace("   IV ", "      ").replace("   V  ", "      ")])
        self.assertEqual(levels(grids[0]), ["1", "2", "3", "4", "5"])
        self.assertEqual(rates(grids[0]), [200.0, 175.0, 150.0, 125.0, 100.0])

    def test_rows_that_do_not_carry_the_grid_on_are_left_out_with_a_note(self):
        page_1 = "\nPricing Grid\n" + GRID + PAGE_NUMBER
        for page_2 in ("\n" + regrid("3.00%", "2.75%", "2.50%", ROWS),  # the levels start again
                       "\n" + NEXT_ROWS.replace("1.25%", "1.80%"),  # not in order with the rows before
                       "\n" + NEXT_ROWS.replace("                   0.15%", "").replace("                   0.10%", "")):  # a column short
            grids = find([page_1, page_2])
            self.assertEqual([rates(g) for g in grids], [[200.0, 175.0, 150.0]], page_2)
            self.assertIn("top of page 2", " ".join(grids[0].notes))

    def test_no_join_when_the_grid_did_not_close_its_page_or_a_new_table_follows(self):
        page_1 = "\nPricing Grid\n" + GRID
        grids = find([page_1 + "\nEvents of Default:                Customary.\n" + PAGE_NUMBER, "\n" + NEXT_ROWS])
        self.assertEqual([rates(g) for g in grids], [[200.0, 175.0, 150.0]])
        self.assertEqual(grids[0].notes, [])
        grids = find([page_1 + PAGE_NUMBER, "\n Term Loan B Pricing\n" + regrid("3.00%", "2.75%", "2.50%")])
        self.assertEqual([(g.page, rates(g)) for g in grids], [(1, [200.0, 175.0, 150.0]), (2, [300.0, 275.0, 250.0])])


class WrappedLabels(unittest.TestCase):
    """R06: 'Facility' and 'Fee' on separate lines are still a facility fee."""

    HEADER = """
                                    Pricing Grid

            Debt Rating (S&P / Moody's)        SOFR Margin          ABR Margin           {first}
{second}
 Level I    A / A2 or higher                     0.805%               0.000%              0.070%
 Level II   A- / A3                              0.910%               0.000%              0.090%
 Level III  BBB+ / Baa1                          1.025%               0.025%              0.100%
"""
    SIDEWAYS = """
                                        PRICING GRID

 BASIS FOR PRICING            LEVEL I        LEVEL II       LEVEL III
                              A / A2         A- / A3        BBB+ / Baa1

{fee}

 Applicable
 Margin                        0.805%         0.91%          1.025%
"""
    FEE_RATES = "                          0.07%          0.09%          0.10%"

    def test_header_word_far_to_the_right_is_not_page_furniture(self):
        for first, second, fee in (("Facility", " " * 92 + "Fee", "facility_fee"), ("Commitment", " " * 94 + "Fee", "commitment_fee"),
                                   ("Facility", " " * 90 + "Fee Rate", "facility_fee"), ("Unused", " " * 92 + "Fee", "commitment_fee")):
            grid = find(self.HEADER.format(first=first, second=second))[0]
            self.assertEqual(grid.columns, ["drawn", "base", fee])
            self.assertEqual(rates(grid, fee), [7.0, 9.0, 10.0])
            self.assertEqual(grid.notes, [])

    def test_page_number_under_the_header_is_still_skipped(self):
        grid = find(self.HEADER.format(first="Facility Fee", second=" " * 96 + "12"))[0]
        self.assertEqual(grid.columns, ["drawn", "base", "facility_fee"])

    def test_facility_column_is_never_guessed_to_be_a_commitment_fee(self):
        for second in ("", " " * 53 + "Fee"):  # no "Fee" at all, or "Fee" under another column
            grid = find(self.HEADER.format(first="Facility", second=second))[0]
            self.assertEqual(grid.columns, ["drawn", "base", "unknown"])
            self.assertEqual(grid.undrawn_fee_type, "not_stated")
            self.assertEqual(rates(grid, "commitment_fee"), [None, None, None])
            self.assertIn("could not be identified", " ".join(grid.notes))

    def test_sideways_row_name_wrapped_above_its_rates(self):
        for name, fee in ((" Facility\n Fee  ", "facility_fee"), (" Commitment\n Fee  ", "commitment_fee"), (" Facility Fee\n Rate ", "facility_fee"),
                          (" Unused\n Fee (1)", "commitment_fee"), (" Facility Fee", "facility_fee")):
            grid = find(self.SIDEWAYS.format(fee=name + self.FEE_RATES[len(name.split("\n")[-1]) - 6:]))[0]
            self.assertEqual(grid.undrawn_fee_type, fee, name)
            self.assertEqual(rates(grid, fee), [7.0, 9.0, 10.0])
            self.assertEqual(rates(grid), [80.5, 91.0, 102.5])
            self.assertEqual(levels(grid), ["I", "II", "III"])  # the header is searched above the wrapped name
            self.assertEqual([t.criteria for t in grid.tiers], ["A / A2", "A- / A3", "BBB+ / Baa1"])

    def test_three_line_row_name(self):
        grid = find(self.SIDEWAYS.format(fee=" Letter of\n Credit\n Fee  " + self.FEE_RATES))[0]
        self.assertEqual(rates(grid, "lc"), [7.0, 9.0, 10.0])
        self.assertEqual(levels(grid), ["I", "II", "III"])

    def test_row_that_cannot_be_named_is_left_out_with_a_note(self):
        grid = find(self.SIDEWAYS.format(fee=" Facility\n\n Fee  " + self.FEE_RATES))[0]  # a blank line: not one label
        self.assertEqual(grid.undrawn_fee_type, "not_stated")
        self.assertEqual(rates(grid), [80.5, 91.0, 102.5])
        self.assertIn("rows of the table could not be identified", " ".join(grid.notes))


class ColumnClasses(unittest.TestCase):
    """R15: what a column is comes from its own header; an adjustment, floor or utilisation fee is neither margin nor fee."""

    TWO_COLUMNS = """
 Level    Leverage Ratio          {first:<27}{second}
   I      > 3.50:1.00                  2.00%                      {a}
   II     > 2.50:1.00                  1.75%                      {b}
   III    <= 2.50:1.00                 1.50%                      {c}
"""

    def two(self, first: str, second: str, a: str = "0.10%", b: str = "0.10%", c: str = "0.10%") -> list[tables.Grid]:
        return find(self.TWO_COLUMNS.format(first=first, second=second, a=a, b=b, c=c))

    def test_header_cells_run_together(self):
        grid = find("""
                                    Pricing Grid

 Level    Leverage Ratio     SOFR Loans ABR Loans Fee
   I      > 3.50:1.00          2.00%     1.25%   0.30%
   II     > 2.50:1.00          1.75%     1.00%   0.25%
   III    <= 2.50:1.00         1.50%     0.75%   0.20%
""")[0]
        self.assertEqual(rates(grid), [200.0, 175.0, 150.0])  # not the ABR column the jammed header sits over
        self.assertEqual(rates(grid, "base"), [125.0, 100.0, 75.0])
        self.assertIn("spans several value columns", " ".join(grid.notes))

    def test_jammed_header_naming_a_facility_fee(self):
        grid = find("""
 Level    Leverage Ratio     SOFR Loans Facility Fee
   I      > 3.50:1.00          2.00%     0.30%
   II     > 2.50:1.00          1.75%     0.25%
   III    <= 2.50:1.00         1.50%     0.20%
""")[0]
        self.assertEqual(rates(grid), [200.0, 175.0, 150.0])
        self.assertEqual(grid.undrawn_fee_type, "not_stated")  # the fee column is not guessed at
        self.assertEqual(len(grid.notes), 2)

    def test_title_over_sub_headers_does_not_name_a_column(self):
        grid = find("""
 Level    Leverage Ratio                   Applicable Margin                    Commitment Fee
                                  Term SOFR Loans      Base Rate Loans
   I      > 3.50:1.00                  2.00%               1.00%                    0.30%
   II     > 2.50:1.00                  1.75%               0.75%                    0.25%
   III    <= 2.50:1.00                 1.50%               0.50%                    0.20%
""")[0]
        self.assertEqual(grid.columns, ["drawn", "base", "commitment_fee"])
        self.assertEqual(grid.notes, [])

    def test_adjustment_floor_and_utilisation_columns_are_not_fees(self):
        for header in ("Credit Spread Adjustment", "SOFR Adjustment", "CSA", "SOFR Floor", "Utilization Fee", "Usage Fee"):
            grid = self.two("Term SOFR Margin", header)[0]
            self.assertEqual(grid.columns, ["drawn", "other"], header)
            self.assertEqual(grid.undrawn_fee_type, "not_stated")
            self.assertEqual(grid.notes, [])

    def test_adjustment_column_beside_a_fee_column(self):
        text = self.TWO_COLUMNS.format(first="Term SOFR Margin", second="Credit Spread Adjustment      Commitment Fee",
                                       a="0.10%" + " " * 24 + "0.30%",
                                       b="0.10%" + " " * 24 + "0.25%", c="0.10%" + " " * 24 + "0.20%")
        grid = find(text)[0]
        self.assertEqual(grid.columns, ["drawn", "other", "commitment_fee"])
        self.assertEqual(rates(grid, "commitment_fee"), [30.0, 25.0, 20.0])

    def test_margin_header_that_mentions_the_adjustment_is_still_the_margin(self):
        grid = self.two("SOFR Margin (plus CSA)", "Commitment Fee", "0.30%", "0.25%", "0.20%")[0]
        self.assertEqual(grid.columns, ["drawn", "commitment_fee"])
        for header in ("S + CSA", "SOFR + CSA +"):  # the header is the formula the cells complete
            grid = find(f"""
              Unsecured Ratings              Facility Fee              {header}
              > AA/Aa2/AA                      4.0 bps                 S + CSA + 62.5 bps
              AA-/Aa3/AA-                      6.0 bps                 S + CSA + 75.0 bps
              A+/A1/A+                         7.5 bps                 S + CSA + 87.5 bps
""")[0]
            self.assertEqual((grid.columns, rates(grid)), (["facility_fee", "drawn"], [62.5, 75.0, 87.5]), header)

    def test_unit_of_bare_numbers_is_taken_column_by_column(self):
        table = """
 Level    Leverage Ratio          Term SOFR Margin {u1:<10}Base Rate Margin {u2:<8}Commitment Fee {u3}
   I      > 3.50:1.00                  2.00                       1.00                     {a}
   II     > 2.50:1.00                  1.75                       0.75                     {b}
   III    <= 2.50:1.00                 1.50                       0.50                     {c}
"""
        mixed = find(table.format(u1="(%)", u2="(%)", u3="(bps)", a="30.0", b="25.0", c="20.0"))[0]
        self.assertEqual((rates(mixed), rates(mixed, "base"), rates(mixed, "commitment_fee")),
                         ([200.0, 175.0, 150.0], [100.0, 75.0, 50.0], [30.0, 25.0, 20.0]))
        percent = find(table.format(u1="(%)", u2="(%)", u3="(%)", a="0.30", b="0.25", c="0.20"))[0]
        self.assertEqual(rates(percent, "commitment_fee"), [30.0, 25.0, 20.0])
        # one column without a unit under a header that uses both: its numbers cannot be scaled, so nothing is read
        self.assertEqual(find(table.format(u1="(%)", u2="", u3="(bps)", a="30.0", b="25.0", c="20.0")), [])
        self.assertEqual(find(table.format(u1="", u2="", u3="", a="0.30", b="0.25", c="0.20")), [])

    def test_margin_column_under_ten_basis_points_is_rejected(self):
        notes: list[str] = []
        self.assertEqual(find(self.TWO_COLUMNS.format(first="Term SOFR Margin", second="Commitment Fee", a="0.30%", b="0.25%", c="0.20%")
                              .replace("2.00%", "0.02%").replace("1.75%", "0.03%").replace("1.50%", "0.04%"), notes), [])
        self.assertIn("under 10 bps", " ".join(notes))
        fee_only = find("\n Level    Rating            Facility Fee\n   I      A / A2              0.07%\n   II     A- / A3             0.09%\n"
                        "   III    BBB+ / Baa1         0.10%\n")
        self.assertEqual([rates(g, "facility_fee") for g in fee_only], [[7.0, 9.0, 10.0]])  # no margin column: nothing to doubt


class ProportionalFont(unittest.TestCase):
    """Page text as pypdf lays out a proportional font: cells start a few columns off, rates stand right of their headers."""

    COMPARISON = """Summary of terms

                                                                      Existing                                                                       Proposed

Borrower                                Example Holdings, Inc.                                               Same as existing
Facility                                   $500 million revolving credit facility                             $750 million revolving credit facility
Pricing                                   S + 250 bps                                                                 S + 200 bps
Commitment fee                    37.5 bps                                                                      25 bps
Maturity                                  June 30, 2027                                                             Five years from closing
Financial covenants               Net Leverage <= 3.50x                                               Net Leverage <= 4.00x
"""
    FEES_THEN_GRID = """
Upfront Fees:                                     Existing Lenders                                     New Lenders
                                                     10 bps                                                     25 bps

Applicable Margin:                             As set out below.
                                                     Level           Leverage Ratio                Term SOFR Loans          Commitment Fee
                                                     I                   >= 3.50:1.00                            2.00%                              0.30%
                                                     II                  < 3.50:1.00                              1.75%                              0.25%
                                                     III                 < 2.50:1.00                              1.50%                              0.20%
"""

    def test_comparison_rows_are_cut_at_their_own_cells(self):
        raw = Doc([self.COMPARISON])
        proposed, existing, pages = views.split_views(raw)
        self.assertEqual(pages, {1})
        got = [(proposed.lines[n].text.split(), existing.lines[n].text.split()) for n in (7, 9)]
        self.assertEqual(got, [(["Commitment", "fee", "25", "bps"], ["Commitment", "fee", "37.5", "bps"]),  # nothing of "37.5 bps" left behind
                               (["Financial", "covenants", "Net", "Leverage", "<=", "4.00x"],
                                ["Financial", "covenants", "Net", "Leverage", "<=", "3.50x"])])
        grids = tables.find_grids(proposed)
        self.assertEqual([t.values for g in grids for t in g.tiers], [{"drawn": 200.0, "commitment_fee": 25.0}])

    def test_header_row_is_told_by_its_cells_and_matched_in_order(self):
        self.assertEqual(views.split_views(Doc([self.FEES_THEN_GRID]))[2], set())
        grids = find(self.FEES_THEN_GRID)  # the fee table's row is not a tier, though no header word stands above a rate
        self.assertEqual(len(grids), 1)
        self.assertEqual((levels(grids[0]), rates(grids[0]), rates(grids[0], "commitment_fee")),
                         (["I", "II", "III"], [200.0, 175.0, 150.0], [30.0, 25.0, 20.0]))
        self.assertEqual(grids[0].metric, "Leverage Ratio")

    def test_wrapped_header_cell_goes_with_the_cell_it_wraps_from(self):
        two_lines = "Term SOFR                Commitment Fee\n" + " " * 99 + "Loans"
        grids = find(self.FEES_THEN_GRID.replace("Term SOFR Loans          Commitment Fee", two_lines))
        self.assertEqual((grids[0].columns, rates(grids[0]), rates(grids[0], "commitment_fee")),
                         (["drawn", "commitment_fee"], [200.0, 175.0, 150.0], [30.0, 25.0, 20.0]))

    def test_margin_read_under_a_fee_header_is_not_reported_as_a_fee(self):
        # With one header cell missing the cells cannot be matched in order; by position "Commitment Fee" lands on the margins.
        text = self.FEES_THEN_GRID.replace("Term SOFR Loans          Commitment Fee", "                         Commitment Fee")
        self.assertEqual(find(text), [])  # rather no grid than a commitment fee of 200 bps


class RateCells(unittest.TestCase):
    """R19: cells written as a spread over a named rate, and whole basis points under a header that gives the unit."""

    def test_tokens_know_their_reference_rate(self):
        text = "  SOFR + 2.00%   ABR + 1.00%   B + 0.5%  B+  3.00%  Term SOFR + CSA + 62.5 bps  LIBOR + 250 bps  Alternate Base Rate + 75 bp"
        got = [(text[t.start: t.end], t.bps, t.splus, t.base) for t in tables.value_tokens(text)]
        self.assertEqual(got, [("SOFR + 2.00%", 200.0, True, False), ("ABR + 1.00%", 100.0, False, True), ("B + 0.5%", 50.0, False, True),
                               ("3.00%", 300.0, False, False),  # "B+" before it is a rating, not a base rate
                               ("Term SOFR + CSA + 62.5 bps", 62.5, True, False), ("LIBOR + 250 bps", 250.0, True, False),
                               ("Alternate Base Rate + 75 bp", 75.0, False, True)])

    def swap(self, sofr: tuple[str, str, str], base: tuple[str, str, str], grid: str = GRID) -> str:
        for old, new in zip(("2.00%  ", "1.75%  ", "1.50%  ", "1.00%  ", "0.75%  ", "0.50%  "), sofr + base):
            grid = grid.replace(old, new)
        return grid

    def test_cells_with_the_reference_rate_written_out(self):
        for text in (self.swap(("SOFR + 2.00%", "SOFR + 1.75%", "SOFR + 1.50%"), ("ABR + 1.00%", "ABR + 0.75%", "ABR + 0.50%")),
                     self.swap(("S + 200 bps", "S + 175 bps", "S + 150 bps"), ("ABR + 100 bps", "ABR + 75 bps", "ABR + 50 bps")),
                     self.swap(("LIBOR + 2.00%", "LIBOR + 1.75%", "LIBOR + 1.50%"), ("Prime + 1.00%", "Prime + 0.75%", "Prime + 0.50%"))):
            grids = find(text)
            self.assertEqual(len(grids), 1, text)
            self.assertEqual((rates(grids[0]), rates(grids[0], "base"), rates(grids[0], "commitment_fee")),
                             ([200.0, 175.0, 150.0], [100.0, 75.0, 50.0], [30.0, 25.0, 20.0]))

    def test_reference_rates_name_the_columns_where_no_header_does(self):
        grid = find("""
   I      >= 3.50:1.00      Prime + 1.00%      L + 2.00%
   II     < 3.50:1.00       Prime + 0.75%      L + 1.75%
   III    < 2.50:1.00       Prime + 0.50%      L + 1.50%
""")[0]
        self.assertEqual(grid.columns, ["base", "drawn"])
        self.assertEqual(rates(grid), [200.0, 175.0, 150.0])

    def test_rating_ending_in_plus_is_not_a_base_rate(self):
        grid = find("\n Rating         SOFR Margin\n BB             2.50%\n BB-            2.75%\n B+             3.00%\n B              3.25%\n")[0]
        self.assertEqual([t.criteria for t in grid.tiers], ["BB", "BB-", "B+", "B"])
        self.assertEqual(rates(grid), [250.0, 275.0, 300.0, 325.0])

    def test_rate_inside_a_sentence_is_no_row(self):
        self.assertEqual(find("\n Interest:   At the Borrower's option, Term SOFR + 2.00% or\n             ABR + 1.00%, payable quarterly.\n"), [])

    WHOLE = """
 Pricing        Leverage          SOFR Margin       Base Rate Margin      Commitment Fee
 Level          Ratio                (bps)               (bps)                (bps)
   1            > 3.50x               200                 100                  30
   2            > 2.50x               175                  75                  25
   3            <= 2.50x              150                  50                  20
"""

    def test_whole_basis_points_under_a_header_with_the_unit(self):
        shared = self.WHOLE.replace("                (bps)               (bps)                (bps)", "              (all rates in basis points)")
        for text in (self.WHOLE, shared, shared.replace("   1 ", "Level 1").replace("   2 ", "Level 2").replace("   3 ", "Level 3")):
            grids = find(text)
            self.assertEqual(len(grids), 1, text)
            self.assertEqual((levels(grids[0]), rates(grids[0]), rates(grids[0], "base"), rates(grids[0], "commitment_fee")),
                             (["1", "2", "3"], [200.0, 175.0, 150.0], [100.0, 75.0, 50.0], [30.0, 25.0, 20.0]))
            self.assertEqual([t.criteria for t in grids[0].tiers], ["> 3.50x", "> 2.50x", "<= 2.50x"])

    def test_whole_and_decimal_cells_in_one_grid(self):
        text = self.WHOLE.replace("200 ", "112.5").replace("100 ", "12.5").replace("30", "10").replace("175 ", "125.0").replace(" 75", "25.0")
        grid = find(text.replace("150 ", "137.5").replace(" 50", "37.5"))[0]
        self.assertEqual((rates(grid), rates(grid, "base"), rates(grid, "commitment_fee")),
                         ([112.5, 125.0, 137.5], [12.5, 25.0, 37.5], [10.0, 25.0, 20.0]))

    def test_whole_numbers_without_a_basis_point_header_are_not_rates(self):
        for text in (self.WHOLE.replace("(bps)", "     "), self.WHOLE.replace("(bps)", " (%) "),
                     self.WHOLE.replace("SOFR Margin", "Revenue    ").replace("Base Rate Margin", "EBITDA          ")
                     .replace("Commitment Fee", "Capex         "),
                     "\n Fiscal year      2023      2024      2025\n Stores            120       135       150\n"
                     " Countries          12        14        15\n"):
            self.assertEqual(find(text), [], text)

    def test_lone_line_of_whole_numbers_stays_a_header(self):
        grid = find("\n Pricing Level                  1              2              3\n\n Commitment Fee                0.04%          0.05%"
                    "          0.065%\n\n Applicable Margin             0.50%          0.625%         0.75%\n")[0]
        self.assertEqual([(t.criteria, t.values) for t in grid.tiers], [("1", {"commitment_fee": 4.0, "drawn": 50.0}),
                                                                         ("2", {"commitment_fee": 5.0, "drawn": 62.5}),
                                                                         ("3", {"commitment_fee": 6.5, "drawn": 75.0})])

    def test_column_of_whole_numbers_without_a_name_is_not_guessed(self):
        grid = find("""
 Level     Leverage      SOFR Margin (bps)     Commitment Fee (bps)
   1         3.50              200                   30
   2         3.00              175                   25
   3         2.50              150                   20
""")[0]
        self.assertEqual([t.values for t in grid.tiers], [{"drawn": 200.0, "commitment_fee": 30.0}, {"drawn": 175.0, "commitment_fee": 25.0},
                                                         {"drawn": 150.0, "commitment_fee": 20.0}])
        self.assertIn("could not be identified", " ".join(grid.notes))


class ComparisonLayout(unittest.TestCase):
    """R09: only a comparison of existing and proposed terms splits a page, and only the rows that keep to its columns."""

    HEAD = """
                                SUMMARY OF TERMS AND CONDITIONS

Borrower:                         Example Holdings, Inc. (the "Borrower").

Facility:                         A senior secured revolving credit facility in an aggregate principal
                                  amount of $750,000,000.
"""

    def split(self, text: str) -> tuple[Doc, Doc, Doc, set[int]]:
        raw = Doc([text])
        return (raw,) + views.split_views(raw)

    def test_table_of_fees_by_lender_group_does_not_split_the_page(self):
        for cells in ("Existing Lenders              New Lenders", "Existing Commitments          New Commitments",
                      "Existing Money                New Money",
                      "Current Lenders               New Lenders", "Existing                      New Money"):
            text = self.HEAD + "\nUpfront Fees:                     " + cells + "\n" + " " * 34 + "10 bps                        25 bps\n" + SECTIONS
            raw, proposed, existing, pages = self.split(text)
            self.assertEqual(pages, set(), cells)
            self.assertEqual([ln.text for ln in proposed.lines], [ln.text for ln in raw.lines])
            self.assertEqual([ln.text for ln in existing.lines], [ln.text for ln in raw.lines])

    def test_labelled_row_with_two_column_heads_does_not_split_the_page(self):
        for row in ("Ratings:                          Current                       New\n" + " " * 34 + "BB / Ba2                      BB+ / Ba1\n",
                    "Upfront Fees:                     Existing                      New\n" + " " * 34 + "10 bps                        25 bps\n"):
            self.assertEqual(self.split(self.HEAD + "\n" + row + SECTIONS)[3], set(), row)

    def test_header_without_rows_does_not_split_the_page(self):
        self.assertEqual(self.split("\n" + " " * 35 + "Existing" + " " * 31 + "Proposed\n" + SECTIONS)[3], set())

    def test_comparison_headers_split_the_page(self):
        for old, new in (("Existing", "Proposed"), ("Existing Terms", "Proposed Terms"), ("Current Facility", "Amended Facility"),
                         ("Existing Credit Agreement", "New Terms")):
            text = COMPARISON.replace("Existing" + " " * 31, old.ljust(39)).replace("Proposed", new)
            raw, proposed, existing, pages = self.split(text)
            self.assertEqual(pages, {1}, old)
            self.assertEqual(proposed.lines[4].text.split(), ["Drawn", "margin", "S", "+", "200", "bps"])
            self.assertEqual(existing.lines[4].text.split(), ["Drawn", "margin", "S", "+", "250", "bps"])
            self.assertEqual(proposed.lines[4].qstart, 73)
        raw, proposed, existing, pages = self.split(COMPARISON.replace("\n         ", "\nKey terms", 1))  # a heading over the label column
        self.assertEqual(pages, {1})

    def test_cells_that_touch_are_still_cut_at_the_column(self):
        _, proposed, existing, _ = self.split(COMPARISON)  # "... credit facility $750 million ...": one space between the cells
        self.assertEqual(proposed.lines[3].text.split(None, 1)[1], "$750 million revolving credit facility")
        self.assertEqual(existing.lines[3].text.split(None, 1)[1], "$500 million revolving credit facility")

    def test_only_the_rows_of_the_comparison_are_split(self):
        raw, proposed, existing, pages = self.split(COMPARISON + SECTIONS)
        self.assertEqual(pages, {1})
        changed = [ln.n for ln in proposed.lines if ln.text != raw.lines[ln.n].text or ln.qstart]
        self.assertEqual(changed, [2, 3, 4, 5, 6])
        for view in (proposed, existing):  # the sections under the table are whole in both views
            text = " ".join(ln.text for ln in view.lines)
            self.assertIn("0.375% per annum on the unused commitments.", text)
            self.assertIn("Maximum Total Leverage Ratio of 4.50:1.00 and minimum Interest Coverage Ratio of", text)

    def test_note_across_both_columns_is_left_whole_and_the_rows_under_it_are_still_split(self):
        note = " " * 20 + "Pricing-and-fees-are-payable-quarterly-in-arrears-on-the-unused-commitments\n"
        text = COMPARISON.replace("Drawn margin", note + "Drawn margin")
        raw, proposed, existing, pages = self.split(text)
        self.assertEqual((proposed.lines[4].text, existing.lines[4].text), (raw.lines[4].text, raw.lines[4].text))
        self.assertEqual(proposed.lines[5].text.split(), ["Drawn", "margin", "S", "+", "200", "bps"])
        self.assertEqual([t.values for g in tables.find_grids(proposed) for t in g.tiers], [{"drawn": 200.0, "commitment_fee": 25.0}])
        # Two such lines end the comparison only where no row follows them: here the rows below still start at the proposed
        # column, so they are split and the two notes are left whole.
        raw, proposed, existing, pages = self.split(COMPARISON.replace("Drawn margin", note + note + "Drawn margin"))
        self.assertEqual([ln.n for ln in proposed.lines if ln.text != raw.lines[ln.n].text], [2, 3, 6, 7, 8])
        self.assertEqual(proposed.lines[6].text.split(), ["Drawn", "margin", "S", "+", "200", "bps"])
        # With ordinary text under the two notes instead, the comparison ends there and none of that text is cut.
        raw, proposed, existing, pages = self.split(COMPARISON.split("Drawn margin")[0] + note + note + SECTIONS)
        for view in (proposed, existing):
            self.assertEqual([ln.text for ln in view.lines[4:]], [ln.text for ln in raw.lines[4:]])

    def test_ordinary_text_under_a_comparison_is_never_cut(self):
        words = ("the Borrower shall pay to each Lender a fee on its unused commitment at the rate per annum set forth above payable "
                 "quarterly in arrears and on the date of termination of the commitments in full").split()
        for shift in range(len(words)):  # the same paragraph with every word in turn at the column boundary
            line = " ".join(words[shift:] + words[:shift])
            text = COMPARISON + "\nFees:" + " " * 29 + line[:88] + "\n" + " " * 34 + line[88:140] + "\n" + " " * 34 + "and unpaid.\n"
            raw, proposed, existing, _ = self.split(text)
            for n in (8, 9, 10):
                self.assertEqual((proposed.lines[n].text, existing.lines[n].text), (raw.lines[n].text, raw.lines[n].text), raw.lines[n].text)

    def test_column_starts_at_the_bullet_not_at_its_text(self):
        gap = " " * 3
        rows = [("Borrower", "Example Holdings, Inc.", "Same as existing"),
                ("Restricted payments", BULLET + gap + "Unlimited if Net Leverage < 1.00x", BULLET + gap + "Unlimited if Net Leverage < 1.75x"),
                ("", "    and Liquidity of $350mm", "    and Liquidity of $350mm"),
                ("", "    and no Default", "    and no Default"),
                ("", BULLET + gap + "Otherwise $50mm", BULLET + gap + "Otherwise $75mm"),
                ("", "    in any fiscal year", "    in any fiscal year"),
                ("Drawn margin", BULLET + gap + "S + 250 bps", BULLET + gap + "S + 200 bps"),
                ("Investments", "$100mm", "Same as existing")]
        text = "\n" + " " * 50 + "Existing" + " " * 50 + "Proposed\n" + "".join(f"{a:<35}{b:<53}{c}\n" for a, b, c in rows)  # centred heads
        _, proposed, existing, pages = self.split(text)
        self.assertEqual(pages, {1})
        # more cells start at the text after a bullet than at the column itself: "Same as existing" must still come out whole
        self.assertEqual([ln.text[ln.qstart:].strip() for ln in proposed.lines[2:10]], [c.strip() for _, _, c in rows])
        self.assertEqual([ln.text[35:].strip() for ln in existing.lines[2:10]], [b.strip() for _, b, _ in rows])


class Speed(unittest.TestCase):
    """A page of thousands of rate rows is not a grid, and must not take long to say so (it took minutes before)."""

    def test_running_mean_matches_the_plain_mean(self):
        self.assertEqual(tables._cluster_columns([10.5, 30.0, 12.0, 11.5, 33.5, 80.0]), [(10.5 + 11.5 + 12.0) / 3, (30.0 + 33.5) / 2, 80.0])

    def test_long_run_of_rate_rows(self):
        for row in ("Level I    > 3.50:1.00    2.00%    1.00%    0.30%", "           > 3.50:1.00    2.00%    1.00%    0.30%",
                    "Upfront Fee:      0.10%", "  7     120     135     150"):
            start = time.perf_counter()
            self.assertEqual(find((row + "\n") * 8000), [])
            self.assertLess(time.perf_counter() - start, 20.0, row)  # about a third of a second; over 45 seconds before the fix

    def test_rows_out_of_line_and_very_wide_rows(self):
        drifting = "\n".join(f"Level {r + 1}" + " " * (3 + 9 * r) + ("2.00%" + " " * 600) * 12 for r in range(60))
        wide = "Level I   " + "2.00%    " * 3000 + "\nLevel II  " + "1.75%    " * 3000
        for text in (drifting, wide):
            start = time.perf_counter()
            self.assertEqual(find(text), [])
            self.assertLess(time.perf_counter() - start, 20.0)

    def test_many_pages_and_many_split_rows(self):
        page = "\n Level   Leverage     Margin     Fee\n" + " " * 12 + "I   > 3.5x    2.00%    0.30%\n" + " " * 12 + "II  < 3.5x    1.75%    0.25%\n"
        rows = "Margin" + " " * 29 + "S + 250 bps" + " " * 27 + "S + 200 bps\n"
        start = time.perf_counter()
        self.assertEqual(len(find([page] * 2000)), 2000)
        proposed = views.split_views(Doc(["\n" + " " * 35 + "Existing" + " " * 30 + "Proposed\n" + rows * 8000]))[0]
        self.assertEqual(proposed.lines[8000].text.split(), ["Margin", "S", "+", "200", "bps"])
        self.assertLess(time.perf_counter() - start, 20.0)

    def test_pages_that_keep_their_layout(self):
        doc = Doc([GRID, "Pricing:\nDrawn:      S + 300 bps\nUndrawn: 50 bps\n", "", COMPARISON])
        self.assertEqual(tables._layout_pages(doc), {1, 4})  # page 2 starts every line at the left edge; page 3 is empty

    def test_table_longer_than_any_grid_is_left_alone(self):
        rows = "".join(f"   {i + 1:<4}  > {9 - i * 0.1:.2f}x      {3.0 - i * 0.02:.2f}%      0.30%\n" for i in range(tables.MAX_TABLE_ROWS + 1))
        self.assertEqual(find("\n Level   Leverage    SOFR Margin  Commitment Fee\n" + rows), [])
        self.assertEqual(len(find("\n Level   Leverage    SOFR Margin  Commitment Fee\n" + "".join(rows.splitlines(True)[:12]))[0].tiers), 12)


if __name__ == "__main__":
    unittest.main()
