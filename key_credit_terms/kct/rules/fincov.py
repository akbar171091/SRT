"""Rules for the Financial Covenants rows.

Fields: fc_leverage, fc_interest_cover, fc_other, fc_testing, select_definitions.

How the rules work
------------------
1. Find the financial covenant section (``_do_analyse``). Normally it is a labelled block ("Financial
   Covenant(s):", a slide row "Financial covenants": ``_resolve``); failing that, the passage that
   follows the words "financial covenants:" (or the run-in heading "Financial Covenants.") inside a
   "Covenants:" block (``_embedded``); failing that, rows labelled with a covenant's own name
   ("Minimum Liquidity:", "Collateral Coverage Ratio:": ``_rows``). On amendment slides the proposed
   terms are read; "Same as existing" falls back to the existing column, and a slide extracted in
   plain reading order (existing cell, then proposed cell) is split where the second cell mirrors
   the first. With no section at all, an express "no financial covenants" or a covenant list that
   leaves them out decides the rows (``_unlisted``).
2. Read the section (``_read``). Every covenant name in it ("... Leverage Ratio", "Debt to
   Capitalization", "Interest Coverage Ratio", "ratio of A to B", "Minimum Liquidity", "Fixed Charge
   Coverage" ...) opens a covenant; two tests of one kind under different names ("Net Leverage ...
   Gross Leverage") are two covenants. A ratio spelled out beside a name ("Minimum Fixed Charge
   Coverage Ratio: ... the ratio of EBITDAR to the sum of interest and rent ...", "the ratio of A to
   B (the “X Ratio”)") is that covenant: the name, not the components, says what kind of test it
   is. The levels that follow a name (3.50 to 1.00, 3.5x, 65.0%,
   $150 million) become its tiers (``_tiers``), each with the operator the wording gives ("not more
   than", "to be less than" after "shall not permit", "shall not at any time exceed", "Max.", a
   symbol: ``_operator``) and the condition printed with it (an enumerated step schedule, a dated
   step-down, a period heading on a slide, a table row or column head, a trailing "(X only)"). A
   table with one column per covenant is read by column (``_table``). Sentences after the main
   statement that carry further levels (acquisition step-ups, covenant resets) are kept as clauses
   of the term sheet's own wording in house style, never re-derived.
3. Assemble the rows. The leverage-type test goes to fc_leverage (a debt-to-capitalisation test
   counts; a secured / first lien test moves to fc_other when a total test also exists), the
   interest cover test to fc_interest_cover, everything else to fc_other. A row whose covenant is
   absent says "none" with its basis (``_absent``): stated when the section is a plain or closed
   list, by_reference when the list is open and points to another agreement. fc_testing is built
   from the testing wording of the covenant statements (frequency, calculation period, first test,
   springing trigger); what it reports as missing is missing from that wording, which is what the
   line says. Wording that stands in the statement of one covenant of several is said of that
   covenant only ("Fixed Charge Coverage Ratio: tested quarterly"); a level to be met "at any time"
   is said so; a frequency carried only by the covenants' names ("Maximum Quarterly ... Ratio") is
   given as derived. select_definitions collects definition and cure sentences, netting and add-back
   sentences, ratio components, definitions given in a bracket after a term ("EBITDAR (to be defined
   as set forth in ...)"), footnotes, the labelled definition rows (cash netting, equity cure,
   EBITDA; from a list of definitions only those the covenants rest on) and paragraphs anywhere in
   the term sheet that open with the quoted term (“Consolidated EBITDA” shall ...) for EBITDA and
   the ratios the covenants test; a long EBITDA definition is reduced to its synergy add-back, its
   capped provisos and its other add-backs in brief, every cut shown by an ellipsis.

What the rules will not do
--------------------------
* Assume. The one exception: a level printed with no operator ("Leverage Ratio of 3.75x") is read
  as a maximum for leverage-type tests and a minimum for coverage / liquidity tests; the line
  itself and the entry's note say so.
* Print a comparison they are not sure of. Wording whose reading runs against the nature of the
  test (a leverage ratio that must stay above a level), a range ("between 3.50x and 4.00x"), a level
  in words or of an unexpected kind is printed as worded, after the covenant's name. A ratio named
  only as a condition of something else ("subject to a pro forma Total Leverage Ratio of 4.00x",
  "if the Leverage Ratio is greater than 3.00x, ...") is not a covenant level.
* Guess which covenant a level belongs to. Wording that names several covenants before giving
  several levels ("X and Y of 3.50x and 3.00x respectively") is printed as it stands; a schedule
  whose conditions cannot be paired with its levels keeps the first level and quotes the rest; a
  second figure that the wording does not tie to the first ("4.50x (currently 0.7x)") is no tier.
* Print an optional, alternative or doubtfully placed test as one more covenant. A test opened by
  option wording ("or (2) at the Company's option, solely to the extent ..., X not to be greater
  than 3.50x", "in lieu of the foregoing ...") or given as one of "either ... or" is kept whole in
  the term sheet's words with the covenant it stands with ("Alternative, as worded ...") and the
  row it would have had says so; one worded after another covenant's proviso ("...; provided that
  ...; and X of not less than 3.00x") is printed as worded, with where it stands. "shall not permit
  A or B" is two covenants.
* Take a definition in brackets for the sentence around it: "X (to be defined as ...)" sets the
  bracket aside, never the covenant sentence, its level or its testing wording. A lead-in that ends
  in a colon ("Maintenance of the following financial covenants:") is no period heading.
* Conclude "none" where a test may have gone unread: when running text follows the block
  (``_runs_on``: a layout the block finder could not follow), when the section holds a test under a
  name the rules do not know (printed as worded in fc_other), or when the covenants were read from
  rows of their own, the rows for covenants that were not found read "not stated", with a note.
Every stated line is backed by a quote cut from the section, and a row that cannot be separated
(existing from proposed) or read returns not_stated.
"""
from __future__ import annotations

import functools
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..textmodel import fragments, is_footer, tidy
from .blocks import Block, find_blocks
from .common import MONEY_RE, SAME_AS_EXISTING_RE, Ctx, by_reference, fmt_money, money_mm, not_stated, points_elsewhere, restyle_money, stated

LINE = 250  # house style: about this many characters per line
MAX_COV_LINES = 6  # lines one covenant may take in its row

# ---------------------------------------------------------------------------------------------------
# labels
# ---------------------------------------------------------------------------------------------------

# "Financial Covenant(s)", "Financial Maintenance Covenant", "Maintenance Covenants", "Financial Undertakings (RCF only)",
# "Key Financial Covenants", "Financial Covenant Levels"
_FC_LABEL = (r"(?:(?:key|principal|springing)\s+)?(?:financial|maintenance)\s+(?:maintenance\s+)?(?:covenants?|undertakings?)(?:\s+(?:levels?|package))?"
             r"(?:\s*\([^)]{0,40}\))?")
# labels that show a page is part of a term sheet (and not, say, a financial policy slide of a presentation)
_TERM_ROW_LABEL = (r"borrowers?|facilit(?:y|ies)|maturity(?:\s+date)?|tenor|pricing|events?\s+of\s+default|(?:negative|affirmative)\s+covenants?|security|collateral"
                   r"|guarantors?|purpose|use\s+of\s+proceeds|interest\s+rates?|(?:commitment|upfront|facility)\s+fees?|governing\s+law|amortization|ranking")
_FC_LABEL_RE = re.compile(_FC_LABEL, re.IGNORECASE)
# any covenant heading: "Covenants", "Negative Covenants", "Affirmative and Negative Covenants", "General Undertakings"
_COV_LABEL = r"(?:(?:certain|affirmative|negative|general|other|positive|information)\s+(?:and\s+(?:negative|affirmative)\s+)?)?(?:covenants?|undertakings?)"
# what the label says of the covenants' reach: "Financial Covenants (Revolving Facility only)"
_LABEL_SCOPE_RE = re.compile(r"\(([^()“”\"]{0,30}(?:\bonly\b|facilit|revolv|term\s+loan|\bRCF\b|lenders)[^()“”\"]{0,30})\)\s*$", re.IGNORECASE)
# a label at the start of a line, with its name: "Interest Cover: ...", "- Related Definitions: ..."
_LINE_LABEL_RE = re.compile(r"\s*(?:[-–•]\s*)?([A-Z][A-Za-z /&\-()’']{2,48}?)\s*:(?:\s|$)")
# a line that starts a new labelled row ("- Affirmative Covenants :", "Events of Default:")
_NEW_LABEL_RE = re.compile(r"^\s*(?:[-–•]\s*)?[A-Z][A-Za-z /&,\-()’']{2,48}?\s*:(?:\s|$)")
# the slide header of an amendment table extracted in reading order: "Existing Terms Proposed Terms"
_PLAIN_HEADER_RE = re.compile(r"^\W*(?:existing|current)(?:\s+\w+){0,2}\s+(?:proposed|amended|new)(?:\s+\w+){0,2}\W*$", re.IGNORECASE)
# footnote under a slide table: "1. Liquidity defined as", "(1) ...", "* ...", "Note: ..."
_FOOTNOTE_RE = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|\*+|notes?\s*:)\s*\S", re.IGNORECASE)
# labelled definition rows found outside the covenant section
_CASH_NETTING_LABEL = r"cash\s+netting(?:\s+(?:for|cap|limit))?|netting\s+of\s+cash"
_EQUITY_CURE_LABEL = r"equity\s+cures?(?:\s+rights?)?|cure\s+rights?"
_EBITDA_LABEL = r"(?:(?:consolidated|adjusted|covenant)\s+)*EBITDAR?(?:\s+(?:definition|add[\s-]?backs?|adjustments?))?|(?:cost\s+)?synergies(?:\s+cap)?"
_DEFS_LABEL = r"(?:related|certain|financial|key)\s+definitions"

# ---------------------------------------------------------------------------------------------------
# covenant names
# ---------------------------------------------------------------------------------------------------

# words that qualify a ratio's name: "Consolidated Total Net ...", "Senior Secured ...", "First Lien ...", "Lease-Adjusted ..."
_MOD = (r"(?:consolidated|total|net|senior|secured|first[\s-]+lien|funded|adjusted|gross|priority|super[\s-]+senior|cash|group"
        r"|tangible|(?:lease|rent)[\s-]+adjusted)")
# an enumerator between the two sides of a ratio: "to (ii) Consolidated EBITDA"
_ENUM = r"(?:\(\w{1,4}\)\s*)?"
# "Consolidated Net Leverage Ratio", "Net First Lien Leverage", "Debt to Capitalization Ratio",
# "Consolidated Debt / Capitalization", "Net Debt/EBITDA", "funded indebtedness to (ii) Consolidated EBITDA",
# "Total Debt to Total Assets", "Gearing"
_LEV_NAME_RE = re.compile(
    rf"(?:{_MOD}\s+){{0,5}}(?:debt\s+)?leverage\b(?:\s+ratio)?"
    rf"|(?:{_MOD}\s+){{0,4}}(?:debt|indebtedness|borrowings)\s*(?:/|-?\s*to\s*-?)\s*{_ENUM}(?:(?:{_MOD}|LTM|pro\s+forma)\s+){{0,3}}"
    r"(?:capitali[sz]ation|capital\b|EBITDA[RX]?\b|net\s+worth|equity|assets|cash\s+flow)(?:\s+ratio)?"
    r"|gearing(?:\s+ratio)?", re.IGNORECASE)
# "Interest Coverage Ratio", "consolidated interest coverage ratio", "Interest Cover", "ICR",
# "Consolidated Adjusted EBITDA to Consolidated Interest Expense", "EBITDA / Net Finance Charges", "EBITDA / Interest"
_INT_NAME_RE = re.compile(
    rf"(?:{_MOD}\s+){{0,3}}interest\s+(?:expense\s+|charges?\s+)?cover(?:age)?\b(?:\s+ratio)?|\bICR\b"
    rf"|(?:{_MOD}\s+){{0,3}}EBIT(?:DA[RX]?)?\s*(?:/|-?\s*to\s*-?)\s*{_ENUM}(?:the\s+)?(?:{_MOD}\s+){{0,3}}(?:interest|finance)\b"
    r"(?:\s+(?:expense|charges?|costs?))?",
    re.IGNORECASE)
# other maintenance tests: (sub-kind, name pattern, level types it takes, operator when none is printed)
_OTHER_NAMES = [
    ("fccr", r"(?:(?:consolidated|cash)\s+){0,2}fixed\s+charges?\s+cover(?:age)?(?:\s+ratio)?|\bFCCR\b"
             rf"|(?:{_MOD}\s+){{0,3}}EBITDA[RX]?\s*(?:/|-?\s*to\s*-?)\s*{_ENUM}(?:{_MOD}\s+){{0,3}}fixed\s+charges?", ("ratio",), ">="),
    ("dscr", r"debt\s+service\s+cover(?:age)?(?:\s+ratio)?|\bDSCR\b", ("ratio",), ">="),
    ("ltv", r"loan[\s-]+to[\s-]+value(?:\s+ratio)?|\bLTV\b", ("pct", "ratio"), "<="),
    ("liquidity", r"(?:min(?:imum|\.)\s+)?(?:(?:consolidated|available|total)\s+)?liquidity\b|min(?:imum|\.)\s+(?:unrestricted\s+)?cash(?:\s+balance)?",
     ("money",), ">="),
    ("networth", r"(?:min(?:imum|\.)\s+)?(?:(?:consolidated|tangible)\s+){0,2}net\s+worth", ("money",), ">="),
    ("coverage", r"(?:collateral|asset|vessel|security|borrowing\s+base)\s+cover(?:age)?(?:\s+ratio)?", ("ratio", "pct"), ">="),
    # not "Minimum EBITDA to Fixed Charges", which is a ratio
    ("ebitda", r"min(?:imum|\.)\s+(?:consolidated\s+)?(?:adjusted\s+)?EBITDA[RX]?\b(?!\s*(?:/|-?\s*to\b))", ("money",), ">="),
    ("capex", r"(?:max(?:imum|\.)\s+)?(?:capital\s+expenditures?|capex)", ("money",), "<="),
    ("current", r"current\s+ratio", ("ratio",), ">="),
]
_OTHER_NAME_RES = [(sub, re.compile(rx, re.IGNORECASE), types, op) for sub, rx, types, op in _OTHER_NAMES]
# the label of a row that is a covenant of its own: "Minimum Liquidity", "Maximum Total Leverage Ratio", "Interest Cover Covenant"
_COV_ROW_LABEL = (r"(?:(?:maximum|minimum|max\.?|min\.?)\s+)?(?:" + "|".join(f"(?:{rx})" for rx in [_LEV_NAME_RE.pattern, _INT_NAME_RE.pattern]
                                                                               + [rx for _, rx, _, _ in _OTHER_NAMES])
                  + r")(?:\s+(?:covenant|test|requirement))?")
# covenant wording in such a row: "shall not permit", "will maintain", "not less than", "at least"
_MAINTAIN_VERB_RE = re.compile(r"(?:shall|will|must|may)\s+not\b|(?:shall|will|must|to)\s+(?:maintain|ensure|be\s+maintained)|not\s+to\s+exceed|not\s+(?:be\s+)?(?:less|more|greater)\s+than"
                               r"|no\s+(?:less|more|greater)\s+than|at\s+least|at\s+all\s+times|[≤≥]", re.IGNORECASE)
# ... and what shows the row is about pricing or fees, where a leverage grid is not a covenant
_PRICING_WORDS_RE = re.compile(r"\bbps\b|basis\s+points|applicable\s+(?:margin|rate)|\bmargin\b|commitment\s+fee|\bSOFR\b|\bSONIA\b|EURIBOR|LIBOR|per\s+annum"
                               r"|\bpricing\b|\bspread\b|\bfees?\b", re.IGNORECASE)
# a ratio given by its components: "ratio of (i) A to (ii) B", "ratio (“Net Leverage Ratio”) of A to B"
_RATIO_OF_RE = re.compile(
    r"ratio\s*(?:\([^)]{0,60}\)\s*)?of\s+(?P<body>(?:\((?:i|a|x|1)\)\s+)?[A-Za-z“\"][^.;]{8,600}?)"
    r"(?=,?\s*(?:of\s+(?:not|no|at)\s|(?:not\s+)?to\s+exceed\s+(?![$€£U])|to\s+be\s+(?:less|greater|more|lower|higher)|shall\s+not|will\s+not|is\s+not"
    r"|\(such\s+ratio|\(the\s+[“\"]|[<>≤≥]|$))", re.IGNORECASE)
_CAP_WORDS_RE = re.compile(r"capitali[sz]ation|capital\b|net\s+worth|equity|gearing|assets", re.IGNORECASE)  # balance-sheet leverage
# a denominator that adds other charges to interest: "the sum of (i) Interest Expense plus (ii) rental expense", "interest and
# scheduled principal payments"
_CHARGE_WORD = r"(?:rent(?:al|s)?|leases?|principal|dividends?|taxes|capital\s+expenditures?|amorti[sz]ation\s+payments?)\b"
_CHARGE_SUM_RE = re.compile(
    rf"(?:\bplus\b|\+|\bsum\s+of\b)(?:(?!exclud|other\s+than|net\s+of)[^.;]){{0,200}}?\b{_CHARGE_WORD}"
    rf"|\b{_CHARGE_WORD}(?:(?!exclud|other\s+than|net\s+of)[^.;]){{0,200}}?(?:\bplus\b|\+)[^.;]{{0,80}}?\binterest\b"
    rf"|\binterest(?:\s+(?:expense|charges?|payments?))?\s*(?:,|\band\b)\s*(?:(?:scheduled|cash|required|mandatory)\s+){{0,2}}{_CHARGE_WORD}", re.IGNORECASE)
# what stands between a ratio spelled out by its components and the name given to it: "ratio of A to B (the “X Ratio”)"
_NAMED_AFTER_RE = re.compile(r"[\s,]*\((?:[^()“”\"]{0,40})[“\"]\s*")
# the "ratio of" that leads into such a ratio, at the end of the words before it: "... shall not permit the ratio (the “X”) of "
_RATIO_LEAD_RE = re.compile(r"(?:the\s+|an?\s+)?(?:(?:maximum|minimum)\s+)?ratio\s*(?:\([^)]{0,60}\)\s*)?of\s+(?:\((?:i|a|x|1)\)\s+)?$", re.IGNORECASE)
# an interest element named inside a denominator, which does not make the lease or the rent a charge of its own: "plus the
# interest component of Capital Lease Obligations"
_INTEREST_PART_RE = re.compile(r"\binterest\s+(?:component|portion|element)\s+of\s+[^,;()]{0,60}", re.IGNORECASE)
# words that do not tell one covenant's name from another's ("the Leverage Ratio" is "Maximum Consolidated Leverage Ratio")
_NAME_STOP = {"the", "a", "an", "ratio", "maximum", "minimum", "max", "min", "of", "to", "covenant", "test", "consolidated"}
_SECURED_WORDS_RE = re.compile(r"first[\s-]+lien|secured|senior|priority|super", re.IGNORECASE)  # a secured-debt leverage test
# words that stay in capitals when a name printed in capitals is put in title case
_ACRONYM_RE = re.compile(r"EBIT(?:DA[RX]?)?|LTM|LTV|DSCR|FCCR|ICR|[A-Z]/[A-Z]")
# words dropped from the front of a ratio's name (the operator carries them)
_NAME_LEAD_RE = re.compile(r"^(?:(?:the|an?|maximum|minimum|max\.?|min\.?)\s+)+", re.IGNORECASE)
# the capitalised term that stands right before a bracket: "EBITDAR (to be defined ...)", "(i) Interest Expense (to be defined ...)"
_TERM_BEFORE_RE = re.compile(r"((?:[A-Z][\w’'/-]*)(?:\s+[A-Z][\w’'/-]*){0,5})\s*$")
# ... when it is one of the parts a covenant ratio is made of
_RATIO_PART_RE = re.compile(r"EBIT|debt|indebtedness|leverage|ratio|interest|cover|capitali[sz]ation|charges?|net\s+income|cash|liquidity|net\s+worth"
                            r"|assets|rent|expense|value", re.IGNORECASE)
# pointing at an agreement under any name the term sheet gives it: "substantially consistent with the Precedent Credit Agreement"
# (the shared pattern knows "the Existing / Prior / Current ... Agreement")
_NAMED_DOC_RE = re.compile(
    r"(?i:(?:substantially\s+)?(?:similar|consistent|the\s+same|identical)\s+(?:to|with|as)\s+(?:(?:those|that)\s+(?:(?:set\s+forth|contained|provided)\s+)?in\s+"
    r"|under\s+|in\s+)?the)\s+(?:[A-Z0-9][\w\-]*\s+){1,5}?(?:Agreements?|Facilit(?:y|ies)|Documentation|Documents)\b"
    r"(?:\s+(?:Agreements?|Documentation|Documents)\b)?")
# a definition bracket that only names the document the definition will come from: "to be defined as set forth in the Initial Revolving
# Credit Agreement"
_DOC_END_RE = re.compile(r"\b(?:Agreements?|Documentation|Documents|Facilit(?:y|ies))\W*$")
# a sentence on how the covenants are calculated: "For purposes of calculating the Financial Covenants ..., pro forma effect
# will be given to ...", "The financial covenants will be calculated on a pro forma basis for ..."
_CALC_WORD_RE = re.compile(r"\b(?:calculat|comput|determin)\w*", re.IGNORECASE)
_CALC_OF_RE = re.compile(r"\bfinancial\s+covenants?\b|\bfinancial\s+ratios?\b|\bEBITDA\b", re.IGNORECASE)

# ---------------------------------------------------------------------------------------------------
# levels and operators
# ---------------------------------------------------------------------------------------------------

# what follows the number of a ratio level: "x", ":1.00", "to 1.00", "times" (after a decimal: "3.5 times", not "4 times")
_RATIO_TAIL = r"(?:[xX]\b|:\s?1(?:\.0{1,2})?\b|to\s+1(?:\.0{1,2})?\b|(?<=\.\d)\s?times\b|(?<=\.\d\d)\s?times\b)"
# "3.50 to 1.00", "3.5x", "4.00:1.00", "3.5:1", "[4.50]:1.00"
_RATIO_LEVEL_RE = re.compile(r"(?<![\w.$])(?P<open>\[\s*)?(?P<num>\d{1,2}(?:\.\d{1,2})?)(?:\s*\])?\s*" + _RATIO_TAIL, re.IGNORECASE)
# "65.0%", "35 %", "[35]%"
_PCT_LEVEL_RE = re.compile(r"(?<![\w.$])(?P<open>\[\s*)?(?P<num>\d{1,3}(?:\.\d+)?)(?:\s*\])?\s*(?:%|per\s?cent\b\.?)", re.IGNORECASE)
# a level left blank: "[●]:1.00", "[ ]x", "[__]%"
_BLANK_LEVEL_RE = re.compile(r"\[\s*[●•_ ]{0,8}\]\s*(?:" + _RATIO_TAIL + r"|%)", re.IGNORECASE)
# an amount in a currency the shared money pattern does not know: "CHF 500 million", "CAD 75,000,000", "NOK 1.5 billion"
_FX_MONEY_RE = re.compile(
    r"(?<![A-Za-z])(?P<cur>CAD|AUD|NZD|CHF|JPY|SEK|NOK|DKK|SGD|HKD|ZAR|MXN|BRL|CNY|RMB|INR)\s?(?P<num>\d{1,3}(?:\s?,\s?\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?"
    r"(?P<unit>billion|bn|million|mm|mn|m|thousand|k)?(?![A-Za-z0-9])", re.IGNORECASE)
# a digit that is not a footnote mark ("Liquidity(1)", "Liquidity1")
_FREE_DIGIT_RE = re.compile(r"(?<![(\w])\d")
# an amount left blank: "$[●] million", "$[ ]", "US$[___]mm"
_BLANK_MONEY_RE = re.compile(r"(?:US\$|U\.S\.\s?\$|USD\s?|\$|€|£|EUR\s?|GBP\s?)\s?\[\s*[●•_ ]{0,8}\](?:\s?(?:billion|bn|million|mm|mn|m)\b)?", re.IGNORECASE)
# operator wording, most specific first; the *_neg forms take their sense from "shall not permit"
_OP_RE = re.compile(
    r"(?P<le>less\s+than\s+or\s+equal\s+to|≤|<=|=<|not\s+(?:to\s+be\s+|to\s+|be\s+)?(?:more|greater|higher)\s+than|no\s+(?:more|greater|higher)\s+than"
    r"|not\s+(?:to\s+)?exceed(?:ing)?|at\s+most|\bmax(?:imum|\.)?(?![a-z]))"
    r"|(?P<ge>greater\s+than\s+or\s+equal\s+to|≥|>=|=>|not\s+(?:to\s+be\s+|to\s+|be\s+)?(?:less|lower)\s+than|no\s+(?:less|lower)\s+than|at\s+least"
    r"|not\s+(?:to\s+)?(?:fall\s+|be\s+)?below|\bmin(?:imum|\.)?(?![a-z]))"
    r"|(?P<lt_neg>to\s+be\s+(?:less|lower)\s+than|to\s+fall\s+below)"
    r"|(?P<gt_neg>to\s+exceed|to\s+be\s+(?:more|greater|higher)\s+than)"
    r"|(?P<lt>less\s+than|lower\s+than|\bbelow\b|<)"
    r"|(?P<gt>greater\s+than|more\s+than|higher\s+than|in\s+excess\s+of|\bexceed(?:s|ing)?\b|\babove\b|>)", re.IGNORECASE)
# words that compare only when the level follows at once ("be below $250 million"; not "as set out below")
_LOOSE_OPS = ("below", "above")
# "The Borrowers shall not permit ... to exceed / to be less than", also with words in between:
# "will not, as of the last day of any fiscal quarter, permit the Leverage Ratio to be greater than"
_NEG_FRAME_RE = re.compile(r"\b(?:shall|will|may|must)\s+not\b(?:(?![.;]\s)[^\n]){0,140}?\b(?:permit|allow|suffer)\b|\bnot\s+(?:to\s+)?permit", re.IGNORECASE)
# a negation a few words before a bare comparison: "shall not at any time be less than", "may never exceed"
_NEAR_NOT_RE = re.compile(r"\b(?:not|never)\b(?:[\s,]+[\w’'()“”\"-]+){0,7}[\s,]*$", re.IGNORECASE)
# how close a figure must follow an operator to be the figure the operator speaks of ("not to exceed $200,000,000")
_OP_REACH = 25

# ---------------------------------------------------------------------------------------------------
# sentence structure
# ---------------------------------------------------------------------------------------------------

# what follows a percentage that is a share or a margin, not the level of a ratio: "35% drawn", "30% cushion", "25% cap"
_SHARE_WORDS_RE = re.compile(r"\s*(?:drawn|utili[sz]ed|utili[sz]ation|usage|cushion|headroom|cap\b|per\s+annum|p\.a\.)", re.IGNORECASE)
# ... or what precedes it: "with headroom of at least 30% to the Base Case Model"
_SHARE_LEAD_RE = re.compile(r"\b(?:headroom|cushion|buffer)\s+(?:of\s+|at\s+|equal\s+to\s+)?(?:at\s+least\s+|not\s+less\s+than\s+|approximately\s+|up\s+to\s+)?$",
                            re.IGNORECASE)
# a level that is one of two amounts: "the greater of $50,000,000 and 10% of ..."
_COMPOUND_RE = re.compile(r"\b(?:the\s+)?(?:greater|lesser|higher|lower|larger|smaller)\s+of\s+(?:\(\w{1,3}\)\s*)?$", re.IGNORECASE)

# a bullet or dash that opens a line of a slide
_BULLET_START_RE = re.compile(r"^(?:[•·▪●◼■‣]\s*|[-–‒]\s+)")
# "Max. Consolidated Debt / Capitalization" is one statement: an abbreviation's full stop does not end a sentence
_NOT_ABBREV = r"(?<![Mm]ax)(?<![Mm]in)(?<!Inc)(?<!Ltd)(?<!Corp)(?<!approx)(?<!\bCo)(?<!\bNo)"
# end of a statement: hard line break, full stop / semicolon before a capital, the " | " of a one-line slide row
_HARD_BREAK_RE = re.compile(r"\n|(?<=[a-z0-9\)\]”\"%])" + _NOT_ABBREV + r"[.;]\s+(?=[A-Z(“\"•])|\s\|\s")
# the end of a sentence proper (a colon or a line break does not end it)
_FULL_STOP_RE = re.compile(r"(?<=[a-z0-9\)\]”\"%])" + _NOT_ABBREV + r"\.\s+(?=[A-Z(“\"•])")
# "; provided that", ", provided, however, that", "; provided , further, that"
_PROVISO_RE = re.compile(r"[;,]?\s*\bprovided\b[\s,]*(?:however|further)?[\s,]*(?:that\b)?[\s,]*", re.IGNORECASE)
# a list item that starts a new covenant inside one sentence: "; and 2.", " and (b)"
_SOFT_BREAKS = [re.compile(r";\s*(?:and\s+|or\s+)?"), re.compile(r"(?:,?\s+and)?\s+(?=\(?(?:\d{1,2}|[a-z]|[ivx]{1,4})[.)]\s)"), re.compile(r",?\s+and\s+")]
# an enumerator inside a statement: "(i)", "(vii)", "(a)"
_ENUM_RE = re.compile(r"\(\s*(?:[ivx]{1,5}|[a-h]|\d)\s*\)")
# a period heading above slide bullets: "From Closing Date until December 31, 2026:", "Post-December 31, 2026:"
_PERIOD_WORDS_RE = re.compile(r"\b(?:from|until|through|prior\s+to|after|post|on\s+or\s+(?:after|before|prior)|during|following|before|thereafter|"
                              r"(?:19|20)\d{2}|FY\s?\d{2,4}|Q[1-4]|year|quarter)\b", re.IGNORECASE)
# a condition printed after a level: "(Parent & OpCo only)", "for any Testing Date on or prior to ...", "thereafter"
_COND_LEAD_RE = re.compile(r"^(?:\(|for\b|from\b|until\b|through\b|prior\s+to\b|after\b|post\b|by\b|before\b|during\b|following\b|on\s+or\b|"
                           r"on\s+and\s+after\b|at\s+any\s+time\b|at\s+all\s+times\b|thereafter\b|as\s+of\s+each\b|with\s+respect\s+to\b|"
                           r"in\s+the\s+case\s+of\b|in\s+respect\s+of\b|if\b|when\b|while\b|so\s+long\s+as\b|upon\b)", re.IGNORECASE)
# the facility a covenant is given for, at the head of its statement: "With respect to the Revolving Facility only, a maximum ...",
# "Solely for the benefit of the Revolving Lenders, ...", "Revolving Facility: Maximum ..."
_SCOPE_LEAD_RE = re.compile(
    r"\W*((?:solely\s+)?(?:with\s+respect\s+to|in\s+respect\s+of|for\s+the\s+benefit\s+of|in\s+the\s+case\s+of)\s+(?:the\s+)?[A-Z][\w /&-]{2,60}?(?:\s+only)?)\s*[,:]\s"
    r"|\W*((?:[A-Z][\w-]*\s+){0,3}(?:Facilit(?:y|ies)|Loans?|Revolver|RCF|TL[AB]|Lenders)(?:\s+[A-Z]\b)?(?:\s+only)?)\s*:\s"
    # "During the Covenant Relief Period, the maximum ...", "If any Revolving Loans are outstanding, the ...", "If on the last day
    # of any fiscal quarter the aggregate Revolving Exposure exceeds 35% of the Revolving Commitments, the ..."
    r"|\W*((?:during|prior\s+to|from\s+and\s+after|on\s+and\s+after|following|after|until|unless|(?:for\s+)?so\s+long\s+as|as\s+long\s+as"
    r"|at\s+any\s+time\s+(?:when|that|after|following|prior\s+to|during|while)|if|when(?:ever)?|while|where|upon(?:\s+and\s+after)?|in\s+the\s+event"
    r"|to\s+the\s+extent"
    r"|(?:solely|only)\s+(?:if|when|while|during|upon|after|following|to\s+the\s+extent|for\s+so\s+long\s+as))"
    r"\s+[^,:.;]{3,200}),\s", re.IGNORECASE)
# words between a ratio's name and its level that say nothing: "of", "at", "equal to", "is"
_FILLER_RE = re.compile(r"^(?:(?:of|at|is|are|be|being|equal\s+to|to|shall|will|must|:)\s*)+", re.IGNORECASE)
# the link between two levels of a schedule: ", stepping down to", " (with a step-up to", " and then reducing to"
_CONNECTOR_RE = re.compile(r"[\s,;(]*(?:and\s+)?(?:then\s+)?(?:(?:with\s+)?(?:an?\s+)?step(?:s|ping|ped)?[\s-]*(?:back\s+)?(?:down|up)s?\s+to"
                           r"|(?:reducing|increasing|declining|rising|falling|decreasing)\s+to"
                           r"|(?:which\s+)?(?:shall|will|may|to)\s+be\s+(?:increased|reduced|decreased|stepped\s+(?:up|down))\s+to)\s*$", re.IGNORECASE)
# testing wording that trails a level or its condition: ", tested quarterly on a rolling four-quarter basis"
_TEST_TAIL_RE = re.compile(r"[,;]?\s+(?:(?:only\s+)?(?:to\s+be\s+|in\s+each\s+case\s+|and\s+)?(?:tested|measured|calculated)\b.*)$", re.IGNORECASE | re.DOTALL)
# wording that belongs to the testing row, not to a tier's condition
_TESTING_WORDS_RE = re.compile(r"\btest(?:ed|ing)?\b|\bcommenc|\bmeasured\b", re.IGNORECASE)
# a level given as a range, which is not a level the rules may print: "between 3.50:1.00 and 4.00:1.00 depending on ..."
_RANGE_RE = re.compile(r"\b(?:between|ranging\s+from|in\s+the\s+range(?:\s+of)?|from)\s*$", re.IGNORECASE)
# a period in the heading row of a level table: "FY2026", "Q4 2026", "December 31, 2026", "2027", "Year 3"
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_PERIOD_TOKEN_RE = re.compile(
    rf"(?:Q[1-4]\s?)?FY\s?[’']?\d{{2,4}}|Q[1-4]\s?[’']?\d{{2,4}}|{_MONTH}\.?\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+{_MONTH}\.?\s+\d{{4}}|{_MONTH}\.?\s+\d{{4}}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}|\b(?:19|20)\d{2}\b|\bYears?\s+\d(?:\s?[-–]\s?\d)?", re.IGNORECASE)
# A line that ends in a colon and holds a period word is a period heading ("From Closing Date until December 31, 2026:",
# "Each fiscal quarter in 2026:") unless it is the lead-in of the list: "Maintenance of the following financial covenants:",
# "The Borrower shall maintain, as of the last day of each fiscal quarter:", "Each of the following, tested quarterly:"
# (words a period heading does not use; not "may", "including" or "maintenance": "Through May 31, 2026:", "From and including ...:")
_LIST_LEAD_IN_RE = re.compile(r"\bthe\s+following\b|\bas\s+follows\b|\b(?:shall|will|must)\b|\bmaintain(?:s|ed)?\b|\bfinancial\s+covenants?\b"
                              r"|\blimited\s+to\b|\bconsist|\btested\b|\bcompl(?:y|ies|iance)\b|\bensure\b"
                              r"|\bto\s+(?:include|observe|satisfy|meet)\b|\bobserve[sd]?\b|\bsatisf(?:y|ies|ied)\b|\bmeasured\b|\bcalculated\b"
                              r"|\bundertak|\bnamely\b|\bcompris|\brequire", re.IGNORECASE)
# ... and a heading that opens with the period ("Thereafter:", "Prior to a Qualified IPO:", "FY2026:") is recognised as one
# even where it looks like the label of a row (a page read without layout)
_PERIOD_HEAD_RE = re.compile(
    r"^\W*(?:from|until|through|prior\s+to|after|post\b|on\s+or\s+(?:after|before|prior)|on\s+and\s+after|during|following|before|thereafter"
    r"|for\s+(?:the|each|any)\b|as\s+(?:of|at)\b|by\b|commencing|beginning|starting|upon|(?:fiscal\s+|financial\s+|calendar\s+)?(?:years?|quarters?)\b"
    rf"|(?:Q[1-4]\s?)?FY|Q[1-4]\b|(?:19|20)\d{{2}}\b|\d{{1,2}}[\s/]|{_MONTH}\b)", re.IGNORECASE)
# ... as is one that opens by counting periods: "Each fiscal quarter in 2026:", "First four quarters after the Closing Date:"
_EACH_PERIOD_RE = re.compile(r"\W*(?:each|any|every|all|the|first|second|third|fourth|next|last|initial|\d{1,2})\s+(?:\w+\s+){0,3}?"
                             r"(?:quarters?|years?|months?|periods?|dates?)\b", re.IGNORECASE)
# a word that names a financial measure: a statement that sets "<measure> <operator> <level>" without a covenant name
# the rules know is a test they cannot classify ("Minimum Debt Yield of 8%", "Senior Debt / Tangible Assets ≤ 40%")
_METRIC_RE = re.compile(r"\b(?:ratio|cover(?:age)?|EBIT\w*|debt|indebtedness|yield|worth|assets?|cash|capex|expenditures?|interest|equity|value"
                        r"|availability|headroom|earnings|revenues?|turnover|backlog|occupancy|rent(?:al)?|solvency|capital)\b|[A-Za-z]\s?/\s?[A-Za-z]",
                        re.IGNORECASE)
# ... unless the statement carries on a covenant already named: "Thereafter, not more than 4.00x", "such ratio shall step down to"
_CONTINUATION_RE = re.compile(r"\bstep|\bthereafter\b|\bincreas|\bdecreas|\breduc|\bsuch\s+(?:ratio|level|covenant)|\bthe\s+(?:foregoing|above|same)\b"
                              r"|\bholiday\b|\breset\b|\bin\s+each\s+case\b|\bthe\s+(?:maximum|minimum)\s+(?:level|ratio)\b", re.IGNORECASE)
# a later sentence that changes the level
_STEP_UP_RE = re.compile(r"acquisition|step(?:s|ped|ping)?[\s-]*up|increase", re.IGNORECASE)
# ... or brings it down
_STEP_DOWN_RE = re.compile(r"step(?:s|ped|ping)?[\s-]*(?:back\s+)?down|decrease|reduc", re.IGNORECASE)
# "(the “Acquisition Closing Date”)", "(such election, a “Transition Period Election”)", "(“ Net Leverage Ratio”)"
# (not "(including, without limitation, “Adjusted Consolidated EBITDA”)", which says what the sentence covers)
_DEFINED_PAREN_RE = re.compile(r"\s*\((?!\s*includ)(?:[^()“”\"]{0,90})[“\"][^”\"]{1,60}[”\"]\s*\)", re.IGNORECASE)
# "(which amount of aggregate consideration is calculated consistent with past practice)"
_WHICH_PAREN_RE = re.compile(r"\s*\(which\s[^()]{0,160}\)")
# the words that open a proviso, dropped when the proviso becomes a line of its own
_LEAD_IN_RE = re.compile(r"^[\s;,]*(?:provided\b[\s,]*(?:however|further)?[\s,]*(?:that\b)?[\s,]*)?", re.IGNORECASE)
# words that open the closing phrase of a schedule condition: "... ending after the Acquisition Closing Date"
_SUFFIX_OPENERS = {"ending", "ended", "after", "following", "occurring", "commencing", "beginning", "prior", "before", "from"}
# first words that may be lower-cased when a clause is joined to a line
_LOWER_FIRST = {"following", "upon", "if", "in", "at", "for", "after", "prior", "during", "the", "provided", "subject", "on", "from", "until", "each",
                "any", "such", "with", "notwithstanding", "when", "where", "commencing", "only", "tested", "to", "as", "post", "there", "an", "a",
                "solely", "thereafter", "through"}

# ---------------------------------------------------------------------------------------------------
# section wording
# ---------------------------------------------------------------------------------------------------

# the section says there is no financial covenant
_NONE_RE = re.compile(r"^\W*(?:none|n\s?/\s?a|not\s+applicable|nil|no\s+financial\s+(?:maintenance\s+)?covenants?|cov(?:enant)?[\s-]*lite)\b", re.IGNORECASE)
# a facility for which the section says there is none: "Term Loan Facility: None."
_FACILITY_NONE_RE = re.compile(r"\W*[A-Z][\w /&-]{2,40}:\s*(?:none|n\s?/\s?a|not\s+applicable)\W*$", re.IGNORECASE)
# the same statement in the running text of a covenants section: "... will be covenant-lite, with no financial covenants"
_NO_FC_RE = re.compile(r"\bno\s+financial\s+(?:maintenance\s+)?covenants?\b(?!\s+(?:other\s+than|except|save|apart|unless|until|if|while"
                       r"|defaults?|breach|event|cure|compliance|calculation|levels?|tests?\b|definitions?))"
                       r"|\bcov(?:enant)?[\s-]lite\b", re.IGNORECASE)
# the words that make a ratio a condition of something else rather than a maintenance test, read just before its name:
# "subject to a pro forma Total Leverage Ratio of 4.00:1.00", "if the Leverage Ratio is greater than 3.00x, ..."
_CONDITION_LEAD_RE = re.compile(
    r"(?:\bsubject\s+to\s+(?:pro\s+forma\s+)?(?:compliance\s+with\s+)?|\bpro\s+forma\s+(?:compliance\s+with\s+)?"
    r"|\b(?:if|unless|so\s+long\s+as|to\s+the\s+extent(?:\s+that)?|when(?:ever)?|until|while)\s+)"
    r"(?:(?:an?|the|its)\s+)?(?:pro\s+forma\s+)?(?:(?:maximum|minimum)\s+)?$", re.IGNORECASE)
# wording that makes the covenant named after it an option or a substitute rather than one more test: "or (2) at the
# Company's option, solely to the extent ...", "in lieu of the foregoing", "the Borrower may elect instead to maintain"
_OPTION_LEAD_RE = re.compile(
    r"\b(?:at|upon|following|after|in|on|by)\s+(?:the\s+|its\s+|their\s+|an?\s+)?(?:[\w’']+\s+){0,3}?(?:option|election|discretion)\b"
    r"|\bin\s+lieu\s+of\b|\binstead\b|\bin\s+place\s+of\b"
    r"|\balternatively\b|\bas\s+an\s+alternative\b|\b(?:solely|only)\s+(?:to\s+the\s+extent|if|when|for\s+so\s+long\s+as)\b|\bmay\s+elect\b"
    r"|\b(?:so\s+)?elects\b|\bin\s+substitution\b|\bswitch(?:es|ing|ed)?\b", re.IGNORECASE)
# wording that puts the covenant named after it in the place of another, wherever it stands in the words that lead to the
# name: "... the Total Leverage Ratio covenant shall be replaced by a Senior Secured Leverage Ratio of 3.00x", "... shall
# instead comply with a Debt to Capitalization Ratio of ...", "a substitute covenant of ..."
_SUBSTITUTE_RE = re.compile(
    r"\bin\s+lieu\s+of\b|\binstead\b|\bin\s+place\s+of\b|\bin\s+substitution\b|\b(?:be|is|are)\s+replaced\b|\b(?:shall|will|to|may)\s+replace\b"
    r"|\bin\s+replacement\s+of\b|\bsubstitute[ds]?\b|\brather\s+than\b|\bswitch(?:es|ing|ed)?\b", re.IGNORECASE)
# wording right before a name that makes it the test that is given up, not one that is set: "..., which replaces the Fixed
# Charge Coverage Ratio in the Existing Credit Agreement", "in lieu of the Interest Coverage Ratio"
_GIVEN_UP_RE = re.compile(r"(?:\breplac\w+|\bin\s+lieu\s+of|\binstead\s+of|\bin\s+place\s+of|\brather\s+than|\bsupersed\w+|\bdelet\w+|\bremov\w+|\bno\s+longer(?:\s+\w+){0,2})"
                          r"\s+(?:(?:the|an?|any)\s+)?(?:existing\s+|current\s+)?(?:(?:maximum|minimum)\s+)?$", re.IGNORECASE)
# wording that makes the tests it introduces a choice: "either (i) ... or (ii) ...", "must satisfy one of the following tests"
_CHOICE_RE = re.compile(r"\beither\b|\b(?:any\s+|at\s+least\s+)?one\s+of\b", re.IGNORECASE)
# "or" at the head of an item, after whatever closes the item before it: "; or (b) ", " (or, ", ", or "
_OR_OPEN_RE = re.compile(r"[\s,;.()\[\]]*or\b[\s,]*(?:\(\w{1,4}\)[\s,]*)?", re.IGNORECASE)
# a condition that opens an item ("or, following a Collateral Release Event, X of ..."): the test after it applies in that case
_CASE_OPEN_RE = re.compile(r"(?:following|after|upon|if|when(?:ever)?|where|during|while|until|unless|prior\s+to|(?:for\s+)?so\s+long\s+as|as\s+long\s+as"
                           r"|in\s+the\s+event|from\s+and\s+after|on\s+and\s+after|at\s+any\s+time\s+(?:when|that|after|following)|to\s+the\s+extent"
                           r"|subject\s+to|with\s+the\s+consent|solely|only)\b", re.IGNORECASE)
# a condition at the head of a covenant's statement, in whatever form: what _SCOPE_LEAD_RE reads when it is one plain clause,
# and what makes the statement one to keep as worded when it is not ("For so long as ... and, in any event, until ..., the
# Borrower shall ...", "None for so long as ...; otherwise a ...")
_CASE_HEAD_RE = re.compile(r"\W*(?:" + _CASE_OPEN_RE.pattern + r"|otherwise\b|(?:with\s+respect\s+to|in\s+respect\s+of|for\s+the\s+benefit\s+of"
                           r"|in\s+the\s+case\s+of)\b)", re.IGNORECASE)
# what may stand before that wording at the head of an item: "; or (2) ", ", and (b) ", ". "
_ITEM_OPEN_RE = re.compile(r"[\s,;.)\]]*(?:(?:and/or|and|or)\b[\s,]*)?(?:\(\w{1,4}\)|\d{1,2}[.)])?[\s,]*", re.IGNORECASE)
# a break in a list of covenants, and what may stand between it and the next covenant's name: "; and (b) a minimum ",
# ", and (b) an "
_LIST_BREAK_RE = re.compile(r";\s*(?:and\s+|or\s+)?|,\s*(?:and|or)\s+", re.IGNORECASE)
_ITEM_HEAD_RE = re.compile(r"(?:\(?\w{1,4}[.)]\s*)?(?:(?:an?|the)\s+)?(?:(?:maximum|minimum|max\.?|min\.?)\s+)?", re.IGNORECASE)
# a name brought in as one more item of a list: "..., and (c) a minimum " before it
_ITEM_JOINED_RE = re.compile(r"(?:\band\b|\bor\b)[\s,]*(?:\(\w{1,4}\)\s*)?(?:(?:an?|the)\s+)?(?:(?:maximum|minimum)\s+)?$", re.IGNORECASE)
# a qualifier printed after a level, kept with it: "which shall cease to apply during ...", "subject to ...", "with a 30% cushion"
_QUALIFIER_RE = re.compile(r"(?:which|subject\s+to|except|unless|excluding|including|calculated|net\s+of|as\s+defined|but|provided|only|springing"
                           r"|other\s+than|with\s+(?:an?|the|no|up|step|respect))\b", re.IGNORECASE)
# a point about the level that the term sheet leaves open, printed after it: "with step-downs to be agreed", "(levels TBD)"
_OPEN_POINT_RE = re.compile(r"to\s+be\s+(?:mutually\s+)?(?:agreed|determined|negotiated|set)|\bTBD\b|\bTBA\b", re.IGNORECASE)
# a level left for later: "at a level to be agreed", "levels to be determined"
_TO_BE_AGREED_RE = re.compile(r"to\s+be\s+(?:mutually\s+)?(?:agreed|determined|negotiated)", re.IGNORECASE)
# a closed list: "Limited to", "only the following", "consisting of"
_CLOSED_RE = re.compile(r"\blimited\s+to\b|\b(?:only|solely)\s+(?:of\s+)?the\s+following\b|\bconsist(?:s|ing)?\s+(?:solely\s+|only\s+)?of\b", re.IGNORECASE)
# an open list: "including", "such as"
_OPEN_RE = re.compile(r"\binclud(?:e|es|ing)\b|\bsuch\s+as\b|\bamong\s+other", re.IGNORECASE)
# a sub-heading that belongs to the financial covenants: "Related Definitions:", "Testing:", "Equity Cure:"
_SUB_LABEL_RE = re.compile(r"(?:related\s+|certain\s+)?definitions|test(?:ing)?(?:\s+(?:dates?|periods?|frequency))?|equity\s+cures?(?:\s+rights?)?|cure\s+rights?",
                           re.IGNORECASE)
_SUB_LABEL_START_RE = re.compile(r"\W*(?:" + _SUB_LABEL_RE.pattern + r")\s*:", re.IGNORECASE)  # the same at the head of a paragraph
# a sub-heading that follows the financial covenants inside a Covenants section: "Negative Covenants:", "(d) Events of Default -"
_SIBLING_LABEL_RE = re.compile(
    r"^(?:[-–•]\s*|\(?[a-z0-9]{1,3}[.)]\s+)?(?:(?:Affirmative|Negative|Reporting|Information|General|Other|Positive)\s+(?:Covenants?|Undertakings?)"
    r"|Events?\s+of\s+Default|Representations|Conditions|Assignments?|Voting|Amendments?|Governing\s+Law)\b", re.IGNORECASE)
# "financial covenants:" inside a wider Covenants section
_EMBEDDED_RE = re.compile(r"financial\s+(?:maintenance\s+)?covenants?\s*(?:\([^)]{0,40}\)\s*)?(?::|[-–]\s"
                          r"|,?\s+(?:(?:shall|will|to)\s+(?:be\s+limited\s+to|consist\s+of|include|be)|consisting\s+of|limited\s+to|including)\b:?)",
                          re.IGNORECASE)
# the same as a run-in heading that opens a paragraph of the Covenants section: "Financial Covenants. A maximum ..."
_EMBEDDED_HEAD_RE = re.compile(r"\W*(?:\(?\w{1,3}[.)]\s+)?financial\s+(?:maintenance\s+)?covenants?\s*(?:\([^)]{0,40}\)\s*)?\.\s+(?=[A-Z(“\"])", re.IGNORECASE)
# a maintenance test named in running text: "Maximum Consolidated Leverage Ratio", "minimum interest coverage"
_MAINTENANCE_PHRASE = r"(?:maximum|minimum|max\.|min\.)\s+(?:[A-Za-z]+\s+){0,4}(?:leverage|coverage\s+ratio|interest\s+cover|liquidity)\b"
# a paragraph that carries on a list of financial covenants
_MAINTAIN_RE = re.compile(r"shall\s+not\s+permit|will\s+not\s+permit|(?:shall|will)\s+maintain|not\s+to\s+exceed|maximum|minimum", re.IGNORECASE)


# ---------------------------------------------------------------------------------------------------
# testing wording
# ---------------------------------------------------------------------------------------------------

# "as of the last day of each fiscal quarter of Parent", "tested quarterly", "each fiscal quarter-end"
_FREQ_QUARTER_RE = re.compile(
    r"(?:as\s+of|as\s+at|on|at)\s+(?:the\s+)?(?:last\s+day|end)\s+of\s+(?:each|any|every)\s+(?:fiscal\s+|financial\s+|calendar\s+)?quarter"
    r"(?:\s+of\s+(?:the\s+)?[A-Z]\w+)?"
    r"|(?:tested|measured|calculated|testing)\s+(?:on\s+a\s+)?quarterly|quarterly\s+(?:basis|tests?|testing)"
    r"|each\s+(?:fiscal\s+|financial\s+)?quarter[\s-]end(?:\s+date)?|each\s+Quarter\s+Date", re.IGNORECASE)
# the other testing frequencies: "tested semi-annually", "the last day of each financial half-year", "tested annually"
_FREQ_OTHER_RES = [
    ("semi-annually", re.compile(r"semi[\s-]?annual(?:ly)?|half[\s-]?yearly|(?:last\s+day|end)\s+of\s+each\s+(?:financial\s+)?half[\s-]year", re.IGNORECASE)),
    ("monthly", re.compile(r"(?:tested|measured|calculated)\s+(?:on\s+a\s+)?monthly|monthly\s+(?:basis|tests?|testing)"
                           r"|(?:last\s+day|end)\s+of\s+(?:each|any|every)\s+(?:calendar\s+|fiscal\s+|financial\s+)?month|each\s+month[\s-]end", re.IGNORECASE)),
    ("annually", re.compile(r"(?:tested|measured)\s+(?:on\s+an\s+)?annual(?:ly)?\b|(?:last\s+day|end)\s+of\s+(?:each|any|every)\s+(?:fiscal|financial)\s+year",
                            re.IGNORECASE)),
]
# a period known only by its defined name: a defined term, so written in capitals ("during the relevant period" is plain English)
_PERIOD_TERM = r"(?:T(?:est|EST)|R(?:elevant|ELEVANT)|M(?:easurement|EASUREMENT))\s+P(?:eriod|ERIOD)"
# words after "period of four fiscal quarters" that show it is the length of a step-up or a holiday, not the calculation period
_NOT_CALC_PERIOD = r"(?:following|after|commencing|beginning|immediately|ending\s+after|ended\s+after|thereafter|in\s+which|during\s+which|from\b)"
# "any period of four consecutive fiscal quarters for which financial statements have been ... delivered",
# "four fiscal quarter period", "rolling 12-month basis", "LTM", "Test Period"; not the length of a step-up
# ("for the four fiscal quarter period following a Qualified Acquisition")
_PERIOD_RE = re.compile(
    r"(?:(?:any|each|the|such)\s+)?period\s+of\s+four\s+(?:\(4\)\s+)?(?:consecutive\s+)?(?:fiscal\s+|financial\s+)?quarters"
    r"(?:\s+of\s+(?:the\s+)?[A-Z]\w+)?(?:\s+(?:then\s+)?most\s+recently\s+ended(?:\s+on\s+or\s+prior\s+to\s+such\s+date)?)?"
    r"(?:\s+for\s+which\s+financial\s+statements\s+(?:have\s+been|are)[^.;]{0,60}?delivered)?(?!\s+" + _NOT_CALC_PERIOD + r")"
    r"|four[\s-](?:consecutive\s+)?(?:fiscal\s+)?quarter\s+period(?!\s+" + _NOT_CALC_PERIOD + r")"
    r"|rolling\s+(?:four[\s-]quarter|12[\s-]months?|twelve[\s-]months?|LTM)(?:\s+basis)?"
    r"|(?:trailing|last|preceding|most\s+recently\s+ended|most\s+recent)\s+(?:four|twelve|12)[\s-](?:consecutive\s+)?(?:fiscal\s+|financial\s+)?"
    r"(?:quarters?|months?)(?:\s+(?:period|basis))?"
    r"|period\s+of\s+(?:twelve|12)\s+(?:consecutive\s+)?(?:calendar\s+)?months(?!\s+" + _NOT_CALC_PERIOD + r")"
    r"|\bLTM\b|(?:12|twelve)[\s-]months?\s+(?:(?:look[\s-]?back|rolling|trailing)\s+)?(?:period|basis)|(?-i:\b" + _PERIOD_TERM + r"\b)", re.IGNORECASE)
# a period the term sheet only names: its length is defined elsewhere
_PERIOD_TERM_RE = re.compile(_PERIOD_TERM)
# "at any time", "at all times" said of a level (not "at any time when ...", which opens a condition)
_ALWAYS_RE = re.compile(r"\bat\s+(?:any\s+time|all\s+times)\b(?!\s+(?:when|that|after|prior|during|on\b|following|from|while|in\s+which|before|until|upon|as\s+of))",
                        re.IGNORECASE)
# words that make a testing phrase speak of all the covenants although it stands with one: "..., in each case tested quarterly"
_EACH_CASE_RE = re.compile(r"\bin\s+each\s+case\b|\beach\s+of\s+the\s+(?:foregoing|above)\b|\bboth\b|\ball\s+(?:of\s+the\s+)?(?:financial\s+)?covenants\b",
                           re.IGNORECASE)
# the frequency carried by a covenant's name: "Maximum Quarterly Consolidated Total Net Leverage Ratio"
_NAME_FREQ_RE = re.compile(r"((?:(?:maximum|minimum|max\.?|min\.?)\s+)?(quarterly|monthly|semi[\s-]?annual|annual)\s+(?:(?:maximum|minimum|max\.?|min\.?)\s+)?)$",
                           re.IGNORECASE)
# "commencing with the Testing Date for the fiscal quarter ending August 31, 2025"
_FIRST_TEST_RE = re.compile(
    r"(?:commencing|beginning|starting)\s+(?:with|on|from)\s+[^.;]{5,170}?"
    r"(?=,\s+(?:a|the|of)\s|,\s+(?:the\s+)?\w+\s+(?:will|shall)\s|[.;]|\s*$)", re.IGNORECASE)
# "with the first test date being 31 December 2026", "first tested as of the fiscal quarter ending June 30, 2026"
# (also with nothing between: "first test date 30 June 2026", "First test date: 31 March 2027")
_FIRST_DATE_RE = re.compile(r"(?:with\s+)?(?:the\s+)?first\s+(?:test(?:ing)?(?:\s+date)?|tested|measurement\s+date|compliance\s+date)"
                            r"(?:\s+(?:being|is|to\s+be|will\s+be|shall\s+be|on|as\s+of|as\s+at|for|in\s+respect\s+of)\s+|\s*:\s*|\s+(?=\d))[^.;]{4,120}", re.IGNORECASE)
# "The Financial Covenants will commence with the first full fiscal quarter after the Closing Date"
_COMMENCE_RE = re.compile(r"(?:will|shall)\s+(?:commence|first\s+be\s+tested|be\s+first\s+tested|begin)\s+(?:with|on|as\s+of)\s+[^.;]{5,140}", re.IGNORECASE)
# "only to be tested quarterly when 30% of facility is drawn", "tested ... if ... exceeds 35% of the commitments", "springing"
# (a full stop inside a figure, "7.50:1.00", does not end the clause)
_NO_STOP = r"(?:[^.;]|\.(?=\d))"
_SPRINGING_RE = re.compile(
    r"(?:only\s+)?(?:to\s+be\s+)?(?:tested|applicable|in\s+effect|apply|applies|measured)\b" + _NO_STOP
    + r"{0,90}?\b(?:when(?:ever)?|if|to\s+the\s+extent|at\s+any\s+time|so\s+long\s+as|only|(?:on|in|for)\s+which|where)\b"
    + _NO_STOP + r"{0,200}?\d{1,3}(?:\.\d+)?\s*%" + _NO_STOP + r"{0,120}", re.IGNORECASE)
# ... failing that, the clause that calls the covenant springing
_SPRINGING_WORD_RE = re.compile(r"springing\b" + _NO_STOP + r"{0,300}", re.IGNORECASE)
# Words that show the covenant wording speaks of a testing point the patterns above could not read. Where one stands, the row
# does not claim that the point is "not stated".
# (the length of a step-up, "for the four fiscal quarters following a Material Acquisition", is no such word)
_FREQ_HINT_RE = re.compile(r"\bquarterly\b|\bmonthly\b|\bannually\b|\bsemi[\s-]?annual|\bhalf[\s-]?yearly\b|\b(?:quarter|month|year)[\s-]end\b"
                           r"|\b(?:each|any|every)\s+(?:fiscal\s+|financial\s+|calendar\s+)?(?:quarter|month|half[\s-]?year|year)\b"
                           r"|\btest(?:ing)?\s+dates?\b|\b(?:quarter|month|year)s?\s+end(?:ing|ed)\b", re.IGNORECASE)
_PERIOD_HINT_RE = re.compile(r"\b(?:12|twelve|four|4)[\s-]+(?:consecutive\s+)?(?:fiscal\s+|financial\s+|calendar\s+)?(?:months?|quarters?)\b"
                             r"(?!(?:\s+periods?)?\s+" + _NOT_CALC_PERIOD + r")|\bLTM\b|\brolling\b"
                             r"|\btrailing\b|\blook[\s-]?back\b|\bannuali[sz]ed\b|\b(?:test|relevant|measurement|reference|calculation)\s+periods?\b", re.IGNORECASE)
_FIRST_HINT_RE = re.compile(r"\bfirst\s+(?:\w+\s+){0,2}?(?:test|tested|testing|measurement|compliance|calculation)\b|\bcommenc|\b(?:beginning|starting)\s+(?:with|on|from)\b"
                            r"|\binitial\s+test|\bcovenant\s+holiday\b", re.IGNORECASE)
# a row of its own on how the covenants are tested: "Covenant Testing:", "Test Dates:", "Testing Frequency:"
_TEST_ROW_LABEL = r"(?:(?:financial\s+)?covenants?\s+)?(?:test(?:ing)?(?:\s+(?:dates?|periods?|frequency|basis))?|compliance\s+(?:testing|dates?))"
_TEST_ROW_WORDS_RE = re.compile(r"quarter|annual|month|half[\s-]?year|rolling|\bLTM\b|trailing|test\s+date|each\s+(?:fiscal|financial)\s+year", re.IGNORECASE)

# ---------------------------------------------------------------------------------------------------
# definitions
# ---------------------------------------------------------------------------------------------------

# "“Consolidated EBITDAR” shall be defined ...", "X means ...", "Liquidity defined as ..."
_DEF_SENTENCE_RE = re.compile(r"[“\"]([^”\"]{2,60})[”\"]\s*(?:(?:shall|will|to|is)\s+(?:be\s+defined|mean|have\s+the\s+meaning)|means\b)"
                              r"|\bshall\s+mean\b|\bdefined\s+(?:as|to)\b|\bRelated\s+Definitions\b", re.IGNORECASE)
# a footnote or sentence that defines a term: "1. Liquidity defined as, at any time, the sum of ..."
_TERM_DEFINED_AS_RE = re.compile(r"^\W*(?:\(?\d{1,2}[.)]\s*)?([A-Z][A-Za-z ]{2,40}?)\s+(?:is\s+|shall\s+be\s+)?defined\s+as\b[,:]?\s*", re.IGNORECASE)
# a paragraph that opens with a quoted term and says what it means: “Consolidated EBITDA” shall be calculated ..., “X” means ...
# (or sets it off with a colon or a dash: “Consolidated EBITDA”: as defined in ..., with the following modifications: ...)
_DEF_PARA_RE = re.compile(r"\s*[“\"]([^”\"]{2,60})[”\"](?:\s+(?:(?:shall|will)\s+(?:mean|have\s+the\s+meaning|be\s+(?:defined|calculated|determined|computed))"
                          r"|means\b|is\s+defined|has\s+the\s+meaning)|\s*:\s+\S|\s+[-–—]\s+\S)", re.IGNORECASE)
# the heading of a part of the term sheet that sets out definitions: "Annex I - Certain Defined Terms", "SCHEDULE 1 - DEFINITIONS"
_DEFS_HEADING_RE = re.compile(r"\bdefinitions?\b|\bdefined\s+terms?\b|\bglossary\b", re.IGNORECASE)
# a proviso that opens at the top level of such a paragraph ("; provided that ..."; not "to the extent provided below")
_PROVISO_START_RE = re.compile(r"[;,]\s*provided\b(?:[\s,]+(?:however|further))?(?:[\s,]+that\b)?|\bprovided(?:[\s,]+(?:however|further))?[\s,]+that\b",
                               re.IGNORECASE)
_ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx"]
# a definition that opens with its quoted term: "“Relevant Period” means", "“Consolidated EBITDA” shall be defined as"
_QUOTED_TERM_RE = re.compile(r"\W*[“\"]([^”\"]{2,60})[”\"]\s*(?:(?:shall|will|is|to)\s+(?:be\s+defined\s+(?:as|to\s+mean)|mean)|means|is)?\s*:?\s*", re.IGNORECASE)
# a defined term that belongs under the house prefix "Adjusted EBITDA" (EBITDA, the debt it is measured against, the ratios)
_RATIO_TERM_RE = re.compile(r"EBIT|debt|indebtedness|leverage|ratio|interest|cover|capitali[sz]ation|fixed\s+charges?", re.IGNORECASE)
# a definition the financial covenants rest on (in a list of definitions, the others are left out)
_COVENANT_TERM_RE = re.compile(r"EBITDA|leverage|interest\s+(?:cover|expense|charges)|net\s+debt|indebtedness|funded\s+debt|synerg|cost\s+savings|\bcures?\b"
                               r"|liquidity|netting|unrestricted\s+cash|(?:test|relevant|measurement)\s+period|fixed\s+charges?|capitali[sz]ation", re.IGNORECASE)
# the sub-heading "Related Definitions: Identical to those set forth in ..."
_RELATED_DEFS_RE = re.compile(r"^\W*Related\s+Definitions\s*:?\s*", re.IGNORECASE)
# the subjects of the definition lines
_SYNERGY_RE = re.compile(r"synerg|cost\s+savings|run[\s-]rate", re.IGNORECASE)  # "cost synergies", "run-rate cost savings"
_EBITDA_RE = re.compile(r"EBITDA", re.IGNORECASE)  # "Consolidated EBITDAR", "Adjusted EBITDA"
_NETTING_RE = re.compile(r"\bnetting\b|\bnet\s+of\b|unrestricted\s+cash", re.IGNORECASE)  # "to permit the netting of ... unrestricted cash"
_EQUITY_CURE_RE = re.compile(r"equity\s+cures?|cure\s+rights?|specified\s+equity\s+contribution|cure\s+amount", re.IGNORECASE)
_DEEMED_CURE_RE = re.compile(r"deemed\s+cures?|deemed\s+(?:to\s+(?:be|have\s+been)\s+)?(?:cured|remedied)", re.IGNORECASE)
# wording that speaks of the definitions as a body ("definitions and calculations to be consistent with ...")
_DEFS_POINTER_RE = re.compile(r"\bdefinitions\b|\bdefined\s+terms\b", re.IGNORECASE)
# wording about what is added to or left out of EBITDA
_ADJUSTMENT_RE = re.compile(r"add[\s-]?backs?|added\s+back|synerg|cost\s+savings|\bcapped\b|\bcap\s+of\b|exclud|pro\s+forma\s+(?:adjustments?|effect)", re.IGNORECASE)
# wording that shows a labelled "EBITDA" row is a definition and not a row of figures
_DEFINITION_WORDS_RE = re.compile(r"add[\s-]?back|defin|\bcap(?:ped)?\b|synerg|cost\s+savings|pro\s+forma|exclud|adjust|netting|unrestricted\s+cash", re.IGNORECASE)
# a lender presentation's remark on how covenant ratios are calculated
_CALC_WORD = r"(?:calculat|comput)\w*"  # "calculates", "as calculated", "computed"
_CALC_SOURCE = (r"(?:in\s+accordance\s+with|pursuant\s+to|under|in|consistent\s+with)\s+(?:the\s+terms\s+of\s+)?(?:its|the|our)\s+(?:existing\s+)?"
                r"(?:debt|credit|loan|financing)\s+(?:agreements?|facilit(?:y|ies)|documents?|documentation)")
_COVENANT_CALC = (rf"covenant\s+EBITDA\s+(?:is|are|includes?|excludes?|reflects?|calculation|definition)"
                  rf"|{_CALC_WORD}[^.]{{0,40}}(?:leverage|covenant\s+EBITDA)[^.]{{0,40}}{_CALC_SOURCE}"
                  rf"|(?:leverage|covenant\s+EBITDA)[^.]{{0,40}}{_CALC_WORD}[^.]{{0,40}}{_CALC_SOURCE}")
# time phrases cut from ratio components: "as of the last day of each fiscal quarter", "for such period of four ...", "at such date"
_COMPONENT_TIME_RE = re.compile(
    r"\s+as\s+of\s+(?:the\s+)?(?:last\s+day|end|such\s+date)[^,]*?(?=\s+(?:plus|minus|less)\b|,|$)|\s+at\s+such\s+(?:date|time)"
    r"|\s+in\s+respect\s+of\s+(?:any|each|the|such|that)\s+[^,]*?(?=\s+(?:plus|minus|less)\b|,|$)"
    r"|\s+for\s+(?:such|the)\s+(?:period|four)[^,]*|,\s+(?:all\s+)?(?:calculated|determined)\s+.*$|,\s+which\s+.*$", re.IGNORECASE)


# ---------------------------------------------------------------------------------------------------
# small text helpers
# ---------------------------------------------------------------------------------------------------

def _vocab(ctx: Ctx) -> Counter:
    """Word counts of the document, used to rejoin words the PDF extraction split ("acquisi tion")."""
    cache = ctx.__dict__.setdefault("_fincov_cache", {})
    if "vocab" not in cache:
        cache["vocab"] = Counter(w.lower() for w in re.findall(r"[A-Za-z]+", ctx.text or ""))
    return cache["vocab"]


def _heal(text: str, vocab: Counter) -> str:
    """Remove extraction gaps without touching any other character: "acquisi tion", "15 %", "18- month", "(“ Net".

    Only spaces are removed, so the result still matches the page once whitespace is ignored.
    """
    text = re.sub(r"(\d) +(?=%)", r"\1", text)  # "15 %"
    text = re.sub(r"(\d)- +(?=[A-Za-z])", r"\1-", text)  # "18- month"
    text = re.sub(r"(\d) +-(?=[A-Za-z])", r"\1-", text)  # "364 -Day"
    text = re.sub(r"([A-Za-z])- +(?!(?:and|or|to)\b)(?=[a-z])", r"\1-", text)  # "non- recurring"
    text = re.sub(r"“ +", "“", text)
    text = re.sub(r" +”", "”", text)
    text = re.sub(r"\( +", "(", text)
    text = re.sub(r" +\)", ")", text)

    def real(word: str) -> bool:
        return len(word) >= 2 and vocab.get(word, 0) >= 3

    words = list(re.finditer(r"[A-Za-z]+", text))
    out, pos, skip = [], 0, False
    for w1, w2 in zip(words, words[1:]):
        if skip:  # w1 was just joined to the word before it
            skip = False
            continue
        if text[w1.end():w2.start()] != " " or text[w1.start() - 1:w1.start()] in ("’", "'", "-") or text[w2.end():w2.end() + 1] in ("’", "'", "-"):
            continue
        a, b = w1.group(0), w2.group(0)
        joined = (a + b).lower()
        if len(joined) < 5 or joined not in vocab or (b[0].isupper() and not a.isupper()):
            continue
        la, lb = a.lower(), b.lower()
        plural = lb == "s" and len(a) >= 4  # "Agreement s"
        if plural or (not (real(la) and real(lb)) and (vocab.get(la, 0) <= vocab[joined] or vocab.get(lb, 0) <= vocab[joined])):
            out.append(text[pos:w1.end()])
            pos = w2.start()
            skip = True
    out.append(text[pos:])
    return "".join(out)


def _fmt_ratio(num: str) -> str:
    """ "3.5" -> "3.50x"."""
    try:
        return f"{float(num):.2f}x"
    except ValueError:
        return f"{num}x"


def _money(text: str) -> str:
    """Amounts in house style ($500,000,000 -> $500m). A bare small figure ("$325" on a slide whose amounts are in
    millions) is left as printed: its unit is not in the text, and read as dollars it would print as "$0k"."""
    def sub(m: re.Match) -> str:
        mm = money_mm(m)
        if mm is None or mm <= 0 or (not m.group("unit") and mm < 0.01):
            return m.group(0)
        return restyle_money(m.group(0))
    return MONEY_RE.sub(sub, text)


def _house(text: str) -> str:
    """House style for a passage kept in the term sheet's words: 3.50 to 1.00 -> 3.50x, $500,000,000 -> $500m."""
    text = _RATIO_LEVEL_RE.sub(lambda m: ("[" if m.group("open") else "") + _fmt_ratio(m.group("num")) + ("]" if m.group("open") else ""), text)
    text = _money(text)
    text = re.sub(r"[“”\"]", "", text)
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    return tidy(text)


def _clause(text: str) -> str:
    """A clause of the term sheet tidied for a line: defined-term brackets and "provided that" dropped, house-style figures."""
    text = _DEFINED_PAREN_RE.sub("", text)
    text = _WHICH_PAREN_RE.sub("", text)
    text = _LEAD_IN_RE.sub("", text, count=1)
    text = _BULLET_START_RE.sub("", text.strip())
    text = re.sub(r"[\s,;]+(?:and|or)$", "", _house(text).strip(" ,;:."), flags=re.IGNORECASE)
    if text.startswith("(") and text.endswith(")") and "(" not in text[1:-1] and ")" not in text[1:-1]:
        text = text[1:-1].strip()  # a clause that was a bracketed aside
    return text


def _lower_first(text: str) -> str:
    """Lower-case the first word when it is an ordinary one ("Following ...", "Upon ..."), never a defined term."""
    word = re.match(r"[A-Za-z]+", text)
    if word and word.group(0).lower() in _LOWER_FIRST and not word.group(0).isupper():
        return text[0].lower() + text[1:]
    return text


def _upper_first(text: str) -> str:
    """Capitalise the first letter for the start of a line."""
    return text[:1].upper() + text[1:] if text[:1].islower() else text


def _split_long(text: str, limit: int = LINE, slack: int = 40) -> list[str]:
    """Cut a long clause into pieces of about ``limit`` characters at commas / semicolons / "and" (nothing is dropped).
    A remainder that is over the limit by no more than ``slack`` is left whole rather than cut into a stub."""
    text = tidy(text)
    out = []
    while len(text) > limit + (slack if out else 0):
        depth, best, fallback = 0, -1, -1
        for i, ch in enumerate(text[:limit]):
            if ch == "(":
                if depth == 0 and i and text[i - 1] == " ":
                    fallback = max(fallback, i - 1)
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and ch in ";," and text[i + 1:i + 2] == " ":
                best = i
            elif depth == 0 and text.startswith(" and ", i):
                fallback = max(fallback, i)
        cut = best if best >= limit // 3 else fallback if fallback >= limit // 5 else text.rfind(" ", 0, limit)
        if cut <= 0:
            break
        out.append(text[:cut + 1].rstrip(" ,;"))
        text = text[cut + 1:].strip()
    if text:
        out.append(text)
    return out


def _first_lines(text: str, limit: int, count: int) -> list[str]:
    """The first ``count`` pieces of a long clause; a cut is always shown by a closing ellipsis, never silent."""
    pieces = _split_long(text, limit)
    if len(pieces) > count:
        pieces = pieces[:count]
        pieces[-1] += " …"
    return pieces


def _pack(pieces: list[str], limit: int = LINE, sep: str = "; ") -> list[str]:
    """Join pieces into as few lines as possible without passing ``limit``."""
    lines: list[str] = []
    for piece in pieces:
        if lines and len(lines[-1]) + len(sep) + len(piece) <= limit:
            lines[-1] += sep + piece
        else:
            lines.append(piece)
    return lines


def _figure_chunks(text: str, limit: int = LINE) -> list[str]:
    """A long clause reduced to its comma-separated parts that carry a figure, packed into lines."""
    if len(text) <= limit + 50:
        return [text]
    chunks = [c.strip() for c in re.split(r",\s+(?![^()]*\))", text) if c.strip()]
    keep = [c for c in chunks if re.search(r"\d", c)] or chunks
    if keep[-1] is not chunks[-1]:  # what follows the last figure is left out: shown, never silent
        keep[-1] += " …"
    lines: list[str] = []
    for piece in _pack(keep, limit, ", "):
        lines.extend([piece] if len(piece) <= limit + 50 else _split_long(piece, limit))
    return lines


def _names(items: list[str]) -> str:
    """ "the X Ratio and the Y Ratio" / "Minimum Liquidity and Net Leverage" for a sentence."""
    items = [("the " if re.search(r"(?i)ratio$", i) and not re.match(r"(?i)(?:the|minimum|maximum)\s", i) else "") + i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---------------------------------------------------------------------------------------------------
# the section
# ---------------------------------------------------------------------------------------------------

@dataclass
class _Sec:
    """The financial covenant passage: where quotes are cut from, and the text that is parsed."""

    block: Block
    text: str = ""  # block text with hard line breaks kept and extraction gaps healed
    label: str = "Financial Covenants"
    same_as_existing: bool = False  # amendment slide: the proposed cell reads "Same as existing"
    pointer: Block | None = None  # that proposed cell, for the quote
    existing: str = ""  # the existing cell (read like ``text``), when the proposed cell differs from it
    twin: Block | None = None  # that existing cell, for a quote when the proposed cell is too short to quote
    embedded: bool = False  # found inside a wider "Covenants" block
    lead: str = ""  # words of the wider block that introduce the covenants (open / closed list, by reference)
    foot: Block | None = None  # footnote lines under a slide table cell
    runs_on: bool = False  # running text follows the block: the block finder may have stopped before the section's end
    _marks: tuple | None = field(default=None, repr=False)

    def span(self, a: int, b: int) -> re.Match | None:
        """The match object on ``block.text`` for ``text[a:b]`` (the two differ only in whitespace)."""
        if self._marks is None:
            btext = self.block.text
            self._marks = ([i for i, ch in enumerate(btext) if not ch.isspace()], [0])
            count = 0
            for ch in self.text:
                count += not ch.isspace()
                self._marks[1].append(count)
        bpos, seen = self._marks
        a, b = max(0, min(a, len(self.text))), max(0, min(b, len(self.text)))
        while a < b and self.text[a].isspace():
            a += 1
        first, last = seen[a], seen[b] - 1
        if not (0 <= first <= last < len(bpos)):
            return None
        piece = self.block.text[bpos[first]:bpos[last] + 1]
        return re.compile(re.escape(piece)).match(self.block.text, bpos[first])


def _flow(block: Block) -> str:
    """Block text with the line breaks that separate statements kept as newlines (bullets, headings, paragraphs)."""
    out: list[str] = []
    prev_line, prev, prev_bullet, prev_row = None, "", False, False
    rows = [_is_table_row(part or "") for part in block.parts]
    for i, (ln, part) in enumerate(zip(block.lines, block.parts)):
        text = tidy(part or "")
        if not text:
            continue
        bullet = bool(_BULLET_START_RE.match(text))
        # a table row ("June 30, 2026      4.25:1.00") and the column heads above it are statements of their own
        row = rows[i] or (len(fragments(part or "", 3)) > 1 and i + 1 < len(rows) and rows[i + 1])
        if prev_line is None:
            sep = ""
        else:
            gap = ln.n - prev_line.n > 1
            capital = text[0].isupper() or text[0] in "“\"("
            heading = text.endswith(":") and len(text) < 80 and (block.mode == "plain" or prev_bullet)
            label = _LINE_LABEL_RE.match(text)  # "Interest Cover: EBITDA to ..." opens a statement of its own
            heading = heading or bool(label and (block.mode == "plain" or _is_sub_label(label.group(1))))
            hard = bullet or row or prev_row or prev.endswith(":") or heading or (
                gap and (prev[-1] in ".;:" or (capital and (ln.page == prev_line.page or len(prev) < 60))))
            sep = "\n" if hard else " "
        out.append(sep + text)
        prev_line, prev, prev_bullet, prev_row = ln, text, bullet, row
    return "".join(out)


def _is_table_row(part: str) -> bool:
    """A line of a level table: two or more cells, the last of which is nothing but a level."""
    cells = fragments(part.strip(), 3)
    if len(cells) < 2 or len(part.strip()) > 110:
        return False
    last = cells[-1][2].strip()
    return bool(_RATIO_LEVEL_RE.fullmatch(last) or _PCT_LEVEL_RE.fullmatch(last) or _BLANK_LEVEL_RE.fullmatch(last) or MONEY_RE.fullmatch(last))


def _sub_block(block: Block, start: int, stop: int | None = None, first_part: str | None = None) -> Block:
    """The lines ``start:stop`` of a block as a block of their own (label line kept for the page number)."""
    lines, parts = list(block.lines[start:stop]), list(block.parts[start:stop])
    if first_part is not None and parts:
        parts[0] = first_part
    return Block(label=block.label, line=lines[0] if lines else block.line, lines=lines, parts=parts, inline=block.inline, mode=block.mode)


def _own(block: Block, label_re: re.Pattern) -> Block:
    """The block from its own label line on.

    In a slide table every row is one line, and the block finder takes the short rows above for the
    first lines of a wrapped label ("Commitment fee 0.50%" + "Financial covenants ..."). The row's own
    text starts on the line whose first cell is the label.
    """
    for i, ln in enumerate(block.lines[:4]):
        if re.match(r"\s*(?:[-–•]\s*)?" + label_re.pattern + r"(?:\s*:|\s+[-–]\s|\s{2,}|\s*$)", ln.text, re.IGNORECASE):
            # ... and it ends where the next row starts: a line back at the label column whose first cell opens with a
            # capital or a digit and has a value beside it (a wrapped label carries on in lower case: "leverage calculation")
            # Only the one or two lines the block finder may have taken for label lines are looked at.
            stop = None
            for j in range(i + 1, min(i + 3, len(block.lines))):
                nxt = block.lines[j]
                cells = fragments(nxt.text, 3)
                if block.mode != "column" or nxt.page != ln.page or not cells or abs(nxt.indent - ln.indent) > 1:
                    break
                if (cells[0][2][0].isupper() or cells[0][2][0].isdigit()) and (len(cells) > 1 or cells[0][2].rstrip().endswith(":")):
                    stop = j
                    break
            return block if i == 0 and stop is None else _sub_block(block, i, stop)
    return block


def _cut_overrun(block: Block) -> Block:
    """Drop the tail of a block that ran on into the next labelled rows: after a page break ("- Affirmative Covenants :"),
    or on a page read without columns whose rows are indented (the block finder ends such a block only at a label
    that starts in the first column)."""
    if block.mode not in ("column", "plain") or not block.lines:
        return block
    indent = block.lines[0].indent
    seen_value = False
    for i, (ln, part) in enumerate(zip(block.lines, block.parts)):
        if i and seen_value and ln.indent <= indent + 2 and _NEW_LABEL_RE.match(ln.text) and not _FC_LABEL_RE.search(ln.text[:60]):
            label = _LINE_LABEL_RE.match(ln.text)
            if not (label and _is_sub_label(label.group(1))):  # "Interest Coverage Ratio:" under the heading is part of the section
                return _sub_block(block, 0, i)
        seen_value = seen_value or bool(tidy(part or ""))
    return block


def _runs_on(ctx: Ctx, block: Block) -> bool:
    """True when the line after a labelled block is running text rather than the next label or heading.

    The block finder follows the layout; where it loses it (a page extracted without columns, an unusual
    indent) the block ends mid-section. Rows that would say "none" must then not be concluded.
    """
    if block.mode not in ("column", "plain") or not block.lines:
        return False
    lines = ctx.doc.lines
    last = block.lines[-1]
    n = last.n + 1
    while n < len(lines) and (lines[n].blank or is_footer(lines[n].text)):
        n += 1
    if n >= len(lines) or lines[n].page > last.page + 1:
        return False
    text = lines[n].text
    cells = fragments(text, 3)
    if not cells or _NEW_LABEL_RE.match(text) or _SIBLING_LABEL_RE.match(text.strip()):
        return False
    first = cells[0][2]
    if len(cells) > 1 and len(first.split()) <= 6 and (first[0].isupper() or first[0].isdigit()):
        return False  # a label with its value beside it
    return first[0].islower() or len(first) >= 60 or bool(re.match(r"\(\w{1,4}\)\s", first))


def _stitch_plain(ctx: Ctx, block: Block) -> Block:
    """On a page read without layout every "Xxx:" line ends a block. Take back the lines that follow when their
    label is itself a covenant name or a part of the covenant section ("Interest Cover: ...", "Related Definitions: ...")."""
    if block.mode != "plain" or not block.lines:
        return block
    lines, parts = list(block.lines), list(block.parts)
    doc_lines = ctx.doc.lines
    n = lines[-1].n + 1
    while n < len(doc_lines) and doc_lines[n].page == lines[-1].page and len(lines) < 200:
        ln = doc_lines[n]
        label = _LINE_LABEL_RE.match(ln.text)
        stripped = ln.text.strip()
        # (a period heading above the levels, "Thereafter:", "Prior to a Qualified IPO:", is no row of the term sheet either)
        period = stripped.endswith(":") and len(stripped) < 80 and bool(_PERIOD_WORDS_RE.search(stripped)) and bool(_PERIOD_HEAD_RE.match(stripped)) \
            and not _LIST_LEAD_IN_RE.search(stripped)
        if label and not _is_sub_label(label.group(1)) and not period:
            break  # the next row of the term sheet
        if not ln.blank and not is_footer(ln.text):
            lines.append(ln)
            parts.append(ln.text.strip())
        n += 1
    if len(lines) == len(block.lines):
        return block
    return Block(label=block.label, line=block.line, lines=lines, parts=parts, inline=block.inline, mode=block.mode)


def _is_sub_label(name: str) -> bool:
    """A line label that is part of the covenant section: a covenant's own name ("Interest Cover", "Minimum Liquidity")
    or one of its sub-headings ("Related Definitions", "Testing", "Equity Cure")."""
    if _SUB_LABEL_RE.fullmatch(name.strip()):
        return True
    found = _first_mention(name)
    if not found:
        return False
    return not re.sub(r"(?i)maximum|minimum|ratio|covenant|test|\W", "", name[:found.start] + name[found.end:])


def _plain_cells(ctx: Ctx, block: Block) -> tuple | None:
    """Split a table row that was extracted in reading order (existing cell, then proposed cell, then any footnotes).

    Returns (terms to read, existing cell or None, footnotes or None, the "Same as existing" line or None);
    None when the page is not an existing / proposed table; ``()`` when the two cells cannot be told apart.
    """
    if block.mode != "plain" or block.page in ctx.split_pages:
        return None
    if not any(_PLAIN_HEADER_RE.match(ln.text) for ln in ctx.doc.page_lines(block.page)):
        return None
    idx = [i for i, part in enumerate(block.parts) if tidy(part or "")]
    if not idx:
        return ()
    same = next((k for k, i in enumerate(idx) if SAME_AS_EXISTING_RE.match(tidy(block.parts[i]))), None)
    if same:  # existing cell, then "Same as existing", then at most the footnotes of the table
        rest = idx[same + 1:]
        if not rest or _FOOTNOTE_RE.match(block.parts[rest[0]]):
            foot = _sub_block(block, rest[0], rest[-1] + 1) if rest else None
            return _sub_block(block, idx[0], idx[same - 1] + 1), None, foot, _sub_block(block, idx[same], idx[same] + 1)

    def alike(a: str, b: str) -> bool:
        a, b = re.sub(r"\d+", "#", tidy(a)), re.sub(r"\d+", "#", tidy(b))
        return SequenceMatcher(None, a, b).ratio() >= 0.85

    for k in range(len(idx) // 2, 0, -1):
        rest = idx[2 * k:]
        if rest and not _FOOTNOTE_RE.match(block.parts[rest[0]]):
            continue
        if all(alike(block.parts[idx[i]], block.parts[idx[k + i]]) for i in range(k)):
            existing = _sub_block(block, idx[0], idx[k - 1] + 1)
            proposed = _sub_block(block, idx[k], idx[2 * k - 1] + 1)
            foot = _sub_block(block, rest[0], rest[-1] + 1) if rest else None
            return proposed, existing, foot, None
    return ()


def _resolve(ctx: Ctx, block: Block, label: str) -> _Sec | None | bool:
    """The section for a labelled block: the proposed terms on an amendment slide, the block itself otherwise.

    Returns False when existing and proposed terms cannot be told apart, None when the row is empty.
    """
    label_re = re.compile(label, re.IGNORECASE)
    vocab = _vocab(ctx)
    shown = tidy(label_re.search(block.label).group(0)) if label_re.search(block.label or "") else tidy(block.label or "")
    sec = _Sec(block=block, label=shown)
    if block.page in ctx.split_pages:
        own = _own(block, label_re)
        twin = next((b for b in find_blocks(ctx.existing, label) if any(ln.n == own.line.n for ln in b.lines)), None)
        twin = _own(twin, label_re) if twin is not None else None
        if SAME_AS_EXISTING_RE.match(own.text or ""):
            if twin is None or not twin.text:
                return None
            sec.block, sec.same_as_existing, sec.pointer = twin, True, own
        elif not own.text:
            return False if twin is not None and twin.text else None
        else:
            sec.block = own
            sec.existing = _heal(_flow(twin), vocab) if twin is not None else ""
            sec.twin = twin
    else:
        cells = _plain_cells(ctx, block)
        if cells == ():
            return False
        if cells:
            terms, existing, foot, pointer = cells
            sec.block, sec.foot, sec.same_as_existing, sec.pointer = terms, foot, pointer is not None, pointer
            sec.existing = _heal(_flow(existing), vocab) if existing is not None else ""
        else:
            if any(len(cells) > 1 and any(SAME_AS_EXISTING_RE.match(c[2]) for c in cells[1:])
                   for cells in (fragments(part or "", 3) for part in block.parts)):
                return False  # an existing / proposed table whose columns were not separated: "... 3.00x      Same as existing"
            sec.block = _stitch_plain(ctx, _cut_overrun(_own(block, label_re)))
            sec.runs_on = _runs_on(ctx, sec.block)
    if not sec.block.text:
        return None
    sec.text = _heal(_flow(sec.block), vocab)
    return sec


def _embedded(ctx: Ctx) -> _Sec | None:
    """Financial covenants described inside a wider Covenants block: "..., including, with respect to the financial covenants: ..."."""
    for block in ctx.all(_COV_LABEL):
        if _FC_LABEL_RE.search(block.label or ""):
            continue
        block = _stitch_plain(ctx, block)
        m = _EMBEDDED_RE.search(block.text)
        if not m:  # a run-in heading at the start of a paragraph of the block: "Financial Covenants. A maximum ..."
            m = next((h for st, part in zip(block._starts or [], block.parts) if tidy(part or "")
                      for h in [_EMBEDDED_HEAD_RE.match(block.text, st)] if h), None)
        if not m:
            continue
        i = block.line_at(m.end() - 1)
        starts = block._starts or []
        offset = m.end() - (starts[i] if i < len(starts) else 0)
        first = tidy(block.parts[i] or "")[max(0, offset):]
        # keep the paragraphs that carry on the list of financial covenants; stop at the next sub-heading
        stop = len(block.lines)
        seen_text = bool(first.strip())
        for j in range(i + 1, len(block.lines)):
            if _SIBLING_LABEL_RE.match(tidy(block.parts[j] or "")):
                stop = j
                break
            new_para = block.lines[j].n - block.lines[j - 1].n > 1
            if new_para and seen_text:
                head = " ".join(tidy(p or "") for p in block.parts[j:j + 3])[:160]
                if not (_first_mention(head[:90]) or _MAINTAIN_RE.search(head) or _SUB_LABEL_START_RE.match(head)):
                    stop = j
                    break
            seen_text = seen_text or bool(tidy(block.parts[j] or ""))
        sub = _sub_block(block, i, stop, first_part=first)
        if not sub.text:
            continue
        return _Sec(block=sub, text=_heal(_flow(sub), _vocab(ctx)), label="financial covenants", embedded=True, lead=block.text[:m.end()],
                    runs_on=stop == len(block.lines) and _runs_on(ctx, block))
    return None


# ---------------------------------------------------------------------------------------------------
# reading the section
# ---------------------------------------------------------------------------------------------------

@dataclass
class _Mention:
    start: int
    end: int
    kind: str  # "lev" | "int" | "other"
    sub: str  # lev: total / cap / secured; other: fccr, liquidity ...
    name: str
    a: str = ""  # components of "ratio of A to B"
    b: str = ""


@dataclass
class _Level:
    start: int
    end: int
    typ: str  # "ratio" | "pct" | "money"
    shown: str


@dataclass
class _Tier:
    op: str
    level: str
    cond: str = ""
    pos: int = 0
    assumed: bool = False  # no operator printed
    span: tuple = (0, 0)  # the statement the level was read from
    verbatim: bool = False  # ``level`` is the statement as worded: it could not safely be read as "<operator> <level>"


@dataclass
class _Cov:
    kind: str
    sub: str
    start: int
    end: int = 0
    mentions: list = field(default_factory=list)
    tiers: list = field(default_factory=list)
    extras: list = field(default_factory=list)  # (start, end, proviso) spans of follow-on clauses
    name: str = ""
    lower_name: bool = False  # the term sheet writes the name in lower case
    a: str = ""
    b: str = ""
    def_ref: str = ""
    def_span: tuple = ()  # the bracket after the name that ``def_ref`` was read from
    first_level: int = -1
    truncated: bool = False  # follow-on clauses that did not fit in the row
    unmatched: bool = False  # amendment table: no counterpart found in the existing cell
    table: bool = False  # levels read from a table with one column per covenant
    words: set = field(default_factory=set)  # the distinguishing words of its name(s): {"net", "leverage"}
    scope: str = ""  # where or when it applies, as its statement opens: "with respect to the Revolving Facility only"
    alts: list = field(default_factory=list)  # [start, end] of clauses that give an optional / alternative test, kept as worded
    alt_names: list = field(default_factory=list)  # the mentions that name those tests
    alt_choice: list = field(default_factory=list)  # ... and whether each is an alternative to this covenant ("or ...")
    proviso_names: list = field(default_factory=list)  # tests of another kind named, with a level, only in this covenant's provisos
    worded_from: int | None = None  # the covenant itself is kept as worded from here (an option opens it, or it follows a proviso)
    follows: "_Cov | None" = None  # ... the covenant whose proviso it is worded after

    @property
    def in_sentence(self) -> str:
        """The name as it reads inside a sentence."""
        return self.name[:1].lower() + self.name[1:] if self.lower_name else self.name


def _lev_sub(text: str, denominator: str = "") -> str:
    """The sort of leverage test a name stands for: "cap" (debt to capitalisation), "secured" or "total"."""
    if _CAP_WORDS_RE.search(denominator or text):
        return "cap"
    return "secured" if _SECURED_WORDS_RE.search(text) else "total"


def _component_kind(a: str, b: str) -> tuple[str, str] | None:
    """(kind, sub-kind) of a ratio given as "ratio of A to B", from what stands on each side; None if it is not a covenant ratio."""
    if re.search(r"fixed\s+charges?", b, re.IGNORECASE):
        return "other", "fccr"
    if re.search(r"debt\s+service", b, re.IGNORECASE):
        return "other", "dscr"
    if re.search(r"interest|finance\s+(?:charges?|costs?)", b, re.IGNORECASE):
        # interest plus rent, scheduled principal, dividends ...: a fixed-charge type of cover, not an interest cover
        return ("other", "fccr") if _CHARGE_SUM_RE.search(_INTEREST_PART_RE.sub("interest", b)) else ("int", "")
    if re.search(r"debt|indebtedness|borrowings|liabilities", a, re.IGNORECASE) and re.search(
            r"EBITDA|capital|worth|equity|assets|value|cash\s+flow", b, re.IGNORECASE):
        return "lev", _lev_sub(a, b)
    return None


def _mentions(text: str) -> list[_Mention]:
    """Every covenant name in the text, in order, without overlaps (the longer / earlier match wins)."""
    found: list[_Mention] = []
    for m in _RATIO_OF_RE.finditer(text):
        body = m.group("body")
        if re.match(r"\((?:i|a|x|1)\)\s", body):
            parts = re.split(r"\s+to\s+\((?:ii|b|y|2)\)\s+", body, maxsplit=1)
        else:
            parts = re.split(r"\s+to\s+(?!exceed)", body, maxsplit=1)
        if len(parts) != 2:
            continue
        kind = _component_kind(parts[0], parts[1])
        if kind:
            found.append(_Mention(m.start("body"), m.end("body"), kind[0], kind[1], "", _component(parts[0]), _component(parts[1])))
    for m in _LEV_NAME_RE.finditer(text):
        a, b = _sides(m.group(0))
        found.append(_Mention(m.start(), m.end(), "lev", _lev_sub(m.group(0)), m.group(0), a, b))
    for m in _INT_NAME_RE.finditer(text):
        a, b = _sides(m.group(0))
        found.append(_Mention(m.start(), m.end(), "int", "", m.group(0), a, b))
    for sub, rx, _, _ in _OTHER_NAME_RES:
        for m in rx.finditer(text):
            found.append(_Mention(m.start(), m.end(), "other", sub, m.group(0)))
    found.sort(key=lambda x: (x.start, -(x.end - x.start)))
    out: list[_Mention] = []
    for item in found:
        if out and item.start < out[-1].end:
            continue
        out.append(item)
    return out


def _sides(name: str) -> tuple[str, str]:
    """The two sides of a ratio that is named by its components: "Total Net Debt to EBITDA", "Consolidated Debt / Capitalization"."""
    parts = re.split(r"\s*/\s*|\s*-?\bto\b-?\s*", tidy(name), maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return "", ""
    return _component(parts[0]), _component(re.sub(r"\s+ratio$", "", parts[1], flags=re.IGNORECASE))


def _first_mention(text: str) -> _Mention | None:
    """The first covenant name in a short piece of text, if any."""
    found = _mentions(text)
    return found[0] if found else None


def _component(text: str) -> str:
    """One side of "ratio of A to B" in a few words: enumerator and time phrases removed."""
    text = re.sub(r"^\s*\(\w{1,3}\)\s*", "", tidy(text))
    text = _DEFINED_PAREN_RE.sub("", text)
    text = re.sub(r"\s*\(\s*(?:to\s+be\s+|as\s+)?defined\b[^()]*\)", "", text, flags=re.IGNORECASE)  # "(as defined in the Existing Credit Agreement)"
    prev = None
    while prev != text:
        prev = text
        text = _COMPONENT_TIME_RE.sub("", text)
    text = re.sub(r"^the\s+", "", text.strip(" ,;"), flags=re.IGNORECASE)
    return _house(text)


def _levels(text: str) -> list[_Level]:
    """Every ratio, percentage, blank and amount in the text, in order, each shown in house style."""
    out: list[_Level] = []
    for m in _RATIO_LEVEL_RE.finditer(text):
        shown = _fmt_ratio(m.group("num"))
        out.append(_Level(m.start(), m.end(), "ratio", f"[{shown}] (in brackets in term sheet)" if m.group("open") else shown))
    for m in _PCT_LEVEL_RE.finditer(text):
        shown = m.group("num") + "%"
        out.append(_Level(m.start(), m.end(), "pct", f"[{shown}] (in brackets in term sheet)" if m.group("open") else shown))
    for m in _BLANK_LEVEL_RE.finditer(text):
        out.append(_Level(m.start(), m.end(), "pct" if m.group(0).rstrip().endswith("%") else "ratio", "[ ] - left blank in term sheet"))
    for m in MONEY_RE.finditer(text):
        shown = _money(m.group(0))
        if re.search(r"\d", shown):
            # "C$100 million", "HK$1 billion": the letters before the dollar sign are part of the currency
            pre = re.search(r"(?<![A-Za-z])[A-Z]{1,3}$", text[max(0, m.start() - 4):m.start()]) if m.group("cur") == "$" else None
            out.append(_Level(m.start() - (len(pre.group(0)) if pre else 0), m.end(), "money", (pre.group(0) if pre else "") + shown.strip()))
    for m in _FX_MONEY_RE.finditer(text):
        mm = money_mm(m)
        if mm is not None and mm > 0 and (m.group("unit") or mm >= 0.01):
            out.append(_Level(m.start(), m.end(), "money", fmt_money(mm, m.group("cur").upper().replace("RMB", "CNY") + " ")))
    for m in _BLANK_MONEY_RE.finditer(text):
        out.append(_Level(m.start(), m.end(), "money", "[ ] - left blank in term sheet"))
    out.sort(key=lambda x: x.start)
    return out


def _allowed(cov: _Cov | _Mention) -> tuple[str, ...]:
    """The kinds of level a covenant takes: a ratio for leverage and cover tests, an amount for liquidity, ..."""
    if cov.kind == "lev":
        return ("ratio", "pct") if cov.sub == "cap" else ("ratio",)
    if cov.kind == "int":
        return ("ratio", "pct")  # "Interest Cover: not less than 200%"
    return next((types for sub, _, types, _ in _OTHER_NAME_RES if sub == cov.sub), ("ratio",))


def _default_op(cov: _Cov) -> str:
    """The sense of a level printed without an operator: a ceiling for leverage-type tests, a floor for cover and liquidity."""
    if cov.kind == "lev":
        return "<="
    if cov.kind == "int":
        return ">="
    return next((op for sub, _, _, op in _OTHER_NAME_RES if sub == cov.sub), ">=")


def _statements(text: str) -> list[tuple[int, int]]:
    """Spans of the statements of the text (sentences, bullets, slide cells)."""
    spans, pos = [], 0
    for m in _HARD_BREAK_RE.finditer(text):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    return spans


def _brackets(text: str, a: int, b: int) -> list[tuple[int, int]]:
    """Spans of the outermost round brackets in ``text[a:b]`` (a bracket left open runs to ``b``)."""
    out, depth, start = [], 0, a
    for i in range(a, min(b, len(text))):
        ch = text[i]
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
            if depth == 0:
                out.append((start, i + 1))
    if depth:
        out.append((start, b))
    return out


def _def_wording(text: str, a: int, b: int) -> tuple[re.Match | None, list[tuple[int, int]]]:
    """Definition wording in the statement ``text[a:b]``: (the first that stands in the sentence itself, the brackets that
    hold one). "EBITDAR (to be defined as set forth in the Existing Credit Agreement)" is an aside: the bracket is a
    definition, the sentence around it is not."""
    spans = _brackets(text, a, b)
    top, held = None, []
    for m in _DEF_SENTENCE_RE.finditer(text, a, b):
        span = next((s for s in spans if s[0] <= m.start() < s[1]), None)
        if span is None:
            top = top or m
        elif span not in held:
            held.append(span)
    for span in spans:  # "(to be defined in the Financing Documentation as ...)", "(as defined in the Existing Credit Agreement)"
        if span not in held and re.match(r"\(\s*(?:to\s+be\s+|as\s+)?defined\b", text[span[0]:span[1]], re.IGNORECASE):
            held.append(span)
    return top, sorted(held)


def _def_aside(text: str, pos: int, limit: int = 600) -> tuple[str, int, int] | None:
    """The bracket that opens right after ``pos`` when it says how the term before it is defined: "(to be defined in the
    Financing Documentation as (i) total indebtedness minus (ii) cash ... divided by EBITDA)". Returns (its words, start, end)."""
    lead = re.match(r"\s*\(", text[pos:pos + 4])
    if not lead:
        return None
    start = pos + lead.end() - 1
    span = next((s for s in _brackets(text, start, min(len(text), start + limit)) if s[0] == start), None)
    if span is None or text[span[1] - 1] != ")":
        return None
    inner = text[start + 1:span[1] - 1]
    if not re.match(r"\s*(?:to\s+be\s+|as\s+)?defined\b", inner, re.IGNORECASE) or len(tidy(inner)) < 12:
        return None
    return tidy(inner), start, span[1]


def _provisos(text: str, a: int, b: int) -> list[tuple[int, int]]:
    """Spans of the provisos inside the statement ``text[a:b]``."""
    cuts = [m.start() for m in _PROVISO_RE.finditer(text, a, b) if m.group(0).strip()]
    return [(cut, cuts[i + 1] if i + 1 < len(cuts) else b) for i, cut in enumerate(cuts)]


def _breaks_before(rx: re.Pattern, text: str, floor: int, pos: int) -> list[int]:
    """End positions of the matches of a sentence-break pattern that lie between ``floor`` and ``pos``."""
    out = []
    for m in rx.finditer(text, floor):
        if m.end() > pos:
            break
        out.append(m.end())
    return out


def _item_start(text: str, pos: int, floor: int) -> int:
    """Where the statement of a covenant first named at ``pos`` begins, looking back no further than ``floor``."""
    window = text[floor:pos]
    hard = _breaks_before(_HARD_BREAK_RE, text, floor, pos)  # searched on the whole text: the pattern looks ahead
    if hard:
        return hard[-1]
    for rx in _SOFT_BREAKS:
        m = rx.search(window)
        if m:
            return floor + m.end()
    return floor


def _operator(text: str, a: int, b: int, frame: bool, figures: list[int] | None = None) -> str | None:
    """The comparison stated in ``text[a:b]`` (the words leading up to a level that starts at ``b``); the last one wins.

    ``figures`` are the start offsets of every figure in the text: an operator directly followed by another figure
    speaks of that figure ("minus cash not to exceed $200,000,000 ... of not more than 4.00 to 1.00") and is passed over.
    ``frame`` says the sentence is a prohibition ("shall not permit X to exceed"); a "not" a few words before a bare
    comparison does the same ("shall not at any time be less than").
    """
    found, prev_end = None, a
    for m in _OP_RE.finditer(text, a, b):
        if figures and any(m.end() <= f < b and f - m.end() <= _OP_REACH for f in figures):
            prev_end = m.end()
            continue
        if m.group(0).lower() in _LOOSE_OPS and text[m.end():b].strip(" :,"):
            continue
        if found is not None:
            prev_end = found.end()
        found = m
    if found is None:
        return None
    group = found.lastgroup
    if group == "le":
        return "<="
    if group == "ge":
        return ">="
    if found.group(0) in ("<", ">"):  # a symbol says what it says
        return found.group(0)
    # the words between the previous operator / figure and this comparison: are they a negation?
    floor = max([prev_end, found.start() - 90] + [f for f in figures or [] if f < found.start()])
    negated = frame or bool(_NEAR_NOT_RE.search(text[floor:found.start()]))
    if group in ("lt_neg", "lt"):
        return ">=" if negated else "<"
    return "<=" if negated else ">"


def _against_nature(op: str, cov: "_Cov") -> bool:
    """The comparison read runs against what the test is (a leverage test that must stay above a level, a cover test
    that must stay below one): the wording was not a covenant level, or the rules misread it."""
    return bool(op) and op[0] != _default_op(cov)[0]


def _clean_cond(text: str) -> str:
    """The condition of a tier as it is printed after the level: enumerator, defined-term bracket and joining words removed."""
    text = _DEFINED_PAREN_RE.sub("", text)
    text = _ENUM_RE.sub(" ", text)
    text = _DEFINED_PAREN_RE.sub("", text)  # a bracket that held an enumerator: "(this clause (2), the “Covenant Adjustment”)"
    text = tidy(text).strip(" ,;:.")
    text = re.sub(r"^(?:and|or|then)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\s,;]+(?:and|or)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^on\s+the\s+last\s+day\s+of\s+(?:each\s+of\s+)?", "for ", text, flags=re.IGNORECASE)
    return _house(text).strip(" ,;:.")


def _headers(text: str, levels: list[_Level]) -> list[tuple[int, str]]:
    """Period headings of a slide cell: short lines ending in a colon that carry no level."""
    found, pos = [], 0
    for line in text.split("\n"):
        end = pos + len(line)
        stripped = line.strip()
        if stripped.endswith(":") and len(stripped) < 80 and _PERIOD_WORDS_RE.search(stripped) and not _LIST_LEAD_IN_RE.search(stripped) \
                and not _first_mention(stripped) and not any(pos <= lv.start < end and lv.typ != "money" for lv in levels):
            found.append((pos, stripped.rstrip(": "), bool(_PERIOD_HEAD_RE.match(stripped) or _EACH_PERIOD_RE.match(stripped))))
        pos = end + 1
    # A line that opens with its period ("From ... until ...:", "Each fiscal quarter in 2026:", "Thereafter:") is a heading.
    # One that does not ("Covenants applicable following the Closing Date:", "Two tests, set for the first year:") is a
    # heading only where the section is laid out as a schedule: there are several such lines, or levels stand above it.
    # Alone at the top of the list it introduces the list, and is no condition of the levels under it.
    return [(p, h) for p, h, opens in found if opens or len(found) > 1 or any(lv.start < p for lv in levels)]


def _read(text: str) -> tuple[list[_Cov], bool, list[tuple[int, int]], list[tuple[str, int, int]]]:
    """The reading of a section: its covenants; whether its wording was too tangled to attribute levels safely; the spans
    of tests the rules cannot classify; and the clauses (kind, start, end) that name a ratio only as a condition."""
    mentions, levels = _mentions(text), _levels(text)
    statements = _statements(text)
    provisos = [p for a, b in statements for p in _provisos(text, a, b)]

    def sets_level(a: int, b: int) -> bool:
        """A covenant name followed by a level of its kind: the passage sets a covenant, whatever else it says."""
        return any(a <= m.start < b and any(m.end <= lv.start < min(b, m.end + 200) and lv.typ in _allowed(m) for lv in levels) for m in mentions)

    # Definition and cure sentences are read by select_definitions; their figures are not covenant levels. A sentence
    # that sets a covenant and mentions a definition or a cure in passing ("... of 4.50x (subject to equity cure rights)")
    # stays a covenant sentence; only its cure wording is set aside.
    # A definition in brackets after a term ("EBITDAR (to be defined as set forth in ...)") is an aside: only the bracket
    # is set aside, never the sentence, which may be the covenant itself however far its level stands from its name.
    def leads_level(a: int, b: int, top: re.Match) -> bool:
        """The statement opens with a covenant's name, says how it is defined, and closes on a level of the covenant's kind:
        "Maximum Total Leverage Ratio, which shall be defined as the ratio of ... [however long], of 4.00 to 1.00". It is a
        covenant sentence with a definition in it, not a definition."""
        m = next((m for m in mentions if a <= m.start < b), None)
        if m is None or not m.name or m.end > top.start() or not _ITEM_HEAD_RE.fullmatch(_BULLET_START_RE.sub("", text[a:m.start].lstrip())):
            return False
        end = min([b] + [x for x, _ in _provisos(text, a, b)])
        mine = [lv for lv in levels if top.end() <= lv.start < end and lv.typ in _allowed(m)]
        return bool(mine) and end - mine[-1].end <= 120

    def next_item(pos: int, b: int) -> int:
        """Where the next item of a list of covenants opens after ``pos`` in a statement that ends at ``b``: a break ("; and
        (b) a minimum ", ", and ") followed at once by a covenant's name that has a level of its own. ``b`` when there is none."""
        for q in _LIST_BREAK_RE.finditer(text, pos, b):
            m = next((m for m in mentions if q.end() <= m.start < b and m.name and _ITEM_HEAD_RE.fullmatch(text[q.end():m.start])), None)
            if m is not None and any(m.end <= lv.start < min(b, m.end + 200) and lv.typ in _allowed(m) for lv in levels):
                return q.start()
        return b

    definitions: list[tuple[int, int]] = []
    for a, b in statements:
        cure = _EQUITY_CURE_RE.search(text, a, b) or _DEEMED_CURE_RE.search(text, a, b)
        if cure:
            # (the cure wording ends where the list goes on to its next covenant: "..., provided that an equity cure may be
            # exercised twice, and Interest Coverage Ratio not to be less than 3.00x")
            definitions.append((cure.start(), next_item(cure.end(), b)) if sets_level(a, cure.start()) else (a, b))
            continue
        top, held = _def_wording(text, a, b)
        if top is not None and not sets_level(a, b) and not leads_level(a, b, top):
            definitions.append((a, b))
        else:
            definitions.extend(held)
    headers = _headers(text, levels)

    # A ratio spelled out by its components is the covenant named beside it, whatever the components look like: "Minimum
    # Fixed Charge Coverage Ratio: ... the ratio of EBITDAR to the sum of interest and rent ...", "the ratio of A to B (the
    # “Leverage Ratio”)". The name says what kind of test it is.
    for i, c in enumerate(mentions):
        if c.name:
            continue
        s_start, s_end = next(((a, b) for a, b in statements if a <= c.start < b), (0, len(text)))
        nxt = mentions[i + 1] if i + 1 < len(mentions) else None
        prv = mentions[i - 1] if i else None
        if nxt is not None and nxt.name and nxt.start < s_end and _NAMED_AFTER_RE.fullmatch(text[c.end:nxt.start]):
            c.kind, c.sub = nxt.kind, nxt.sub
        elif prv is not None and prv.name and prv.start >= s_start and "ratio" in _allowed(prv) \
                and not any(prv.end <= lv.start < c.start for lv in levels):
            # ... however many words lead from the name to the ratio ("X Ratio: As of the last day of ..., Holdings and its
            # Restricted Subsidiaries shall not permit the ratio of ..."), unless they bring the ratio in as one more item of
            # a list ("a maximum X Ratio and a minimum ratio of ...", "X Ratio; ratio of ...")
            gap = _RATIO_LEAD_RE.sub("", text[prv.end:c.start])
            if ";" not in gap and not _ITEM_JOINED_RE.search(gap):
                c.kind, c.sub = prv.kind, prv.sub

    def inside(pos: int, spans: list[tuple[int, int]]) -> bool:
        return any(a <= pos < b for a, b in spans)

    figures = [lv.start for lv in levels]
    covs: list[_Cov] = []
    by_key: dict[tuple[str, str], list[_Cov]] = {}  # the covenants of each kind, in order
    conditions: list[tuple[str, int, int]] = []  # (kind, start, end) of clauses that name a ratio only as a condition

    def has_level(cov: _Cov, upto: int) -> bool:
        """The covenant has been given a level of its kind before ``upto``."""
        ok = _allowed(cov)
        return any(cov.mentions[0].end <= lv.start < upto and lv.typ in ok and not inside(lv.start, definitions)
                   and not any(a <= lv.start < b for _, a, b in conditions) for lv in levels)

    def choice_lead(prev: _Cov) -> bool:
        """The words that introduce the covenant ``prev`` make it one of a choice: "either" / "one of" before its name, in its
        own statement or in the lead-in line above it ("The Company must satisfy one of the following tests:")."""
        first = prev.mentions[0].start
        i = next((k for k, (a, b) in enumerate(statements) if a <= first < b), None)
        if i is None:
            return False
        start = statements[i][0]
        if i and text[statements[i - 1][0]:statements[i - 1][1]].rstrip().endswith(":"):
            start = statements[i - 1][0]
        return bool(_CHOICE_RE.search(text, start, first))

    def owner(m: _Mention, create: bool) -> _Cov | None:
        """The covenant a mention speaks of. Two tests of one kind under different names ("Net Leverage Ratio ... Gross
        Leverage Ratio", "Minimum Liquidity ... minimum unrestricted cash") are two covenants; a shorter name ("the Leverage
        Ratio" for "Consolidated Leverage Ratio") or a ratio given by its components is the covenant already open."""
        group = by_key.get((m.kind, m.sub), [])
        words = _name_words(m.name)
        for cov in reversed(group):
            if not m.name or not cov.words or words <= cov.words:
                cov.words |= words
                return cov
        if group and not has_level(group[-1], m.start):  # a heading and the fuller name under it: one covenant
            group[-1].words |= words
            return group[-1]
        s_start, s_end = next(((a, b) for a, b in statements if a <= m.start < b), (m.start, len(text)))
        own_level = any(m.end <= lv.start < min(s_end, m.end + 200) and lv.typ in _allowed(m) for lv in levels)
        follows = None  # the covenant whose proviso this one is worded after
        if create and covs and inside(m.start, provisos) and not group and own_level:
            # "... 4.00x; provided that ...; and Interest Coverage Ratio of not less than 3.00x": a test with a level of its own
            # after a break in the list is a covenant, but whether the proviso's case governs it is not for the rules to
            # say. It is taken as worded, and the line says where it stands.
            pa = max(a for a, b in provisos if a <= m.start < b)
            brk = next((q for q in reversed(list(_LIST_BREAK_RE.finditer(text, pa, m.start))) if _ITEM_HEAD_RE.fullmatch(text[q.end():m.start])), None)
            if brk is not None:
                follows = (covs[-1], brk.end())
        if not create or (covs and inside(m.start, provisos) and follows is None):
            if create and not group and own_level and m.name:
                covs[-1].proviso_names.append(m)  # (the row it would have had says where it is named)
            return None  # a ratio named in another covenant's proviso or definition is a condition, not a covenant
        if group and not sets_level(m.start, min(s_end, m.end + 200)):
            return group[-1]  # another name for the test already set, with no level of its own ("... Net Debt / EBITDA is calculated ...")
        if covs and not own_level and _GIVEN_UP_RE.search(text, max(s_start, m.start - 60), m.start):
            return None  # the test another one takes the place of ("..., which replaces the Fixed Charge Coverage Ratio in the Existing ...")
        if any(m.kind == x.kind and m.sub == x.sub and (words <= _name_words(x.name) or _name_words(x.name) <= words)
               for c in covs for x in c.alt_names):
            return None  # the alternative test already taken as worded, spoken of again
        floor, worded_from = 0, None
        if follows is not None:
            floor = worded_from = follows[1]
        else:
            prev = covs[-1] if covs else None
            if prev is not None:
                ok = _allowed(prev)
                floor = max([lv.end for lv in levels if prev.start <= lv.start < m.start and lv.typ in ok] + [prev.mentions[0].end])
                while floor < m.start and text[floor] in ")]":  # a level in brackets keeps its brackets: "(currently (0.7x))"
                    floor += 1
            # A test that applies only at someone's option, in place of another, or as one of "either ... or" is not one
            # more covenant: "X not to be greater than 4.25x or (2) at the Company's option, solely to the extent ..., Y not
            # to be greater than 3.50x". Its clause is kept whole, in the term sheet's words, with the covenant before it.
            if prev is not None:  # (a test already kept as worded with that covenant ends where this one's words begin)
                floor = max([floor] + [lv.end for lv in levels for x, y in prev.alts if x <= lv.start < min(y, m.start)])
            lead_from = max(floor, s_start)
            lead = text[lead_from:m.start]
            # "or" at the head of the item, outside a prohibition ("shall not permit A to exceed ... or B to be less than ..."
            # is two covenants): one of several tests of which one is to be met ("either (i) X or (ii) Y", "one of the
            # following tests: (a) X; or (b) Y"), or a test for the case named after the "or" ("X <= 4.25x (or, following a
            # Collateral Release Event, Y >= 3.00x)")
            joined = _OR_OPEN_RE.match(text, floor, m.start) if prev is not None else None
            if joined is not None and _NEG_FRAME_RE.search(text[max(_breaks_before(_FULL_STOP_RE, text, 0, m.start) + [0]):m.start]):
                joined = None
            either = joined is not None and (choice_lead(prev) or bool(_CASE_OPEN_RE.match(text, joined.end(), m.start)))
            # the option wording must be what introduces this test: it opens the item ("or (2) at the Company's option, ..."),
            # no clause ends between it and the name, and the name does not start a new item of the list after it
            # ("..., which at the Borrower's election may be tested net of cash, and an Interest Coverage Ratio ...")
            option = _OPTION_LEAD_RE.search(lead)
            opening = _ITEM_OPEN_RE.match(lead).end()
            optional = option is not None and option.start() - opening <= 40 and ";" not in lead[option.start():] \
                and not _ITEM_JOINED_RE.search(lead)
            # ... or wording that puts this test in the place of another, close before its name: "... shall be replaced by a "
            subst = next(iter(reversed(list(_SUBSTITUTE_RE.finditer(lead)))), None)
            if subst is not None and len(lead) - subst.end() <= 100 and ";" not in lead[subst.start():] and not _ITEM_JOINED_RE.search(lead):
                optional = True
            if (optional or either) and own_level:
                if prev is not None and has_level(prev, m.start):
                    prev.alts.append([lead_from, s_end])
                    prev.alt_names.append(m)
                    prev.alt_choice.append(either)
                    return None
                if optional:  # no covenant before it to stand with: the covenant itself is kept as worded
                    worded_from = lead_from + opening
        cov = _Cov(m.kind, m.sub, _item_start(text, m.start, floor), words=set(words))
        if worded_from is not None:
            cov.start, cov.worded_from, cov.follows = min(cov.start, worded_from), worded_from, follows[0] if follows else None
        for c in covs:  # a covenant that opens inside a clause kept as worded ends that clause
            for alt in c.alts:
                if alt[0] < cov.start < alt[1]:
                    alt[1] = cov.start
        covs.append(cov)
        by_key.setdefault((m.kind, m.sub), []).append(cov)
        return cov

    # A ratio named as a condition of something else ("subject to a pro forma Total Leverage Ratio of 4.00:1.00", "if the
    # Leverage Ratio is greater than 3.00x, ...") is not a maintenance test: it opens no covenant and its level is no tier.
    for m in mentions:
        s_start, s_end = next(((a, b) for a, b in statements if a <= m.start < b), (0, len(text)))
        group = by_key.get((m.kind, m.sub), [])
        if _CONDITION_LEAD_RE.search(text[max(s_start, m.start - 90):m.start]) and not (group and has_level(group[-1], m.start)):
            # (a condition that speaks of a covenant already set, "provided that if the Collateral Coverage Ratio is less
            # than 1.60 to 1.00 the Borrower shall ...", stays with that covenant as a follow-on clause)
            conditions.append((m.kind, m.start, next((pb for pa, pb in provisos if pa <= m.start < pb), s_end)))
            continue
        in_definition = inside(m.start, definitions) and not _RELATED_DEFS_RE.match(text[max(0, m.start - 30):m.start + 1]) and bool(covs)
        cov = owner(m, create=not in_definition)
        if cov is not None:
            cov.mentions.append(m)
    for i, cov in enumerate(covs):
        cov.end = covs[i + 1].start if i + 1 < len(covs) else len(text)
    conditional = [(a, b) for _, a, b in conditions] + [(x, y) for c in covs for x, y in c.alts]

    # Statements that set "<measure> <operator> <level>" for a measure the rules have no name for: a test they cannot
    # classify. It is reported as worded in the "other" row, never attached to the covenant named before it.
    unknown: list[tuple[int, int]] = []
    for a, b in statements:
        if inside(a, definitions) or any(a <= m.start < b for m in mentions) or _CONTINUATION_RE.search(text, a, b) \
                or _NETTING_RE.search(text, a, b) or _DEFINITION_WORDS_RE.search(text, a, b):
            continue
        for lv in levels:
            if a <= lv.start < b and not (lv.typ == "pct" and re.match(r"\s+of\b", text[lv.end:lv.end + 5])) \
                    and _METRIC_RE.search(text, a, lv.start) and _operator(text, a, lv.start, False, figures) \
                    and not _row_cond(text, a, b, lv):
                unknown.append((a, b))
                break
    # ... and a level with its own measure and operator ahead of the first covenant the rules know, in the same statement:
    # "Minimum Debt Yield of not less than 8.0% and maximum Total Leverage Ratio of 4.00x"
    if covs:
        prev_end = 0
        for lv in levels:
            if lv.start >= covs[0].start:
                break
            a = max([prev_end] + [s for s, e in statements if s <= lv.start < e])
            prev_end = lv.end
            if inside(lv.start, definitions) or inside(lv.start, unknown) or inside(lv.start, conditional) \
                    or (lv.typ == "pct" and re.match(r"\s+of\b", text[lv.end:lv.end + 5])):
                continue
            if _METRIC_RE.search(text, a, lv.start) and _operator(text, a, lv.start, False, figures) and not _NETTING_RE.search(text, a, lv.start):
                while a < lv.start and not text[a].isalnum():
                    a += 1
                unknown.append((a, lv.end))

    tangled = bool(re.search(r"\brespectively\b", text, re.IGNORECASE)) and len(covs) > 1
    _table(text, statements, mentions, levels, covs)
    for cov in covs:
        cov.extras += [(x, y, False) for x, y in cov.alts if y > x]
        if cov.table:
            _name(cov, text)
            continue
        ok = _allowed(cov)
        mine = [lv for lv in levels if cov.start <= lv.start < cov.end and lv.typ in ok and not inside(lv.start, definitions)
                and not inside(lv.start, unknown) and not inside(lv.start, conditional)]
        if cov.kind in ("lev", "int"):  # "35% of the commitments", "65% of unrestricted cash" are shares of something, not a ratio level
            mine = [lv for lv in mine if not (lv.typ == "pct" and (re.match(r"\s+of\b", text[lv.end:lv.end + 5]) or _SHARE_WORDS_RE.match(text, lv.end)
                                                                   or _SHARE_LEAD_RE.search(text, max(0, lv.start - 60), lv.start)))]
        if cov.worded_from is not None:
            # a covenant that an option opens, or that is worded after another covenant's proviso: its statement as it stands
            if mine:
                stop = min(next((b for a, b in statements if a <= mine[0].start < b), cov.end), cov.end)
                cov.tiers.append(_Tier("", _as_worded(text[cov.worded_from:stop], 330), "", mine[0].start, False, (cov.worded_from, stop), verbatim=True))
                cov.first_level = mine[0].start
            _name(cov, text)
            continue
        main_done, last_extra = False, False
        for a, b in statements:
            a, b = max(a, cov.start), min(b, cov.end)
            for x, y in cov.alts:  # a clause kept as worded is no part of the statement around it
                if a < x < b:
                    b = x
                elif x <= a < y:
                    a = y
            if a >= b:
                continue
            if inside(a, definitions):
                related = _RELATED_DEFS_RE.match(text[a:b])
                if related and not cov.def_ref and _points(text[a:b]):  # "Related Definitions: Identical to those in the Existing ..."
                    body = _clause(text[a + related.end():b])
                    cov.def_ref = "related definitions " + body[:1].lower() + body[1:]
                continue
            here = [lv for lv in mine if a <= lv.start < b]
            parts = _provisos(text, a, b)
            p0_end = parts[0][0] if parts else b
            head = [lv for lv in here if lv.start < p0_end]
            if not main_done:
                if not here:
                    continue
                if not head:
                    p0_end, head, parts = b, here, []
                _tiers(cov, text, a, p0_end, head, headers, statements, figures)
                main_done = True
                cov.first_level = head[0].start
                last_extra = False
                for pa, pb in parts:
                    has_level = any(pa <= lv.start < pb for lv in here)
                    # (a proviso that speaks of the covenant itself says what follows from it: "provided that if ... the
                    # Borrower is not in compliance with the Asset Coverage Ratio, the Borrower shall, within sixty days, ...")
                    about = pb - pa <= 520 and any(pa <= m.start < pb for m in cov.mentions)
                    if has_level or about or (last_extra and pb - pa <= 330):
                        cov.extras.append((pa, pb, True))
                        last_extra = True
                    else:
                        last_extra = False
                continue
            if not here:
                last_extra = False
                continue
            names_me = any(a <= m.start < b for m in cov.mentions)
            body = _BULLET_START_RE.sub("", text[a:b].strip())
            spare = len(body) - sum(m.end - m.start for m in cov.mentions if a <= m.start < b) - (here[0].end - here[0].start)
            if len(here) == 1 and ((names_me and spare <= 70) or (not names_me and _row_cond(text, a, b, here[0]))):
                _tiers(cov, text, a, b, here, headers, statements, figures)  # a parallel statement or a table row: another tier
                continue
            cov.extras.append((a, p0_end, False))
            last_extra = True
            for pa, pb in parts:
                if any(pa <= lv.start < pb for lv in here) or pb - pa <= 330:
                    cov.extras.append((pa, pb, True))
        _name(cov, text)
    # A covenant named without a level, followed by another covenant that collects several: the levels may belong to
    # both ("X and Y of 3.50x and 3.00x", a table the rules could not read by column). Do not guess.
    for i, cov in enumerate(covs[:-1]):
        nxt = covs[i + 1]
        if not cov.tiers and not cov.table and len(nxt.tiers) > 1 and not nxt.table:
            tangled = True
    # A covenant that got no level although a figure stands right after its name (a figure of a kind the rules do not
    # expect for it, e.g. "Leverage Ratio: 65%"): the statement is kept as worded, never reported as "level not set out".
    for cov in covs:
        if cov.tiers or cov.table or not cov.mentions:
            continue
        for m in cov.mentions:  # (its first name, and any fuller name under it: "Interest Cover: Projected Interest Cover ... each to be ...")
            s_start, s_end = next(((a, b) for a, b in statements if a <= m.start < b), (m.start, len(text)))
            later = [x.start for x in mentions if x.start >= m.end]
            stop = min(later + [s_end, m.end + 45])
            near = [lv.start for lv in levels if m.end <= lv.start < stop and not inside(lv.start, definitions) and not inside(lv.start, conditional)]
            # ... or a comparison follows the name with a level the rules cannot read ("not to exceed three and one-half times")
            worded = _OP_RE.search(text, m.end, min(stop, m.end + 30)) if not inside(m.start, definitions) else None
            if worded and (_TO_BE_AGREED_RE.search(text, m.end, s_end) or _points(text[m.end:s_end])
                           or re.fullmatch(r"(?i)max(?:imum|\.)?|min(?:imum|\.)?", worded.group(0))):
                worded = None  # "not to exceed a level to be agreed": the level is deferred, which the row says; "X and Minimum Y"
            # ... or a number, whatever it measures ("of ISK 500 million"): something is set, so "level not set out" would be wrong
            number = _FREE_DIGIT_RE.search(text, m.end, min(stop, m.end + 30)) if not inside(m.start, definitions) \
                and not inside(m.start, conditional) else None
            # ... or, further on in the statement and before any other name, a comparison with a figure right after it, whatever
            # the figure measures ("The Total Leverage Ratio as of the last day of each fiscal quarter shall not exceed 65%")
            far = None
            if not (near or worded or number) and not inside(m.start, definitions) and not inside(m.start, conditional):
                for op in _OP_RE.finditer(text, m.end, min(later + [s_end])):
                    if re.fullmatch(r"(?i)max(?:imum|\.)?|min(?:imum|\.)?", op.group(0)) or inside(op.start(), definitions) or inside(op.start(), conditional):
                        continue
                    far = _FREE_DIGIT_RE.search(text, op.end(), min(s_end, op.end() + 30))
                    if far:
                        break
            if near or worded or number or far:
                pos = near[0] if near else worded.end() if worded else number.start() if number else far.start()
                cov.tiers.append(_Tier("", _as_worded(text[max(s_start, cov.start):s_end]), "", pos, False, (s_start, s_end), verbatim=True))
                cov.first_level = pos
                break
    return covs, tangled, unknown, conditions


def _name_words(name: str) -> set[str]:
    """The words that tell one covenant's name from another's: "Maximum Consolidated Net Leverage Ratio" -> {net, leverage}."""
    return {w for w in re.findall(r"[a-z]+", (name or "").lower())} - _NAME_STOP


def _table(text: str, statements: list[tuple[int, int]], mentions: list[_Mention], levels: list[_Level], covs: list[_Cov]) -> None:
    """Read a level table that has one column per covenant: a heading line naming two or more covenants, then rows
    that each carry one level per covenant ("March 31, 2026    4.50:1.00    2.50:1.00")."""
    owner = {id(m): cov for cov in covs for m in cov.mentions}
    for si, (a, b) in enumerate(statements):
        heads: list[tuple[_Cov, _Mention]] = []
        for m in mentions:
            cov = owner.get(id(m))
            if a <= m.start < b and cov is not None and all(cov is not c for c, _ in heads):
                heads.append((cov, m))
        if len(heads) < 2 or any(a <= lv.start < b for lv in levels) or any(c.tiers for c, _ in heads):
            continue
        rows = []
        for ra, rb in statements[si + 1:]:
            row = [lv for lv in levels if ra <= lv.start < rb]
            if len(row) != len(heads) or any(ra <= m.start < rb for m in mentions) \
                    or any(lv.typ not in _allowed(c) for lv, (c, _) in zip(row, heads)):
                break
            rows.append((ra, rb, row))
        if not rows:
            continue
        for i, (cov, m) in enumerate(heads):
            floor = max([a] + [h.end for _, h in heads if h.end <= m.start])
            op = _operator(text, max(floor, m.start - 15), m.start, False)
            if op is not None and _against_nature(op, cov):
                op = None  # a column head the rules misread: fall back on the nature of the test, and say so
            for ra, rb, row in rows:
                cond = _clean_cond(_BULLET_START_RE.sub("", text[ra:row[0].start].strip()))
                cov.tiers.append(_Tier(op or _default_op(cov), row[i].shown, cond, row[i].start, op is None, (ra, rb)))
            cov.first_level, cov.table = rows[0][2][i].start, True


def _name(cov: _Cov, text: str) -> None:
    """Name, components and "to be defined" remark of a covenant, from its mentions."""
    named = [m for m in cov.mentions if m.name]
    first = named[0] if named else None
    limit = cov.first_level if cov.first_level >= 0 else cov.end
    # the components are taken from the covenant's own statement (up to its level), or from a name that is the components
    # ("Total Net Debt to EBITDA"); a ratio spelled out in a later sentence is not assumed to be this one
    comp = next((m for m in cov.mentions if m.a and m.b and m is not first and m.start < limit), None) or \
        (first if first is not None and first.a and first.b else None)
    if first is not None:
        raw = tidy(first.name).strip("“”\" ")
        money = "money" in _allowed(cov)
        if not money:
            raw = _NAME_LEAD_RE.sub("", raw)
        else:
            raw = re.sub(r"^(?:the|an?)\s+", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"^min\.?(?=\s)", "Minimum", raw, flags=re.IGNORECASE)
            raw = re.sub(r"^max\.?(?=\s)", "Maximum", raw, flags=re.IGNORECASE)
        if raw.isupper() and len(raw.split()) > 1:  # a term sheet set in capitals: "TOTAL LEVERAGE RATIO" -> "Total Leverage Ratio"
            raw = " ".join(w if _ACRONYM_RE.fullmatch(w) else w.capitalize() if w not in ("TO", "OF", "AND") else w.lower() for w in raw.split())
        cov.name, cov.lower_name = _upper_first(raw), raw[:1].islower()
        ref = _def_aside(text, first.end)
        if ref:
            cov.def_ref, cov.def_span = _money(ref[0]), (ref[1], ref[2])
    if comp is not None:
        cov.a, cov.b = comp.a, comp.b
        squashed = re.sub(r"ratio$", "", re.sub(r"\W+", "", cov.name).lower())
        if not cov.name or squashed in (re.sub(r"\W+", "", f"{comp.a}to{comp.b}").lower(), re.sub(r"\W+", "", comp.a + comp.b).lower()):
            cov.name = cov.name or _upper_first(f"{comp.a} to {comp.b}")  # the ratio is named by its components
            cov.a = cov.b = ""
    if not cov.name:
        cov.name = {"lev": "Leverage ratio", "int": "Interest cover"}.get(cov.kind, "Financial covenant")


def _tiers(cov: _Cov, text: str, a: int, b: int, here: list[_Level], headers: list[tuple[int, str]], statements: list[tuple[int, int]],
           figures: list[int] | None = None) -> None:
    """Turn the levels of one statement ``text[a:b]`` into tiers of the covenant, each with operator and condition."""
    if not here:
        return
    # "shall not permit: 1. ... to exceed X; and 2. ... to be less than Y": the frame sits at the start of the sentence
    sentence_start = max(_breaks_before(_FULL_STOP_RE, text, 0, here[0].start) + [0])
    frame = bool(_NEG_FRAME_RE.search(text[sentence_start:here[0].start]))
    op = _operator(text, a, here[0].start, frame, figures)
    if op is None and not cov.tiers:
        op = _operator(text, cov.start, here[0].start, frame, figures)  # "Maximum Total Leverage Ratio:" above a table of levels
    assumed = op is None
    read = [t for t in cov.tiers if not t.verbatim]
    if op is None and read:
        op, assumed = read[0].op, read[0].assumed
    if op is None:
        op = _default_op(cov)
    # Wording the rules must not turn into "<= level": a comparison that runs against the nature of the test ("if the
    # Leverage Ratio is greater than 3.00x, ..." is a condition, not a ceiling) and a level given as a range.
    if _against_nature(op, cov) or _RANGE_RE.search(text[max(a, here[0].start - 40):here[0].start]):
        cov.tiers.append(_Tier("", _as_worded(text[a:b]), "", here[0].start, False, (a, b), verbatim=True))
        return

    def header_for(pos: int) -> str:
        last = [h for p, h in headers if p < pos]
        return _lower_first(_house(last[-1])) if last else ""

    named = [m for m in cov.mentions if a <= m.start < b]
    if named and not cov.tiers and not cov.scope:
        # what the statement says, before the name, of where or when the covenant applies: "With respect to the Revolving
        # Facility only, a maximum ...", "During the Covenant Relief Period, the maximum ...", "Revolving Facility: Maximum ..."
        lead = text[a:named[0].start]
        lead = lead[_ITEM_OPEN_RE.match(lead).end():]  # "; or (b) "
        scope = _SCOPE_LEAD_RE.match(lead)
        if scope and _plain_lead(lead[scope.end():]):
            cov.scope = _lower_first(_clean_cond(next(g for g in scope.groups() if g)))
        elif scope or _CASE_HEAD_RE.match(lead):
            # a condition the rules cannot cut cleanly from the words around it (it runs over several clauses, or more is
            # said between it and the name): the level is not printed without it. The statement is kept as worded, from
            # its start when nothing else was set there ("None for so long as ...; otherwise a ...").
            start = max([s for s, e in statements if s <= here[0].start < e] + [0])
            # (... or when the item hangs on a prohibition that opens the sentence: "shall not permit (a) ... or (b) at any
            # time ..., X to exceed 2.50x" is not to be read without its "shall not permit")
            start = start if start < a and (frame or not any(start <= f < a for f in figures or [])) else a
            cov.tiers.append(_Tier("", _as_worded(text[start:b], 330), "", here[0].start, False, (start, b), verbatim=True))
            return
    compound = _COMPOUND_RE.search(text, max(a, here[0].start - 40), here[0].start)
    if compound:  # "the greater of $50m and 10% of ...": the level is the whole expression, kept in the term sheet's words
        shown = _clause(_TEST_TAIL_RE.sub("", text[compound.start():b]))
        if len(shown) > 170:
            shown = shown[:170].rsplit(" ", 1)[0] + " …"
        cov.tiers.append(_Tier(op, shown, header_for(here[0].start), here[0].start, assumed, (a, b)))
        return
    if len(here) == 1:
        lv = here[0]
        tail = _clean_cond(_balance(_TEST_TAIL_RE.sub("", text[lv.end:b])))
        cond = ""
        # what is said of the level right after it is kept: a condition ("for any Testing Date on or prior to ..."), a
        # qualifier ("which shall cease to apply during any Investment Grade Period"), a point left open ("with step-downs
        # to be agreed"); testing wording goes to the testing row
        keep = tail and (_COND_LEAD_RE.match(tail) or _QUALIFIER_RE.match(tail) or _OPEN_POINT_RE.search(tail))
        if keep and len(tail) <= 120 and not _TESTING_WORDS_RE.search(tail) and not _first_mention(tail) and not _dangling(tail):
            cond = tail
        elif not named:
            cond = _row_cond(text, a, b, lv)
        if not cond and not cov.tiers:
            # "... shall not permit X at any time to be less than 1.25:1.00": said before the level instead of after it
            # (or before the name: "shall at all times maintain Liquidity of not less than ...")
            always = _ALWAYS_RE.search(re.sub(r"\([^()]*\)", " ", text[a:lv.start]))
            if always:
                cond = tidy(always.group(0)).lower()
        cond = " ".join(x for x in (header_for(lv.start), cond) if x)
        if cov.tiers and not cond:
            # a further level for a covenant that has one already must say when it applies: by what opens its statement
            # ("Following an IPO, the Total Leverage Ratio shall not exceed 3.50x"), or else it is kept as worded
            scope = _SCOPE_LEAD_RE.match(text[a:named[0].start]) if named else None
            if scope is None:
                cov.extras.append((a, b, False))
                return
            cond = _lower_first(_clean_cond(next(g for g in scope.groups() if g)))
        cov.tiers.append(_Tier(op, lv.shown, cond, lv.start, assumed, (a, b)))
        return
    # Several levels in one statement: a schedule. The condition sits before each level ("(i) prior to X, 3.50 to 1.00":
    # words between the operator and the first level, nothing after the last) or after it ("5.00x through 2026, 4.75x
    # thereafter": nothing between the name and the first level). Anything else is left in the term sheet's own words.
    name_end = max([m.end for m in named if m.start < here[0].start] + [a])
    op_end = name_end
    for m in _OP_RE.finditer(text, name_end, here[0].start):
        op_end = m.end()
    lead = _FILLER_RE.sub("", re.sub(r"^[^\w(]+", "", _clean_cond(_balance(text[op_end:here[0].start])))).strip()
    trail = _clean_cond(_balance(text[here[-1].end:b]))
    conds: list[str] = []
    if lead and not trail:
        conds = [_clean_cond(text[(op_end if i == 0 else here[i - 1].end):lv.start]) for i, lv in enumerate(here)]
        if not all(conds):
            conds = []
    elif not lead:
        linked = [True]  # is each later level tied to the one before it by "stepping down to", "and then" ...
        for i, lv in enumerate(here):
            raw = text[lv.end:(here[i + 1].start if i + 1 < len(here) else b)]
            if i + 1 == len(here):
                raw = _TEST_TAIL_RE.sub("", raw)
            bare = _CONNECTOR_RE.sub("", raw)
            linked.append(bare != raw)
            conds.append(_clean_cond(_balance(bare)))
        if not any(conds):
            # levels side by side with nothing said of them: a table row; its periods are the column heads above, or unknown
            conds = _column_heads(text, a, len(here), statements, figures or [])
        # A second figure is a tier only if the wording makes it one: a connector before it or a period of its own.
        # "4.50:1.00 (currently 0.7x)" is a level and a remark, not a schedule.
        if any(not linked[i] and not (conds[i] and (_COND_LEAD_RE.match(conds[i]) or _PERIOD_WORDS_RE.search(conds[i])))
               for i in range(1, min(len(here), len(conds)))):
            conds = []
    if not conds or any(len(c) > 170 or _dangling(c) or _first_mention(c) for c in conds) or re.search(r"\brespectively\b", text[a:b], re.IGNORECASE):
        cov.tiers.append(_Tier(op, here[0].shown, header_for(here[0].start), here[0].start, assumed))
        cov.extras.append((here[0].end, b, False))
        return
    for lv, cond in zip(here, conds):
        cov.tiers.append(_Tier(op, lv.shown, cond, lv.start, assumed))


def _plain_lead(text: str) -> bool:
    """The words between a condition and a covenant's name add nothing to the condition: "the Borrower shall maintain a maximum "."""
    return len(text) <= 120 and not re.search(r"[,;:]", text.strip(" ,")) and not _CASE_OPEN_RE.search(text)


def _column_heads(text: str, a: int, count: int, statements: list[tuple[int, int]], figures: list[int]) -> list[str]:
    """The periods that head the columns of a level-table row starting at ``a`` ("FY2026  FY2027  FY2028" above
    "Maximum Total Leverage  5.00x  4.50x  4.00x"): the nearest statement above that carries no level, when it holds
    exactly ``count`` periods. Empty when there is none: the levels of the row then cannot be told apart."""
    for sa, sb in reversed([s for s in statements if s[1] <= a][-8:]):
        if any(sa <= f < sb for f in figures):
            continue  # another row of the table
        heads = [tidy(m.group(0)) for m in _PERIOD_TOKEN_RE.finditer(text, sa, sb)]
        return heads if len(heads) == count and not _first_mention(text[sa:sb]) else []
    return []


def _as_worded(passage: str, limit: int = 210) -> str:
    """A statement kept in the term sheet's words (house-style figures), cut at a word with a visible ellipsis."""
    shown = _clause(passage.replace("\n", " "))
    return shown if len(shown) <= limit else shown[:limit].rsplit(" ", 1)[0] + " …"


def _balance(text: str) -> str:
    """Drop brackets left unmatched when a clause is cut out of a sentence: " by FY27)" -> " by FY27"."""
    out, depth = [], 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                continue
            depth -= 1
        out.append(ch)
    text = "".join(out)
    while depth > 0 and "(" in text:
        i = text.rfind("(")
        text = text[:i] + text[i + 1:]
        depth -= 1
    return text


def _dangling(text: str) -> bool:
    """The clause breaks off: unmatched bracket, or it ends on a word that needs another ("with a step-up to")."""
    return text.count("(") != text.count(")") or bool(re.search(
        r"\b(?:to|of|for|and|the|an?|or|with|at|by|in|on|than|as|be|is|are|may|shall|will|would|must|been|being|not|that|which)$", text, re.IGNORECASE))


def _row_cond(text: str, a: int, b: int, lv: _Level) -> str:
    """The condition of a level-table row ("June 30, 2026      4.25:1.00"): a short period in front of a level that ends the line."""
    if text[lv.end:b].strip(" .;,"):
        return ""
    before = _clean_cond(_BULLET_START_RE.sub("", text[a:lv.start].strip()))
    if not before or len(before) > 60 or _OP_RE.search(before) or _first_mention(before):
        return ""
    return before if _PERIOD_WORDS_RE.search(before) or re.search(r"\d", before) else ""


# ---------------------------------------------------------------------------------------------------
# analysis of the document (shared by the five rules)
# ---------------------------------------------------------------------------------------------------

@dataclass
class _Analysis:
    """What the document says about financial covenants.

    state:  covenants        a section with covenants and levels
            names_only       a section that names covenants without levels
            none             the term sheet says there are none
            reference        a section that only points to another document
            tangled          covenants and levels that cannot be paired safely (printed as they stand)
            unlisted_closed  no section, and a closed covenant list without a financial covenant
            unlisted_open    no section, and an open covenant list that points to another agreement
            unlisted_ref     no section; covenants are by reference only
            unseparated      an amendment row whose existing and proposed cells cannot be told apart
            absent           nothing found
    """

    state: str = "absent"
    sec: _Sec | None = None
    covs: list = field(default_factory=list)
    leverage: _Cov | None = None
    interest: _Cov | None = None
    others: list = field(default_factory=list)
    listing: str = "plain"  # how the section lists its covenants: closed | open | plain
    refers: str = ""  # the words that point to another agreement
    quote: dict | None = None  # evidence for a state that rests on a Covenants block or a sentence
    note: str = ""
    unknown: list = field(default_factory=list)  # spans of tests the rules could not classify (reported as worded)
    conditions: list = field(default_factory=list)  # (kind, start, end) of ratios named only as a condition of something else
    tail: tuple | None = None  # span of what a section that opens with "None" goes on to say
    rows: bool = False  # read from rows labelled with a covenant's own name, not from a financial covenant section
    also: str = ""  # reviewer note: another section of the document gives different financial covenants


def _listing(lead: str) -> str:
    """How the words that introduce a list frame it: "closed" (limited to ...), "open" (including ...) or "plain"."""
    closed, opened = _CLOSED_RE.search(lead), _OPEN_RE.search(lead)
    if closed and re.search(r"not\s+$", lead[:closed.start()], re.IGNORECASE):
        closed = None
    if closed and (not opened or closed.start() < opened.start()):
        return "closed"
    return "open" if opened else "plain"


def _points(text: str) -> re.Match | None:
    """points_elsewhere, also seeing through a bracketed aside ("Similar to (and no less favorable ... than) the Existing
    Agreement") and whatever the other agreement is called ("substantially consistent with the Precedent Credit Agreement")."""
    bare = re.sub(r"\s*\([^()]*\)", "", text)
    return points_elsewhere(text) or points_elsewhere(bare) or _NAMED_DOC_RE.search(text) or _NAMED_DOC_RE.search(bare)


def _defers(aside: str) -> bool:
    """A definition that gives no content of its own: it points to another document, or ends on that document's name, and
    adds nothing to it ("... except that", "but with ...", a figure)."""
    return bool(_points(aside) or _DOC_END_RE.search(aside)) and not re.search(r"\bexcept|\bprovided\b|\bbut\b|add[\s-]?back|netting|\d", aside, re.IGNORECASE)


def _refers(text: str) -> str:
    """The words with which a passage points to another document, worded to follow "covenants are ..." in a line."""
    m = _points(text)
    if not m:
        return ""
    phrase = tidy(m.group(0))
    if re.search(r"(?:Existing|Prior|Current)$", phrase):  # the match stops at "the Existing": add the document's name
        source = m.string
        tail = re.match(r"(?:\s+(?:\d+-\s?)?[A-Z][\w\-]*){1,5}", source[m.end():])
        phrase = tidy(phrase + " " + (tail.group(0) if tail else "agreement"))
    phrase = re.sub(r"(\d)- +(?=[A-Za-z])", r"\1-", phrase)
    phrase = phrase[:1].lower() + phrase[1:]
    if re.match(r"documentation\s+principles", phrase, re.IGNORECASE):
        return "subject to the Documentation Principles"
    if re.match(r"same\s+as\b", phrase):
        return "the " + phrase
    return phrase


def _analyse(ctx: Ctx) -> _Analysis:
    """The reading of the document's financial covenants, made once and shared by the five rules."""
    cache = ctx.__dict__.setdefault("_fincov_cache", {})
    if "analysis" not in cache:
        cache["analysis"] = _do_analyse(ctx)
    return cache["analysis"]


def _candidates(ctx: Ctx) -> list[Block]:
    """Every block labelled as financial covenants, in document order."""
    seen: dict[int, Block] = {}
    for block in ctx.blocks(_FC_LABEL):  # also a label with nothing beside it: on a page without layout its text is stitched on
        seen.setdefault(block.line.n, block)
    for block in ctx.all(_COV_LABEL):  # a label wrapped over two lines: "Financial" / "Covenants:"
        if _FC_LABEL_RE.search(block.label or ""):
            seen.setdefault(block.line.n, block)
    return [seen[k] for k in sorted(seen)]


def _do_analyse(ctx: Ctx) -> _Analysis:
    """Read every candidate section and keep the one that yields most; fall back on rows labelled with a covenant's
    own name, then on what the covenant list says."""
    best: _Analysis | None = None
    unseparated = False
    read: list[_Analysis] = []
    for block in _candidates(ctx):
        sec = _resolve(ctx, block, _FC_LABEL)
        if sec is False:
            unseparated = True
            continue
        if sec is None:
            continue
        cand = _analyse_section(sec)
        read.append(cand)
        if best is None or _score(cand) > _score(best):
            best = cand
    # the same covenants read from the wider Covenants block: used when there is no labelled section, or when the
    # labelled one was cut short (a sub-heading inside the value column whose text wraps back to its own margin)
    sec = _embedded(ctx)
    if sec is not None:
        cand = _analyse_section(sec)
        if best is None or _score(cand) > _score(best):
            best = cand
    if best is None or not any(c.tiers for c in best.covs):
        rows = _rows(ctx)  # "Minimum Liquidity: ...", "Collateral Coverage Ratio: ..." as rows of their own
        if rows is not None and (best is None or best.state not in ("none", "tangled")):
            return rows
    if best is not None:
        # two sections with different covenants (a term loan and a revolver term sheet in one document): say which was read
        mine = _signature(best)
        pages = sorted({o.sec.block.page for o in read if o is not best and o.sec is not None and _signature(o) and _signature(o) != mine})
        if mine and pages and best.sec is not None:
            best.also = (f" The term sheet has another financial covenant section with different terms (page {', '.join(map(str, pages))}); "
                         f"the one on page {best.sec.block.page} was read.")
        return best
    if unseparated:
        return _Analysis(state="unseparated", note="The financial covenant row shows existing and proposed terms that could not be told apart.")
    return _unlisted(ctx)


def _signature(a: _Analysis) -> tuple:
    """The covenants and levels a reading found, to tell two sections that say the same from two that differ."""
    return tuple((c.kind, c.sub, tuple((t.op, t.level) for t in c.tiers)) for c in a.covs if c.tiers)


def _row_blocks(ctx: Ctx) -> list[Block]:
    """Top-level rows whose label is a covenant's own name ("Minimum Liquidity:", "Maximum Total Leverage Ratio:"), on
    pages that carry term sheet rows (two or more of Borrower, Maturity, Pricing ... on the page or the pages next to it):
    a "Maximum leverage" line on a financial policy slide is not a covenant."""
    counts = Counter(b.page for b in ctx.all(_TERM_ROW_LABEL) if b.text and not b.inline)
    return [b for b in ctx.all(_COV_ROW_LABEL) if b.text and not b.inline and b.page not in ctx.split_pages
            and sum(counts.get(p, 0) for p in (b.page - 1, b.page, b.page + 1)) >= 2]


def _rows(ctx: Ctx) -> _Analysis | None:
    """Financial covenants given as rows of their own rather than under a "Financial Covenants" heading.

    A row is taken only when it reads as a maintenance test: its label names the covenant, its text sets one level for
    it in covenant wording ("shall not permit", "not less than" ...), and it does not speak of pricing. The rows found
    are read together as one section. Rows under labels the rules do not know are not seen, so the rows for covenant
    types that were not found read "not stated" rather than "none".
    """
    vocab = _vocab(ctx)
    lines: list = []
    parts: list[str] = []
    for block in _row_blocks(ctx):
        if len(block.text) > 2500 or _PRICING_WORDS_RE.search(block.text) or not block.parts:
            continue
        own = _sub_block(block, 0, None, first_part=f"{tidy(block.label)}: {tidy(block.parts[0] or '')}")
        text = _heal(_flow(own), vocab)
        covs, tangled, unknown, _ = _read(text)
        first = covs[0] if covs else None
        if tangled or unknown or first is None or not first.tiers or first.mentions[0].start > len(block.label) + 2:
            continue
        clean = len(first.tiers) == 1 and not first.tiers[0].verbatim and not first.extras
        worded = bool(_MAINTAIN_VERB_RE.search(block.text)) and not any(t.verbatim for t in first.tiers)
        labelled = bool(re.match(r"(?:max|min)", block.label, re.IGNORECASE)) and clean and len(_levels(block.text)) == 1
        if worded or labelled:
            lines += own.lines
            parts += own.parts
    if not lines:
        return None
    block = Block(label="Financial covenant rows", line=lines[0], lines=lines, parts=parts, inline=False, mode="column")
    out = _analyse_section(_Sec(block=block, text=_heal(_flow(block), vocab), label="Financial covenant rows"))
    out.rows = True
    out.also = " The term sheet has no financial covenant section; this was read from a row labelled with the covenant's own name."
    return out if out.state == "covenants" else None


def _score(a: _Analysis) -> tuple:
    """How much of a covenant package a candidate section yields; the richest reading of the document is used."""
    return (sum(len(c.tiers) for c in a.covs), sum(len(c.extras) for c in a.covs), a.state in ("none", "reference", "names_only"))


def _analyse_section(sec: _Sec) -> _Analysis:
    """Read one section: its covenants, which of them fills which row, and how the section frames its list."""
    out = _Analysis(sec=sec)
    covs, tangled, out.unknown, out.conditions = _read(sec.text)
    out.covs = covs
    with_tiers = [c for c in covs if c.tiers]
    first = min((c.mentions[0].start for c in covs), default=len(sec.text))
    lead = (sec.lead + " " if sec.lead else "") + sec.text[:first]
    out.listing = _listing(lead)
    out.refers = _refers(lead) or (_refers(sec.text) if not with_tiers else "")
    none = _NONE_RE.match(sec.text)
    if tangled:
        out.state = "tangled"
    elif with_tiers:
        out.state = "covenants"
        lev = [c for c in with_tiers if c.kind == "lev"]
        out.leverage = next((c for c in lev if c.sub in ("total", "cap")), lev[0] if lev else None)
        ints = [c for c in with_tiers if c.kind == "int"]
        out.interest = ints[0] if ints else None
        out.others = [c for c in with_tiers if c is not out.leverage and c is not out.interest]
    elif none and not out.unknown:
        out.state = "none"
        if len(sec.text) - none.end() > 15:  # "None; provided that Incremental Facilities shall be subject to a pro forma ..."
            out.tail = (none.end(), len(sec.text))
    elif covs:
        out.state = "names_only"
    elif out.refers:
        out.state = "reference"
    else:
        out.state = "absent"
        out.note = "A financial covenant heading was found but its text could not be read as covenants."
    return out


def _unlisted(ctx: Ctx) -> _Analysis:
    """No financial covenant section: an express statement that there is none, or a covenant list that leaves them out."""
    for block in ctx.all(_COV_LABEL):  # only what a covenants section says of itself: other instruments may be covenant-lite
        m = _NO_FC_RE.search(block.text or "")
        q = ctx.quote(block, m) if m else None
        if q:
            return _Analysis(state="none", quote=q)
    blocks = [b for b in ctx.all(_COV_LABEL) if b.text and not b.inline]
    if not blocks or any(_mentions(b.text) or re.search(r"financial\s+covenant", b.text, re.IGNORECASE) for b in blocks):
        return _Analysis()
    # the term sheet speaks of financial covenants somewhere the rules did not read: nothing can be concluded from the list
    if ctx.search(r"financial\s+(?:maintenance\s+)?covenants?\b") or ctx.search(_MAINTENANCE_PHRASE) or any(_runs_on(ctx, b) for b in blocks):
        return _Analysis()
    # ... or has a row labelled with a covenant's own name ("Leverage Ratio:", "Collateral Coverage Ratio:") that was not read
    if _row_blocks(ctx):
        return _Analysis(note="A row labelled with a financial covenant's name was found but could not be read as a maintenance test.")
    # ... or words a ratio test anywhere else, under a label the rules do not know ("Debt Covenant: Total Debt to
    # Capitalization shall not exceed 60%"): what the covenant list leaves out then proves nothing
    for m in _mentions(ctx.text):
        window = ctx.text[max(0, m.start - 200):m.end + 150]
        if _MAINTAIN_VERB_RE.search(window) and (_RATIO_LEVEL_RE.search(window) or _PCT_LEVEL_RE.search(window)):
            return _Analysis(note="The covenant list names no financial covenant, but the term sheet words a ratio test elsewhere; "
                                  "the rows were not concluded.")
    kinds = [_listing(b.text[:500]) for b in blocks]
    if all(k == "closed" for k in kinds):
        m = _CLOSED_RE.search(blocks[0].text)
        return _Analysis(state="unlisted_closed", quote=ctx.quote(blocks[0], m) or ctx.quote(blocks[0]))
    for block, kind in zip(blocks, kinds):
        ref = _refers(block.text[:500])
        if ref and kind != "closed":
            # an open list ("including, but not limited to: ...") or no list at all ("usual and customary")
            return _Analysis(state="unlisted_open" if kind == "open" else "unlisted_ref", refers=ref,
                             quote=ctx.quote(block, points_elsewhere(block.text[:500])) or ctx.quote(block))
    return _Analysis()


# ---------------------------------------------------------------------------------------------------
# lines
# ---------------------------------------------------------------------------------------------------

def _schedule(tiers: list[_Tier]) -> list[str]:
    """The tiers as "<= 4.50x for ..." pieces. A condition that ends like the one before it is not repeated in full
    ("... ending after the Acquisition Closing Date" is printed once for a run of tiers)."""
    pieces, prev = [], []
    for t in tiers:
        if t.verbatim:  # wording the rules would not reduce to an operator and a level
            pieces.append(f"as worded in the term sheet: {t.level}")
            prev = []
            continue
        words = t.cond.split()
        common = 0
        while common < min(len(words), len(prev)) and words[-1 - common] == prev[-1 - common]:
            common += 1
        # the shared ending is dropped from the word that opens it ("ending after ...", "following ..."), never mid-phrase
        cut = next((i for i in range(len(words) - common, len(words)) if words[i].lower() in _SUFFIX_OPENERS), None)
        cond = " ".join(words[:cut]) if cut is not None and len(words) - cut >= 4 and cut >= 2 else t.cond
        if cond and not _COND_LEAD_RE.match(cond):
            cond = f"({cond})"  # a bare period from a table row or a slide heading
        pieces.append(f"{t.op} {t.level}" + (f" {cond}" if cond else ""))
        prev = words
    return pieces


def _cov_lines(cov: _Cov, sec: _Sec, budget: int = MAX_COV_LINES) -> list[str]:
    """The lines for one covenant: name, level(s), then its follow-on clauses in the term sheet's words."""
    definition = ""
    if cov.a and cov.b and len(cov.a) + len(cov.b) <= 90:
        definition = f" ({cov.a} / {cov.b})"
    pieces = _schedule(cov.tiers)
    first = cov.tiers[0]
    if first.assumed and not first.verbatim:  # the one assumption the rules make is shown where the reader sees it
        sense = "maximum" if first.op.startswith("<") else "minimum"
        pieces[0] += f" (no 'maximum' / 'minimum' wording in term sheet; read as a {sense})"
    scope = f" ({cov.scope})" if cov.scope and not first.verbatim else ""  # (a statement kept as worded has it already)
    if first.verbatim and cov.follows is not None:  # where it stands is said, so that the reader checks what governs it
        pieces[0] = pieces[0].replace("as worded in the term sheet:", f"as worded in the term sheet, after a proviso to the {cov.follows.name} covenant:", 1)
    lines = [f"{cov.name}{definition}{scope}{' -' if first.verbatim else ''} {pieces[0]}"]
    rest = pieces[1:]
    while rest and len(lines[0]) + 2 + len(rest[0]) <= LINE:
        lines[0] += "; " + rest.pop(0)
    if rest:
        packed = _pack(rest, LINE - 6)
        lines += ["Then " + packed[0]] + packed[1:]
    if cov.def_ref and len(lines[0]) + len(cov.def_ref) + 3 <= LINE + 30:
        lines[0] += f" ({cov.def_ref})"
    scope = _LABEL_SCOPE_RE.search(sec.label or "")  # "Financial Covenants (Revolving Facility only):"
    if scope and tidy(scope.group(1)).lower() not in lines[0].lower():
        lines[0] += f" ({tidy(scope.group(1))})"
    if sec.same_as_existing:
        lines[0] += " (same as existing)"
    elif sec.existing:
        lines[-1] += _versus_existing(cov, sec)
    cov.truncated = False
    for a, b, proviso in cov.extras:
        raw = sec.text[a:b]
        clause = _lower_first(_clause(_balance(raw)))
        if not clause:
            continue
        if [a, b] in cov.alts:
            # an optional or alternative test: its whole clause in the term sheet's words, conditions included; what does
            # not fit is cut visibly, never silently
            choice = any(c for span, c in zip(cov.alts, cov.alt_choice) if span == [a, b]) or bool(_OR_OPEN_RE.match(raw))
            label = "Alternative, as worded in the term sheet: " if choice else "Also, as worded in the term sheet: "
            if len(lines) >= budget:
                cov.truncated = True
                break
            chunks = _first_lines(label + clause, LINE, budget - len(lines))
            lines += [chunks[0]] + ["… " + c for c in chunks[1:]]
            continue
        if not proviso and len(lines) == 1 and len(lines[0]) + 2 + len(clause) <= LINE:
            lines[0] += "; " + clause
            continue
        has_figure = bool(_RATIO_LEVEL_RE.search(raw) or _PCT_LEVEL_RE.search(raw) or MONEY_RE.search(raw))
        if has_figure:
            prefix = "Step-up: " if _STEP_UP_RE.search(clause) else "Step-down: " if _STEP_DOWN_RE.search(clause) else "Also: "
            chunks = _figure_chunks(clause, LINE - len(prefix))
        else:
            prefix = "Conditions: "
            chunks = [clause] if len(clause) <= LINE + 30 else _split_long(clause, LINE - len(prefix))
        if len(lines) + len(chunks) > budget:  # never half a clause: leave it out and say so in the note
            cov.truncated = True
            break
        lines += [prefix + chunks[0]] + ["… " + c for c in chunks[1:]]
    return lines[:budget]


def _versus_existing(cov: _Cov, sec: _Sec) -> str:
    """On an amendment table: how the proposed level compares with the existing cell, read with the same rules."""
    try:
        old = next((c for c in _read(sec.existing)[0] if (c.kind, c.sub) == (cov.kind, cov.sub) and c.tiers), None)
    except Exception:  # noqa: BLE001 - the comparison is an extra; the proposed terms stand without it
        old = None
    if old is None:
        cov.unmatched = True
        return ""
    was, now = "; ".join(_schedule(old.tiers)), "; ".join(_schedule(cov.tiers))
    return " (unchanged from existing terms)" if was == now else f" (proposed; existing terms: {was})"


def _block_quote(ctx: Ctx, block: Block, needle: re.Match | str | None = None) -> dict | None:
    """ctx.quote, falling back to the block's label line when its text is too short to quote ("None.")."""
    q = ctx.quote(block, needle) if block is not None and block.text else None
    if q is None and block is not None and block.line is not None:
        words = block.line.text.split()[:8]
        if words:
            q = ctx.quote_text(r"\s+".join(re.escape(w) for w in words), pages=[block.line.page])
    return q


def _cov_evidence(ctx: Ctx, cov: _Cov, sec: _Sec) -> list[dict]:
    """Quotes for a covenant: its first level, its first follow-on clause, its last level."""
    out = []
    # a short statement (a bullet, a table row) is quoted whole; in running text the clause around the level is cut
    spots = [t.span if 0 < t.span[1] - t.span[0] <= 160 else (t.pos, t.pos + 12) for t in cov.tiers[:1]]
    spots += [(a, a + 12) for a, _, _ in cov.extras[:1]]
    spots += [t.span if 0 < t.span[1] - t.span[0] <= 160 else (t.pos, t.pos + 12) for t in cov.tiers[-1:]]
    for a, b in spots:
        b = min(b, len(sec.text))
        while a < b and (sec.text[a].isspace() or _BULLET_START_RE.match(sec.text[a:a + 2])):
            a += 1
        if a >= b:
            continue
        m = sec.span(a, b)
        q = ctx.quote(sec.block, m) if m else None
        if q:
            out.append(q)
    if not out:
        q = _block_quote(ctx, sec.block)
        if q:
            out.append(q)
    if sec.same_as_existing and sec.pointer is not None and len(out) < 3:
        q = ctx.quote(sec.pointer)  # the proposed cell itself: "Same as existing"
        if q:
            out.append(q)
    return out


def _cov_note(covs: list[_Cov], sec: _Sec) -> str:
    """The reviewer note for a covenant row: an assumed operator, provisos left out, a section that may run on."""
    notes = []
    if any(t.assumed and not t.verbatim for c in covs for t in c.tiers):
        notes.append("The term sheet prints the level without 'maximum' / 'minimum'; read as a maximum for a leverage-type test and a minimum otherwise.")
    if any(c.worded_from is not None for c in covs):
        notes.append("The covenant is opened by option wording, or is worded after a proviso to another covenant; it is printed as the term "
                     "sheet has it. Check whether it applies generally.")
    elif any(t.verbatim for c in covs for t in c.tiers):
        notes.append("The wording could not safely be reduced to a level (a comparison that runs against the nature of the test, a "
                     "range, or a condition that could not be separated from the level); it is printed as the term sheet has it.")
    if any(c.truncated for c in covs):
        notes.append("The term sheet attaches further provisos to this covenant that are not reproduced in the row.")
    if sec.runs_on:
        notes.append("The financial covenant section appears to continue beyond the text the rules could read; check the term sheet for further terms.")
    if sec.existing and not sec.same_as_existing and any(c.unmatched for c in covs):
        notes.append("Proposed terms recorded. Existing terms: " + _house(sec.existing.replace("\n", " "))[:300])
    return " ".join(notes)


def _listed(a: _Analysis) -> str:
    """The covenants the section names, for the basis of a "none" line."""
    return _names([c.in_sentence for c in a.covs])


def _is_row(sec: _Sec) -> bool:
    """The section is a row of a summary table or slide rather than a section of a term sheet."""
    if sec.embedded:
        return False
    label_line = sec.block.line.text if sec.block.line is not None else ""
    m = _FC_LABEL_RE.search(label_line)
    # (a lettered sub-heading, "(d) Financial Covenants - ...", heads a section of the term sheet whatever closes it)
    no_colon = bool(m) and not label_line[m.end():].lstrip().startswith(":") and sec.block.mode != "enum"
    return sec.block.mode == "plain" or sec.same_as_existing or bool(sec.existing) or no_colon or len(label_line.rstrip()) > 130  # slides are wide


def _bare_line(a: _Analysis, cov: _Cov) -> str:
    """The line for a covenant the term sheet names without giving its level."""
    where = "a row of the term sheet" if a.rows else f"the {_title(a.sec.label)} {'row' if _is_row(a.sec) else 'section'}"
    return f"{cov.name}: named in {where}, level not set out in term sheet"


def _absent(ctx: Ctx, a: _Analysis, prefix: str) -> dict:
    """The row for a covenant type the section does not have, with the basis for saying so."""
    sec = a.sec
    listed = _listed(a)
    evidence = [_block_quote(ctx, sec.block)]
    if sec.runs_on:
        return not_stated(note="The financial covenant section appears to continue beyond the text the rules could read, so this row "
                               "was not concluded.")
    kind = {"Net Debt/EBITDA": "lev", "Interest Cover": "int"}.get(prefix, "other")
    bare = next((c for c in a.covs if not c.tiers and (c.kind == kind or (kind == "other" and c.kind == "lev" and a.leverage is not None))), None)
    if bare is not None:  # the covenant is named but the term sheet gives it no level: say that, never "none"
        m = bare.mentions[0]
        span = sec.span(m.start, min(len(sec.text), m.end + 60))
        line = _bare_line(a, bare)
        around = sec.text[max(0, m.start - 80):m.end + 120]
        deferred = _TO_BE_AGREED_RE.search(around) or _points(around)  # "at a level to be agreed"
        quotes = [ctx.quote(sec.block, span) if span else None] + evidence
        return by_reference(f"{line} ({_lower_first(tidy(deferred.group(0)))})", quotes) if deferred else stated(line, quotes)
    if a.unknown:  # a test the rules could not classify may be of this very type
        return not_stated(note="The financial covenant section has a test the rules could not classify (it is printed as worded in the "
                               "'other' row), so this row was not concluded.")
    if a.rows:  # only the rows whose label the rules know were read: the absence of a test cannot be concluded
        return not_stated(note=f"The term sheet has no financial covenant section; {listed} read from the row(s) labelled with the "
                               "covenant's name. Whether there are other tests was not concluded.")
    if sec.embedded:
        evidence = [ctx.quote_text(_EMBEDDED_RE.pattern, pages=sec.block.pages)] + evidence
    where = f"the {_title(sec.label)} {'row' if _is_row(sec) else 'section'}"
    # a ratio of this type that the section names only as a condition of something else is said so, as worded
    aside: list[str] = []
    # ... and one it gives only as an option or an alternative to another covenant is said so, with that covenant's row
    also = ""
    for owner in a.covs:
        for i, (m, span) in enumerate(zip(owner.alt_names, owner.alts)):
            if m.kind == kind or (kind == "other" and m.kind == "lev" and owner is a.leverage):
                row = "leverage" if owner is a.leverage else "interest cover" if owner is a.interest else "'other'"
                name = tidy(_NAME_LEAD_RE.sub("", m.name))
                name = ("the " if re.search(r"(?i)ratio$", name) else "") + name
                if (i < len(owner.alt_choice) and owner.alt_choice[i]) or _OR_OPEN_RE.match(sec.text[span[0]:span[1]]):
                    also += f"; {name} is given only as an alternative to the {owner.name} - see the {row} row"
                else:
                    also += f"; {name} is given subject to an option or condition, as worded in the {row} row"
                quote = sec.span(span[0], min(span[1], span[0] + 80))
                evidence.append(ctx.quote(sec.block, quote) if quote else None)
        # ... and one it names, with a level, only inside a proviso to another covenant
        for m in owner.proviso_names:
            if m.kind == kind or (kind == "other" and m.kind == "lev" and a.leverage is not None):
                row = "leverage" if owner is a.leverage else "interest cover" if owner is a.interest else "'other'"
                name = tidy(_NAME_LEAD_RE.sub("", m.name))
                name = ("the " if re.search(r"(?i)ratio$", name) else "") + name
                shown = any(x <= m.start < y for x, y, _ in owner.extras) and not owner.truncated
                also += f"; {name} is named only in a proviso to the {owner.name} covenant" + (f" - see the {row} row" if shown else "")
                quote = sec.span(max(0, m.start - 40), min(len(sec.text), m.end + 60))
                evidence.append(ctx.quote(sec.block, quote) if quote else None)
    cond = next(((x, y) for k, x, y in a.conditions if k == kind), None)
    if cond is not None:
        start = max(_breaks_before(_HARD_BREAK_RE, sec.text, 0, cond[0]) + [0])
        aside += _first_lines(f"Named in {where} only as a condition, as worded: " + _as_worded(sec.text[start:cond[1]], 400), LINE, 2)
        span = sec.span(cond[0], min(cond[1], cond[0] + 60))
        evidence.insert(0, ctx.quote(sec.block, span) if span else None)
    if a.listing == "closed":
        m = _CLOSED_RE.search(sec.text)
        if m and not sec.embedded:
            evidence.insert(0, ctx.quote(sec.block, sec.span(m.start(), m.end())))
        limited = "the financial covenants are limited to" if len(a.covs) > 1 else "the financial covenant is limited to"
        return stated([f"{prefix}: none ({limited} {listed}{also})"] + aside, evidence)
    if a.listing == "open" or (sec.embedded and a.refers):
        if a.refers:
            return by_reference([f"{prefix}: none set out in term sheet (only {listed} described; covenants are otherwise {a.refers}{also})"] + aside,
                                evidence)
        return not_stated(note=f"The term sheet gives an open list of financial covenants ({listed}).")
    return stated([f"{prefix}: none (not stated expressly; {where} lists only {listed}{also})"] + aside, evidence)


def _title(label: str) -> str:
    """The section's label as it is named in a line: "FINANCIAL COVENANT" -> "Financial Covenant"."""
    label = tidy(re.sub(r"\([^)]*\)", "", label)).strip(" :")
    return " ".join(w.capitalize() if w.isupper() or w.islower() else w for w in label.split()) or "Financial Covenants"


def _simple_states(ctx: Ctx, a: _Analysis, none_line: str, pointer: str) -> dict | None:
    """Rows for the states that do not depend on the covenant type. None when the section names covenants (with or
    without levels): those rows are written covenant by covenant."""
    sec = a.sec
    if a.state in ("covenants", "names_only"):
        return None
    if a.state == "absent":
        return not_stated(note=a.note)
    if a.state == "unseparated":
        return not_stated(note=a.note)
    if a.state == "none":
        evidence = a.quote or (_block_quote(ctx, sec.block) if sec else None)
        note = ""
        if sec is not None and sec.existing:  # an amendment table: the proposed cell says there is none
            try:
                was = [c for c in _read(sec.existing)[0] if c.tiers]
            except Exception:  # noqa: BLE001 - the comparison is an extra
                was = []
            if was:
                none_line += " (proposed; existing terms: " + "; ".join(f"{c.name} {'; '.join(_schedule(c.tiers))}" for c in was[:3]) + ")"
            if evidence is None and sec.twin is not None:
                # "None" is too short for the quote helper to verify: the existing cell of the same row is quoted instead
                evidence = ctx.quote(sec.twin)
                note = "The proposed cell of the financial covenant row reads as 'none'; the quote is the existing cell of that row."
        return stated(none_line, evidence, note)
    if a.state == "unlisted_closed":
        return stated(f"{none_line} (not among the covenants listed in the term sheet)", a.quote)
    if a.state == "unlisted_open":
        basis = f"the covenant list is open and covenants are {a.refers}"
        if pointer == "Net Debt/EBITDA":
            return by_reference(f"None listed - no financial maintenance covenant is among the covenants listed in the term sheet; {basis}", a.quote)
        if pointer == "n/a":
            return by_reference(f"n/a - no financial covenant listed in term sheet ({basis})", a.quote)
        return by_reference(f"{pointer}: none listed in term sheet ({basis})", a.quote)
    if a.state == "unlisted_ref":
        if pointer == "n/a":
            return not_stated()
        if pointer == "Net Debt/EBITDA":
            return by_reference(f"Not set out in term sheet: there is no financial covenant section, and covenants are {a.refers}", a.quote)
        return by_reference(f"{pointer}: not set out in term sheet (covenants are {a.refers})", a.quote)
    if a.state == "reference":
        return by_reference(f"{pointer}: not set out in term sheet (financial covenants are {a.refers})", _block_quote(ctx, sec.block))
    if a.state == "tangled":
        line = _first_lines(f"{_title(sec.label)}: " + _clause(sec.text.replace("\n", " ")), LINE, 3)
        return stated(line, _block_quote(ctx, sec.block), note="The covenants are given in one sentence; levels were not attributed by the rules.")
    return not_stated()


def _safe(rule):
    """A rule never raises: an unexpected failure is reported in the note and the row reads 'not stated'."""
    @functools.wraps(rule)
    def wrapped(ctx: Ctx) -> dict:
        try:
            return rule(ctx)
        except Exception as exc:  # noqa: BLE001 - one awkward document must not stop the run
            return not_stated(note=f"The rule for this row failed ({type(exc).__name__}: {exc}).")
    return wrapped


# ---------------------------------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------------------------------

@_safe
def fc_leverage(ctx: Ctx) -> dict:
    """The leverage-type maintenance covenant, with its level, schedule and acquisition step-ups."""
    a = _analyse(ctx)
    simple = _simple_states(ctx, a, "None - no financial maintenance covenants", "Net Debt/EBITDA")
    if simple is not None:
        if a.state == "none" and a.tail and a.sec is not None and simple["status"] == "stated":
            # "None; provided that Incremental Facilities shall be subject to a pro forma ...": what follows is shown as worded
            x, y = a.tail
            simple["lines"] += _first_lines("The section adds: " + _as_worded(a.sec.text[x:y], 400), LINE, 2)
            span = a.sec.span(x, min(y, x + 80))
            more = ctx.quote(a.sec.block, span) if span else None
            if more and more not in simple["evidence"]:
                simple["evidence"].append(more)
        return simple
    if a.leverage is None:
        return _absent(ctx, a, "Net Debt/EBITDA")
    lines, evidence = _cov_lines(a.leverage, a.sec, 7), _cov_evidence(ctx, a.leverage, a.sec)
    # what the section says of a facility that has no covenant: "There will be no financial maintenance covenant for the Term Loan Facility"
    text = a.sec.text
    for s, e in _statements(text):
        if len(lines) < 7 and e - s <= 220 and (_NO_FC_RE.search(text, s, e) or _FACILITY_NONE_RE.match(text[s:e])) \
                and not any(c.tiers and s <= c.first_level < e for c in a.covs):
            lines.append("Also: " + _lower_first(_clause(text[s:e])))
            span = a.sec.span(s, min(e, s + 80))
            evidence = evidence[:2] + [ctx.quote(a.sec.block, span) if span else None]
            break
    return stated(lines, evidence, (_cov_note([a.leverage], a.sec) + a.also).strip())


@_safe
def fc_interest_cover(ctx: Ctx) -> dict:
    """The interest cover covenant, with its components in a few words when the term sheet gives them."""
    a = _analyse(ctx)
    simple = _simple_states(ctx, a, "Interest Cover: none", "Interest Cover")
    if simple is not None:
        if a.state == "tangled":
            return stated("Interest Cover: see the leverage row (the term sheet gives its financial covenants in one sentence)", simple.get("evidence"))
        return simple
    if a.interest is None:
        return _absent(ctx, a, "Interest Cover")
    return stated(_cov_lines(a.interest, a.sec, 7), _cov_evidence(ctx, a.interest, a.sec),
                  (_cov_note([a.interest], a.sec) + (a.also if a.rows else "")).strip())


@_safe
def fc_other(ctx: Ctx) -> dict:
    """Any other financial maintenance covenant, one per line."""
    a = _analyse(ctx)
    simple = _simple_states(ctx, a, "Other: none", "Other")
    if simple is not None:
        if a.state == "tangled":
            return stated("Other: see the leverage row (the term sheet gives its financial covenants in one sentence)", simple.get("evidence"))
        return simple
    # a test the rules have no name for is shown as worded: it is another financial covenant, whatever it measures
    extra_lines, extra_evidence = [], []
    for x, y in a.unknown[:3]:
        span = a.sec.span(x, min(y, x + 80))
        q = ctx.quote(a.sec.block, span) if span else None
        if q:
            extra_lines += _first_lines("As worded in the term sheet (test not classified by the rules): " + _as_worded(a.sec.text[x:y], 400), LINE, 2)
            extra_evidence.append(q)
    extra_note = "The section has a test the rules could not classify; it is printed as the term sheet words it. " if extra_lines else ""
    if not a.others:
        if extra_lines:
            return stated(extra_lines, extra_evidence, extra_note.strip())
        return _absent(ctx, a, "Other")
    lines, evidence = [], []
    budget = max(2, (8 - len(extra_lines)) // len(a.others))
    for cov in a.others:
        lines += _cov_lines(cov, a.sec, budget)
        evidence += _cov_evidence(ctx, cov, a.sec)[:2 if len(a.others) == 1 else 1]
    for cov in a.covs:  # a test named without a level is said, not dropped
        if not cov.tiers and cov.kind == "other":
            lines.append(_bare_line(a, cov))
    return stated(lines[:8 - len(extra_lines)] + extra_lines, evidence[:3 - min(1, len(extra_evidence))] + extra_evidence[:1],
                  (extra_note + _cov_note(a.others, a.sec) + (a.also if a.rows else "")).strip())


@_safe
def fc_testing(ctx: Ctx) -> dict:
    """How the covenants are tested: frequency, calculation period, springing condition, first test date."""
    a = _analyse(ctx)
    if a.state in ("none", "unlisted_closed", "unlisted_open", "unlisted_ref"):
        simple = _simple_states(ctx, a, "n/a", "n/a")
        if simple["status"] == "stated":
            simple["lines"] = ["n/a (no financial covenants)"]
        return simple
    if a.state not in ("covenants", "names_only") or a.sec is None:
        return not_stated(note=a.note)
    sec, text = a.sec, a.sec.text
    covs = [c for c in a.covs if c.tiers]
    where = "covenant rows" if a.rows else f"financial covenant {'row' if _is_row(sec) else 'section'}"

    def quote(m: re.Match | None) -> dict | None:
        span = sec.span(m.start(), m.end()) if m else None
        return ctx.quote(sec.block, span) if span else None

    # Testing wording is looked for in the covenant statements themselves, not in their provisos, follow-on
    # clauses (acquisition step-ups, reset periods) or definitions, where periods mean something else.
    stmts = _statements(text)
    skip = [(x, y) for c in a.covs for x, y, _ in c.extras] + list(a.unknown) + [(x, y) for _, x, y in a.conditions]
    zones: list[tuple[int, int]] = []
    asides: list[tuple[int, int]] = []  # definition brackets inside covenant sentences: read for the calculation period only
    for s, e in stmts:
        sets_level = any(c.tiers and s <= c.first_level < e for c in a.covs)  # a covenant sentence, whatever else it mentions
        cure = _EQUITY_CURE_RE.search(text, s, e) or _DEEMED_CURE_RE.search(text, s, e)
        top, held = _def_wording(text, s, e)
        # (a covenant sentence that says in passing how its ratio is defined is read whole: "X, defined as the ratio of A to B
        # for each Relevant Period, shall not exceed 3.50:1 as of the last day of each fiscal quarter")
        aside = min((m.start() for m in (cure, None if sets_level else top) if m), default=None)
        if (aside is not None and not sets_level) or any(x <= s < y for x, y in skip):
            continue  # "two cures in any four fiscal quarter period" is not the calculation period
        # the statement up to its first proviso, follow-on clause (a step-up, an alternative test), cure or definition
        cuts = _provisos(text, s, e)
        end = min([e] + [c[0] for c in cuts[:1]] + ([aside] if aside is not None else []) + [x for x, _ in skip if s < x < e])
        pos = s
        for x, y in held:  # a definition in brackets after a term is an aside: only the bracket is left out
            if x >= end:
                break
            if x > pos:
                zones.append((pos, x))
            if sets_level:
                asides.append((x, min(y, end)))
            pos = max(pos, y)
        if pos < end:
            zones.append((pos, end))

    # the definitions of the section ("“Relevant Period” means each period of twelve months ..."): read for the length of
    # the calculation period only
    definitions = [(s, e) for s, e in stmts if _def_wording(text, s, e)[0] is not None
                   and not _EQUITY_CURE_RE.search(text[s:e]) and not any(c.tiers and s <= c.first_level < e for c in a.covs)]
    homes = {id(c): next(((s, e) for s, e in stmts if s <= c.first_level < e), None) for c in covs}  # the statement that sets each level

    def find_all(rx: re.Pattern, spans: list[tuple[int, int]]) -> list[re.Match]:
        return [m for s, e in sorted(spans) for m in rx.finditer(text, s, e)]

    def said_of(m: re.Match, rx: re.Pattern) -> str:
        """The covenant(s) a testing phrase is said of, when it stands in the statement of some covenants and the statements
        of the others have nothing of the kind: "... to be less than 1.25:1.00, to be tested at the end of each fiscal
        quarter" under one covenant of two says nothing of the other. Empty when it is said of all (or in a sentence of its own)."""
        def has(c: _Cov) -> bool:  # the statement of that covenant has such a phrase (in the parts that are read)
            lo, hi = homes[id(c)] or (0, 0)
            return any(rx.search(text, max(s, lo), min(e, hi)) for s, e in zones + asides if s < hi and e > lo)

        if not any(homes[id(c)] and homes[id(c)][0] <= m.start() < homes[id(c)][1] for c in covs) or _EACH_CASE_RE.search(text, max(0, m.start() - 60), m.start()):
            return ""  # a sentence of its own, or "..., in each case tested quarterly"
        mine = [c for c in covs if has(c)]
        if len(mine) == len(covs):
            return ""
        return " and ".join(c.name for c in mine)

    def pick(matches: list[re.Match], rx: re.Pattern) -> re.Match | None:
        """The first match said of the covenants in general, else the first."""
        return next((m for m in matches if not said_of(m, rx)), matches[0] if matches else None)

    def find(rx: re.Pattern) -> re.Match | None:
        return pick(find_all(rx, zones), rx)

    lines, evidence = [], []
    freq_word, freq_rx, freq = "quarterly", _FREQ_QUARTER_RE, find(_FREQ_QUARTER_RE)
    if not freq:
        for word, rx in _FREQ_OTHER_RES:
            freq = find(rx)
            if freq:
                freq_word, freq_rx = word, rx
                break
    # the calculation period: wording that gives its length ("four consecutive fiscal quarters", "rolling 12-month")
    # before a bare defined term ("Relevant Period", "Test Period"), whose length is then looked up in the definitions
    periods = find_all(_PERIOD_RE, zones + asides)
    period = pick([m for m in periods if not _PERIOD_TERM_RE.fullmatch(m.group(0))], _PERIOD_RE)
    term = None
    if period is None:
        term = periods[0] if periods else None
        defined = [m for m in find_all(_PERIOD_RE, definitions) if not _PERIOD_TERM_RE.fullmatch(m.group(0))]
        period = defined[0] if defined else term
    spring = find(_SPRINGING_RE) or find(_SPRINGING_WORD_RE)
    parts: list[list[str]] = []  # [the covenant(s) it is said of ("" = all), what is said]
    derived = False
    if freq:
        phrase = _house(freq.group(0))
        said = f"tested {freq_word}"
        plain = re.fullmatch(r"(?i)(?:tested|measured|calculated|testing)\s+(?:on\s+a\s+)?\w+|\w+\s+(?:basis|tests?|testing)|[\w-]+", phrase)
        inside_spring = spring is not None and spring.start() <= freq.start() < spring.end()
        if not plain and not inside_spring:
            said += f" ({_lower_first(phrase)})"
        parts.append([said_of(freq, freq_rx), said])
        evidence.append(quote(freq))
    elif covs and not spring:
        # the frequency carried by the covenants' own names ("Maximum Quarterly ... Ratio"): derived, and said to be
        named = []
        for c in covs:
            m0 = next((m for m in c.mentions if m.name), None)
            lead = _NAME_FREQ_RE.search(text[max(0, m0.start - 40):m0.start]) if m0 else None
            if lead:
                named.append((c, re.sub(r"\W", "", lead.group(2).lower()), m0.start - len(lead.group(1)), m0.end))
        if named and len({w for _, w, _, _ in named}) == 1:
            word = {"quarterly": "quarterly", "monthly": "monthly", "semiannual": "semi-annually", "annual": "annually"}[named[0][1]]
            shown = " and ".join(f"'{tidy(text[x:y])}'" for _, _, x, y in named)
            parts.append(["" if len(named) == len(covs) else " and ".join(c.name for c, _, _, _ in named),
                          f"tested {word} (not stated expressly; the term sheet names the covenant{'s' if len(named) > 1 else ''} {shown})"])
            derived = True
            span = sec.span(named[0][2], named[0][3])
            evidence.append(ctx.quote(sec.block, span) if span else None)
    if period:
        phrase = _house(period.group(0))
        of = said_of(period, _PERIOD_RE) if not any(s <= period.start() < e for s, e in definitions) else ""
        same = bool(parts) and parts[-1][0] == of
        if _PERIOD_TERM_RE.fullmatch(period.group(0)):
            # the term sheet names the period without saying how long it is: nothing is assumed about its length
            said = f"by reference to the term sheet's '{phrase}' (its length is not given in the {where})"
        else:
            basis = "rolling 12-month" if re.search(r"month|LTM", phrase, re.IGNORECASE) else "rolling four-quarter"
            if re.fullmatch(r"(?i)rolling\s+.*", phrase):
                basis, phrase = re.sub(r"(?i)\s+basis$", "", phrase), ""
            if term is not None and phrase:  # the length comes from the definition of the period the covenants name
                phrase = f"'{_house(term.group(0))}' is defined by reference to: {phrase if phrase.isupper() else _lower_first(phrase)}"
            detail = f" ({phrase if phrase.isupper() or term is not None else _lower_first(phrase)})" if phrase else ""
            said = f"on a {basis} basis{detail}"
        if same:
            parts[-1][1] += ", " + said
        else:
            parts.append([of, ("tested " if not parts else "calculated ") + said])
        evidence.append(quote(period))
    # a level that is to be met at any time, where no testing frequency is given for its covenant
    always = []
    for c in covs:
        home = homes[id(c)]
        if home is None or (freq and home[0] <= freq.start() < home[1]) or (spring and home[0] <= spring.start() < home[1]):
            continue
        m = next((x for s, e in sorted(zones) for x in [_ALWAYS_RE.search(text, max(s, home[0], c.start), min(e, home[1], c.end))]
                  if s < min(home[1], c.end) and e > max(home[0], c.start) and x), None)
        if m:
            always.append((c, m))
    if always:
        parts.append(["" if len(always) == len(covs) else " and ".join(c.name for c, _ in always),
                      f"the level{'s apply' if len(always) > 1 else ' applies'} {tidy(always[0][1].group(0)).lower()}"])
        evidence.append(quote(always[0][1]))
    head = [_upper_first(h) for h in _pack([f"{of}: {said}" if of else said for of, said in parts], LINE)]
    first_line = head[0] if head else ""
    if spring:
        clause = _lower_first(_clause(spring.group(0)))
        while _dangling(clause) and "," in clause:  # the words read stop where a cure or a proviso begins: "..., with customary"
            clause = clause[:clause.rfind(",")].rstrip()
        if text[spring.end():spring.end() + 1] not in ("", ".", ";", "\n") and not any(spring.end() == e for _, e in zones):
            clause += " …"  # the clause runs on beyond what was read: shown, never silent
        if head:
            head[-1] += "; springing test: " + clause
        else:
            head = ["Springing test: " + clause]
        first_line = head[0]
        evidence.append(quote(spring))
    # first test: the "commencing with ..." of each covenant's own statement, and any sentence on when testing starts
    firsts: list[tuple[str, str]] = []
    first_spans: list[tuple[int, int]] = []
    for cov in covs:
        m = _FIRST_TEST_RE.search(text, cov.start, max(cov.start, cov.first_level))
        if m:
            firsts.append(({"lev": "leverage", "int": "interest cover"}.get(cov.kind, cov.in_sentence), _house(m.group(0))))
            first_spans.append(m.span())
            evidence.append(quote(m))
    if not firsts:  # "The financial covenants shall be tested quarterly, commencing with ..." in a sentence of its own
        m = find(_FIRST_TEST_RE) or find(_FIRST_DATE_RE)
        if m:
            firsts.append(("", _house(m.group(0))))
            first_spans.append(m.span())
            evidence.append(quote(m))
    commence = find(_COMMENCE_RE)
    second = ""
    if firsts:
        if len({f for _, f in firsts}) == 1:
            second = "First test: " + re.sub(r"(?i)^(?:with\s+)?(?:the\s+)?first\s+test(?:ing)?(?:\s+date)?(?:\s+(?:being|is|to\s+be|will\s+be|shall\s+be)\s+|\s*:\s*|\s+(?=\d))",
                                             "", firsts[0][1])
        else:
            second = "First test: " + "; ".join(f"{name} - {clause}" for name, clause in firsts)
    if commence:
        start = max(_breaks_before(_HARD_BREAK_RE, text, 0, commence.start()) + [0])
        sentence = _clause(text[start:commence.end()])
        second = (second + "; " + _lower_first(sentence)) if second else "First test: " + _lower_first(sentence)
        evidence.append(quote(commence))
    # a row of its own on testing, next to the covenant section ("Covenant Testing: Quarterly, on a rolling twelve month basis,
    # commencing with ..."): given in the term sheet's words
    row_lines: list[str] = []
    inside = {ln.n for ln in sec.block.lines}
    pages = sec.block.pages or [sec.block.page]
    for block in ctx.all(_TEST_ROW_LABEL):
        if block.inline or block.line.n in inside or not (min(pages) - 1 <= block.page <= max(pages) + 1) or block.page in ctx.split_pages:
            continue
        body = _heal(tidy(block.text), _vocab(ctx))
        q = ctx.quote(block)
        if q and 8 <= len(body) <= 700 and _TEST_ROW_WORDS_RE.search(body) and not _first_mention(tidy(block.label)):
            row_lines = _first_lines(f"As worded in the term sheet's '{tidy(block.label).strip(' :')}' row: " + _lower_first(_clause(body)), LINE, 2)
            evidence.append(q)
            break
    # what the covenant wording speaks of without the rules being able to read it: not reported as missing
    read = [m.span() for m in (freq, period, term, spring, commence) if m] + [m.span() for _, m in always] + first_spans
    zone_text = " ".join("".join(" " if any(x <= i < y for x, y in read) else ch for i, ch in enumerate(text[s:e], s)) for s, e in sorted(zones + asides))
    unread = []
    if not first_line and not second and not row_lines:
        if sec.same_as_existing and sec.pointer is not None:  # the row only points to the existing facility
            return by_reference("Testing frequency, calculation period and first test date not set out; the proposed financial covenants "
                                "are 'Same as existing', i.e. as under the existing facility", ctx.quote(sec.pointer))
        hinted = _FREQ_HINT_RE.search(zone_text) or _PERIOD_HINT_RE.search(zone_text) or _FIRST_HINT_RE.search(zone_text)
        return not_stated(note=f"The {where} has wording on testing ('{tidy(hinted.group(0))}') that the rules could not read; check the term sheet."
                          if hinted else "")
    missing = []
    if not freq and not spring and not derived and not always:
        (unread if _FREQ_HINT_RE.search(zone_text) else missing).append("testing frequency")
    if not period:
        (unread if _PERIOD_HINT_RE.search(zone_text) else missing).append("calculation period")
    if not second:
        (unread if _FIRST_HINT_RE.search(zone_text) else missing).append("first test date")
    if row_lines:  # the row may deal with any of them
        unread, missing = [], []
    lines += head
    if second:
        lines += _first_lines(second, LINE + 40, 2)
    lines += row_lines
    if missing:
        # only the covenant wording was read for these points: the claim is made of that wording, not of the whole term sheet
        tail = " and ".join([", ".join(missing[:-1]), missing[-1]] if len(missing) > 1 else missing) + f" not stated in the {where}"
        if len(lines) == 1 and len(lines[0]) + len(tail) + 2 <= LINE:
            lines[0] += "; " + tail
        else:
            lines.append(_upper_first(tail))
    if sec.same_as_existing:
        lines[0] += " (same as existing)"
    ordered = [e for e in evidence if e]
    note = f"The {where} may also speak of the {' and the '.join(unread)}, in wording the rules could not read; check the term sheet." if unread else ""
    return stated(lines, ordered or _block_quote(ctx, sec.block), note)


@_safe
def select_definitions(ctx: Ctx) -> dict:
    """Equity cures, deemed cures, synergies, Adjusted EBITDA and the other definitions the covenants rest on."""
    a = _analyse(ctx)
    sec = a.sec if a.state in ("covenants", "names_only", "tangled", "reference") else None
    found: list[tuple[str, dict | None, bool]] = []  # (line, evidence, is only a pointer to another document)
    ranks: dict[str, int] = {}  # lines that give way first when the row runs out of room (0 = never before the others)
    unfinished: set[str] = set()  # lines whose statement carries on in the next line

    def add(prefix: str, text: str, quote: dict | None, pointer: bool = False, limit: int = LINE + 40, rank: int = 0) -> None:
        text = _lower_first(text.strip(" ,;:."))
        if not text or quote is None:
            return
        pieces = _first_lines(text, limit - len(prefix), 2)
        for i, piece in enumerate(pieces):
            line = prefix + ("… " if i else "") + piece
            if all(line != seen for seen, _, _ in found):
                found.append((line, quote, pointer))
                ranks[line] = rank
                if i + 1 < len(pieces):
                    unfinished.add(line)

    if sec is not None:
        text = sec.text

        def quote(x: int, y: int) -> dict | None:
            span = sec.span(x, y)
            return ctx.quote(sec.block, span) if span else None

        for s, e in _statements(text):
            sentence = text[s:e]
            cure = _EQUITY_CURE_RE.search(sentence) or _DEEMED_CURE_RE.search(sentence)
            if cure:
                start = s
                # (a covenant that opens after the cure wording, in the same sentence, is not part of it)
                e = min([c.start for c in a.covs if s + cure.end() <= c.start < e] + [e])
                if any(c.tiers and s <= c.first_level < s + cure.start() for c in a.covs):
                    # a covenant sentence that mentions the cure in passing: only the clause that holds the mention
                    start = s + max(sentence.rfind(ch, 0, cure.start()) for ch in ("(", ";", ",")) + 1
                    if text[start - 1:start] == "(" and text.find(")", start, e) > 0:
                        e = text.find(")", start, e)  # a bracketed aside ends with its bracket
                body = re.sub(r"^\W*(?:equity\s+cures?(?:\s+rights?)?|cure\s+rights?|deemed\s+cures?)\s*:\s*", "", text[start:e], flags=re.IGNORECASE)
                add("Deemed cures: " if _DEEMED_CURE_RE.search(body) and not _EQUITY_CURE_RE.search(body) else "Equity cures: ",
                    _clause(_balance(body)), quote(start, min(e, start + 60)))
                continue
            top, held = _def_wording(text, s, e)
            setter = next((c for c in a.covs if c.tiers and s <= c.first_level < e), None)  # the covenant this sentence sets
            if top is None or setter is not None:
                # no definition, or one only in a bracket after a term, or a covenant sentence that says in passing how its
                # ratio is defined: the sentence itself is not a definition
                if any(x <= s < y for x, y in a.unknown) or any(x <= s < y for c in a.covs for x, y, _ in c.extras):
                    continue
                if top is not None and not (setter.kind == "lev" and setter.a and setter.b) and not setter.tiers[0].verbatim:
                    # "Interest Cover, defined as the ratio of EBITDA to Net Finance Charges ..., shall not be less than 4.00:1":
                    # the defining clause only, up to the comma that leads on to the level
                    cut = text.rfind(",", top.end(), setter.first_level) if top.start() < setter.first_level else e
                    if cut > top.end():
                        named_first = text[top.start()] in "“\""
                        add("Adjusted EBITDA: ", "ratio definitions - " + ("" if named_first else setter.in_sentence + " ") + _clause(text[top.start():cut]),
                            quote(top.start(), min(e, top.start() + 60)))
                # terms of the covenant whose definition is given or pointed to in a bracket: "EBITDAR (to be defined as set
                # forth in the Existing Credit Agreement)"; the covenants' own names are dealt with below
                named = []
                for x, y in held:
                    ref = _def_aside(text, x)
                    term = _TERM_BEFORE_RE.search(text[s:x])
                    if ref is None or term is None or any(c.def_span == (x, y) for c in a.covs) or not _RATIO_PART_RE.search(term.group(1)) \
                            or re.match(r"(?:as\s+)?defined\s+(?:below|above|herein|hereinafter|therein)\b", ref[0], re.IGNORECASE):
                        continue
                    named.append((f"{tidy(term.group(1))} {ref[0]}", x, _defers(ref[0])))
                if named:
                    add("Adjusted EBITDA: ", "ratio definitions - " + "; ".join(n for n, _, _ in named), quote(named[0][1], min(e, named[0][1] + 60)),
                        pointer=all(p for _, _, p in named))
                asides = [x for x in re.finditer(r"\(([^()]{12,220})\)", sentence)]
                # where the definitions are left to another document: "(with definitions and calculations to be consistent
                # with the Existing Credit Agreement)", "Financial definitions to be consistent with ..."
                deferred = next((x for x in asides if _DEFS_POINTER_RE.search(x.group(1)) and _points(x.group(1))), None)
                if deferred:
                    add("Adjusted EBITDA: ", "ratio definitions - " + _clause(deferred.group(1)), quote(s + deferred.start(1), s + deferred.end(1)),
                        pointer=True)
                elif _DEFS_POINTER_RE.search(sentence) and _points(sentence) and len(sentence) <= 300 and not _first_mention(sentence):
                    add("Adjusted EBITDA: ", "ratio definitions - " + _lower_first(_clause(sentence)), quote(s, min(e, s + 60)), pointer=True)
                if setter is not None:
                    # an aside in a covenant sentence: "(with unrestricted cash netting capped at $200 million)", "(EBITDA to be
                    # defined in a manner to be agreed, including add-backs for restructuring costs capped at 15% of EBITDA)"
                    for aside in asides:
                        if any(c.def_span and c.def_span[0] == s + aside.start() for c in a.covs) or any(x <= s + aside.start() < y for x, y in held):
                            continue  # the bracket that defines the covenant's ratio, or one of its terms, has its own line
                        words = aside.group(1)
                        if _NETTING_RE.search(words) and re.search(r"\d", words):
                            add("Adjusted EBITDA: ", "cash netting - " + _clause(words), quote(s + aside.start(1), s + aside.end(1)))
                        elif _EBITDA_RE.search(words) and (_ADJUSTMENT_RE.search(words) or re.search(r"\bdefin", words, re.IGNORECASE)):
                            add("Synergies: " if _SYNERGY_RE.search(words) else "Adjusted EBITDA: ", _clause(words),
                                quote(s + aside.start(1), s + aside.end(1)), pointer=_defers(words))
                    # ... and a proviso that is not shown in the covenant's own row: "provided that cash netting shall be capped at ..."
                    for pa, pb in _provisos(text, s, e):
                        words = text[pa:pb]
                        if any(x <= pa < y for c in a.covs for x, y, _ in c.extras) or _first_mention(words):
                            continue
                        if _NETTING_RE.search(words) and re.search(r"\d", words):
                            add("Adjusted EBITDA: ", "cash netting - " + _clause(words), quote(pa, min(pb, pa + 80)))
                        elif _EBITDA_RE.search(words) and _ADJUSTMENT_RE.search(words):
                            add("Synergies: " if _SYNERGY_RE.search(words) else "Adjusted EBITDA: ", _clause(words), quote(pa, min(pb, pa + 80)))
                elif _NETTING_RE.search(sentence) and re.search(r"\d", sentence):
                    # a sentence of its own on what may be netted: "up to $150,000,000 of unrestricted cash may be netted against ..."
                    add("Adjusted EBITDA: ", "cash netting - " + _clause(sentence), quote(s, min(e, s + 60)))
                elif _EBITDA_RE.search(sentence) and _ADJUSTMENT_RE.search(sentence):
                    # ... or on what goes into EBITDA: "Consolidated EBITDA will include add-backs for ... capped at 25%"
                    add("Synergies: " if _SYNERGY_RE.search(sentence) else "Adjusted EBITDA: ", _clause(sentence), quote(s, min(e, s + 60)))
                elif _CALC_WORD_RE.search(sentence) and re.search(r"pro\s+forma", sentence, re.IGNORECASE) and _CALC_OF_RE.search(sentence) \
                        and len(sentence) <= 400 and not _first_mention(sentence):
                    # ... or on how the covenants are calculated: "For purposes of calculating the Financial Covenants ..., pro
                    # forma effect will be given to certain acquisitions ..."
                    add("Adjusted EBITDA: ", _clause(sentence), quote(s, min(e, s + 60)))
                continue
            related = _RELATED_DEFS_RE.match(sentence)
            if related:
                body = _clause(sentence[related.end():])
                add("Adjusted EBITDA: " if _EBITDA_RE.search(text) else "Definitions: ", "related definitions " + body[:1].lower() + body[1:],
                    quote(s, min(e, s + 60)), pointer=bool(points_elsewhere(sentence)))
                continue
            # "<by reference>, provided that “X” shall be defined ...": the definition starts at the quoted term
            cut = _PROVISO_RE.search(sentence)
            body_start = s + cut.end() if cut and cut.group(0).strip() and _DEF_SENTENCE_RE.search(sentence[cut.end():]) else s
            body = text[body_start:e]
            pointer = bool(points_elsewhere(body)) and not re.search(r"except|provided|add[\s-]?back|netting|\d", body, re.IGNORECASE)
            own = _TERM_DEFINED_AS_RE.match(body) or _QUOTED_TERM_RE.match(body)
            if own and not _RATIO_TERM_RE.search(own.group(1)):
                # a defined term that is not EBITDA, debt or a ratio keeps its own name: "Liquidity: the sum of ..."
                add(f"{_upper_first(tidy(own.group(1)))}: ", _clause(body[own.end():]), quote(body_start, min(e, body_start + 60)), pointer=pointer)
            elif _SYNERGY_RE.search(body):
                pieces = [p for p in re.split(r"(?:,?\s+and)?\s+(?=\((?:[ivx]{1,4}|[a-e])\)\s)", body) if p.strip()]
                syn = [p for p in pieces if _SYNERGY_RE.search(p)]
                other = [p for p in pieces if not _SYNERGY_RE.search(p)]
                if other and syn and len(pieces) > 1:
                    add("Adjusted EBITDA: ", _clause(" ".join(other)), quote(body_start, min(e, body_start + 60)))
                    at = text.find(syn[0], body_start)
                    add("Synergies: ", _clause(re.sub(r"^\(\w{1,4}\)\s*", "", " ".join(syn).strip())), quote(at, min(e, at + 80)) if at >= 0 else None)
                else:
                    add("Synergies: ", _clause(body), quote(body_start, min(e, body_start + 60)))
            elif _NETTING_RE.search(body) and not re.search(r"EBITDA[”\"]?\s+(?:shall|will|to|is)\s", body):
                add("Adjusted EBITDA: ", "cash netting - " + _clause(body), quote(body_start, min(e, body_start + 60)))
            elif _EBITDA_RE.search(body):
                add("Adjusted EBITDA: ", _clause(body), quote(body_start, min(e, body_start + 60)), pointer=pointer)
            else:
                term = _TERM_DEFINED_AS_RE.match(body) or _QUOTED_TERM_RE.match(body)
                if term:  # "“Relevant Period” means each period of twelve months ..." -> "Relevant Period: each period of ..."
                    add(f"{_upper_first(tidy(term.group(1)))}: ", _clause(body[term.end():]), quote(body_start, min(e, body_start + 60)), pointer=pointer)
        # how each ratio is put together, and ratios whose definition is left to another document
        for cov in a.covs:
            if cov.kind == "lev" and cov.a and cov.b and cov.tiers:
                comp = next((m for m in cov.mentions if m.a), None)
                sep = " / " if len(cov.a) + len(cov.b) <= 90 else ", to "
                add("Adjusted EBITDA: ", f"leverage definition - {cov.name} = {cov.a}{sep}{cov.b}",
                    quote(comp.start, min(comp.end, comp.start + 80)) if comp else None)
        refs: list[str] = []
        for cov in a.covs:  # one line for each definition given in a bracket after a covenant's name; covenants that share one share the line
            if not cov.def_ref or cov.def_ref.startswith("related definitions") or cov.def_ref in refs:
                continue
            refs.append(cov.def_ref)
            deferred = [c for c in a.covs if c.def_ref == cov.def_ref]
            first = deferred[0].mentions[0]
            verb = "is" if len(deferred) == 1 else "are"
            add("Adjusted EBITDA: ", f"ratio definitions - {_names([c.in_sentence for c in deferred])} {verb} {cov.def_ref}",
                quote(first.start, min(len(text), first.end + 40)), pointer=_defers(cov.def_ref))
        if sec.foot is not None:
            foot = _heal(tidy(sec.foot.text), _vocab(ctx))
            term = _TERM_DEFINED_AS_RE.match(foot)
            if term:
                add(f"{_upper_first(tidy(term.group(1)))}: ", _clause(foot[term.end():]), ctx.quote(sec.foot, re.escape(tidy(term.group(1)))))
            elif _DEFINITION_WORDS_RE.search(foot):
                add("Note: ", _clause(re.sub(r"^\W*\(?\d{1,2}[.)]\s*", "", foot)), ctx.quote(sec.foot))

    # labelled rows elsewhere in the term sheet
    near, inside = set(), set()
    consumed: set[int] = set()  # lines of the labelled rows read here
    unused: list[str] = []  # definitions found away from the term sheet's rows and not tied to the covenants: left out, and said in the note
    if sec is not None:
        pages = sec.block.pages or [sec.block.page]
        near = set(range(min(pages) - 1, max(pages) + 3))
        inside = {ln.n for ln in sec.block.lines}  # sub-labels of the covenant section itself were read above
    for label, heading, anywhere in ((_EQUITY_CURE_LABEL, "Equity cures: ", True), (_CASH_NETTING_LABEL, "Adjusted EBITDA: cash netting - ", True),
                                     (_EBITDA_LABEL, "Adjusted EBITDA: ", False), (_DEFS_LABEL, "Definitions: ", False)):
        for block in ctx.all(label):
            prefix = heading
            if block.line.n in inside or (not anywhere and block.page not in near):
                continue
            row = _resolve(ctx, block, label)
            if not row or len(row.text.split()) < 4:
                continue
            consumed.update(ln.n for ln in row.block.lines)
            if label is _DEFS_LABEL:
                # a list of definitions: only those the covenants rest on, one line each, never the whole list
                for s, e in _statements(row.text):
                    sentence = row.text[s:e]
                    if not _COVENANT_TERM_RE.search(sentence) or not (_DEF_SENTENCE_RE.search(sentence) or points_elsewhere(sentence)):
                        continue
                    span = row.span(s, min(e, s + 60))
                    term = _QUOTED_TERM_RE.match(sentence)
                    named = f"{_upper_first(tidy(term.group(1)))} = " if term else ""
                    add("Synergies: " if _SYNERGY_RE.search(sentence) and not _EBITDA_RE.search(sentence) else
                        "Equity cures: " if _EQUITY_CURE_RE.search(sentence) else "Adjusted EBITDA: ",
                        named + _clause(sentence[term.end():] if term else sentence), ctx.quote(row.block, span) if span else None,
                        pointer=bool(points_elsewhere(sentence)) and not re.search(r"\d", sentence))
                continue
            body = row.text.replace("\n", " ")
            digits = sum(ch.isdigit() for ch in body) / max(1, len(body))
            if not anywhere and (digits > 0.2 or not _DEFINITION_WORDS_RE.search(body)):
                continue
            if _SYNERGY_RE.search(row.label) or (prefix == "Adjusted EBITDA: " and _SYNERGY_RE.search(body) and not _EBITDA_RE.search(row.label)):
                prefix = "Synergies: "
            clause = _clause(body) + (" (same as existing)" if row.same_as_existing else "")
            add(prefix, clause, ctx.quote(row.block), pointer=bool(points_elsewhere(body)) and not re.search(r"\d", body))
    # Definitions set out in a paragraph of their own anywhere in the term sheet (“Consolidated EBITDA” shall ..., “Consolidated
    # Net Leverage Ratio” shall mean the ratio of ...): EBITDA, and the ratios the covenants test. In the term sheet's words.
    if sec is not None and a.state in ("covenants", "names_only"):
        tested = {frozenset(_name_words(c.name)): c.kind for c in a.covs if c.name}
        paras = _definition_paragraphs(ctx, inside | consumed)
        # An EBITDA definition is the facility's when it stands among the rows of the term sheet, or under a definitions
        # heading on a page that follows them ("Annex I - Certain Defined Terms"), or when the covenant section or the
        # definition of a covenant ratio uses the term (the EBITDA a presentation defines on a financial slide is not it).
        rows = sorted({b.page for b in ctx.all(_TERM_ROW_LABEL) if b.text and not b.inline})
        used = sec.text + " " + " ".join(p.text for t, p in paras if frozenset(_name_words(t)) in tested)
        for term, para in paras:
            among_rows = len(rows) > 1 and rows[0] <= para.page <= rows[-1]
            annexed = bool(rows) and para.page >= rows[0] and any(
                len(ln.text.strip()) <= 80 and _DEFS_HEADING_RE.search(ln.text) and not re.search(r"[.;,]\s*$", ln.text)
                for ln in ctx.doc.page_lines(para.page) if not ln.blank and ln.n < para.line.n)
            if frozenset(_name_words(term)) not in tested and not among_rows and not annexed and tidy(term).lower() not in tidy(used).lower():
                if _EBITDA_RE.search(term):
                    unused.append(f"'{tidy(term)}' (page {para.page})")
                continue
            body_sec = _Sec(block=para, text=_heal(tidy(para.text), _vocab(ctx)))
            head = _QUOTED_TERM_RE.match(body_sec.text)
            if head is None:
                continue
            name = _upper_first(tidy(term))
            lead = f"{name} = " if re.search(r"mean|defined|\bis\b", head.group(0)[head.end(1):], re.IGNORECASE) else f"{name} "
            body = body_sec.text[head.end():]
            if lead.endswith("= "):
                body = re.sub(r"^[\s,:]*(?:defined\s+(?:as|to\s+mean)\s+)?", "", body, flags=re.IGNORECASE)
            else:
                body = re.sub(r"^[\s:–—-]+", "", body)
            base = len(body_sec.text) - len(body)

            def para_quote(offset: int) -> dict | None:
                span = body_sec.span(base + offset, min(len(body_sec.text), base + offset + 60))
                return ctx.quote(para, span) if span else None

            kind = tested.get(frozenset(_name_words(term)))
            if _EBITDA_RE.search(term) and not re.search(r"ratio|leverage|cover", term, re.IGNORECASE):
                for prefix, said, offset, rank in _ebitda_points(lead, body):
                    add(prefix, _clause(said), para_quote(offset), pointer=_defers(said), rank=rank)
            elif kind is not None:
                label = {"lev": "leverage definition", "int": "interest cover definition"}.get(kind, "ratio definition")
                add("Adjusted EBITDA: ", f"{label} - {lead}{_clause(body)}", para_quote(0), pointer=_defers(body), rank=1)
    if not any(line.startswith("Equity cures") for line, _, _ in found):
        add("Equity cures: ", *_sentence_about(ctx, r"equity\s+cures?\b"))
    if not any(line.startswith("Deemed cures") for line, _, _ in found):
        add("Deemed cures: ", *_sentence_about(ctx, r"deemed\s+cures?\b"))
    if not any(line.startswith("Adjusted EBITDA") for line, _, _ in found) and a.state in ("covenants", "names_only"):
        sentence, q = _sentence_about(ctx, _COVENANT_CALC)
        if _EBITDA_RE.search(sentence):  # (a pricing grid "calculated by reference to the Leverage Ratio under the Credit Agreement" is not it)
            add("Adjusted EBITDA: ", sentence, q, pointer=True)

    note = ""
    if unused:
        note = (f"A definition of {', '.join(unused[:3])} stands outside the rows of the term sheet and is not used by the covenant section; "
                "it was not taken as the facility's definition. Check it.")
    if not found:
        return not_stated(note=note)
    if len(found) > 7:  # the figures (cures, synergies, caps) and the covenant ratios before the long lists; never more than the row holds
        found.sort(key=lambda x: ranks.get(x[0], 0))
        found = found[:7]
        if found[-1][0] in unfinished:  # the cut fell inside a statement: shown, never silent
            found[-1] = (found[-1][0] + " …", found[-1][1], found[-1][2])
    evidence = []
    for _, q, _ in sorted(found, key=lambda x: x[2]):
        if q and q not in evidence:
            evidence.append(q)
    lines = [line for line, _, _ in found]
    if all(pointer for _, _, pointer in found):
        return by_reference(lines, evidence, note)
    return stated(lines, evidence, note)


def _definition_paragraphs(ctx: Ctx, skip: set[int]) -> list[tuple[str, Block]]:
    """Paragraphs that open with a quoted term and say what it means, anywhere in the term sheet: (term, the paragraph as a
    block). A paragraph ends at a blank line; over a page break it carries on while its last line is unfinished and the
    next page starts in mid-sentence. Only whole paragraphs are returned (they end in a full stop)."""
    lines = ctx.doc.lines
    out: list[tuple[str, Block]] = []
    n = 0
    while n < len(lines):
        ln = lines[n]
        n += 1
        if ln.blank or ln.n in skip or ln.page in ctx.split_pages:
            continue
        m = _DEF_PARA_RE.match(ln.text)
        prev = next((x for x in reversed(lines[max(0, ln.n - 3):ln.n]) if not x.blank), None)
        if not m or (prev is not None and prev.n == ln.n - 1 and prev.page == ln.page and not re.search(r"[.;:]\s*$", prev.text)):
            continue  # (a quoted term at the start of a wrapped line inside a sentence is not the start of a definition)
        para = [ln]
        k = ln.n + 1
        while k < len(lines) and len(para) < 150:
            cur = lines[k]
            if cur.blank or is_footer(cur.text) or cur.page != para[-1].page:
                j = k
                while j < len(lines) and (lines[j].blank or is_footer(lines[j].text)):
                    j += 1
                carries_on = j < len(lines) and lines[j].page == para[-1].page + 1 and not re.search(r"[.:]\s*$", para[-1].text) \
                    and re.match(r"\s*[a-z(]", lines[j].text) and lines[j].page not in ctx.split_pages
                if not carries_on:
                    break
                k = j
                cur = lines[k]
            para.append(cur)
            k += 1
        n = max(n, k)
        block = Block(label=tidy(m.group(1)), line=para[0], lines=para, parts=[x.text.strip() for x in para], inline=False, mode="column")
        if re.search(r"[.]\W*$", block.text):
            out.append((tidy(m.group(1)), block))
    return out


def _enumerated(text: str) -> tuple[int, list[tuple[int, int]]]:
    """A passage that lists its points as (a) ..., (b) ... or (i) ..., (ii) ...: (where the list starts, the span of each item).
    Only labels that run in sequence at the top level of the passage count: the "(a)" of "clauses (a) and (e)" inside an
    item, or a nested (A) ... (B), does not start an item."""
    tops = [(x, y) for x, y in _brackets(text, 0, len(text)) if re.fullmatch(r"\((?:[a-z]|[ivx]{1,5}|\d{1,2})\)", text[x:y])]
    if not tops:
        return len(text), []
    # the list is the longest run of labels in sequence: "(a) ..., (b) ...", or the "(i) ..., (ii) ..." inside a lone "(a)"
    best: list[int] = []
    for k, (x0, y0) in enumerate(tops):
        first = text[x0 + 1:y0 - 1]
        if first not in ("a", "i", "1", "x"):
            continue
        if first == "i":
            order = _ROMAN
        elif first.isdigit():
            order = [str(i) for i in range(int(first), int(first) + 40)]
        else:
            order = [chr(c) for c in range(ord(first), ord("z") + 1)]
        starts, want = [x0], 1
        for x, y in tops[k + 1:]:
            if want < len(order) and text[x + 1:y - 1] == order[want]:
                starts.append(x)
                want += 1
        if len(starts) > len(best):
            best = starts
    if len(best) < 2:
        return len(text), []
    return best[0], [(s, best[i + 1] if i + 1 < len(best) else len(text)) for i, s in enumerate(best)]


def _brief(text: str, limit: int = 140) -> str:
    """A list item in a few of its own words: cut at a comma or before a bracket (never inside one), the cut shown by an ellipsis."""
    text = re.sub(r"[\s,;]+(?:and|or)$", "", tidy(text).rstrip(" ,;"), flags=re.IGNORECASE)
    if len(text) <= limit or (len(text) <= 240 and re.search(r"(?<![(\w])\d", text)):
        return text  # (an item that carries a figure is kept whole while it is short enough)
    spans = [(x, y) for x, y in _brackets(text, 0, len(text)) if y - x > 6]
    stops = [i for i, ch in enumerate(text[:limit]) if ch == "," and not any(x < i < y for x, y in spans)]
    stops += [x - 1 for x, _ in spans if 0 < x <= limit and text[x - 1] == " "]
    cut = max(stops) if stops and max(stops) >= limit * 3 // 5 else text.rfind(" ", 0, limit)
    piece = text[:cut].rstrip(" ,;")
    opened: list[int] = []  # a bracket left open by the cut goes with it
    for i, ch in enumerate(piece):
        if ch == "(":
            opened.append(i)
        elif ch == ")" and opened:
            opened.pop()
    if opened:
        piece = piece[:opened[0]].rstrip(" ,;")
    return piece + " …"


def _excerpt(text: str, limit: int) -> tuple[str, str]:
    """A long list item cut down to (its opening, the clause that carries its figure): "(a) pro forma adjustments, including
    run rate cost savings ... …" and "are expected to be taken within 18 months after ...". The second is empty when the
    item is short enough to stand whole, or has no figure after its opening."""
    text = re.sub(r"[\s,;]+(?:and|or)$", "", tidy(text).rstrip(" ,;"), flags=re.IGNORECASE)
    if len(text) <= limit:
        return text, ""
    lead = _brief(text, limit)
    spans = [(x, y) for x, y in _brackets(text, 0, len(text)) if y - x > 6]

    def top(i: int) -> bool:
        return not any(x < i < y for x, y in spans)

    # the clause that holds the figure runs from the noun its last "that" hangs on ("actions that have been taken or ... are
    # expected to be taken within 18 months"), or failing that from the last comma / "or" / "and" before the figure
    nouns = [m.start() for m in re.finditer(r"\S+\s+that\s+(?=[a-z])", text) if top(m.start())]
    opens = [m.end() for m in re.finditer(r",\s+|\s+(?:or|and)\s+(?=[a-z])", text) if top(m.start())]
    for fig in (m.start() for m in re.finditer(r"(?<![(\w])\d", text)):
        start = max([o for o in nouns if fig - 320 <= o <= fig] or [o for o in opens if fig - 240 <= o <= fig] or [-1])
        if start >= len(lead) - 2:
            return lead, text[start:]
    return lead, ""


def _ebitda_points(lead: str, body: str) -> list[tuple[str, str, int, int]]:
    """The lines for an EBITDA definition, in its own words: (prefix, text, offset in ``body`` for the quote, rank).

    A short definition is one line. A long one that lists its add-backs gives: the add-back for cost savings / synergies
    (its opening, and the clause with its time limit), the provisos that carry a figure (caps), the other add-backs in
    brief, and the words that open the definition. The rank orders them when the row runs out of lines."""
    body = body.strip()
    spans = [(x, y) for x, y in _brackets(body, 0, len(body)) if y - x > 6]
    cuts = [m.start() for m in _PROVISO_START_RE.finditer(body) if not any(x < m.start() < y for x, y in spans)]
    main = body[:cuts[0]] if cuts else body
    provisos = [(c, cuts[i + 1] if i + 1 < len(cuts) else len(body)) for i, c in enumerate(cuts)]
    list_start, items = _enumerated(main)
    if len(body) <= 2 * LINE or not items:
        if items or not _SYNERGY_RE.search(body):
            return [("Adjusted EBITDA: ", lead + body, 0, 0)]
        # no list of add-backs: the clause that speaks of cost savings / synergies goes under that prefix, the rest of the
        # definition under its own ("EBITDA = operating profit before ...; and including Pro Forma Cost Savings not exceeding 10%")
        cuts = [0] + [i + 1 for i, ch in enumerate(body) if ch == ";" and not any(x < i < y for x, y in spans)] + [len(body)]
        pieces = [(x, body[x:y]) for x, y in zip(cuts, cuts[1:]) if body[x:y].strip(" ;")]
        if len(pieces) > 1 and not all(_SYNERGY_RE.search(piece) for _, piece in pieces):
            out = []
            for x, piece in pieces:
                piece = re.sub(r"^\s*(?:and|or)\s+", "", piece.strip(" ;"), flags=re.IGNORECASE)
                # (the piece that opens the definition carries the term; a later one is shown as a continuation)
                said = lead + piece if x == 0 else piece if _SYNERGY_RE.search(piece) else f"… {piece}"
                out.append(("Synergies: " if _SYNERGY_RE.search(piece) else "Adjusted EBITDA: ", said, x, 0))
            return out
        return [("Synergies: " if len(lead) + len(body) <= LINE else "Adjusted EBITDA: ", lead + body, 0, 0)]
    out: list[tuple[str, str, int, int]] = []
    head = tidy(main[:list_start])
    last = head[head.rfind(", ", 0, max(0, len(head) - 2)) + 2:]  # the clause of the opening words that leads into the list
    opening = head if len(head) <= 100 else "… " + last if len(last) <= 110 else "…"
    labels = []
    for x, y in items:
        if _SYNERGY_RE.search(main[x:y]):
            labels.append(re.escape(main[x:main.index(")", x) + 1]))
            first, figure = _excerpt(main[x:y], LINE + 20 - len(lead) - len(opening))
            out.append(("Synergies: ", f"{lead}{opening} {first}", x, 0))
            if figure:
                out.append(("Synergies: ", f"… {figure}", x + main[x:y].find(figure[:40]) if figure[:40] in main[x:y] else x, 0))
    for x, y in provisos:
        clause = body[x:y]
        if re.search(r"(?<![(\w])\d", clause):
            about = _SYNERGY_RE.search(clause) or any(re.search(r"clauses?\s[^.;]{0,40}" + lab, clause) for lab in labels)
            out.append(("Synergies: " if about else "Adjusted EBITDA: ", clause, x, 0))
    out.append(("Adjusted EBITDA: ", f"{lead}{head} …", 0, 3))
    rest = [(x, _brief(main[x:y])) for x, y in items if not _SYNERGY_RE.search(main[x:y])]
    if rest:
        out.append(("Adjusted EBITDA: ", f"{lead}… " + "; ".join(r for _, r in rest), rest[0][0], 2))
    return out


def _sentence_about(ctx: Ctx, pattern: str) -> tuple[str, dict | None]:
    """The sentence of the running text that matches ``pattern`` (a pattern that fits on one source line), with its quote."""
    q = ctx.quote_text(pattern)
    if not q:
        return "", None
    rx = re.compile(pattern, re.IGNORECASE)
    lines = ctx.doc.lines
    hit = next((ln for ln in lines if not ln.blank and ln.page == q["page"] and rx.search(ln.text)), None)
    if hit is None:
        return "", None
    first = hit.n
    while first > 0 and hit.n - first < 6 and not lines[first - 1].blank and lines[first - 1].page == hit.page \
            and not re.search(r"[.:]\s*$", lines[first - 1].text):
        first -= 1
    last = hit.n
    while last + 1 < len(lines) and last - hit.n < 6 and not lines[last + 1].blank and lines[last + 1].page == hit.page \
            and not re.search(r"\.\s*$", lines[last].text):
        last += 1
    passage = _heal(tidy(" ".join(ln.text[ln.qstart:] if ln.qstart else ln.text for ln in lines[first:last + 1])), _vocab(ctx))
    passage = _BULLET_START_RE.sub("", passage)
    sentence = next((s for s in re.split(r"(?<=[a-z0-9\)])\.\s+(?=[A-Z])", passage) if rx.search(s)), "")
    # in a list ("...; violation of covenants (subject to equity cure rights); cross-default ...") only the item that speaks of it
    item = next((p for p in re.split(r";\s+(?![^()]*\))", sentence) if rx.search(p)), sentence)
    item = re.sub(r"^\s*(?:and|or)\s+", "", item, flags=re.IGNORECASE)
    item = _NEW_LABEL_RE.sub("", item, count=1) if _NEW_LABEL_RE.match(item) else item  # "Equity Cure: ..." without its label
    return _clause(item), q


RULES: dict = {
    "fc_leverage": fc_leverage,
    "fc_interest_cover": fc_interest_cover,
    "fc_other": fc_other,
    "fc_testing": fc_testing,
    "select_definitions": select_definitions,
}
