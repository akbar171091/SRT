"""The rows of the Key Credit Terms template, and what belongs in each.

Every extraction engine (rules, Claude, the audited records) produces one entry per field listed
here; ``kct/template.py`` writes each entry into its row. A row is found in the template by its
section header and label (or, for the unlabelled rows, by its position inside the section), so a
template whose rows have been reordered or restyled still works.

The ``guidance`` strings are the drafting instructions. They are used verbatim in the Claude prompt
and were the brief for the audited records, so the engines aim at the same house style.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    id: str
    section: str  # template section header ("" = the rows above the first header)
    label: str  # label in the left-hand cell ("" = unlabelled row, located by ``ordinal``)
    ordinal: int  # position among the rows of the section (0-based); fallback locator
    row: int  # row index in the stock template; last-resort locator
    prompt: str  # what the template itself asks for in this row
    guidance: str


FIELDS: list[Field] = [
    Field("facility", "", "Facility:", 0, 0,
          "[total facility amount, RCF/Term Loan/SSRCF]",
          "Total facility amount and type on one line, e.g. '$2.0bn RCF', '$275m super senior RCF (SSRCF)', "
          "'$500m Term Loan A + $750m RCF (total $1.25bn)'. Use RCF / Term Loan / SSRCF wording and keep descriptors "
          "that matter (364-day, first lien, delayed draw, multicurrency). Add a second line for sub-limits "
          "(letters of credit, swingline, alternative currencies) only if the term sheet states them."),
    Field("borrowers", "Facility Info", "Borrower(s)", 0, 2,
          "",
          "Each borrower by full legal name, with entity type / jurisdiction if the term sheet gives it. Mention any "
          "right to add subsidiary or designated borrowers."),
    Field("lender_commitments", "Facility Info", "Lender Commitments", 1, 3,
          "Barclays = / [add other lenders]",
          "First line always starts 'Barclays = ': the Barclays commitment if stated; otherwise 'Barclays = not stated in "
          "term sheet', adding Barclays' title if it is named (e.g. '(named as Joint Lead Arranger)'). Then other lenders' "
          "commitments if stated, one per line. If no commitments are stated, give one line naming the administrative "
          "agent and the arrangers / bookrunners as the term sheet lists them, and set status to not_stated."),
    Field("purpose", "Facility Info", "Purpose", 2, 4,
          "General corporate purposes / [add other purpose]",
          "Use of proceeds: 'General corporate purposes' where that is what the term sheet says, plus every other stated "
          "purpose (refinancing of a named existing facility, acquisitions, working capital, letters of credit, "
          "commercial paper backstop, transaction costs)."),
    Field("maturity", "Facility Info", "Maturity Date", 3, 5,
          "[ ] years + 1 + 1 [remove as applicable]",
          "Tenor or maturity date as stated ('5 years from the Closing Date', '364 days'), then any extension options in "
          "the template's style ('+ 1 + 1: two 1-year extension options at the Borrower's request, subject to consent of "
          "extending Lenders'), term-out options and springing maturities. One facility per line if they differ."),
    Field("repayment", "Facility Info", "Repayment", 4, 6,
          "Bullet / Amortising [include amort profile]",
          "'Bullet' or 'Amortising' followed by the detail: for amortising facilities give the profile (e.g. 'Amortising: "
          "1.25% per quarter, balance at maturity'). A revolving facility with no scheduled amortisation is 'Bullet "
          "(revolving; repayable at maturity)'. One facility per line if they differ."),
    Field("accordion", "Facility Info", "Accordion", 5, 7,
          "No / Yes = [insert amount]",
          "'Yes = <amount>' with the key conditions (uncommitted; cap such as greater of $X and 100% of EBITDA; ratio "
          "test; minimum increments; lender consent), or 'No' if the term sheet says there is none. If the term sheet "
          "is silent write 'None stated in term sheet' with status not_stated."),
    Field("guarantors", "Security, Guarantors & Ranking", "Guarantor(s)", 0, 9,
          "[Name(s)]",
          "Named guarantors, or the description the term sheet gives (e.g. 'Parent and each existing and future "
          "wholly-owned material domestic subsidiary'). 'None' if the term sheet says the facility is unguaranteed. "
          "Include release / fall-away provisions if stated."),
    Field("guarantor_coverage", "Security, Guarantors & Ranking", "Guarantee Net Maintenance", 1, 10,
          "Min % of group assets/EBITDA/Turnover",
          "Guarantor coverage test: the minimum share of group assets / EBITDA / turnover that guarantors must "
          "represent. US-style term sheets rarely have one: then write 'None stated in term sheet' (status not_stated), "
          "adding any material-subsidiary threshold that decides who must guarantee (e.g. 'Material Subsidiary: >= 5% "
          "of consolidated total assets or revenues')."),
    Field("security", "Security, Guarantors & Ranking", "Collateral/Security", 2, 11,
          "Unsecured / Debentures / Share Charges / Fixed Charges [please list out any freehold / long leasehold assets being secured]",
          "'Unsecured', or what the collateral is (all-asset first-priority security, share pledges, specific assets "
          "such as vessels, rigs or real estate), notable exclusions, and any release or fall-away trigger (e.g. on "
          "investment-grade ratings)."),
    Field("ranking", "Security, Guarantors & Ranking", "Ranking in Capital Structure", 3, 12,
          "Senior Unsecured / Senior Secured / Super Senior / Subordinated",
          "Start with exactly one of 'Senior Unsecured', 'Senior Secured', 'Super Senior' or 'Subordinated', then a short "
          "qualifier if the term sheet gives one (first lien; pari passu with a named facility or notes; ahead of second "
          "lien notes). If ranking is not stated expressly, derive it from the security position and say so "
          "('Senior Unsecured (not stated expressly; facility is unsecured)')."),
    Field("fc_leverage", "Financial Covenants", "", 0, 14,
          "Net Debt/EBITDA < x",
          "The leverage-type maintenance covenant under the name the term sheet uses, with its level and any step-downs "
          "or acquisition step-ups: 'Total Net Leverage Ratio <= 3.75x (step-up to 4.25x for four quarters after a "
          "Material Acquisition)'. A debt-to-capitalisation test belongs here if it is the leverage test. If the term "
          "sheet has no financial covenants at all write 'None - no financial maintenance covenants'; if it has "
          "covenants but no leverage test write 'Net Debt/EBITDA: none'."),
    Field("fc_interest_cover", "Financial Covenants", "", 1, 15,
          "Interest Cover > x",
          "The interest cover covenant: 'Interest Coverage Ratio >= 3.00x', with its definition in a few words if given "
          "(EBITDA / cash interest expense). If there is none write 'Interest Cover: none'."),
    Field("fc_other", "Financial Covenants", "", 2, 16,
          "[other eg LTV, DSCR, FCCR]",
          "Any other financial maintenance covenant (fixed charge cover, DSCR, LTV, minimum liquidity, net worth, "
          "secured leverage), one per line with its level. If there is none write 'Other: none'."),
    Field("fc_testing", "Financial Covenants", "", 3, 17,
          "Tested quarterly / semi-annually on a rolling 12-months basis",
          "How the covenants are tested: frequency and period ('Tested quarterly on a rolling four-quarter basis'), any "
          "springing condition ('tested only when utilisation exceeds 35% of commitments'), and the first test date. If "
          "there are no financial covenants write 'n/a'."),
    Field("select_definitions", "Financial Covenants", "Other Select Definitions", 4, 18,
          "[Equity Cures] / [Deemed Cures] / [Synergies] / [Adjusted EBITDA]",
          "One line for each item the term sheet addresses, prefixed 'Equity cures: ', 'Deemed cures: ', 'Synergies: ', "
          "'Adjusted EBITDA: ' (add-backs and their caps, pro forma adjustments, cash netting limits, how leverage is "
          "defined). Leave out an item the term sheet does not address; if it addresses none, one line 'Not stated in "
          "term sheet' with status not_stated."),
    Field("negative_pledge", "Non-Financial Covenants", "Negative Pledge (Permitted Security)", 0, 20,
          "[detail basket/carve-out amounts]",
          "The limitation on liens and its permitted-security baskets and carve-outs, with amounts (general lien basket, "
          "purchase money / capital lease liens, securitisation, priority debt cap). If the term sheet only lists the "
          "covenant, say so: 'Limitation on liens; baskets not detailed in term sheet'."),
    Field("permitted_acquisitions", "Non-Financial Covenants", "Permitted Acquisitions", 1, 21,
          "[detail basket/carve-out amounts]",
          "The restriction on acquisitions (often inside the investments covenant in US documents) and its conditions "
          "and baskets: no default, pro forma covenant compliance, caps on non-guarantor targets."),
    Field("permitted_disposals", "Non-Financial Covenants", "Permitted Disposals", 2, 22,
          "[detail basket/carve-out amounts]",
          "The asset sale / disposal covenant and its baskets and conditions (fair market value, 75% cash "
          "consideration, annual caps, sale of all or substantially all assets)."),
    Field("permitted_distributions", "Non-Financial Covenants", "Permitted Distributions", 3, 23,
          "[detail basket/carve-out amounts]",
          "The restricted payments covenant (dividends, share buybacks) and its baskets: general basket, builder / "
          "available amount basket, unlimited basket subject to a leverage test."),
    Field("permitted_indebtedness", "Non-Financial Covenants", "Permitted Financial Indebtedness", 4, 24,
          "[detail basket/carve-out amounts]",
          "The debt covenant and its baskets: general basket, ratio debt, subsidiary / non-guarantor debt cap, priority "
          "debt, securitisation and receivables facilities, capital leases."),
    Field("permitted_loans", "Non-Financial Covenants", "Permitted Loans", 5, 25,
          "[detail basket/carve-out amounts]",
          "Restrictions on loans, advances and other investments, with baskets (intercompany loans, loans to "
          "non-guarantors, general investments basket)."),
    Field("permitted_guarantees", "Non-Financial Covenants", "Permitted Guarantees", 6, 26,
          "[detail basket/carve-out amounts]",
          "Restrictions on giving guarantees (US documents usually treat guarantees as indebtedness or investments: say "
          "so if that is how the term sheet deals with them), with baskets."),
    Field("permitted_payments", "Non-Financial Covenants", "Permitted Payments", 7, 27,
          "[detail basket/carve-out amounts]",
          "Restrictions on payments of junior, subordinated or other restricted debt (prepayments, redemptions), with "
          "baskets and conditions."),
    Field("other_covenants", "Non-Financial Covenants", "[Other]", 8, 28,
          "[]",
          "Other notable undertakings, one per line: mergers / fundamental changes, transactions with affiliates, change "
          "of business, sale and leaseback, restrictive agreements, sanctions / anti-corruption, anti-cash-hoarding, "
          "most-favoured-nation protections. Give the list of negative covenants here when the term sheet lists them "
          "without detail."),
    Field("events_of_default", "Other Terms/Conditions", "Events of Default", 0, 30,
          "Cross default [Include basket] / [include any insolvency / creditors' process baskets]",
          "First line 'Cross default: ' with the cross-default / cross-acceleration threshold. Second line 'Insolvency / "
          "creditors' process: ' with any thresholds and grace periods (unsatisfied judgments above $X for 60 days; "
          "involuntary proceedings undismissed for 60 days). Then other notable events of default or grace periods "
          "(payment, covenant breach cure period, change of control, ERISA)."),
    Field("conditions_subsequent", "Other Terms/Conditions", "Conditions Subsequent", 1, 31,
          "[only significant CS's that are conditions of sanction]",
          "Significant post-closing obligations only (security perfection, account control agreements, delivery of "
          "mortgages within a stated period). If none are stated write 'None stated in term sheet' with status "
          "not_stated. Conditions precedent to closing do not belong here."),
    Field("mandatory_prepayment", "Other Terms/Conditions", "Mandatory Prepayment Events", 2, 32,
          "Change of Control + [include % trigger] / [Disposal Proceeds] / [Insurance Proceeds] / [Acquisition Proceeds] / [Excess Cashflow]",
          "First line 'Change of Control: ' with how it is treated (mandatory prepayment and cancellation, event of "
          "default, lender put) and the ownership trigger (e.g. any person or group acquiring more than 35% of voting "
          "stock). Then one line for each prepayment event the term sheet has, prefixed 'Disposal proceeds: ', 'Insurance "
          "proceeds: ', 'Debt issuance proceeds: ', 'Excess cashflow: ', 'Other: ' (e.g. revolving exposure above "
          "commitments, currency fluctuation, cash hoarding). If the term sheet says there are no mandatory prepayments, "
          "say so."),
    Field("jurisdiction_topco", "Other Terms/Conditions", "Jurisdiction of Topco", 3, 33,
          "[Country]",
          "Country (and state, for the US) of incorporation of the top company of the group named in the term sheet "
          "(the parent, Holdings or the Company), with its name: 'Ireland (Accenture plc)', 'United States - Delaware "
          "(Delta Air Lines, Inc.)'. Use only what the term sheet states. If it does not say, write 'Not stated in term "
          "sheet' (status not_stated) and add the governing law of the facility on a second line if given."),
    Field("transferability", "Other Terms/Conditions", "Transferability", 4, 34,
          "Borrower Consent / Consultation / Unrestricted / [Restrictions to Competitors or L2O]",
          "First line starts with 'Borrower consent', 'Borrower consultation' or 'Unrestricted', then the terms: not "
          "unreasonably withheld, deemed consent after N Business Days, no consent for assignments to Lenders / "
          "affiliates / approved funds or while a payment or bankruptcy event of default continues, other consents "
          "(Agent, issuing banks), minimum amounts. Second line: restrictions on transferees (disqualified lenders, "
          "competitors, natural persons, the Borrower and its affiliates, defaulting lenders) and participations."),
    Field("info_annual_consolidated", "Information Requirements", "", 0, 36,
          "annual consolidated accounts - 180 days",
          "'Annual audited consolidated accounts - within N days of financial year end', as stated."),
    Field("info_annual_obligor", "Information Requirements", "", 1, 37,
          "annual obligor accounts - 270 days",
          "'Annual obligor accounts - N days' if the term sheet requires standalone accounts of obligors. US-style term "
          "sheets rarely do: then 'Annual obligor accounts - not stated in term sheet' with status not_stated."),
    Field("info_quarterly", "Information Requirements", "", 2, 38,
          "quarterly management accounts - 45 days",
          "'Quarterly accounts - within N days of each of the first three quarter ends' (or the monthly / quarterly "
          "management accounts requirement), as stated."),
    Field("info_budget", "Information Requirements", "", 3, 39,
          "annual budgets - 30 days after new financial year",
          "'Annual budget - N days after the start of the financial year' if required. Add a second line 'Other: ' for "
          "other notable reporting (compliance certificates, notices of default, ratings changes, projections)."),
]

FIELD_IDS: list[str] = [f.id for f in FIELDS]
BY_ID: dict[str, Field] = {f.id: f for f in FIELDS}

STATUSES = ("stated", "by_reference", "not_stated")

STYLE_GUIDE = """\
House style for every field:
- Write for a credit committee: short factual lines in the form the template asks for, not sentences copied from
  the term sheet. One point per line, normally 1 to 4 lines per field and never more than 8; keep each line under
  about 250 characters.
- Use only what this term sheet says. Do not use the credit agreement, other documents or general knowledge about
  the company. Do not guess.
- Amounts: '$750m', '$1.25bn' for US dollars; other currencies with their code ('EUR 500m'). Ratios as '3.50x',
  percentages as '50%', periods as '90 days'. Use '<=' / '>=' / '<' / '>' for covenant levels.
- status:
    stated        the term sheet addresses the point and the lines summarise it (this includes an express 'none',
                  and a point that follows directly from stated facts, such as an unsecured revolver being senior
                  unsecured);
    by_reference  the term sheet addresses the point only by pointing somewhere else ('substantially consistent with
                  the Existing Credit Agreement', 'customary for facilities of this type', 'to be agreed') without
                  the detail the row needs. Say what it points to;
    not_stated    the term sheet is silent. Use the wording given in the field guidance, or 'Not stated in term sheet'.
- evidence: for every stated or by_reference field give 1 to 3 short verbatim quotes that support the lines, each
  with the PDF page it is on. A quote is copied exactly from the page text (same words, same order, no ellipsis, no
  paraphrase), is contiguous, comes from a single page and is at most 300 characters. not_stated fields have no
  evidence.
- note: optional reviewer note (an ambiguity, an assumption, where the term sheet contradicts itself). Leave empty
  if there is nothing to say. It is not printed in the table.
- Where the document shows existing and proposed terms side by side (an amendment), record the proposed terms and
  say where they are unchanged from the existing ones.
- Closed lists. Where the term sheet sets out a package as a closed list ('limited to', 'consisting of', 'the
  following covenants') and a row's subject is not on the list, the row is stated: write 'None: not among the
  covenants listed in the term sheet (limited to liens, mergers, ...)' and quote the words that close the list.
  Where the list is open ('including', 'customary', 'substantially similar to the Existing Credit Agreement' with no
  closed list), the row is by_reference if the term sheet points to another document for the package, and
  not_stated otherwise.
- Derived points. A point may be derived only from facts the term sheet states, and the line must say so in
  brackets with the basis: 'Unsecured (not stated expressly; no security or collateral provision, and pricing is
  based on senior unsecured debt ratings)'. The status is stated and the evidence quotes the basis. With no basis
  in the term sheet the row is not_stated.
- Blanks. Where the term sheet leaves a blank or a bracket for a value, say so ('[ ] - left blank in term sheet')
  rather than dropping the point or filling it in.
- No repetition across rows. US-style documents deal with loans and guarantees inside the investments and
  indebtedness covenants: say that in the row and point to the row that has the baskets ('see Permitted Financial
  Indebtedness') instead of repeating them.
"""


def guidance_text() -> str:
    """The drafting brief: style guide followed by the per-field guidance, in template order."""
    out = [STYLE_GUIDE, "Fields (id - template row - what goes in it):"]
    for f in FIELDS:
        row = f.label or f"(unlabelled row {f.ordinal + 1} of '{f.section}')"
        where = f"{f.section} / {row}" if f.section else row
        asks = f" Template prompt: {f.prompt}." if f.prompt else ""
        out.append(f"- {f.id} - {where}.{asks}\n    {f.guidance}")
    return "\n".join(out)
