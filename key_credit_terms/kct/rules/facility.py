"""Rules for the Facility Info rows.

Fields: facility, borrowers, lender_commitments, purpose, maturity, repayment, accordion.

How the rules work
------------------
Every rule starts from the labelled sections of the term sheet ("Borrowers:", "Maturity:", "Increase Option:",
or the label cells of a one-page summary table) and assembles short lines from the wording it recognises there.
Nothing is assumed: a rule that finds no section, or cannot read the section with confidence, returns
``not_stated()``, and every line that is written is backed by a quote cut from the page. Where a rule cannot
compress a passage safely it keeps the passage's own words, and where a point is derived (a revolver is a
bullet; a ceiling on the facility gives the size of the increase) the line says "derived" / "not stated
expressly" and gives the basis.

1. Finding a section (``_find``). A label family (the ``L_...`` constants) is a pair: a loose pattern that may
   match any one line of a wrapped label, and a strict pattern the complete label must satisfy ("Facility",
   "Type and Amount of Facility", "364-Day Facility", but not "Facility Fee" or "Refinancing Facilities"). The
   shared block finder does the matching; this module then repairs what it gets wrong, mostly on summary tables:
     * rows of a table without colons run together into one label ("Admin agent Facility"), or the whole page
       is read as running text, or "Label:" rows set in from the margin run on to the end of the page: the rows
       are rebuilt from the label lines that match (``_own_rows``, ``_row_at``, ``_trim_plain``);
     * a label centred vertically in its row has value text above it, so the row above runs on into the next
       row's first lines: the block is extended upwards and cut back (``_extend_up``, ``_trim_overrun``);
     * a running footer the shared finder does not know stops a block at a page break (``_resume``); repeated
       header / footer lines are dropped (``_boilerplate``); numbered section headings whose rows carry their
       own labels are ignored; on a page read without layout the tail of a wrapped label is not a label;
     * a long section runs on to pages whose text has shifted to the left margin and is broken off at the next
       item of its own list: it is carried on while the lines are list items or sentences of the section
       (``_carry_over``); a block that had finished its sentence at the foot of a page is not carried on to a
       page that nothing ties to it (``_end_at_finished_page``).
   Where the term sheet has a part for each facility ("A. Revolving Credit Facility", "B. Term Loan Facility"),
   the heading above a section says which facility it is about (``_section_facility``).
2. Amendments (``_cell``). Where a page prints existing and proposed terms, the proposed term is read. On a
   layout page the shared view splitter separates the columns; on a page extracted in reading order the cell
   text is "existing proposed" and is divided at "Same as existing", "Same, except ..." or an amendment verb
   ("Reduce ...", "Eliminate ..."). Lines say "(same as existing)" or give the existing value.
3. Wording. Text is de-noised before matching ("364 -Day", "$5 ,000,000", "multi -currency", "[●]"),
   defined-term brackets are dropped, amounts are restyled ($1.25bn), "five (5) years" becomes "5 years" and
   "3.00 to 1.00" becomes "3.00x" (``_norm``, ``_style``). Quotes are cut from the untouched block text with a
   spacing-tolerant needle (``_loose``, ``_quote``). A word that extraction split in two is rejoined only if
   the document itself uses the joined word (``_mend``); a blank the term sheet leaves for a value is flagged.
4. Status. A section that only points elsewhere ("Same as under the Existing Credit Agreement", "customary for
   facilities of this type", "to be agreed", or the same as an agreement under any other defined name) gives a
   by_reference row that says what it points to (``_defers``, ``_refers``).
5. Less rather than wrong. A line never says the term sheet has no figure when the rules merely could not read
   one: the fall-back lines give the section's own opening words and the figures it mentions, with a note for
   the reviewer. An amount the term sheet leaves open in square brackets ("$[750][800] million") is printed
   as it stands and is never added up or dropped.

The rows
--------
facility            ``_analyse`` finds the tranches: amount + descriptors + type in either order, a row whose
                    label is the type ("Term Loan B: $900mm"), "Facility Amount" / "Type of Facility" rows, or
                    an amount whose type the document gives beside the same figure elsewhere (only if it gives
                    one type). A facility described as "existing" is not a tranche; an amount the wording
                    presents as the aggregate ("consisting of ...") is the total, not a tranche. Amounts in
                    square brackets and "equivalent" amounts are kept as such; two tranches of one type are told
                    apart by the currency they are named by; one facility divided into tranches lists them. Where
                    no label of the family is found, a section on the opening pages that opens with the facility
                    itself is used, with a note. Then an upsize, sub-limits (letters of credit, swingline, a
                    borrower's share), currencies (a list of alternative currencies is headed as such) and a
                    scheduled step-down of commitments.
borrowers           Names with their entity description from the opening sentence - or, where the section goes
                    facility by facility ("With respect to the ... Facility, ..."), one line for each facility -
                    the clause that lets borrowers be added, joint liability, and a table of sub-limits by
                    borrower if there is one.
lender_commitments  "Barclays = <amount>" from a commitment table (a Barclays row under a header that names
                    commitments, allocations or holds) or from a sentence stating the commitment Barclays has
                    made; otherwise not_stated, with Barclays' titles and one line naming the agent and arrangers.
purpose             The purposes after "the proceeds ... shall be used", item by item, per facility if the term
                    sheet separates them (in one section, in one section per facility, or in numbered items that
                    each have their own "shall be used"); the closing condition
                    that retires the existing facility is added as such; on a summary without a purpose row, the
                    purpose given in its introduction.
maturity            The tenor or date without the sentence's lead-in, one line per maturity section, bullet,
                    sub-headed paragraph or facility named; a maturity given only as a defined date is read where
                    that date is defined;
                    extension options ("+ 1 + 1: ..."), amend-and-extend, term-out, springing maturity.
repayment           The amortisation of each term loan with its profile (from the sentence, or from a two-column
                    table of percentages under it; a table the rules cannot read is mentioned, not pasted in), or
                    the statement that it has none; for
                    a revolver "Bullet (revolving; ...)" from what the term sheet says (no amortisation, due in
                    full, repay by a date). With nothing said, the bullet is derived only for a facility that is
                    a revolver, and the line says so. Voluntary prepayment in a last line.
accordion           "Yes = <cap>": a fixed amount, a greater-of basket with a ratio tranche, a short cell in its
                    own words, or - where the term sheet caps the facility after the increase - the difference
                    from the facility if that is unambiguous (marked derived) and otherwise the ceiling as such;
                    a figure of another agreement that the term sheet resets ("... shall be increased to $X (from
                    $Y)") in the term sheet's words; a ratio test that depends on the kind of debt limb by limb,
                    never as one ratio; then conditions, whether lenders must take part, and terms by reference;
                    "No" where the term sheet says none; "None stated in term sheet" where it is silent.

A rule never raises (``_guarded``): a failure becomes a note on a "not stated" row.
"""
from __future__ import annotations

import re
import weakref
from dataclasses import dataclass, field

from ..textmodel import Doc, Line, fragments, is_footer, tidy
from .blocks import Block, find_blocks
from .common import (LINE_LIMIT, MONEY_RE, SAME_AS_EXISTING_RE, Ctx, amounts, by_reference, fmt_money, money_mm, not_stated,
                     points_elsewhere, stated)

NONE_STATED = "None stated in term sheet"
BARCLAYS_NOT_STATED = "Barclays = not stated in term sheet"

# ======================================================================================================
# 1. Text helpers
# ======================================================================================================

# An amount as it appears after de-noising: "$1,250,000,000", "$1.25 billion", "$275mm", "US$500 million", "EUR 50m".
_M = (r"(?:US\$|U\.S\.\s?\$|USD\s?|\$|€|£|EUR\s?|GBP\s?)\s?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
      r"\s?(?:billion|bn|million|mm|mn|m|thousand|k)?(?![A-Za-z0-9])")
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
# "March 16, 2030", "16 March 2030", "July 2028"
_DATE = rf"(?:{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+{_MONTH},?\s+\d{{4}}|{_MONTH}\s+\d{{4}})"
_DATE_RE = re.compile(_DATE)
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
              "twelve": 12}
_NUM_WORD = "|".join(_NUM_WORDS)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
             "tenth": 10}
_BULLET_CHARS = "•·▪●◼■⚫‣"
_BULLET_SPLIT_RE = re.compile(r"\s*[" + _BULLET_CHARS + r"]\s*")  # bullets inside a joined table cell

# Extraction noise: stray spaces that layout extraction leaves inside words, figures and around punctuation.
_NOISE = (
    (re.compile(r"(?<=\w)-\s+(?=\w)"), "-"),                # "364-   Day", "non- consenting"
    (re.compile(r"(?<=\w)\s+-(?=\w)"), "-"),                # "364 -Day", "multi -currency"
    (re.compile(r"(?<=\d)\s*,\s*(?=\d{3}(?!\d))"), ","),    # "$5 ,000,000"
    (re.compile(r"([$€£])\s+(?=\d)"), r"\1"),               # "$ 75,000,000"
    (re.compile(r"\[\s*[●•◼■_]+\s*\]"), "[ ]"),             # "[●]", "[__]": a blank left for a value
    (re.compile(r"([“(\[])\s+"), r"\1"),                    # "(the “ Lenders"
    (re.compile(r"\s+([”)\],.;:])"), r"\1"),                # "Facility ”) ,"
    (re.compile(r"\b(Yen|Euros?|Sterling|Dollars|Francs|provided)(and|or|that)\b"), r"\1 \2"),  # "Japanese Yenand", "providedthat"
)
# "(as defined below)", "(defined below)", "(as hereinafter defined)": cross-references that carry no term.
_AS_DEFINED_RE = re.compile(r"\s*\((?:each\s+)?(?:as\s+)?(?:hereinafter\s+)?defined\s+(?:below|above|herein|therein)\)", re.IGNORECASE)
# A quoted defined term inside a bracket: (the “Facility”), (collectively, the "Borrowers").
_QUOTED_RE = re.compile(r"[“\"][^”\"]{1,70}[”\"]")
# "five (5) years", "ten (10) business days", "five years": a number word in front of a period. Case-sensitive on the
# period, so that the name of a defined term ("Five-Year Facility") is left alone.
_NUM_WORD_CASED = "|".join(f"[{w[0].upper()}{w[0]}]{w[1:]}" for w in _NUM_WORDS)
_WORD_PERIOD_RE = re.compile(
    rf"\b({_NUM_WORD_CASED})\b(?:\s*\(\s*\d{{1,3}}\s*\))?(?=[\s-]*(?:years?|months?|days?|business\s+days?|fiscal\s+quarters?|quarters?)\b)")
# "3.00 to 1.00", "1.25:1.00": a ratio written out.
_RATIO_WORDS_RE = re.compile(r"(?<![\w.])(\d{1,2}\.\d{1,2})\s*(?:to|:)\s*1(?:\.0{1,2})?(?![\d.]*\d)")
# "50 basis points"
_BPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s+basis\s+points?", re.IGNORECASE)
# Sentence end: a full stop followed by a capital. Abbreviations ("Inc.", "N.A.", "U.S.") are not sentence ends.
_SENT_BREAK_RE = re.compile(r"(?<=[\w)\]”\"%])\.\s+(?=[A-Z“\"(\[•])")
_ABBREV_END_RE = re.compile(r"(?:\b(?:Inc|Corp|Ltd|Co|Sr|Jr|No|Nos|St|vs|approx)|\b[A-Z])$")
# Words that open a new sentence after a name ending in an abbreviation: "... Acme Finance B.V. Each Borrower will be ..."
_OPENS_SENTENCE_RE = re.compile(r"(?:The|Each|All|Any|If|Such|This|These|Those|Upon|Subject|After|Following|Notwithstanding|With\s+respect\s+to|"
                                r"In\s+(?:respect\s+of|the\s+case\s+of|addition|each\s+case))\s")
# A line that ends a sentence (closing quotes / brackets allowed after the stop).
_CLOSED_RE = re.compile(r"[.;:][”\")\]]*\s*$")
# A bracket that carries a figure (an amount, a percentage, a decimal) is substance, not a definition.
_HAS_FIGURE_RE = re.compile(r"[$€£%]|\d\.\d")
# "Inc.." left behind when "Inc. (the “Company”)." loses its bracket.
_DOUBLE_STOP_RE = re.compile(r"(?<!\.)\.\.(?!\.)")
# "10 (10) days": a figure repeated in brackets.
_REPEATED_NUMBER_RE = re.compile(r"\b(\d{1,3})\s*\(\s*\1\s*\)")
# "two (2) one-year extension options": a number word with the same number in brackets, wherever it stands.
_WORD_AND_DIGIT_RE = re.compile(rf"\b({_NUM_WORD_CASED})\s*\(\s*(\d{{1,2}})\s*\)")
# A bracketed aside of some length: "(on terms and conditions satisfactory to the Administrative Agent)".
_ASIDE_RE = re.compile(r"\s*\([^()]{12,}\)")
_DIGIT_RE = re.compile(r"\d")  # any figure
# Several full stops at the end of a name ("N.A..").
_TRAILING_STOPS_RE = re.compile(r"\.{2,}$")
# A name that ends with an abbreviation keeps its full stop: "Inc.", "Corp.", "N.A.", "S.p.A."
_ABBREV_STOP_RE = re.compile(r"(?:\b(?:Inc|Corp|Ltd|Co)|\b[A-Z]\.[A-Z]|\b[A-Z]\.\w\.[A-Z])\.$")
_LEADING_DIGITS_RE = re.compile(r"\d+")  # "5" in "5th"
# Small words that stay in lower case in a title.
_SMALL_WORD_RE = re.compile(r"\b(And|Of|The|To|For|In)\b")
# A word, for the document's own vocabulary.
_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_NON_WORD_RE = re.compile(r"\W")  # punctuation and spaces, to compare two names
_NOT_ALNUM_RE = re.compile(r"[^a-z0-9]")  # the same, on lower-cased text
# "the" at the start of a phrase.
_LEADING_THE_RE = re.compile(r"^the\s+", re.IGNORECASE)
# A cell that only refers back: "Same as under the Existing Credit Agreement", "Same as existing"
_SAME_AS_START_RE = re.compile(r"\W*same\s+as\b", re.IGNORECASE)


def _norm(text: str) -> str:
    """Collapse whitespace and remove extraction noise; the words themselves are untouched."""
    text = tidy(text or "")
    for rx, rep in _NOISE:
        text = rx.sub(rep, text)
    return text.replace("[]", "[ ]")  # a blank left for a value stays visible


def _loose(text: str, limit: int = 110) -> str:
    """A regex that finds ``text`` whatever the spacing: matching is done on de-noised text, quoting on the page text.
    A blank ("[ ]" after de-noising) matches whatever the page has between its brackets."""
    pieces = [r"\s*".join(re.escape(c) for c in piece if not c.isspace()) for piece in text[:limit].split("[ ]")]
    return r"\s*\[[^\]]{0,8}\]\s*".join(pieces)


def _drop_defined(text: str) -> str:
    """Remove brackets that only define a term - (the “Facility”), (collectively, the “Borrowers”) - but keep
    brackets that carry substance (figures, or no quoted term)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "(":
            depth, j = 1, i + 1
            while j < n and depth:
                depth += text[j] == "("
                depth -= text[j] == ")"
                j += 1
            inner = text[i + 1:j - 1] if depth == 0 else None
            if inner is not None and len(inner) <= 220 and _QUOTED_RE.search(inner) and not _HAS_FIGURE_RE.search(inner):
                while out and out[-1] == " ":
                    out.pop()
                i = j
                continue
        out.append(text[i])
        i += 1
    return _DOUBLE_STOP_RE.sub(".", "".join(out))


def _figures(text: str) -> str:
    """House style for numbers: "five (5) years" -> "5 years", "3.00 to 1.00" -> "3.00x", "50 basis points" -> "50 bps"."""
    text = _WORD_PERIOD_RE.sub(lambda m: str(_NUM_WORDS[m.group(1).lower()]), text)
    text = _WORD_AND_DIGIT_RE.sub(lambda m: m.group(2) if _NUM_WORDS.get(m.group(1).lower()) == int(m.group(2)) else m.group(0), text)
    text = _REPEATED_NUMBER_RE.sub(r"\1", text)
    text = _RATIO_WORDS_RE.sub(lambda m: f"{float(m.group(1)):.2f}x", text)
    return _BPS_RE.sub(r"\1 bps", text)


_MIN_MONEY_MM = 0.001  # $1,000: anything smaller is not an amount a facility row deals in
# The currency in front of an amount, as the house style writes it.
_HOUSE_CURRENCY = {"€": "EUR ", "EUR": "EUR ", "£": "GBP ", "GBP": "GBP "}


def _money_match(m: re.Match) -> tuple[float, str] | None:
    """(value in millions, house-style text) of a MONEY_RE match; None for a figure too small to be an amount."""
    mm = money_mm(m)
    if mm is None or mm < _MIN_MONEY_MM:
        return None
    cur = (m.group("cur") or "").upper().replace(" ", "").replace(".", "")
    return mm, fmt_money(mm, _HOUSE_CURRENCY.get(cur, "$"))


def _restyle(text: str) -> str:
    """Amounts in house style ("$1,250,000,000" -> "$1.25bn"). Unlike the shared restyle_money() this keeps the space
    between an amount and a bracket that follows it, and leaves figures under $1,000 as the page prints them."""
    def sub(m: re.Match) -> str:
        found = _money_match(m)
        if found is None:
            return m.group(0)
        whole = m.group(0)
        return found[1] + whole[len(whole.rstrip()):]
    return MONEY_RE.sub(sub, text)


def _style(text: str, defined: bool = True) -> str:
    """A passage ready to be used in a line: de-noised, defined-term brackets dropped, figures in house style."""
    text = _norm(text)
    if defined:
        text = _drop_defined(text)
    text = _AS_DEFINED_RE.sub("", text)
    return _norm(_restyle(_figures(text)))


def _clip(text: str, limit: int = LINE_LIMIT) -> str:
    """Cut at a clause or word boundary; a cut line ends with an ellipsis so the reader knows there is more."""
    text = tidy(text)
    if len(text) <= limit:
        return text
    cut = text[:limit - 2]
    for sep in ("; ", ", ", " "):
        i = cut.rfind(sep)
        if i >= limit * 0.6:
            return cut[:i].rstrip(" ,;:(") + " …"
    return cut.rstrip() + " …"


def _fit(text: str, limit: int) -> str:
    """Shorten an over-long line by dropping its brackets that carry no figure, longest first, before cutting it."""
    text = tidy(text)
    while len(text) > limit:
        asides = [m for m in _ASIDE_RE.finditer(text) if not _DIGIT_RE.search(m.group(0))]
        if not asides:
            break
        m = max(asides, key=lambda x: len(x.group(0)))
        text = text[:m.start()] + text[m.end():]
    return _clip(text, limit)


def _sents(text: str) -> list[str]:
    """Sentences of running text; "Inc.", "N.A." and "U.S." do not end one."""
    out, start = [], 0
    for m in _SENT_BREAK_RE.finditer(text):
        if _ABBREV_END_RE.search(text[start:m.start()]) and not _OPENS_SENTENCE_RE.match(text, m.end()):
            continue  # "Acme Holdings, Inc. and ...": the stop belongs to the abbreviation ("... Acme B.V. Each Borrower will ..." does end there)
        out.append(text[start:m.start() + 1].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def _cap(text: str) -> str:
    """First letter in upper case, the rest untouched."""
    return text[:1].upper() + text[1:] if text else text


# Ordinary words that open a sentence or a table cell; anything else in first place is taken to be a name.
_COMMON_OPENER_RE = re.compile(
    r"(?:The|An?|Each|All|Any|At|In|On|Subject|Subsequent|Upon|Up|Not|No|None|Loans|Advances|Voluntary|Freely|Same|Consistent|"
    r"Substantially|Beginning|Unless|Permits?|Full|Cash|One|Two|Three|Four|Reduce|Increase|Eliminate|Remove|Removal|Add|Retain|Amend|"
    r"Extend|Earlier|Later|Individual|Provided|From|During|Following|Prior|To|For|If|Customary|Limited|Similar|Initially|Unlimited|"
    r"Multicurrency|Letters|Such|Other|Certain|Its|Their|Working|General|Fifth|First|Greater|Lesser|Incremental|Uncommitted|"
    r"Additional|Aggregate|Maximum|Minimum|Amounts?|Increases?|Permitted|Proceeds|Payable|Repayable|After|Before|Until|With|As|By|"
    r"Where|When|Those|These|This|That|Borrowings)\b")


def _lower_first(text: str) -> str:
    """Lower-case the first letter unless the word is a name or an acronym ("MK may", "Parent", "U.S.")."""
    if len(text) > 1 and text[0].isupper() and text[1].islower() and _COMMON_OPENER_RE.match(text):
        return text[0].lower() + text[1:]
    return text


def _strip_end(text: str) -> str:
    """Without the closing full stop, comma, colon or semicolon."""
    return text.strip().rstrip(".;:, ").strip()


def _strip_name(text: str) -> str:
    """Like ``_strip_end`` but keeps the full stop of an abbreviation: "Acme Holdings, Inc.", "First National Bank, N.A."."""
    text = _TRAILING_STOPS_RE.sub(".", text.strip().rstrip(";:, ").strip())
    if text.endswith(".") and not _ABBREV_STOP_RE.search(text):
        text = text.rstrip(". ")
    return text


def _first_amount(text: str) -> tuple[float, str] | None:
    """(value in millions, house-style text) of the first amount in ``text``."""
    for m in MONEY_RE.finditer(text or ""):
        found = _money_match(m)
        if found:
            return found
    return None


# An amount the term sheet leaves open in square brackets (after de-noising): "$[750][800] million" (alternatives),
# "$[1.55][1.6] billion", "$[750] million" (a figure not yet final), "$[ ] million" (a blank) - or the whole amount in
# the brackets, as drafts usually write a figure that is not yet settled: "[$750,000,000]", "[$500 million]".
_WHOLE_OPEN_M = r"\[\s?(?:US\$|U\.S\.\s?\$|USD\s?|\$|€|£|EUR\s?|GBP\s?)\s?\d[\d.,]*(?:\s?(?:billion|bn|million|mm|mn|m)(?![A-Za-z0-9]))?\s?\]"
_OPEN_M = (r"(?:(?:US\$|U\.S\.\s?\$|\$|€|£)\s?(?:\[\s?(?:\d[\d.,]*)?\s?\]\s?){1,3}(?:\s?(?:billion|bn|million|mm|mn|m)(?![A-Za-z0-9]))?|"
           + _WHOLE_OPEN_M + r")")
_OPEN_M_RE = re.compile(r"(?P<cur>US\$|U\.S\.\s?\$|\$|€|£)\s?(?P<body>(?:\[\s?(?:\d[\d.,]*)?\s?\]\s?){1,3})\s?(?P<unit>billion|bn|million|mm|mn|m)?(?![A-Za-z0-9])",
                        re.IGNORECASE)
_WHOLE_OPEN_M_RE = re.compile(_WHOLE_OPEN_M, re.IGNORECASE)
_OPEN_UNITS = {"billion": "bn", "bn": "bn", "million": "m", "mm": "m", "mn": "m", "m": "m"}
# A figure in square brackets inside a line: "[750]", "[1.6]", "[$500m]", "[EUR 50m]", "[5] years"
_BRACKET_FIGURE_RE = re.compile(r"\[(?:[$€£]|[A-Z]{3}\s)?\d[\d.,]*(?:bn|m|k)?\]")
_BRACKETS_NOTE = "figures in square brackets are left open in the term sheet"


def _open_amount(text: str) -> str:
    """An amount left open in square brackets, as the page prints it but with the house unit: "$[750][800] million" ->
    "$[750][800]m", "[$500,000,000]" -> "[$500m]", "$[ ] million" -> "$[ ] million" (a blank keeps its words). "" if
    ``text`` does not open with one."""
    text = (text or "").strip()
    whole = _WHOLE_OPEN_M_RE.match(text)
    if whole:  # the whole amount stands inside the brackets
        inner = _first_amount(whole.group(0))
        return f"[{inner[1]}]" if inner else ""
    m = _OPEN_M_RE.match(text)
    if not m:
        return ""
    cur = (m.group("cur") or "").upper().replace(" ", "").replace(".", "")
    body = re.sub(r"\s+", "", m.group("body")).replace("[]", "[ ]")
    unit = (m.group("unit") or "").lower()
    if not _DIGIT_RE.search(body):  # a blank: nothing to restyle
        return f"{_HOUSE_CURRENCY.get(cur, '$')}{body}" + (f" {unit}" if unit else "")
    return f"{_HOUSE_CURRENCY.get(cur, '$')}{body}{_OPEN_UNITS.get(unit, '')}"


def _read_amount(text: str) -> tuple[float, str] | None:
    """(value in millions, house-style text) of the amount ``text`` opens with. An amount the term sheet leaves open in
    square brackets has no known value: (-1.0, the amount as printed)."""
    left_open = _open_amount(text)
    if left_open:
        return -1.0, left_open
    return _first_amount(text)


def _to_int(text: str) -> int | None:
    """"5", "five", "fifth", "5th" -> 5."""
    text = text.strip().lower()
    m = _LEADING_DIGITS_RE.match(text)
    if m:
        return int(m.group(0))
    return _NUM_WORDS.get(text) or _ORDINALS.get(text)


def _title(label: str) -> str:
    """A label as a title: "JOINT LEAD ARRANGERS AND JOINT BOOKRUNNERS" -> "Joint Lead Arrangers and Joint Bookrunners"."""
    label = _norm(label).strip(" :")
    if label.isupper() or label.islower():
        label = _SMALL_WORD_RE.sub(lambda m: m.group(1).lower(), label.title())
        label = label.replace("L/c", "L/C").replace("(S)", "(s)")
    return _cap(label)


def _bullets(text: str) -> list[str]:
    """The points of a bulleted table cell."""
    return [p.strip() for p in _BULLET_SPLIT_RE.split(text) if p.strip()]


def _strip_bullet(text: str) -> str:
    """Without a leading bullet or dash."""
    return text.lstrip(_BULLET_CHARS + " \t-–")


# ======================================================================================================
# 2. Sections: finding a labelled block and repairing table rows
# ======================================================================================================

_MEMO: "weakref.WeakKeyDictionary[Ctx, dict]" = weakref.WeakKeyDictionary()


def _memo(ctx: Ctx) -> dict:
    """Per-document scratch space (boilerplate lines, the facility analysis), dropped with the context."""
    try:
        return _MEMO.setdefault(ctx, {})
    except TypeError:  # an object that cannot be weakly referenced: work without a cache
        return {}


def _whole(ctx: Ctx) -> str:
    """The whole document as one de-noised string, for wording that is looked for outside the labelled sections."""
    memo = _memo(ctx)
    if "whole" not in memo:
        memo["whole"] = _norm(ctx.text)
    return memo["whole"]


def _vocabulary(ctx: Ctx) -> dict[str, int]:
    """How often each word occurs in the document (lower case)."""
    memo = _memo(ctx)
    if "vocab" not in memo:
        counts: dict[str, int] = {}
        for word in _WORD_RE.findall(ctx.text):
            word = word.lower()
            counts[word] = counts.get(word, 0) + 1
        memo["vocab"] = counts
    return memo["vocab"]


# Two word-like pieces separated by one space: candidates for a word that extraction split ("increm ental", "re pay").
_SPLIT_WORD_RE = re.compile(r"\b([A-Za-z]{1,12}) (?=([a-z]{2,12})\b)")


def _mend(ctx: Ctx, line: str) -> str:
    """Rejoin a word that layout extraction split in two. The document is its own dictionary: the pieces are joined
    only if the joined word is used elsewhere in the document at least twice and one of the pieces hardly ever
    stands alone."""
    vocab = _vocabulary(ctx)

    def join(m: re.Match) -> str:
        a, b = m.group(1).lower(), m.group(2).lower()
        whole, rare = vocab.get(a + b, 0), min(vocab.get(a, 0), vocab.get(b, 0))
        return m.group(1) if whole >= 2 and rare <= 2 and whole > rare else m.group(0)
    return _SPLIT_WORD_RE.sub(join, line)


def _label(line: str, full: str | None = None) -> tuple[str, re.Pattern]:
    """A label family: (pattern for one line of the label, pattern the complete label must match)."""
    return line, re.compile(full or line, re.IGNORECASE)


# Section number in front of a heading: "II.", "3.", "A."
_HEADING_RE = re.compile(r"^\s*(?:[IVXLC]{1,5}|\d{1,2}|[A-Z])\.\s+\S")
# "Existing Terms   Proposed Terms" printed as one line on a page extracted in reading order.
_PLAIN_AMEND_HEADER_RE = re.compile(r"^\s*(?:existing|current)(?:\s+terms?)?\s+(?:proposed|amended|new)(?:\s+terms?)?\s*$", re.IGNORECASE)
# The proposed cell of an amendment table on such a page: "... Same as existing" at the end of the cell,
_SAME_TAIL_RE = re.compile(r"\s*\bsame(?:\s+as\s+(?:existing|current))\W*$", re.IGNORECASE)
# "Same, except that ..." / "Same as existing, except ..." after the existing text,
_SAME_EXCEPT_RE = re.compile(r"\bSame,?\s+(?:as\s+existing,?\s+)?except\b")
# or a proposed cell that opens with an amendment verb after the existing text ("... debt Reduce incremental capacity to").
_CHANGE_VERB_RE = re.compile(r"(?<=[a-z0-9)%])\s+(?=(?:Reduce|Increase|Eliminate|Remove|Add|Retain|Amend|Extend|Replace|Delete|Revise|"
                             r"Lower|Raise|Change|Upsize|Tighten|Reset|Removal\s+of|No\s+change)\b)")


def _boilerplate(ctx: Ctx) -> set[str]:
    """Running headers and footers: short whole lines repeated on most pages ("Restricted - External")."""
    memo = _memo(ctx)
    if "boiler" not in memo:
        pages: dict[str, set[int]] = {}
        count: dict[str, int] = {}
        for ln in ctx.raw.lines:
            t = tidy(ln.text)
            if 4 <= len(t) <= 60 and not t.endswith(":") and not SAME_AS_EXISTING_RE.match(t):
                pages.setdefault(t, set()).add(ln.page)
                count[t] = count.get(t, 0) + 1
        need = max(3, (len(ctx.raw.pages) + 1) // 2)
        memo["boiler"] = {t for t, pp in pages.items() if len(pp) >= need and count[t] <= len(pp) + 2}
    return memo["boiler"]


def _label_idx(block: Block) -> int:
    """Index in ``block.lines`` of the label line: in a column layout, the first line at the smallest indent
    (lines pulled in above a vertically centred label sit deeper)."""
    if block.mode != "column" or not block.lines:
        return 0
    head = [ln for ln in block.lines[:14] if ln.page == block.lines[0].page]
    low = min(ln.indent for ln in head)
    for i, ln in enumerate(head):
        if ln.indent <= low + 1:
            return i
    return 0


def _label_line(block: Block) -> Line:
    """The line of a block that carries its label."""
    return block.lines[_label_idx(block)]


def _value_col(block: Block, k: int) -> int | None:
    """Column where the value text starts: the second cell of a label line, else the indent of the first value line
    (a label may wrap over several lines before any value text appears)."""
    base = block.lines[k].indent
    for ln in block.lines[k:k + 6]:
        if abs(ln.indent - base) > 1:
            return ln.indent
        cells = fragments(ln.text, 3)
        if len(cells) > 1:
            return cells[1][0]
    return None


def _part(ln: Line) -> str:
    """Value text of a continuation line (on a split page, the proposed column only)."""
    return ln.text[ln.qstart:].strip() if ln.qstart and ln.indent >= ln.qstart else ln.text.strip()


def _rebuild(block: Block, lines: list[Line], parts: list[str], label: str | None = None, line: Line | None = None) -> Block:
    """A copy of ``block`` over other lines (and, if given, another label)."""
    return Block(label=label if label is not None else block.label, line=line or block.line, lines=lines, parts=parts,
                 inline=block.inline, mode=block.mode)


def _colon_style(ctx: Ctx, view: Doc, page: int) -> bool:
    """True when the labels on this page end with a colon (a term sheet), false for a table whose label cells
    have none (a summary slide). Decides whether a label without a colon can be a wrapped piece of a longer one."""
    memo = _memo(ctx)
    key = ("colon", id(view), page)
    if key not in memo:
        with_colon = total = 0
        for ln in view.page_lines(page):
            cells = fragments(ln.text, 3)
            if len(cells) < 2 or not cells[0][2][:1].isupper() or len(cells[0][2].split()) > 6:
                continue
            total += 1
            with_colon += cells[0][2].rstrip().endswith(":")
        memo[key] = total > 0 and with_colon / total >= 0.25
    return memo[key]


def _row_at(view: Doc, ln: Line) -> Block | None:
    """One row of a table without colons, rebuilt from its label line: the label cell, the value beside it and
    the value lines below, up to the next line that carries a label or a blank line."""
    cells = fragments(ln.text, 3)
    if not cells:
        return None
    lines, parts = [ln], [ln.text[cells[0][1]:].strip()]
    n = ln.n + 1
    while n < len(view.lines) and len(lines) < 40:
        cur = view.lines[n]
        n += 1
        if cur.page != ln.page or cur.blank or cur.indent <= ln.indent + 1:
            break
        if is_footer(cur.text):
            continue
        lines.append(cur)
        parts.append(_part(cur))
    return Block(label=tidy(cells[0][2]).rstrip(": "), line=ln, lines=lines, parts=parts, inline=False, mode="column")


def _own_rows(ctx: Ctx, view: Doc, block: Block, full_re: re.Pattern) -> list[Block]:
    """The sections of the family that a block of the shared finder holds: the block itself if its complete label
    belongs to the family, and the rows it ran together. The shared finder marks the lines after a label as used,
    so in a table it reads as one block ("Admin agent Facility" as one label; a whole page of one-line rows as one
    value) the rows after the first are found only here."""
    if not block.lines:
        return []
    colon = _colon_style(ctx, view, block.page)
    first = block.lines[0]
    if block.mode == "plain" and not colon and len(fragments(first.text, 3)) > 1:
        # one-line rows with no colons and no indented lines: the page was read as running text
        rows = []
        for ln in block.lines:
            cells = fragments(ln.text, 3)
            if ln.page == first.page and len(cells) > 1 and abs(ln.indent - first.indent) <= 1 and full_re.fullmatch(_norm(cells[0][2]).strip(" :")):
                rows.append(_row_at(view, ln))
        return [r for r in rows if r is not None]
    if block.mode == "plain" and first.indent > 0:
        # "Label:" rows set a space or two in from the margin, read as running text: cut at each label line
        starts = [0] + [i for i in range(1, len(block.lines))
                        if 0 < block.lines[i].indent <= first.indent + 1 and _INDENTED_LABEL_RE.match(block.lines[i].text)]
        rows = []
        for a, b in zip(starts, starts[1:] + [len(block.lines)]):
            if a == 0:
                label, parts = block.label, block.parts[:b]
            else:
                head, _, value = block.lines[a].text.partition(":")
                label, parts = tidy(head), [value.strip()] + block.parts[a + 1:b]
            if full_re.fullmatch(_norm(label).strip(" :")):
                rows.append(Block(label=label.rstrip(": "), line=block.lines[a], lines=block.lines[a:b], parts=parts, inline=block.inline, mode="plain"))
        return rows
    if full_re.fullmatch(_norm(block.label).strip(" :")):
        return [block]
    if block.mode != "column" or colon:
        return []
    # rows of a colon-less table merged into one label: every label line of the run that belongs to the family
    k = _label_idx(block)
    base = block.lines[k].indent
    rows = []
    for ln in block.lines[k:k + 6]:
        if ln.page != block.lines[k].page or abs(ln.indent - base) > 1:
            continue
        cells = fragments(ln.text, 3)
        if cells and full_re.fullmatch(_norm(cells[0][2]).strip(" :")):
            rows.append(_row_at(view, ln))
    return [r for r in rows if r is not None]


def _without_boilerplate(ctx: Ctx, block: Block) -> Block:
    """The block without the running header / footer lines that fell inside it."""
    junk = _boilerplate(ctx)
    k = _label_idx(block)
    keep = [i for i, part in enumerate(block.parts) if i == k or tidy(part) not in junk]
    if len(keep) == len(block.parts):
        return block
    return _rebuild(block, [block.lines[i] for i in keep], [block.parts[i] for i in keep])


def _extend_up(view: Doc, block: Block) -> Block:
    """A label centred vertically in its table row has the start of its value on the lines above it. Pull those
    lines in when the value beside the label reads as a continuation, or when both it and the lines above are
    bullets standing alone after a blank line. (The shared finder does this only for unindented continuations;
    the hanging indent of a bulleted cell defeats it.)"""
    if block.mode != "column" or not block.lines or _label_idx(block) != 0:
        return block
    lab = block.lines[0]
    col = _value_col(block, 0)
    first = tidy(block.parts[0])
    if col is None or not first:
        return block
    run: list[Line] = []
    after_blank = False
    n = lab.n - 1
    while n >= 0 and len(run) < 12:
        prev = view.lines[n]
        if prev.page != lab.page or is_footer(prev.text):
            break
        if prev.blank:
            after_blank = True
            break
        if prev.indent < col - 8:  # a line that carries a label: the row above
            break
        run.insert(0, prev)
        n -= 1
    if not run or _CLOSED_RE.search(run[-1].text):
        return block
    continuation = first[0].islower()
    bullets = first[0] in _BULLET_CHARS and _part(run[0])[:1] in _BULLET_CHARS and after_blank
    # the text beside the label hangs under a bullet on the line above: the wrapped second line of that bullet
    hanging = _part(run[-1])[:1] in _BULLET_CHARS and first[0] not in _BULLET_CHARS and 2 <= col - run[-1].indent <= 6
    if not (continuation or bullets or hanging):
        return block
    if not after_blank:
        # no blank line above: the run may open with the lower half of the row above, so take only the bullet
        # point that wraps round the label (correct before complete)
        for i in range(len(run) - 1, -1, -1):
            if _part(run[i])[:1] in _BULLET_CHARS:
                run = run[i:]
                break
    return _rebuild(block, run + block.lines, [_part(x) for x in run] + block.parts, line=lab)


def _centred_page(ctx: Ctx, view: Doc, page: int) -> bool:
    """True when the labels of the table on this page are centred vertically in their rows: some label line has
    value text directly above it that follows a blank line (and so cannot belong to the row above)."""
    memo = _memo(ctx)
    key = ("centred", id(view), page)
    if key not in memo:
        lines = view.page_lines(page)
        labelled = [ln for ln in lines if len(fragments(ln.text, 3)) > 1 and len(fragments(ln.text, 3)[0][2].split()) <= 6]
        base = min((ln.indent for ln in labelled), default=0)
        found = False
        for i, ln in enumerate(lines):
            if ln.blank or ln.indent > base + 1 or len(fragments(ln.text, 3)) < 2:
                continue
            j = i - 1
            while j >= 0 and not lines[j].blank and lines[j].indent > base + 6:
                j -= 1
            if j < i - 1 and (j < 0 or lines[j].blank):
                found = True
                break
        memo[key] = found
    return memo[key]


def _trim_overrun(ctx: Ctx, view: Doc, block: Block) -> Block:
    """Cut off the lines that belong to the next row of a table. When the next label is centred vertically, the
    first lines of its value come before it and the block above has swallowed them. They are recognised by the
    line directly above the next label being unfinished (or the next label's value reading as a continuation)."""
    if block.mode != "column" or len(block.lines) < 2:
        return block
    k = _label_idx(block)
    lab, last = block.lines[k], block.lines[-1]
    if last.n + 1 >= len(view.lines):
        return block
    nxt = view.lines[last.n + 1]
    if nxt.blank or nxt.page != last.page or nxt.indent > lab.indent + 6 or is_footer(nxt.text):
        return block
    cells = fragments(nxt.text, 3)
    if len(cells) < 2 or len(cells[0][2].split()) > 7:
        return block
    nxt_value = nxt.text[cells[0][1]:].strip()
    if not (nxt_value[:1].islower() or not _CLOSED_RE.search(block.parts[-1] or "")):
        return block
    # the run of lines directly above the next label, back to a blank line
    j = len(block.lines) - 1
    while j > 0 and block.lines[j - 1].n == block.lines[j].n - 1:
        j -= 1
    if j > k:  # a blank line separates that run from the rest of this block: the run is the next row's
        return _rebuild(block, block.lines[:j], block.parts[:j]) if block.lines[j - 1].page == block.lines[j].page else block
    first = tidy(block.parts[k])
    if not first:
        return block
    if not _colon_style(ctx, view, lab.page) and _centred_page(ctx, view, lab.page):
        # A centred label has as many value lines below it as above it. This row keeps as many lines after its
        # label as it has before it (k); what is left over is the top half of the next row, if that row has
        # about as many lines under its own label.
        below, n = 0, nxt.n + 1
        while n < len(view.lines) and not view.lines[n].blank and view.lines[n].page == nxt.page and view.lines[n].indent > lab.indent + 6:
            below += 1
            n += 1
        after = [i for i in range(k + 1, len(block.lines)) if block.lines[i].indent > lab.indent + 6]
        excess = after[k:]
        if excess and len(excess) <= below + 1:
            head = tidy(block.parts[excess[0]])
            carries_on = nxt_value[:1].islower() or (head[:1] in _BULLET_CHARS and nxt_value[:1] not in _BULLET_CHARS)
            if below > 0 or carries_on:  # a one-line row below owns the line above it only if its text carries on from it
                keep = [i for i in range(len(block.lines)) if i not in excess]
                return _rebuild(block, [block.lines[i] for i in keep], [block.parts[i] for i in keep])
            return block
    if first[0] in _BULLET_CHARS:
        return block
    col = _value_col(block, k)
    for i in range(k + 1, len(block.lines)):
        part = tidy(block.parts[i])
        if part[:1] in _BULLET_CHARS or (col is not None and block.lines[i].indent > col + 3):
            return _rebuild(block, block.lines[:i], block.parts[:i])
    return block


def _labelish(text: str) -> bool:
    """The line opens with something shaped like a label (a short capitalised first cell)."""
    cells = fragments(text, 3)
    if not cells:
        return False
    first = cells[0][2]
    return (first[:1].isupper() or first[:1].isdigit()) and len(first.split()) <= 7 and (
        first.rstrip().endswith(":") or len(cells) > 1 or len(text.strip()) < 50)


def _resume(ctx: Ctx, view: Doc, block: Block) -> Block:
    """Carry a block over a page break at which the shared finder stopped because of a running footer it does not
    know (a document id such as "123456789_2" at the left margin reads to it as a new label). The block is resumed
    only when nothing but blank lines and repeated header / footer lines follow it on its page."""
    if block.mode != "column" or not block.lines:
        return block
    junk = _boilerplate(ctx)
    last = block.lines[-1]
    n = last.n + 1
    stopped_by_footer = False
    while n < len(view.lines) and view.lines[n].page == last.page:
        ln = view.lines[n]
        if tidy(ln.text) in junk and not is_footer(ln.text):
            stopped_by_footer = True
        elif not (ln.blank or is_footer(ln.text)):
            return block
        n += 1
    if not stopped_by_footer or n >= len(view.lines):
        return block
    k = _label_idx(block)
    base, col = block.lines[k].indent, _value_col(block, k)
    lines, parts = list(block.lines), list(block.parts)
    prev_page, shifted = last.page, False
    while n < len(view.lines) and len(lines) < 260:
        cur = view.lines[n]
        n += 1
        if cur.blank or is_footer(cur.text) or tidy(cur.text) in junk:
            continue
        if cur.page != prev_page:
            prev_page = cur.page
            shifted = cur.indent <= base + 6 and not _labelish(cur.text)
        if shifted:
            cells = fragments(cur.text, 3)
            if len(cells) > 1 and cells[0][2].rstrip().endswith(":") and _labelish(cur.text):
                break
        elif col is not None and cur.indent < col - 3 and cur.indent <= base + 6:
            break
        elif cur.indent <= base + 1 and _labelish(cur.text) and fragments(cur.text, 3)[0][2].rstrip().endswith(":"):
            break
        lines.append(cur)
        parts.append(_part(cur))
    return _rebuild(block, lines, parts) if len(lines) > len(block.lines) else block


# A line that ends a sentence with a full stop (closing quotes / brackets allowed after it).
_FULL_STOP_END_RE = re.compile(r"\.[”\")\]]*\s*$")


# A list marker at the start of a line: "(ii)", "(b)", "(3)"
_LIST_MARK_RE = re.compile(r"^\s*\((?P<mark>[ivx]{1,5}|[a-z]|\d{1,2})\)\s")
_ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx")


def _carries_on(block: Block, line: str) -> bool:
    """The line carries on the block: it is the next item of a list the block has begun ("(ii)" after "(i)", "(c)" after
    "(b)"; a first item only after a line that ends with a colon), or it starts in lower case, in the middle of a sentence."""
    m = _LIST_MARK_RE.match(line)
    if not m:
        return line.strip()[:1].islower()
    mark = m.group("mark")
    before: list[str] = []  # the marker(s) that would stand in front of this one in its series
    if mark.isdigit():
        before = [str(int(mark) - 1)] if int(mark) > 1 else []
    else:
        if mark in _ROMAN and _ROMAN.index(mark) > 0:
            before.append(_ROMAN[_ROMAN.index(mark) - 1])
        if len(mark) == 1 and mark > "a":
            before.append(chr(ord(mark) - 1))
    text = block.text
    if any(f"({b})" in text for b in before):
        return True
    first_of_list = mark in ("1", "a", "i")
    return first_of_list and tidy(block.parts[-1] or "").endswith(":")


def _has_value_column(view: Doc, page: int, col: int) -> bool:
    """Some line of the page starts in the value column ``col`` or beyond it (give or take a few columns): the page is
    set out in two columns like the page the block began on."""
    return any(not ln.blank and not is_footer(ln.text) and ln.indent >= col - 8 for ln in view.page_lines(page))


def _end_at_finished_page(view: Doc, block: Block) -> Block:
    """End a block at a page break it should not have crossed. The shared finder carries a block on to a page whose text
    starts at the left margin, taking the page for a shifted continuation. Where the block had ended its sentence at the
    foot of the page before, the new page has no value column, and its first line neither goes on with the block's list nor
    starts in lower case, nothing ties that page to the section (it may be an annex or a schedule): the block ends at the
    break. A section that does go on there with a new paragraph is cut short, which is the safe side."""
    if block.mode != "column" or len(block.lines) < 2:
        return block
    k = _label_idx(block)
    base, col = block.lines[k].indent, _value_col(block, k)
    if col is None or col < base + 12:
        return block
    for i in range(k + 1, len(block.lines)):
        prev, cur = block.lines[i - 1], block.lines[i]
        if cur.page == prev.page or not _FULL_STOP_END_RE.search(block.parts[i - 1] or "") or _has_value_column(view, cur.page, col):
            continue
        head = _rebuild(block, block.lines[:i], block.parts[:i])
        if not _carries_on(head, cur.text):
            return head
    return block


def _carry_over(ctx: Ctx, view: Doc, block: Block) -> Block:
    """Carry a block on over pages whose text has shifted to the left margin. Layout offsets differ from page to page:
    a long section may run on to pages where nothing sits in the value column any more, and there the shared finder
    takes the first line at the left margin - "(ii) no Lender will be required ..." - for a new label and breaks the
    section off in the middle of its list. The block is carried on only where all of this holds: it stopped on a page
    after the one its label is on, that page has no line in the value column, the block does not end on a full stop,
    and the line it stopped at is not a "Label:" row. On such pages it then ends only at a "Label:" row; on a page
    that has the value column again it ends, as usual, at the next line in the label column."""
    if block.mode != "column" or not block.lines:
        return block
    k = _label_idx(block)
    lab = block.lines[k]
    base, col = lab.indent, _value_col(block, k)
    if col is None or col < base + 12 or _FULL_STOP_END_RE.search(block.parts[-1] or ""):
        return block
    junk = _boilerplate(ctx)

    def skip(ln: Line) -> bool:
        return ln.blank or is_footer(ln.text) or tidy(ln.text) in junk

    def label_row(ln: Line) -> bool:
        cells = fragments(ln.text, 3)
        return len(cells) > 1 and cells[0][2].rstrip().endswith(":") and _labelish(ln.text)

    n = block.lines[-1].n + 1
    while n < len(view.lines) and skip(view.lines[n]):
        n += 1
    if n >= len(view.lines):
        return block
    stop = view.lines[n]
    if stop.page <= lab.page or _has_value_column(view, stop.page, col) or label_row(stop):
        return block
    if not _carries_on(block, stop.text):
        return block  # nothing says the line belongs to this section: the next item of its list, or the rest of its sentence
    lines, parts = list(block.lines), list(block.parts)
    page, shifted = stop.page, True
    while n < len(view.lines) and len(lines) < 420:
        cur = view.lines[n]
        n += 1
        if skip(cur):
            continue
        if cur.page != page:
            page, shifted = cur.page, not _has_value_column(view, cur.page, col)
        if shifted:
            if label_row(cur):
                break
        elif cur.indent < col - 3 and cur.indent <= base + 6:
            break
        lines.append(cur)
        parts.append(_part(cur))
    return _rebuild(block, lines, parts) if len(lines) > len(block.lines) else block


def _starts_fresh(view: Doc, block: Block) -> bool:
    """On a page read without layout, a wrapped label reads as two labels and the second one's text starts
    mid-sentence ("ADMINISTRATIVE First National Bank ... as sole and" / "AGENT: exclusive administrative agent").
    True when the label line follows a blank line, the top of the page or a finished sentence."""
    lab = _label_line(block)
    if lab.n == 0:
        return True
    prev = view.lines[lab.n - 1]
    return prev.blank or prev.page != lab.page or bool(_CLOSED_RE.search(prev.text))


def _is_section_heading(block: Block) -> bool:
    """A numbered heading ("II. Facility") whose rows carry their own labels: the rows are found on their own."""
    k = _label_idx(block)
    if not _HEADING_RE.match(block.lines[k].text) or tidy(block.parts[k]):
        return False
    for ln, part in zip(block.lines[k + 1:], block.parts[k + 1:]):
        if not tidy(part):
            continue
        cells = fragments(ln.text, 3)
        return bool(cells) and len(cells[0][2].split()) <= 6 and (len(cells) > 1 or cells[0][2].rstrip().endswith(":"))
    return False


# "Label:" set one to three spaces in from the left margin, on a page read as running text.
_INDENTED_LABEL_RE = re.compile(r"^\s{1,3}[A-Z][A-Za-z /&\-()’']{2,44}:(\s|$)")


def _trim_plain(block: Block) -> Block:
    """On a page read as running text the shared finder ends a block at the next "Label:" line only when that line
    starts in the first column; a list of rows set a space or two in from the margin runs on to the end of the
    page. Cut the block at the next label line that sits at the label's own indent."""
    if block.mode != "plain" or len(block.lines) < 2:
        return block
    base = block.lines[0].indent
    for i in range(1, len(block.lines)):
        ln = block.lines[i]
        if 0 < ln.indent <= base + 1 and _INDENTED_LABEL_RE.match(ln.text):
            return _rebuild(block, block.lines[:i], block.parts[:i])
    return block


# A value cell of a numeric table (capitalisation, pricing grid, financial summary): "$2,157mm", "2.1x", "2029", "–", "n/a", "Jun-27"
_NUMERIC_CELL_RE = re.compile(r"[$€£]?\(?\d[\d.,]*\)?\s?(?:mm|mn|m|bn|k|x|%|bps)?|[-–—]|n/?a|[A-Z][a-z]{2}-\d{2}", re.IGNORECASE)


def _numeric_row(ln: Line) -> bool:
    """The line is a row of a table of figures - a label and two or more cells that are each only a number, a
    ratio, a year or a dash ("Term Loan B   $2,157mm   2.1x   2029"). Such a row is not a term of the facility."""
    cells = fragments(ln.text, 3)
    return len(cells) >= 3 and all(_NUMERIC_CELL_RE.fullmatch(_norm(c[2])) for c in cells[1:])


def _anchor_page(ctx: Ctx) -> int | None:
    """The page of the first Borrower section: where the terms of the facility begin."""
    return _zone(ctx)[2]


def _zone(ctx: Ctx) -> tuple[int, int, int | None]:
    """(first page, last page, page of the first Borrower section) of the part of the document that sets out the
    terms of the facility. In a term sheet that is the whole document. In a lender presentation the summary of terms
    comes after pages of other tables (capitalisation, the terms of a notes offering) whose rows carry the same
    labels - "Maturity", "Size", "Use of proceeds" - and are not terms of the facility: where the first Borrower
    section is beyond the second page, sections are read from its page on, and only up to the page before a later
    summary that opens with an "Issuer" row."""
    memo = _memo(ctx)
    if "zone" not in memo:
        last = len(ctx.raw.pages)
        memo["zone"] = (1, last, None)  # set first: the lookups below come back through _find
        first = next((b for b in _find(ctx, L_BORROWER, zone=False) if len(_strip_end(b.text)) >= 3), None)
        if first is not None:
            start = first.page if first.page > 2 else 1
            issuer = next((b.page for b in _find(ctx, L_ISSUER, zone=False) if b.page > first.page), None)
            memo["zone"] = (start, issuer - 1 if issuer else last, first.page)
    return memo["zone"]


def _find(ctx: Ctx, spec: tuple[str, re.Pattern], view: Doc | None = None, zone: bool = True) -> list[Block]:
    """Sections whose complete label belongs to the family, in document order, with table rows repaired. With
    ``zone`` (the default) only sections in the part of the document that sets out the terms are returned."""
    line_pat, full_re = spec
    doc = view if view is not None else ctx.doc
    try:
        raw = ctx.blocks(line_pat) if view is None else find_blocks(doc, line_pat)
    except re.error:
        return []
    out: list[Block] = []
    seen: set[int] = set()
    for found in raw:
        for block in _own_rows(ctx, doc, found, full_re):
            if not block.lines or _is_section_heading(block) or _numeric_row(_label_line(block)):
                continue
            key = _label_line(block).n
            if key in seen:
                continue
            block = _carry_over(ctx, doc, _end_at_finished_page(doc, _resume(ctx, doc, _trim_plain(block))))
            block = _trim_overrun(ctx, doc, _extend_up(doc, _without_boilerplate(ctx, block)))
            if not block.text:
                continue
            if block.mode == "plain" and block.text[:1].islower() and not _starts_fresh(doc, block):
                continue  # the tail of a wrapped label on a page read without layout: its text starts mid-sentence
            seen.add(key)
            out.append(block)
    out.sort(key=lambda b: _label_line(b).n)
    if not zone:
        return out
    start, end, _ = _zone(ctx)
    return [b for b in out if start <= b.page <= end]


def _section_facility(ctx: Ctx, block: Block) -> str:
    """The facility a section belongs to where the term sheet has a part for each facility ("A. Revolving Credit
    Facility" ... "B. Term Loan Facility"): the house name of the facility in the nearest heading above the section,
    "" if that heading names none. A heading is a numbered line, or a short line standing alone that names a facility."""
    doc = ctx.doc
    n = _label_line(block).n - 1
    steps = 0
    while n >= 0 and steps < 120:
        ln = doc.lines[n]
        n -= 1
        steps += 1
        if ln.blank or is_footer(ln.text):
            continue
        cells = fragments(ln.text, 3)
        if len(cells) != 1 or len(cells[0][2]) > 70 or _CLOSED_RE.search(ln.text):
            continue
        kind = _kind(cells[0][2])
        numbered = bool(_HEADING_RE.match(ln.text))
        # an un-numbered heading stands alone between blank lines (the first line of a wrapped label does not)
        alone = (ln.n == 0 or doc.lines[ln.n - 1].blank) and (ln.n + 1 >= len(doc.lines) or doc.lines[ln.n + 1].blank)
        named = alone and kind not in _GENERIC_KINDS + _SUB_KINDS and len(cells[0][2].split()) <= 7 and cells[0][2][:1].isupper()
        if numbered or named:
            return kind if kind not in _GENERIC_KINDS + _SUB_KINDS else ""
    return ""


def _top_level(blocks: list[Block]) -> list[Block]:
    """Drop sub-sections that sit inside an earlier block ("Revolving Credit Facility:" inside "Senior Credit Facility:")."""
    out: list[Block] = []
    end = -1
    for b in blocks:
        if _label_line(b).n <= end:
            continue
        out.append(b)
        end = max(end, b.lines[-1].n)
    return out


def _quote(ctx: Ctx, block: Block | None, snippet: str | None = None) -> dict | None:
    """Evidence from ``block``: the clause around ``snippet`` (text as matched after de-noising), else its opening."""
    if block is None:
        return None
    try:
        if snippet:
            found = ctx.quote(block, _loose(snippet))
            if found:
                return found
        found = ctx.quote(block)
        if found:
            return found
        # a table cell too short to quote on its own ("5 years", "None", "$100mm"): the whole row as printed
        ln = _label_line(block)
        row = tidy(ctx.raw.lines[ln.n].text) if ln.n < len(ctx.raw.lines) else ""
        if 8 <= len(row) <= 300 and ctx.raw.has_quote(row, ln.page):
            return {"quote": row, "page": ln.page}
    except (re.error, IndexError, ValueError):
        pass
    return None


def _quote_text(ctx: Ctx, snippet: str, pages=None) -> dict | None:
    """Evidence for wording found outside a labelled section: the page line that holds ``snippet``. The shared
    lookup reads one page line at a time, so wording that wraps over two lines is looked for by its opening words
    and then by its closing words."""
    snippet = tidy(snippet or "")
    tried: set[str] = set()
    for piece in (snippet[:60], snippet[:36], snippet[-36:], snippet[:22], snippet[-22:]):
        piece = piece.strip()
        if len(piece) < 12 or piece in tried:
            continue
        tried.add(piece)
        try:
            found = ctx.quote_text(_loose(piece, 60), pages)
        except (re.error, IndexError, ValueError, AttributeError):
            found = None
        if found:
            return found
    return None


# ---- amendment cells -----------------------------------------------------------------------------------

@dataclass
class _Cell:
    """The value of a labelled section, read as the proposed term."""
    block: Block  # where ``text`` can be quoted from
    text: str  # the term as it will stand (the existing text where the proposed cell defers to it), de-noised
    same: bool = False  # the proposed cell reads "Same as existing"
    old: str = ""  # the existing term, where the page restates or changes it
    old_block: Block | None = None
    change: str = ""  # a proposed cell that describes a change ("Reduce ... to $100 million") instead of restating


def _plain_amendment_page(ctx: Ctx, page: int) -> bool:
    """A page read in plain order (no columns) that prints an "Existing ... Proposed" table."""
    memo = _memo(ctx)
    key = ("plain_amend", page)
    if key not in memo:
        memo[key] = (page not in ctx.split_pages and not ctx.doc.has_columns(page)
                     and any(_PLAIN_AMEND_HEADER_RE.match(ln.text) for ln in ctx.doc.page_lines(page)))
    return memo[key]


def _cell(ctx: Ctx, block: Block, spec: tuple[str, re.Pattern]) -> _Cell:
    """The value of a section as it will stand, with what the page says about the existing term (see ``_Cell``)."""
    text = _norm(block.text)
    if block.page in ctx.split_pages:
        twin = None
        mine = _label_line(block).n
        for b in _find(ctx, spec, view=ctx.existing):
            if _label_line(b).n == mine:
                twin = b
                break
        twin_text = _norm(twin.text) if twin is not None else ""
        if SAME_AS_EXISTING_RE.match(text):
            return _Cell(twin, twin_text, same=True) if twin_text and twin is not None else _Cell(block, "", same=True)
        if twin_text and twin_text != text and not SAME_AS_EXISTING_RE.match(twin_text):
            return _Cell(block, text, old=twin_text, old_block=twin)
        return _Cell(block, text, same=bool(twin_text) and twin_text == text)  # the proposed column restates the existing term
    if _plain_amendment_page(ctx, block.page):
        m = _SAME_TAIL_RE.search(text)
        if m:
            return _Cell(block, text[:m.start()].strip(), same=True)
        m = _SAME_EXCEPT_RE.search(text) or _CHANGE_VERB_RE.search(text)
        if m and m.start() > 0:
            return _Cell(block, text[:m.start()].strip(), change=text[m.start():].strip())
    return _Cell(block, text)


# ======================================================================================================
# 3. Facility
# ======================================================================================================

# Words that describe a facility between its amount and its type.
_DESC_WORD = (r"(?:senior|secured|unsecured|super[\s-]?senior|super-?priority|first[\s-]lien|second[\s-]lien|priority|delayed[\s-]draw|"
              r"multi-?\s?currency|364-?\s?day|\d{1,2}-?\s?year|(?:" + _NUM_WORD + r")-?\s?year|amorti[sz]ing|non-amorti[sz]ing|committed|"
              r"syndicated|sustainability-linked|asset-based|cash[\s-]flow|new|master|U\.S\.|US|dollar|euro|sterling|initial|guaranteed|"
              r"standby|backstop|bilateral|replacement|working[\s-]capital)")
# The type of facility.
_KIND_WORDS = (r"(?:revolving\s+(?:credit\s+|loan\s+)?facilit(?:y|ies)|revolving\s+credit\s+commitments?|revolver|SSRCF|RCF|"
               r"term\s+loan\s+[AB]\s+facility|term\s+[AB]\s+loans?(?:\s+facility)?|term\s+[AB]\s+facility|term\s+loan\s+facilit(?:y|ies)|"
               r"term\s+loan\s+[AB]\b|term\s+loans?|term\s+facility|TL[AB]\b|swing\s?-?line\s+facility|(?:letter\s+of\s+credit|L/?C)\s+facility|"
               r"bridge\s+(?:loan\s+)?facility|credit\s+facilit(?:y|ies)|loan\s+facility)")
# "$2,000,000,000 364-day senior revolving credit facility", "An up to $550,000,000 five-year revolving credit facility"
# The amount may be one the term sheet leaves open in square brackets, and may be an equivalent in another currency:
# "a $[750][800] million five-year Revolving Credit Facility", "a $250 million equivalent five-year Euro Term Loan Facility"
_MX = rf"(?:{_M}|{_OPEN_M})"
_AMOUNT_FIRST_RE = re.compile(rf"(?P<upto>up\s+to\s+)?(?P<amt>{_MX})\s+(?P<eq>equivalent\s+)?(?P<desc>(?:{_DESC_WORD}\s+){{0,6}})(?P<kind>{_KIND_WORDS})",
                              re.IGNORECASE)
# "A senior secured revolving credit facility (the “Revolving Credit Facility”) in an amount up to $1,000,000,000",
# "Revolving Credit Facility: $750 million", "Term Loan B - $1,250 million", "a revolving credit facility of EUR 50,000,000"
# "a term loan facility denominated in Euros in an aggregate principal amount equal to the Euro equivalent of $150,000,000",
# "an asset-based revolving credit facility with aggregate commitments of $600,000,000"
_KIND_FIRST_RE = re.compile(
    rf"(?P<desc>(?:{_DESC_WORD}\s+){{0,6}})(?P<kind>{_KIND_WORDS})\s*(?:\([^()]{{0,90}}\)\s*)?,?\s*(?:(?:to\s+be\s+)?denominated\s+in\s+[A-Za-z.]+"
    rf"(?:\s+[A-Za-z.]+){{0,2}}?\s+)?(?:in\s+an?\s+(?:aggregate\s+)?(?:principal\s+|committed\s+)?amount\s+(?:of\s+|equal\s+to\s+|not\s+to\s+exceed\s+)?|"
    rf"in\s+the\s+(?:aggregate\s+)?(?:principal\s+)?amount\s+of\s+|with\s+(?:aggregate\s+|total\s+)?commitments\s+(?:of\s+|in\s+an\s+aggregate\s+"
    rf"(?:principal\s+)?amount\s+(?:of\s+|equal\s+to\s+))|of\s+|:\s*(?:an?\s+)?|[-–]\s+)"
    rf"(?P<equiv>the\s+(?:[\w.]+\s+){{1,2}}equivalent\s+of\s+)?(?P<upto>up\s+to\s+)?(?P<amt>{_MX})(?P<eq>\s+equivalent\b)?", re.IGNORECASE)
# "An aggregate principal amount (the “Facility Amount”) of $3,000,000,000 (the “Revolving Facility”"
_AGG_NAMED_RE = re.compile(
    rf"aggregate\s+(?:principal\s+)?amount\s*(?:\([^()]{{0,60}}\)\s*)?of\s+(?P<upto>up\s+to\s+)?(?P<amt>{_M})\s*\((?:the\s+)?[“\"]\s*"
    rf"(?P<name>[^”\"]{{3,60}}?)\s*[”\"]", re.IGNORECASE)
# A cell that opens with the amount: "$3,000,000,000.", "Up to $275mm"
_AMOUNT_START_RE = re.compile(rf"^\W*?(?P<upto>up\s+to\s+)?(?P<amt>{_MX})", re.IGNORECASE)
# An amount left blank: "up to $[●]", "$[ ]"
_BLANK_AMOUNT_RE = re.compile(r"(?P<upto>up\s+to\s+)?(?P<cur>[$€£])\s?\[[^\]\d]{0,8}\]", re.IGNORECASE)
# A cell that opens with the type: "364-day unsecured multi-currency revolving credit facility (the ..."
_TYPE_START_RE = re.compile(rf"^\W*(?:an?\s+|the\s+)?(?P<desc>(?:{_DESC_WORD}\s+){{0,6}})(?P<kind>{_KIND_WORDS})", re.IGNORECASE)
# The type next to a figure elsewhere in the document: "RCF capacity of $225mm", "$750mm Revolving Credit Facility"
_KIND_NEAR_RE = re.compile(
    rf"(?P<kind>\bRCF\b|revolving\s+credit\s+facility|revolver|term\s+loan(?:\s+[AB]\b)?)(?:\s+\w+){{0,3}}\s+(?:of\s+)?\(?(?P<amt>{_M})|"
    rf"(?P<amt2>{_M})\)?\s+(?:\w+\s+){{0,3}}?(?P<kind2>\bRCF\b|revolving\s+credit\s+facility|revolver|term\s+loan(?:\s+[AB]\b)?)", re.IGNORECASE)
# "upsized from $750 million to $1,000 million", "increased from $1.0bn to $1.25bn"
_UPSIZE_FROM_RE = re.compile(rf"(?:upsized?|increased?)\s+from\s+(?P<old>{_M})\s+to\s+(?P<new>{_M})", re.IGNORECASE)
# "to be upsized to $1,000,000,000", "increased by $250 million to $1.0 billion"
_UPSIZE_TO_RE = re.compile(rf"(?:upsized?|increased?)\s+(?:by\s+{_M}\s+)?to\s+(?P<new>{_M})", re.IGNORECASE)
# "$1,000,000,000 upsize of the Company's existing $9,000,000,000 ... Facility"
_UPSIZE_OF_RE = re.compile(rf"(?P<add>{_M})\s+upsize\s+of\s+[^.$€£]{{0,80}}?existing\s+(?P<old>{_M})", re.IGNORECASE)

_LC = r"(?:(?:standby|commercial|multi-?\s?currency|performance|financial|trade)\s+(?:and\s+)?)*(?:letters?\s+of\s+credit|L/?Cs?\b)"
_SWING = r"swing\s?-?line(?:\s+(?:loans?|advances?|borrowings?))?"
# "$150,000,000 sublimit for the issuance of standby letters of credit", "a $20,000,000 sublimit for swingline loans"
_SUB_AMOUNT_FIRST_RE = re.compile(rf"(?P<amt>{_M})\s+sub-?\s?(?:limit|facility)\s+for\s+(?:the\s+issuance\s+of\s+)?(?P<what>{_LC}|{_SWING})", re.IGNORECASE)
# "a sublimit of $700,000,000 for the issuance of multi-currency letters of credit"
_SUB_OF_RE = re.compile(rf"sub-?\s?(?:limit|facility)\s+of\s+(?P<amt>{_M})\s+for\s+(?:the\s+issuance\s+of\s+)?(?P<what>{_LC}|{_SWING})", re.IGNORECASE)
# "Up to $500.0 million of the Facility will be available in the form of letters of credit", "of which up to $75,000,000
# will be available for swingline loans", "a portion not in excess of $50,000,000 shall be available for the issuance of letters of credit"
_SUB_AVAILABLE_RE = re.compile(
    rf"(?:up\s+to|not\s+in\s+excess\s+of|not\s+(?:to\s+)?exceed(?:ing)?)\s+(?P<amt>{_M})\s+(?:of\s+the\s+[\w\s-]{{0,40}}?)?(?:will|shall|may)\s+be\s+"
    rf"(?:made\s+)?available\s+(?:in\s+the\s+form\s+of|for(?:\s+the\s+issuance\s+of)?|as)\s+(?P<what>{_LC}|{_SWING})", re.IGNORECASE)
# "letter of credit sublimit of $50 million", "swingline sub-facility of up to $25,000,000"
_SUB_NAMED_RE = re.compile(rf"(?P<what>{_LC}|{_SWING})\s+sub-?\s?(?:limit|facility|commitment)\s*(?:of|:|=)?\s*(?:up\s+to\s+)?(?P<amt>{_M})", re.IGNORECASE)
# "a $40mm letter of credit sublimit", "$25,000,000 swingline sub-facility"
_SUB_AMOUNT_NAMED_RE = re.compile(rf"(?P<amt>{_M})\s+(?P<what>{_LC}|{_SWING})\s+sub-?\s?(?:limit|facility)", re.IGNORECASE)
# "with sublimits for letters of credit of $50,000,000 and swingline loans of $35,000,000" (used only after the word "sublimit")
_SUB_FOR_OF_RE = re.compile(rf"(?P<what>{_LC}|{_SWING})\s+of\s+(?:up\s+to\s+)?(?P<amt>{_M})", re.IGNORECASE)
# "the aggregate Revolving Commitments available to the UK Borrower shall not exceed $1,000,000,000"
_SUB_AVAIL_TO_RE = re.compile(
    rf"aggregate\s+(?P<what>[\w\s]{{3,50}}?\s+available\s+to\s+[^,.;$]{{3,50}}?)\s+shall\s+not\s+exceed\s+(?P<amt>{_M})", re.IGNORECASE)
# A limit stated in the opening of a "Letters of Credit" / "Swingline" section: "of up to $1.0 billion", "not exceeding $20,000,000"
_LIMIT_CUE_RE = re.compile(
    rf"(?:up\s+to|not\s+(?:to\s+)?exceed(?:ing)?|not\s+in\s+excess\s+of|maximum\s+(?:amount\s+)?of|sub-?\s?limit\s+of)\s+"
    rf"(?:the\s+U\.S\.\s+Dollar\s+equivalent\s+(?:of\s+)?)?(?P<amt>{_M})", re.IGNORECASE)
# ... unless the figure is a limit for each lender or each drawing, not for the sub-facility: "each Issuing Bank's fronting
# commitment of up to", "in minimum amounts of"
_PER_LENDER_RE = re.compile(r"\beach\b|\bper\b|\bminimum\b|\bindividual\b|\bfronting\b", re.IGNORECASE)
# Currency names, for a multicurrency facility.
_CURRENCY_RE = re.compile(
    r"\b(?:U\.?S\.?\s+Dollars?|Canadian\s+Dollars?|Australian\s+Dollars?|Singapore\s+Dollars?|Hong\s+Kong\s+Dollars?|New\s+Zealand\s+Dollars?|"
    r"Euros?|Pounds?\s+Sterling|Sterling|Japanese\s+Yen|Yen|Swiss\s+Francs?|Mexican\s+Pesos?|Swedish\s+Kron\w+|Norwegian\s+Kron\w+|"
    r"Danish\s+Kron\w+|Renminbi)\b", re.IGNORECASE)
# What stands between two currencies of a list: ", ", " and ", ", and ", " or "
_LIST_GAP_RE = re.compile(r"\s*(?:,|,?\s*(?:and|or)|,\s*in)\s*", re.IGNORECASE)
# A bracket straight after a sub-limit that qualifies it with a figure: "(... up to $75,000,000 only ... financial letters of credit)"
_SUB_QUALIFIER_RE = re.compile(r"\s*\(([^()]{5,180})\)")
# "Upon the consummation of the Disposal, the aggregate commitments ... shall be automatically and permanently reduced to $2,000,000,000"
_STEP_DOWN_RE = re.compile(
    rf"\b(?P<when>Upon|On|Following|After)\s+(?P<event>[^,.;]{{5,80}}),\s+the\s+aggregate\s+commitments\b[^.;]{{0,80}}?(?P<how>(?:shall|will)\s+be\s+"
    rf"(?:automatically\s+)?(?:and\s+)?(?:permanently\s+)?reduced\s+to)\s+(?P<amt>{_M})")
# The list goes on beyond the named currencies: "and any other currency that is ...", "and such other currencies as ..."
_MORE_CURRENCIES_RE = re.compile(r"\b(?:and|or|together\s+with|plus|as\s+well\s+as)\s+(?:in\s+)?(?:any|certain|such)\s+(?:other|additional)\s+"
                                 r"(?:[\w-]+\s+){0,6}?currenc", re.IGNORECASE)
# The list is of the currencies loans may be drawn in besides the facility's own: "Multicurrency borrowings ... will be available in each of ..."
_ALTERNATIVE_CURRENCY_RE = re.compile(r"multi-?\s?currency|(?:alternative|alternate|optional|foreign|agreed|additional)\s+currenc", re.IGNORECASE)
_US_DOLLAR_RE = re.compile(r"U\.?S\.?\s+Dollars?", re.IGNORECASE)

_FAC_WORD = (r"(?:senior|secured|unsecured|revolving|credit|term|loan|new|proposed|bank|abl|first\s+lien|super\s+senior|delayed\s+draw|"
             r"364-?\s?day|\d{1,2}-?\s?year|(?:" + _NUM_WORD + r")-?\s?year|[ab])")
# "Facility", "Senior Credit Facilities", "Type and Amount of Facility", "Facility Amount", "Commitments", and the rows of a
# summary table that are labelled with the type itself: "Revolver", "RCF", "Term Loan B", "Revolving Commitments"
L_FACILITY = _label(
    r"(?:[\w\-]+\s+){0,4}facilit(?:y|ies)(?:\s+amount|\s+type|\s+size|\s+[A-D1-4])?|type\s+(?:and\s+amount\s+)?of(?:\s+facilit(?:y|ies))?|"
    r"(?:facility\s+|total\s+|aggregate\s+|principal\s+|commitment\s+)?(?:amounts?|commitments?|size)|amount\s+and\s+type|type|tranches?|"
    r"amounts?\s+of(?:\s+(?:the\s+)?(?:facilit(?:y|ies)|commitments))?|"
    r"(?:[\w\-]+\s+){0,3}(?:revolver|rcf|term\s+loans?(?:\s+[ab])?|tl[ab]|revolving\s+(?:credit\s+)?commitments?)",
    rf"(?:the\s+)?(?:{_FAC_WORD}\s+)*facilit(?:y|ies)(?:\s+(?:amount|type|size|description|[A-D1-4]))?|"
    r"type\s+(?:and\s+amount\s+)?of\s+(?:the\s+)?facilit(?:y|ies)|"
    r"(?:facility\s+|total\s+|aggregate\s+|principal\s+|commitment\s+)?(?:amounts?|commitments?|size)|"
    r"amounts?\s+of\s+(?:the\s+)?(?:facilit(?:y|ies)|commitments)|"
    r"amount\s+and\s+type(?:\s+of\s+facilit(?:y|ies))?|type|tranches?|"
    rf"(?:the\s+)?(?:{_FAC_WORD}\s+)*(?:revolver|rcf|term\s+loans?(?:\s+[ab])?|tl[ab]|revolving\s+(?:credit\s+)?commitments?)")
L_LC = _label(r"(?:l/?c|letters?\s+of\s+credit)(?:\s+sub-?\s?(?:limit|facility))?|(?:l/?c|letter\s+of\s+credit)\s+(?:facility|commitments?)")
L_SWING = _label(r"swing\s?-?line(?:\s+(?:sub-?\s?limit|loans?|facility|option|sub-?\s?facility|commitment))?")
L_CURRENCY = _label(r"(?:available\s+|agreed\s+|alternative\s+|optional\s+)?currenc(?:y|ies)|multi-?\s?currency(?:\s+option)?|advances")

_GENERIC_KINDS = ("credit facility", "facility")
_SUB_KINDS = ("swingline facility", "LC facility")
_DESC_ORDER = ("364-day", "year", "super senior", "senior", "secured", "unsecured", "first lien", "second lien", "delayed draw",
               "multicurrency")


# The words that tell the type of a facility apart.
_SWINGLINE_RE = re.compile(r"swing\s?-?line", re.IGNORECASE)                        # "swingline", "swing line", "swing-line"
_LC_WORDS_RE = re.compile(r"letters?\s+of\s+credit|\bl/?c\b", re.IGNORECASE)        # "letter of credit", "L/C", "LC"
_REVOLVING_RE = re.compile(r"revolv|\b(?:ss)?rcf\b", re.IGNORECASE)                 # "revolving", "revolver", "RCF", "SSRCF"
_TERM_LETTER_RE = re.compile(r"\bterm\s+(?:loan\s+)?([ab])\b|\btl([ab])\b", re.IGNORECASE)  # "term loan B", "term A loan", "TLB"
_TERM_LOAN_RE = re.compile(r"\bterm\s+(?:loans?|facilit)", re.IGNORECASE)           # "term loan", "term facility"
# The descriptors worth keeping, as (house wording, what the term sheet may write).
_D364_RE = re.compile(r"\b364-?\s?day\b", re.IGNORECASE)                            # "364-day", "364 day"
_YEAR_TENOR_RE = re.compile(rf"\b(\d{{1,2}}|{_NUM_WORD})-?\s?year\b", re.IGNORECASE)  # "five-year", "5-year", "3 year"
_SUPER_SENIOR_RE = re.compile(r"\bsuper[\s-]?senior\b|\bssrcf\b", re.IGNORECASE)    # "super senior", "SSRCF"
_SENIOR_RE = re.compile(r"\bsenior\b", re.IGNORECASE)                               # "senior"
_DESC_PATTERNS = (
    ("secured", re.compile(r"\bsecured\b", re.IGNORECASE)),
    ("unsecured", re.compile(r"\bunsecured\b", re.IGNORECASE)),
    ("first lien", re.compile(r"\bfirst[\s-]lien\b", re.IGNORECASE)),
    ("second lien", re.compile(r"\bsecond[\s-]lien\b", re.IGNORECASE)),
    ("delayed draw", re.compile(r"\bdelayed[\s-]draw\b", re.IGNORECASE)),
    ("multicurrency", re.compile(r"\bmulti-?\s?currency\b", re.IGNORECASE)),  # "multicurrency", "multi-currency"
)
# The currency in front of a formatted amount ("$", "EUR ", "GBP "), to know whether tranches can be added up.
_CURRENCY_OF_RE = re.compile(r"^(?:[^\d$]*\$|[A-Z]{3}\s)")
# "An aggregate principal amount of up to $1,100,000,000 will be available through the following facilities"
_AGGREGATE_AVAILABLE_RE = re.compile(
    rf"aggregate\s+(?:principal\s+)?amount\s+of\s+(?P<upto>up\s+to\s+)?(?P<amt>{_MX})\s+(?:will|shall)\s+be\s+(?:made\s+)?available", re.IGNORECASE)
# "up to" directly in front of an amount.
_UP_TO_END_RE = re.compile(r"up\s+to\s*$", re.IGNORECASE)
# The label says it is about the facility ("Facility", "Facilities") and not some other amount.
_FACILITY_WORD_RE = re.compile(r"facilit", re.IGNORECASE)
# "sublimit", "sub-limit", "sublimits"
_SUBLIMIT_WORD_RE = re.compile(r"sub-?\s?limits?", re.IGNORECASE)
# "multicurrency", "multi-currency" in a label
_MULTICURRENCY_RE = re.compile(r"multi-?\s?currency", re.IGNORECASE)
# The currencies named are those of letters of credit or swingline loans, not of the loans.
_LC_OR_SWING_RE = re.compile(r"letters?\s+of\s+credit|\bL/?Cs?\b|swing", re.IGNORECASE)
# "Multicurrency borrowings for up to the entire amount ...": the opening words repeat the label.
_MULTI_BORROWINGS_RE = re.compile(r"^Multicurrency\s+borrowings\s+(?:for\s+)?")
# "shall be" / "will be" in front of "reduced to"
_SHALL_BE_RE = re.compile(r"^(?:shall|will)\s+be\s+")


def _kind(text: str) -> str:
    """House name for a facility type."""
    if _SWINGLINE_RE.search(text):
        return "swingline facility"
    if _LC_WORDS_RE.search(text):
        return "LC facility"
    if _REVOLVING_RE.search(text):
        return "RCF"
    m = _TERM_LETTER_RE.search(text)
    if m:
        return "Term Loan " + (m.group(1) or m.group(2)).upper()
    if _TERM_LOAN_RE.search(text):
        return "Term Loan"
    t = text.lower()
    if "bridge" in t:
        return "bridge facility"
    return "credit facility" if "credit facilit" in t or "loan facilit" in t else "facility"


def _descs(text: str) -> list[str]:
    """Descriptors worth keeping, in house wording: "364-DAY SENIOR" -> ["364-day", "senior"]."""
    t = _norm(text)
    out: list[str] = []
    if _D364_RE.search(t):
        out.append("364-day")
    m = _YEAR_TENOR_RE.search(t)
    if m:
        out.append(f"{_to_int(m.group(1))}-year")
    if _SUPER_SENIOR_RE.search(t):
        out.append("super senior")
    elif _SENIOR_RE.search(t):
        out.append("senior")
    out.extend(word for word, rx in _DESC_PATTERNS if rx.search(t))
    return out


def _order_descs(descs: list[str]) -> list[str]:
    """Descriptors in house order (tenor, seniority, security, lien, draw, currency), each once."""
    def rank(d: str) -> int:
        key = "year" if d.endswith("-year") else d
        return _DESC_ORDER.index(key) if key in _DESC_ORDER else len(_DESC_ORDER)
    seen: list[str] = []
    for d in sorted(descs, key=rank):
        if d not in seen:
            seen.append(d)
    return seen


@dataclass
class _Tranche:
    mm: float
    money: str
    kind: str
    descs: list[str] = field(default_factory=list)
    upto: bool = False
    snippet: str = ""  # the wording matched, for the quote
    cell: _Cell | None = None
    title: bool = False  # found in a heading line rather than in running text
    existing: bool = False  # the wording presents it as a facility already in place ("the existing $1.0bn revolving credit facility")
    whole: bool = False  # followed by "consisting of ...": the aggregate of the tranches listed after it
    equivalent: bool = False  # "a $250 million equivalent ... Euro Term Loan Facility": the figure is an equivalent in another currency
    ccy: str = ""  # the currency the wording names the facility by ("U.S. Dollar", "Euro"), shown where it tells two tranches apart
    show_ccy: bool = False

    @property
    def open(self) -> bool:
        """The amount is one the term sheet leaves open in square brackets ("$[750][800]m"): its value is not known."""
        return self.mm < 0

    def text(self) -> str:
        kind = self.kind
        descs = _order_descs(self.descs)
        if kind == "RCF" and "super senior" in descs:
            kind = "RCF (SSRCF)"
        money = self.money + (" equivalent" if self.equivalent else "")
        ccy = [self.ccy] if self.ccy and (self.show_ccy or self.equivalent) else []
        words = " ".join([money] + descs + ccy + [kind])
        return ("up to " + words) if self.upto else words


@dataclass
class _Fac:
    main: list[_Tranche] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    cells: list[_Cell] = field(default_factory=list)
    note: str = ""

    @property
    def kinds(self) -> set[str]:
        return {t.kind for t in self.main}


def _tenor_desc(descs: list[str]) -> str:
    """The tenor among a tranche's descriptors ("364-day", "5-year"), if it has one."""
    return next((d for d in descs if d == "364-day" or d.endswith("-year")), "")


# The words in front of a facility say it is the one already in place: "the Company's existing $9,000,000,000 ...",
# "its current senior secured revolving credit facility of ..." (at most one word between "existing" and the facility).
_EXISTING_BEFORE_RE = re.compile(r"\b(?:existing|current|prior|previous|outstanding)\s+(?:[\w’'.,-]+\s+)?$", re.IGNORECASE)
# The words after a facility say it is the aggregate of what follows: "..., consisting of (a) ...", "comprised of",
# "to be made available through the following facilities", "allocated as follows"
def _gappy(word: str) -> str:
    """A pattern for ``word`` that tolerates one stray space between any two of its letters ("compr ised"): layout
    extraction splits words, and a signal word must not be missed for it."""
    return r"\s?".join(re.escape(ch) for ch in word)


_WHOLE_AFTER_RE = re.compile(
    r"^\s*(?:\([^()]{0,90}\)\s*)?[,:]?\s*(?:" + _gappy("consisting") + r"\s+of|" + _gappy("comprised") + r"\s+of|" + _gappy("comprising")
    + r"|composed\s+of|made\s+up\s+of|(?:to\s+be\s+)?(?:made\s+)?available\s+"
    r"(?:through|as|in\s+the\s+form\s+of)|through\s+the\s+following|as\s+follows|allocated\s+(?:as|between|among)|split\s+(?:as|between|into)|"
    r"divided\s+(?:as|between|into))\b", re.IGNORECASE)
# The name of a facility says it is the one already in place: (the “Existing Credit Facility”)
_EXISTING_WORD_RE = re.compile(r"\bexisting\b", re.IGNORECASE)
# The lower end of a range, directly in front of an amount: "$750,000,000 - ", "$750 million to " (but not "from $X to $Y",
# which says the figure has changed)
_RANGE_LOW_RE = re.compile(rf"(?<!from\s)(?<!from\s\s)(?P<amt>{_M})\s*(?:-|–|—|to)\s*$", re.IGNORECASE)


def _tranche(m: re.Match, kind_text: str, desc_text: str, upto: bool, text: str = "") -> _Tranche | None:
    """A tranche from a match of one of the facility patterns (None where the amount cannot be the size of a facility).
    ``text`` is the passage the match was found in: the words around the match say whether the facility is one
    already in place, or the aggregate of the tranches listed after it."""
    amt = _read_amount(m.group("amt"))  # an amount left open in square brackets is kept as printed, its value unknown
    if amt is None or 0 <= amt[0] < 1:  # under $1m: not the size of a syndicated facility
        return None
    if text and amt[0] > 0:  # a range - "a $750,000,000 - $850,000,000 revolving credit facility": neither end is the size
        low = _RANGE_LOW_RE.search(text[max(0, m.start("amt") - 60):m.start("amt")])
        low_amt = _first_amount(low.group("amt")) if low else None
        if low_amt and low_amt[0] < amt[0]:
            amt = (-1.0, f"{low_amt[1]} to {amt[1]}")
    equiv = m.groupdict().get("equiv") or ""  # "the Euro equivalent of $150,000,000"
    money = (_LEADING_THE_RE.sub("", _norm(equiv)) + " " + amt[1]).strip()
    t = _Tranche(mm=amt[0], money=money, kind=_kind(kind_text), descs=_descs(desc_text + " " + kind_text), upto=upto, snippet=m.group(0),
                 equivalent=bool(m.groupdict().get("eq")), ccy=_facility_currency(desc_text))
    if text:
        t.existing = bool(_EXISTING_BEFORE_RE.search(text[max(0, m.start() - 60):m.start()])) or bool(_EXISTING_WORD_RE.search(kind_text))
        t.whole = bool(_WHOLE_AFTER_RE.match(text[m.end():m.end() + 160]))
    return t


# The currency a facility is named by: "U.S. Dollar Term Loan Facility", "Euro Term Loan Facility", "Sterling Revolving Facility"
_FACILITY_CCY = (("U.S. Dollar", re.compile(r"\bU\.?S\.?\s+dollar\b|\bdollar\b", re.IGNORECASE)),
                 ("U.S.", re.compile(r"\bU\.S\.|\bUS\b")),
                 ("Euro", re.compile(r"\beuro\b", re.IGNORECASE)),
                 ("Sterling", re.compile(r"\bsterling\b", re.IGNORECASE)))


def _facility_currency(desc_text: str) -> str:
    """The currency named among the words that describe a facility, "" if none."""
    return next((name for name, rx in _FACILITY_CCY if rx.search(desc_text or "")), "")


def _same_currency_name(a: str, b: str) -> bool:
    """Two currency names do not contradict each other ("U.S." and "U.S. Dollar"; one of them missing)."""
    return not a or not b or a[:4] == b[:4]


def _merge_tranche(out: list[_Tranche], t: _Tranche) -> None:
    """Add a tranche, or fold it into the one already found with the same amount and type (keeping every descriptor).
    "Term Loan" and "Term Loan B" for the same amount are one tranche named twice."""
    for o in out:
        both_term = o.kind.startswith("Term Loan") and t.kind.startswith("Term Loan") and "Term Loan" in (o.kind, t.kind)
        tenors = {_tenor_desc(o.descs), _tenor_desc(t.descs)} - {""}
        same = abs(o.mm - t.mm) < 1e-6 and o.money == t.money and o.existing == t.existing and _same_currency_name(o.ccy, t.ccy)
        if same and (o.kind == t.kind or both_term) and len(tenors) < 2:  # two tenors: two tranches of equal size
            o.kind = max(o.kind, t.kind, key=len)
            o.descs = _order_descs(o.descs + t.descs)
            o.upto = o.upto or t.upto
            o.whole = o.whole or t.whole
            o.equivalent = o.equivalent or t.equivalent
            o.ccy = max(o.ccy, t.ccy, key=len)
            return
    out.append(t)


def _tranches_in(text: str) -> list[_Tranche]:
    """Facilities described in a passage, in the order they appear."""
    found: list[tuple[int, _Tranche]] = []
    for m in _AMOUNT_FIRST_RE.finditer(text):
        t = _tranche(m, m.group("kind"), m.group("desc"), bool(m.group("upto")), text)
        if t:
            found.append((m.start(), t))
    for m in _KIND_FIRST_RE.finditer(text):
        t = _tranche(m, m.group("kind"), m.group("desc"), bool(m.group("upto")), text)
        if t:
            found.append((m.start(), t))
    for m in _AGG_NAMED_RE.finditer(text):
        if _kind(m.group("name")) not in _GENERIC_KINDS:
            t = _tranche(m, m.group("name"), m.group("name"), bool(m.group("upto")), text)
            if t:
                found.append((m.start(), t))
    out: list[_Tranche] = []
    for _, t in sorted(found, key=lambda x: x[0]):
        _merge_tranche(out, t)
    return out


# A facility divided into tranches that are not facilities of their own: "(i) a three-year tranche (the “3-Year Tranche”) in an
# aggregate amount of $1,325,000,000", "a $500,000,000 five-year tranche"
_TRANCHE_PART_RE = re.compile(
    rf"\ban?\s+(?P<desc>(?:{_DESC_WORD}\s+){{1,4}})tranche\s*(?:\([^()]{{0,140}}\)\s*)?,?\s*(?:in\s+an?\s+(?:aggregate\s+)?(?:principal\s+)?amount\s+"
    rf"(?:of\s+|equal\s+to\s+)|of\s+)(?P<amt>{_M})|(?P<amt2>{_M})\s+(?P<desc2>(?:{_DESC_WORD}\s+){{1,4}})tranche\b", re.IGNORECASE)


def _tranche_parts(text: str) -> list[tuple[float, str]]:
    """(value in millions, "$1.325bn 3-year tranche") for each tranche a facility is divided into, in the order given.
    Empty unless every tranche has a descriptor that tells it from the others (a tenor, a currency)."""
    out: list[tuple[float, str]] = []
    for m in _TRANCHE_PART_RE.finditer(text):
        amt = _first_amount(m.group("amt") or m.group("amt2") or "")
        desc = m.group("desc") or m.group("desc2") or ""
        words = _order_descs(_descs(desc)) or ([_facility_currency(desc)] if _facility_currency(desc) else [])
        if amt is None or amt[0] < 1 or not words:
            return []
        name = f"{amt[1]} {' '.join(words)} tranche"
        if any(name == other for _, other in out):
            return []
        out.append((amt[0], name))
    return out


def _label_tranche(cell: _Cell) -> _Tranche | None:
    """A row whose label names the type and whose value opens with the amount: "Revolving Credit Facility: $750,000,000"."""
    m = _AMOUNT_START_RE.match(cell.text)
    label = _norm(cell.block.label)
    if not m or _kind(label) in _GENERIC_KINDS + _SUB_KINDS:
        return None
    amt = _read_amount(m.group("amt"))  # "Revolving Credit Facility: $[750][800] million", "... [$500,000,000]"
    if amt is None or 0 <= amt[0] < 1:
        return None
    return _Tranche(mm=amt[0], money=amt[1], kind=_kind(label), descs=_descs(label), upto=bool(m.group("upto")), snippet=m.group(0), cell=cell,
                    existing=bool(_EXISTING_WORD_RE.search(label)), ccy=_facility_currency(label))


def _mentions(ctx: Ctx) -> list[_Tranche]:
    """Facilities named with their amount on the opening pages (title lines and introductions)."""
    memo = _memo(ctx)
    if "mentions" not in memo:
        out: list[_Tranche] = []
        for ln in ctx.raw.lines:
            if ln.page > 3:
                break
            text = _norm(ln.text)
            for m in _AMOUNT_FIRST_RE.finditer(text):
                t = _tranche(m, m.group("kind"), m.group("desc"), bool(m.group("upto")) or bool(_UP_TO_END_RE.search(text[:m.start()])), text)
                if t:
                    t.title = len(m.group(0)) >= 0.6 * len(text) and not text.rstrip().endswith(".") and not t.existing
                    out.append(t)
        memo["mentions"] = out
    return memo["mentions"]


def _linked_kinds(ctx: Ctx, values: list[float]) -> list[tuple[str, str]]:
    """(type, wording) wherever the document names a type of facility next to one of these amounts ("RCF capacity
    of $225mm"), in document order."""
    hits: list[tuple[str, str]] = []
    for ln in ctx.raw.lines:
        text = _norm(ln.text)
        for m in _KIND_NEAR_RE.finditer(text):
            amt = _first_amount(m.group("amt") or m.group("amt2") or "")
            if amt and any(abs(amt[0] - v) < 1e-6 for v in values):
                hits.append((_kind(m.group("kind") or m.group("kind2")), m.group(0)))
    return hits


def _split_rows_tranche(ctx: Ctx, cells: list[_Cell], fac: _Fac) -> list[_Tranche]:
    """A facility whose amount and type are in different places: "Facility Amount" and "Type of Facility" rows, or
    an amount whose type the document gives elsewhere beside the same figure."""
    amount_cell, m = None, None
    for c in sorted(cells, key=lambda x: not _FACILITY_WORD_RE.search(x.block.label)):  # a "Facility ..." row before a bare "Amount" row
        m = _AMOUNT_START_RE.match(c.text)
        if m and _read_amount(m.group("amt")):
            amount_cell = c
            break
    if amount_cell is None or m is None:
        return []
    amt = _read_amount(m.group("amt"))
    if amt is None or 0 <= amt[0] < 1:
        return []
    t = _Tranche(mm=amt[0], money=amt[1], kind="facility", upto=bool(m.group("upto")), snippet=m.group(0), cell=amount_cell)
    for c in cells:  # a "Type of Facility" row
        tm = _TYPE_START_RE.match(c.text)
        if tm and c is not amount_cell:
            t.kind, t.descs = _kind(tm.group("kind")), _descs(tm.group("desc"))
            q = _quote(ctx, c.block, tm.group(0))
            if q:
                fac.evidence.append(q)
            return [t]
    if t.open:
        return []  # an amount left open in brackets is not a figure to look up elsewhere
    label = _norm(amount_cell.block.label)
    t.descs = _descs(label)
    named_facility = bool(_FACILITY_WORD_RE.search(label))  # "Facility: $275mm" as against "Amount: ..." in some other table
    values = [t.mm]
    old = _first_amount(amount_cell.old) if amount_cell.old else None
    if old:
        values.append(old[0])
    # the same figure with its type elsewhere: on the opening pages, or beside the figure anywhere in the document
    skip = _GENERIC_KINDS + _SUB_KINDS
    named = [men for men in _mentions(ctx) if any(abs(men.mm - v) < 1e-6 for v in values) and men.kind not in skip]
    linked = [hit for hit in _linked_kinds(ctx, values) if hit[0] not in skip]
    kinds = {men.kind for men in named} | {kind for kind, _ in linked}
    if len(kinds) == 1:  # one type only: the same figure beside two types does not say which of them this facility is
        q = _quote_text(ctx, named[0].snippet) if named else _quote_text(ctx, linked[0][1])
        if q:
            t.kind = kinds.pop()
            if named:  # the tenor of a facility already in place is not the tenor of this one
                t.descs = _order_descs(t.descs + [d for d in named[0].descs if not (named[0].existing and d == _tenor_desc(named[0].descs))])
            fac.evidence.append(q)
            fac.note = "The facility row gives the amount only; the type is taken from where the document names it beside the same figure."
    return [t] if named_facility or t.kind not in _GENERIC_KINDS else []


def _sub_name(what: str) -> str:
    """House name of a sub-limit."""
    return "swingline" if _SWINGLINE_RE.search(what) else "letters of credit"


def _sublimits(ctx: Ctx, cells: list[_Cell]) -> tuple[list[str], list[dict], list[str]]:
    """Sub-limits the term sheet states: letters of credit, swingline, a borrower's share."""
    items: dict[str, str] = {}
    ev: list[dict] = []

    def add(name: str, text: str, q: dict | None) -> None:
        if name not in items and q:
            items[name] = text
            ev.append(q)

    for c in cells:
        stated_at: dict[str, dict[int, str]] = {}  # sub-limit -> where each of its amounts stands in the section
        for rx in (_SUB_AMOUNT_FIRST_RE, _SUB_OF_RE, _SUB_AVAILABLE_RE, _SUB_NAMED_RE, _SUB_AMOUNT_NAMED_RE):
            for m in rx.finditer(c.text):
                amt = _first_amount(m.group("amt"))
                if amt:
                    name = _sub_name(m.group("what"))
                    stated_at.setdefault(name, {})[m.start("amt")] = amt[1]
                    qual = _SUB_QUALIFIER_RE.match(c.text[m.end():])
                    more = f" ({_style(qual.group(1))})" if qual and _first_amount(qual.group(1)) else ""
                    add(name, f"{name} {amt[1]}{more}", _quote(ctx, c.block, m.group(0)))
        for name, places in stated_at.items():
            # the section gives this sub-limit more than once (one for each tranche, say): the first is not "the" sub-limit
            figures = [places[k] for k in sorted(places)]
            if len(figures) > 1 and items.get(name, "").startswith(f"{name} {figures[0]}"):
                if len(set(figures)) > 1:
                    items[name] = f"{name} {' and '.join(dict.fromkeys(figures))} (separate sub-limits in the facility section; see term sheet)"
                else:
                    items[name] = f"{name} {figures[0]} (stated {len(figures)} times in the facility section - may apply to each tranche; see term sheet)"
        for m in _SUB_FOR_OF_RE.finditer(c.text):
            amt = _first_amount(m.group("amt"))
            if amt and _SUBLIMIT_WORD_RE.search(c.text[max(0, m.start() - 90):m.start()]):
                add(_sub_name(m.group("what")), f"{_sub_name(m.group('what'))} {amt[1]}", _quote(ctx, c.block, m.group(0)))
        for t in _tranches_in(c.text):
            if t.kind == "swingline facility":  # named beside the main facility, not expressly as a sub-limit of it
                add("swingline facility", f"Swingline: {t.money} swingline facility", _quote(ctx, c.block, t.snippet))
        m = _SUB_AVAIL_TO_RE.search(c.text)
        if m:
            amt = _first_amount(m.group("amt"))
            if amt:
                add("other", f"{_style(m.group('what'))} not to exceed {amt[1]}", _quote(ctx, c.block, m.group(0)))
    for name, spec in (("letters of credit", L_LC), ("swingline", L_SWING)):
        if name in items:
            continue
        for b in _find(ctx, spec)[:1]:
            c = _cell(ctx, b, spec)
            text = _strip_bullet(c.text)
            if not text:
                continue
            same = " (same as existing)" if c.same else ""
            amt = _first_amount(text)
            start = _AMOUNT_START_RE.match(text)
            first = (_sents(text) or [text])[0]
            if start and amt and len(text) <= 30:  # a table cell that is just the figure
                add(name, f"{name} {amt[1]}{same}", _quote(ctx, c.block, start.group(0)))
            elif _SUBLIMIT_WORD_RE.search(b.label):  # a sub-limit row with wording of its own: keep the wording
                wording = "; ".join(_lower_first(_strip_end(p)) for p in _bullets(_style(text)))
                add(name, f"{name} - {_clip(wording, 170)}{same}", _quote(ctx, c.block))
            else:
                m = _LIMIT_CUE_RE.search(first) or next((rx.search(first) for rx in (_SUB_AMOUNT_FIRST_RE, _SUB_OF_RE, _SUB_AVAILABLE_RE)
                                                         if rx.search(first)), None)
                limit = _first_amount(m.group("amt")) if m else None
                if limit and not _PER_LENDER_RE.search(first[max(0, m.start() - 60):m.start()]):
                    add(name, f"{name} up to {limit[1]}{same}", _quote(ctx, c.block, m.group(0)))
                elif _refers(first) or _SAME_AS_START_RE.match(first):
                    if len(first) <= 120:
                        add(name, f"{name} - {_lower_first(_strip_end(_style(first)))}", _quote(ctx, c.block))
    order = [n for n in ("letters of credit", "swingline", "other") if n in items]
    return [items[n] for n in order], ev, [items[n] for n in ("swingline facility",) if n in items]


def _currencies(ctx: Ctx, cells: list[_Cell], dollar_facility: bool = False) -> tuple[str, dict | None, bool]:
    """(line, quote, multicurrency?) where the term sheet says which currencies loans are available in. ``dollar_facility``
    says the facility is sized in U.S. dollars: a list that leaves them out is then the list of the other currencies."""
    sources: list[tuple[_Cell, bool]] = [(c, False) for c in cells]
    for b in _find(ctx, L_CURRENCY)[:3]:
        sources.append((_cell(ctx, b, L_CURRENCY), bool(_MULTICURRENCY_RE.search(b.label))))
    for c, multi_label in sources:
        for s in _sents(c.text):
            every = list(_CURRENCY_RE.finditer(s))
            names = every[:1]
            for a, b in zip(every, every[1:]):  # the list itself: names separated only by commas and "and" / "or"
                if not _LIST_GAP_RE.fullmatch(s[a.end():b.start()]):
                    break
                names.append(b)
            distinct = {_NON_WORD_RE.sub("", n.group(0).lower()).rstrip("s") for n in names}
            before = s[:names[0].start()] if names else ""
            if len(distinct) >= 2 and not _LC_OR_SWING_RE.search(before):
                span = s[names[0].start():names[-1].end()]
                if len(span) <= 170:
                    more = ""
                    if _MORE_CURRENCIES_RE.search(s[names[-1].end():]):
                        more = ", plus other currencies as provided" if " and " in span or " or " in span else " and other currencies as provided"
                    # a sentence about the term loans alone says nothing of the currencies of the revolver
                    term_only = bool(_TERM_LOAN_TALK_RE.search(before)) and not _REVOLVING_RE.search(before)
                    # a list without U.S. dollars under a multicurrency heading is the list of the other currencies, not of all of them
                    optional = ((multi_label or dollar_facility or bool(_ALTERNATIVE_CURRENCY_RE.search(s)))
                                and not any(_US_DOLLAR_RE.fullmatch(n.group(0)) for n in names))
                    head = "Currencies (term loans)" if term_only else "Multicurrency option" if optional else "Currencies"
                    line = f"{head}: {_style(span)}{more}" + (" (same as existing)" if c.same else "")
                    return line, _quote(ctx, c.block, span), not term_only
        if multi_label and c.text:
            first = (_sents(c.text) or [c.text])[0]
            first = _MULTI_BORROWINGS_RE.sub("", _strip_end(_style(first)))
            return "Multicurrency option: " + _clip(_lower_first(first), 275), _quote(ctx, c.block), True
    return "", None, False


def _currency_of(t: _Tranche) -> str:
    """What stands in front of the figure of a tranche ("$", "EUR ", "Euro equivalent of $"): tranches add up only if it is the same."""
    m = _CURRENCY_OF_RE.match(t.money.lstrip("["))  # "[$500m]": the whole amount stands in brackets
    return m.group(0) if m else ""


def _split_whole(specific: list[_Tranche], generic: list[_Tranche]) -> tuple[_Tranche | None, list[_Tranche]]:
    """(the facility that is the aggregate of the others, the others). A facility is the aggregate when the wording
    says so ("credit facilities in an aggregate amount of $1.25bn, consisting of ...") and the others do not add up
    to more than it; or when it equals the sum of at least two others and is either named generically ("credit
    facilities") or named first with the others being of its own type ("$3.0bn revolving credit facilities: a
    $1.25bn three-year revolving facility and a $1.75bn five-year revolving facility"). A revolver that happens to
    equal the sum of two term loans is a tranche like them."""
    for t in generic + specific:
        others = [o for o in specific if o is not t]
        if not others:
            continue
        known = not t.open and not any(o.open for o in others)  # an amount left open in brackets cannot be added up
        addable = known and all(_currency_of(o) == _currency_of(t) for o in others)
        total = sum(o.mm for o in others)
        if t.whole and (not addable or total <= t.mm + 1e-6):
            return t, others
        if addable and len(others) >= 2 and abs(total - t.mm) < 1e-6:
            first_of_its_kind = specific[:1] == [t] and all(o.kind == t.kind for o in others)
            if t.kind in _GENERIC_KINDS or first_of_its_kind:
                return t, others
    return None, specific


# A sentence about the size of a facility, as against some other figure that went up ("revenue increased from ... to ...").
_FACILITY_CONTEXT_RE = re.compile(r"facilit|\bRCF\b|revolv|commitments?|term\s+loan|\bTL[AB]\b", re.IGNORECASE)


# Any short label in the label column, for the search by content below.
_ANY_LABEL = r"[A-Z][A-Za-z/&’'\-]*(?:\s+[A-Za-z/&’'\-]+){0,5}"
# Sections that are about something other than the facility itself, whatever their text opens with.
_NOT_FACILITY_LABEL_RE = re.compile(
    r"existing|refinanc|replac|increment|accordion|increase|swing|letters?\s+of\s+credit|\bl/?c\b|purpose|use\s+of|fees?\b|pricing|interest|margin|"
    r"prepay|repay|matur|amorti|guarant|collateral|security|covenant|condition|default|assign|document|transaction|background|overview|"
    r"extension\s+(?:option|of|request)|^extensions?$", re.IGNORECASE)


# The sentence speaks of a facility of the past: "... was made available to the Borrower in 2021", "... dated as of June 2, 2022"
_PAST_FACILITY_RE = re.compile(r"\b(?:was|were|has\s+been|had\s+been|previously|dated)\b", re.IGNORECASE)


# A facility named with the indefinite article and no amount in front: "... and a revolving credit facility in an amount to be
# determined", "(ii) a senior secured term loan facility (the “Term Facility”) providing for ..."
_NAMED_FACILITY_RE = re.compile(rf"\b(?:an?|one\s+or\s+more)\s+(?:new\s+)?(?P<desc>(?:{_DESC_WORD}\s+){{0,6}})(?P<kind>{_KIND_WORDS})", re.IGNORECASE)
# ... as one of the facilities the section sets out: at its start, or after "and", a comma, a semicolon or a list marker,
_COORDINATED_RE = re.compile(r"(?:\band|,|;|:|\((?:[ivx]{1,4}|[a-z]|\d)\))\s*$", re.IGNORECASE)
# ... and not as something the facility is turned into, replaces or sits under.
_NOT_A_TRANCHE_RE = re.compile(r"\b(?:into|convert\w*|existing|refinanc\w*|replac\w*|under|increment\w*|increas\w*|additional|prior|previous|"
                               r"form\s+of|as|of|to|in|for|with|from)\s+(?:and\s+)?$", re.IGNORECASE)


# ... nor a facility of the past: "to replace a $900,000,000 revolving credit facility and a term loan facility under the Existing ..."
_OLD_FACILITY_TALK_RE = re.compile(r"\bexisting\b|\brefinanc|\breplac|\brepa(?:y|id)|\bprior\b|\bprevious|\bterminat", re.IGNORECASE)


def _unread_kinds(cells: list[_Cell], found: list[_Tranche]) -> list[str]:
    """Types of facility the facility section sets out beside the ones read, but with no amount the rules could read
    ("a $400,000,000 term loan facility and a revolving credit facility in an amount to be determined"): the line says so
    instead of listing the facilities read as if they were all of them."""
    have = {t.kind for t in found}
    has_term = any(k.startswith("Term Loan") for k in have)
    out: list[str] = []
    for c in cells:
        for m in _NAMED_FACILITY_RE.finditer(c.text):
            kind = _kind(m.group("kind"))
            if kind in _GENERIC_KINDS + _SUB_KINDS or kind in have or kind in out or (has_term and kind.startswith("Term Loan")):
                continue
            before = c.text[max(0, m.start() - 60):m.start()]
            around = c.text[max(0, m.start() - 140):m.end() + 80]
            if _EXISTING_WORD_RE.search(m.group(0)) or _NOT_A_TRANCHE_RE.search(before) or _OLD_FACILITY_TALK_RE.search(around):
                continue
            if m.start() <= 12 or _COORDINATED_RE.search(before):
                out.append(kind)
    return out


def _facility_by_content(ctx: Ctx, anchor: int | None) -> _Cell | None:
    """The section that describes the facility where its label is not one the rules know ("Amounts", "The Financing",
    "Credit Extensions" ...): a section on the pages where the terms begin whose text opens with the facility itself -
    type and amount, in either order ("A senior unsecured revolving credit facility of $2,650,000,000 (the ...").
    Sections whose label says they are about something else (an existing facility, an increase, fees ...) are left out."""
    try:
        blocks = ctx.blocks(_ANY_LABEL)
    except re.error:
        return None
    first_page = anchor or 1
    for b in blocks:
        if b.inline or b.mode != "column" or not first_page <= b.page <= first_page + 1 or not b.text:
            continue
        if _NOT_FACILITY_LABEL_RE.search(b.label) or len(b.label.split()) > 6:
            continue
        text = _norm(b.text)
        opening = (_sents(text) or [""])[0]
        named = [t for t in _tranches_in(opening) if t.kind not in _GENERIC_KINDS + _SUB_KINDS and not t.existing]
        if named and 0 <= opening.find(named[0].snippet) <= 12 and not _PAST_FACILITY_RE.search(opening):
            return _Cell(b, text)
    return None


def _analyse(ctx: Ctx) -> _Fac:
    """Everything the facility row needs; cached because ``repayment`` and ``maturity`` use it too."""
    memo = _memo(ctx)
    if "fac" in memo:
        return memo["fac"]
    fac = _Fac()
    memo["fac"] = fac
    anchor = _anchor_page(ctx)
    # a row labelled only "Amount", "Size", "Type" or with a type ("Term Loan B") counts only close to where the terms
    # begin: further on, such rows belong to other tables (capitalisation, pricing)
    blocks = [b for b in _top_level(_find(ctx, L_FACILITY)) if _FACILITY_WORD_RE.search(b.label) or anchor is None or anchor <= b.page <= anchor + 1]
    cells = [_cell(ctx, b, L_FACILITY) for b in blocks[:6]]
    cells = [c for c in cells if c.text]
    fac.cells = cells
    found: list[_Tranche] = []
    for c in cells:
        tranches = _tranches_in(c.text)
        if not any(t.kind not in _GENERIC_KINDS + _SUB_KINDS for t in tranches):
            by_label = _label_tranche(c)  # "Revolving Credit Facility: $750,000,000": the label names the type
            if by_label:
                tranches = [by_label]
        for t in tranches:
            t.cell = c
            _merge_tranche(found, t)
    if not found:  # no facility under a label the rules know: a section that opens with the facility itself, whatever its label
        by_content = _facility_by_content(ctx, anchor)
        if by_content is not None:
            cells = [by_content]
            fac.cells = cells
            for t in _tranches_in(by_content.text):
                t.cell = by_content
                _merge_tranche(found, t)
            fac.note = (f"The facility was read from the section labelled “{_title(by_content.block.label)}”, which is not a label the rules "
                        "know for this row; check the term sheet.")
    in_place = [t for t in found if t.existing]  # facilities the term sheet describes as already existing
    live = [t for t in found if not t.existing]
    generic = [t for t in live if t.kind in _GENERIC_KINDS]
    whole_t, specific = _split_whole([t for t in live if t.kind not in _GENERIC_KINDS + _SUB_KINDS], generic)
    mentions = _mentions(ctx)
    main = specific or ([whole_t] if whole_t else []) or generic[:1] or _split_rows_tranche(ctx, cells, fac)
    if whole_t is not None and whole_t in main:
        whole_t = None
    if not main:  # the type is there but the amount is a blank still to be filled in
        for c in cells:
            tm, blank = _TYPE_START_RE.match(c.text), _BLANK_AMOUNT_RE.search(c.text)
            if tm and blank:
                main = [_Tranche(mm=-1.0, money=blank.group("cur") + "[ ]", kind=_kind(tm.group("kind")), descs=_descs(tm.group("desc")),
                                 upto=bool(blank.group("upto")), snippet=tm.group(0), cell=c)]
                break
    only_in_place = False
    if not main and in_place:  # the section describes only the facility already in place (an amendment of it)
        main = [t for t in in_place if t.kind not in _GENERIC_KINDS + _SUB_KINDS] or [t for t in in_place if t.kind in _GENERIC_KINDS][:1]
        only_in_place = bool(main)
    from_title = False
    if not main:  # no facility section: the title of the term sheet
        titles = [t for t in mentions if t.title and t.kind not in _SUB_KINDS]
        main = [t for t in titles if t.kind not in _GENERIC_KINDS][:2] or titles[:1]
        from_title = bool(main)
    if not main:
        return fac
    for t in main:  # descriptors given with the same amount on the opening pages ("five-year" in the introduction)
        if t.open or sum(1 for o in main if abs(o.mm - t.mm) < 1e-6) > 1:
            continue  # two tranches of the same size: a figure alone does not say which one is meant
        for men in mentions:
            clash = len({_tenor_desc(men.descs), _tenor_desc(t.descs)} - {""}) > 1
            if men.existing or men.open or abs(men.mm - t.mm) > 1e-6 or clash:
                continue
            if men.kind == t.kind or men.kind in _GENERIC_KINDS:  # the same facility, or the facilities as a whole
                t.descs = _order_descs(t.descs + men.descs)
    for t in main:  # two tranches of one type are told apart by the currency they are named by ("U.S. Dollar" / "Euro" term loan)
        t.show_ccy = bool(t.ccy) and any(o is not t and o.kind == t.kind and o.ccy and not _same_currency_name(o.ccy, t.ccy) for o in main)
    fac.main = main

    cur_line, cur_q, multi = _currencies(ctx, cells, dollar_facility=all(_currency_of(t) == "$" for t in main))
    if multi:
        for t in main:
            if t.kind == "RCF" and "multicurrency" not in t.descs:
                t.descs.append("multicurrency")
                break
    line = " + ".join(t.text() for t in main)
    # the total, where the term sheet states it
    pool = " ".join(c.text for c in cells)
    one_currency = len({_currency_of(t) for t in main}) == 1
    known = not any(t.open for t in main)  # an amount left open in square brackets cannot be added up
    total = sum(t.mm for t in main)
    if whole_t is not None:  # the term sheet gives the aggregate as a facility of its own, "consisting of" the tranches
        if known and not whole_t.open and one_currency and _currency_of(whole_t) == _currency_of(main[0]) and abs(total - whole_t.mm) < 1e-6:
            line += f" (total {whole_t.text()})"
        else:  # the tranches read do not add up to it (another currency, or a tranche the rules did not read)
            line = f"{whole_t.text()}, including {line}"
    elif len(main) > 1 and one_currency and known:
        for mm, money, m in amounts(pool):
            if abs(mm - total) < 1e-6:
                upto = "up to " if _UP_TO_END_RE.search(pool[:m.start()]) else ""
                extra = next((" " + " ".join(_order_descs(men.descs) + [men.kind]) for men in mentions
                              if abs(men.mm - total) < 1e-6 and men.kind in _GENERIC_KINDS and men.descs and not men.existing), "")
                line += f" (total {upto}{money}{extra})"
                break
        else:  # or in the title: "$1,250,000,000 SENIOR SECURED CREDIT FACILITIES"
            for men in mentions:
                if abs(men.mm - total) < 1e-6 and men.kind in _GENERIC_KINDS and men.title:
                    line += f" (total {'up to ' if men.upto else ''}{men.money} {' '.join(_order_descs(men.descs) + [men.kind])})"
                    break
    elif len(main) > 1:  # tranches that cannot be added up (different currencies, an amount left open): the aggregate as the term sheet states it
        m = _AGGREGATE_AVAILABLE_RE.search(pool)
        amt = _read_amount(m.group("amt")) if m else None
        if amt and amt[1]:
            # what the title calls the facilities as a whole, if it gives the same figure: "$[1.55][1.6] BILLION SENIOR SECURED CREDIT FACILITIES"
            extra = next((" " + " ".join(_order_descs(men.descs) + [men.kind]) for men in mentions
                          if men.money == amt[1] and men.kind in _GENERIC_KINDS and men.descs and not men.existing), "")
            line += f" (aggregate {'up to ' if m.group('upto') else ''}{amt[1]}{extra} as stated)"
    if len(main) == 1 and main[0].cell is not None and not main[0].open:  # one facility divided into tranches: "comprised of (i) a three-year tranche ..."
        parts = _tranche_parts(main[0].cell.text)
        if len(parts) >= 2 and sum(mm for mm, _ in parts) <= main[0].mm + 1e-6:
            line += ", including " + " and ".join(f"a {name}" for _, name in parts[:4])
    unread = [] if (from_title or only_in_place) else _unread_kinds(cells, found)
    if unread:  # the list of facilities read is not all the section sets out
        line += (" (the facility section also names " + " and ".join(("an " if k == "RCF" else "a ") + k for k in unread)
                 + ", whose amount was not read)")
        fac.note = (fac.note + " " if fac.note else "") + "The facility section names a type of facility for which no amount was read; check the term sheet."
    if _BRACKET_FIGURE_RE.search(line):
        line += (" (figures in square brackets, and blanks [ ], are left open in the term sheet)" if "[ ]" in line
                 else f" ({_BRACKETS_NOTE})")
        fac.note = (fac.note + " " if fac.note else "") + "The term sheet gives an amount in square brackets (alternatives or a figure not yet final); it is printed as it stands."
    # amendments: what the proposed term does to the existing one
    lead = main[0].cell
    extra_lines: list[str] = []
    if only_in_place:
        line += " (described in the term sheet as the existing facility)"
        m = _UPSIZE_TO_RE.search(pool)
        new = _first_amount(m.group("new")) if m else None
        if new and len(main) == 1 and new[0] > main[0].mm:  # "... the existing $750m revolving credit facility, to be upsized to $1.0bn"
            line += f"; to be increased to {new[1]}"
    elif lead is not None:
        old = _first_amount(lead.old) if lead.old else None
        if lead.same:
            line += " (same as existing)"
        elif old and abs(old[0] - main[0].mm) > 1e-6:
            line += f" (existing: {old[1]})"
        elif len(main) == 1 and len(in_place) == 1 and in_place[0].kind == main[0].kind and abs(in_place[0].mm - main[0].mm) > 1e-6:
            line += f" (existing: {in_place[0].money})"  # "the existing $1.0bn facility will be replaced with a new $1.25bn facility"
        if lead.change:
            extra_lines.append(_fit("Proposed: " + _lower_first(_strip_end(_style(lead.change))), 400))
    whole = _whole(ctx)
    m = _UPSIZE_FROM_RE.search(whole)
    if m and "existing:" not in line and _FACILITY_CONTEXT_RE.search(whole[max(0, m.start() - 160):m.start()]):
        old, new = _first_amount(m.group("old")), _first_amount(m.group("new"))
        q = _quote_text(ctx, m.group(0)) if old and new and any(abs(new[0] - t.mm) < 1e-6 for t in main) else None
        if q:
            line += f" (upsized from {old[1]})"
            fac.evidence.append(q)
    m = _UPSIZE_OF_RE.search(whole)
    if m and "existing" not in line and "upsized" not in line:
        add, old = _first_amount(m.group("add")), _first_amount(m.group("old"))
        q = _quote_text(ctx, m.group(0)) if add and old and any(abs(add[0] + old[0] - t.mm) < 1e-6 for t in main) else None
        if q:
            line += f" ({add[1]} upsize of the existing {old[1]} facility)"
            fac.evidence.append(q)
    fac.lines = [_cap(line)] + extra_lines
    step_line, step_q = "", None
    m = _STEP_DOWN_RE.search(whole)
    if m:  # a scheduled step-down of the commitments
        amt = _first_amount(m.group("amt"))
        step_q = _quote_text(ctx, m.group("how"))
        if amt and step_q:
            how = _SHALL_BE_RE.sub("", m.group("how"))
            step_line = _clip(f"Commitments {how} {amt[1]} {m.group('when').lower()} {_strip_end(m.group('event'))}")

    quotes: list[dict] = []
    for t in main[:2]:
        q = _quote_text(ctx, t.snippet, pages=(1, 2, 3)) if from_title else (_quote(ctx, t.cell.block, t.snippet) if t.cell else None)
        if q:
            quotes.append(q)
    subs, sub_ev, sub_lines = _sublimits(ctx, cells)
    if subs:
        fac.lines.append(_clip("Sub-limits: " + "; ".join(subs), 300))
    fac.lines += sub_lines
    if cur_line and cur_q:
        fac.lines.append(cur_line)
    if step_line and step_q:
        fac.lines.append(step_line)
    fac.evidence = quotes + fac.evidence + sub_ev[:1] + ([cur_q] if cur_q else []) + ([step_q] if step_line and step_q else []) + sub_ev[1:]
    return fac


def facility(ctx: Ctx) -> dict:
    """Total amount and type on one line, then sub-limits and currencies if stated."""
    fac = _analyse(ctx)
    if not fac.main or not fac.lines:
        return not_stated(note="No section that describes the facility (type and amount) was recognised by the rules; check the term sheet.")
    return stated(fac.lines, fac.evidence, fac.note)


# ======================================================================================================
# 4. Borrowers
# ======================================================================================================

L_BORROWER = _label(r"(?:issuers?\s*/\s*)?(?:the\s+|initial\s+|original\s+)?(?:co-?)?borrower(?:s|\(s\))?(?:\s*/\s*issuers?)?")
# "Issuer", "Co-Issuers": the first row of a summary of notes or bonds (not "Issuer / Borrower", not "L/C Issuer")
L_ISSUER = _label(r"(?:co-?)?issuers?")
L_MORE_BORROWERS = _label(r"(?:(?:additional|designated|subsidiary|foreign|domestic|borrowing)\s+){1,3}(?:borrowers?|subsidiar(?:y|ies))")
# A sentence that says who borrows under one facility: "With respect to the Euro Term Loan Facility, Acme B.V., a ..."
_PER_FACILITY_RE = re.compile(
    r"^(?:With\s+respect\s+to|In\s+respect\s+of|In\s+the\s+case\s+of|For\s+purposes\s+of|For|Under)\s+(?:the\s+)?(?P<fac>[^,]{3,80}?)\s*,\s+(?P<who>\S.*)$")
# What such a lead-in names is a facility, a tranche or its loans.
_FACILITY_NAME_RE = re.compile(r"facilit|\bloans?\b|revolv|tranche|commitments|\bRCF\b|\bTL[AB]\b", re.IGNORECASE)
# A phrase that opens like this is a lead-in or a clause, not the name of a borrower.
_NOT_A_NAME_RE = re.compile(r"(?:With|Under|As|Pursuant|By|Solely|Only|Except|Notwithstanding|Other|Certain|Where|When|After|Before|Until)\b")
# A borrower given by the name the term sheet defines for it in a row of its own: "the Company", "the Parent", "Holdings"
_PARTY_REF_RE = re.compile(r"^(?:[Tt]he\s+)?(?P<party>Company|Parent|Holdings)\b")
# A corporate suffix after a comma is part of the name: "Acme Holdings, Inc.", "Acme Energy, LLC"
_CORP_SUFFIX = r"(?:Inc\.?|LLC|L\.L\.C\.|Ltd\.?|Limited|L\.P\.|LP|N\.A\.|NA|S\.A\.|B\.V\.|N\.V\.|PLC|plc|Corp\.?|Co\.|GmbH|S\.p\.A\.|S\.à\s?r\.l\.)"
_SUFFIX_COMMA_RE = re.compile(rf",\s*(?={_CORP_SUFFIX}(?:[\s,;.)]|$))")
# Two names run together where a table cell lost its line break: "Acme Energy, LLC Acme Energy Global Operations, LLC"
_LOST_BREAK_RE = re.compile(r"(\b(?:LLC|Inc\.|Ltd\.|plc|PLC|B\.V\.|N\.V\.|GmbH|L\.P\.))\s+(?=[A-Z][a-z])")
# Separators between borrowers: "; ", ", and ", " and ", ", ", "(i)", "(ii)"
_ENTITY_SEP_RE = re.compile(r"(?:\s*[;,]\s*|\s+)?(?:(?:and|or)\s+)?(?:\((?:[ivx]{1,4}|[a-h]|\d)\)\s*)?", re.IGNORECASE)
# Where a borrower's name ends: before ", a Delaware corporation", before the next name, or before a clause.
_NAME_END_RE = re.compile(r",\s+an?\s+(?=[\w])|\s*;\s*|,\s+(?:and\s+)?(?=\(?[A-Z\d(])|\s+and\s+(?=\(?(?:[ivx]{1,4}\)|[A-Z]))|,?\s+(?:and|or)\s+(?=[a-z])|,\s+(?=[a-z])")
# Where the description of a borrower ends: at a comma or "and" followed by the next name, or at ", and <a clause>".
# ("X, a Delaware corporation and Y LLC, a Delaware limited liability company": after "and", a name that has a corporate suffix or
# a description of its own; "organized under the laws of England and Wales" is not one)
_NEXT_NAME = (r"(?:[A-Z0-9]\S*\s+){0,6}?(?:[A-Z0-9]\S*,\s+an?\s|(?:[A-Z0-9]\S*\x00)?(?:Inc\.?|LLC|L\.L\.C\.|Ltd\.?|Limited|L\.P\.|LP|S\.A\.|B\.V\.|N\.V\.|PLC|plc|"
              r"Corp\.?|Corporation|Incorporated|GmbH|ULC|S\.p\.A\.)(?=[\s,;.)]|$))")
_DESC_END_RE = re.compile(r",\s+(?:and\s+)?(?=\(?(?:[ivx]{1,4}\)|[A-Z]))|\s*;\s*|\s+and\s+(?=\([ivx]{1,4}\))|\s+and\s+(?=" + _NEXT_NAME + r")|"
                          r"(?P<clause>,\s+(?:and|or)\s+(?=[a-z]))")
# The sentence says which borrower borrows under which facility, in whatever order: "the Company, with respect to the Term Facility,
# and ...", "Acme B.V. (in respect of the Revolving Facility)", "..., as borrower under the Term Facility"
_PER_FACILITY_PHRASE_RE = re.compile(
    r"\b(?:with\s+respect\s+to|in\s+respect\s+of|in\s+the\s+case\s+of|for\s+purposes\s+of|under|as\s+(?:the\s+)?(?:sole\s+)?borrowers?\s+(?:under|of|for))\s+"
    r"(?:the\s+|each\s+|any\s+)?(?:[\w.-]+\s+){0,5}?(?:Facilit(?:y|ies)|Loans?|Tranches?|Commitments)\b", re.IGNORECASE)
# What is left after the names is a qualifier of the last of them, not a clause of its own: "as borrower under ...", "in each case ..."
_QUALIFIER_TAIL_RE = re.compile(r"^(?:as|with|in|under|for|solely|only|pursuant|to\s+the\s+extent)\b", re.IGNORECASE)
# A sentence that opens with the facility as a label: "Term Facility: Acme Corporation, a Delaware corporation."
_FACILITY_LABEL_SENT_RE = re.compile(r"^(?P<fac>[A-Z0-9][^:,.;()]{2,60}?(?:Facilit(?:y|ies)|Loans?|Tranche|Commitments)):\s+(?P<who>\S.*)$")
# A sentence about one facility that follows a name ending in an abbreviation: "... Acme B.V. With respect to the Revolving Facility, ..."
_PER_FACILITY_BREAK_RE = re.compile(r"(?<=\.)\s+(?=(?:With\s+respect\s+to|In\s+respect\s+of|In\s+the\s+case\s+of|For\s+purposes\s+of|Under)\s+(?:the|each)\s)")
# A borrower given only by the name the term sheet defines for a party: "The Company", "the Parent", "Holdings"
_PARTY_ONLY_RE = re.compile(r"(?:the\s+)?(?:Company|Parent|Holdings)", re.IGNORECASE)
# A "... Subsidiaries" row belongs to the borrowers only if it speaks of borrowing
_BORROW_TALK_RE = re.compile(
    r"\bas\s+(?:an?\s+)?(?:additional\s+|co-?\s?|designated\s+|subsidiary\s+)*borrowers?\b|\bco-?\s?borrowers?\b|\bbecome\s+(?:an?\s+)?(?:additional\s+)?"
    r"borrowers?\b|\b(?:may|shall|will)\s+(?:be\s+(?:permitted|entitled)\s+to\s+)?borrow\b|\bborrowers?\s+under\b|\bborrowing\s+subsidiar", re.IGNORECASE)
_BORROWER_LABEL_RE = re.compile(r"borrower", re.IGNORECASE)
# "each of the Borrowers shall be jointly and severally liable for all payment and indemnification obligations"
_JOINT_LIABILITY_RE = re.compile(r"(?:each\s+of\s+)?the\s+Borrowers\s+(?:shall|will)\s+be\s+jointly\s+and\s+severally\s+liable\s+for\s+[^.,;]{5,90}",
                                 re.IGNORECASE)
# The separator that opens a borrower's description: ", a Delaware corporation"
_DESC_START_RE = re.compile(r",\s+an?\s")
# "joint and several", "jointly and severally"
_JOINT_SEVERAL_RE = re.compile(r"joint(?:ly)?\s+and\s+several", re.IGNORECASE)
_JOINT_WORD_RE = re.compile(r"\bjoint", re.IGNORECASE)
# A clause that lets further borrowers be added.
_ADD_BORROWER_RE = re.compile(r"designat|additional\s+borrower|other\s+(?:[\w-]+\s+){0,3}subsidiar|from\s+time\s+to\s+time|as\s+(?:are|may\s+be)\s+requested|"
                              r"acced|become\s+(?:a\s+)?borrower", re.IGNORECASE)


# A bracket inside a name or its description: "(incorporated in England and Wales with registered number 01234567)"
_BRACKET_RE = re.compile(r"\([^()]*\)")
# Separators are hidden while the names are told apart (the comma before "Inc.", and whatever stands inside a bracket), then put back.
_MASKS = ((",", "\x01"), (";", "\x02"), (" and ", " \x03 "), (" or ", " \x04 "))


def _unmask(text: str) -> str:
    """Put back the separators that ``_entities`` hid."""
    text = text.replace("\x00", ", ")
    for plain_text, mask in _MASKS:
        text = text.replace(mask, plain_text)
    return text


def _entities(text: str, plain: bool) -> tuple[list[str], str]:
    """(borrowers with their description, trailing clause) from the opening sentence of a Borrowers section."""
    s = _SUFFIX_COMMA_RE.sub("\x00", text)
    for plain_text, mask in _MASKS:  # what stands inside a bracket does not separate two borrowers
        s = _BRACKET_RE.sub(lambda m, a=plain_text, b=mask: m.group(0).replace(a, b), s)
    if plain:
        s = _LOST_BREAK_RE.sub(r"\1; ", s)
    names: list[str] = []
    tail = ""
    pos = 0
    guard = 0
    while pos < len(s) and guard < 40:
        guard += 1
        m = _ENTITY_SEP_RE.match(s, pos)
        if m and m.end() > pos:
            pos = m.end()
            continue
        if not (s[pos].isupper() or s[pos].isdigit()):
            tail = s[pos:]
            break
        m = _NAME_END_RE.search(s, pos)
        if m is None:
            names.append(s[pos:])
            break
        name = s[pos:m.start()]
        sep = m.group(0)
        if _DESC_START_RE.match(sep):  # ", a Delaware corporation ..."
            d = _DESC_END_RE.search(s, m.end())
            desc = s[m.end():d.start()] if d else s[m.end():]
            names.append(f"{name} ({_strip_name(_unmask(desc))})")
            pos = d.end() if d else len(s)
            if d and d.group("clause"):  # ", and certain other subsidiaries designated ...": not a name
                tail = s[pos:]
                break
        elif s[m.end():m.end() + 1].islower() and not sep.strip().startswith(";"):  # a clause follows: the rest is not a name
            names.append(name)
            tail = s[m.end():]
            break
        else:
            names.append(name)
            pos = m.end()
    clean = [_strip_name(_unmask(n)) for n in names]
    return [n for n in clean if n], _strip_end(_unmask(tail))


# A table of sub-limits by borrower: "Borrower Sublimits" beside rows of "A) Acme Energy Corporation   $2,525 MM   $5,575 MM"
_BORROWER_SUB_LABEL = r"borrower\s+sub-?\s?limits?"
# A cell of such a table that is only an amount with its unit.
_TABLE_AMOUNT_RE = re.compile(r"^\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s?(MM|mm|million|bn|billion|m)$")
# The letter or number in front of a row: "A) Acme Energy Corporation"
_ROW_MARK_RE = re.compile(r"^\(?[A-Za-z0-9]{1,2}\)\s*")


def _borrower_sublimits(ctx: Ctx) -> tuple[list[str], list[dict]]:
    """Sub-limits by borrower from a table: one "name amount / amount" item per row, under the table's column names."""
    try:
        blocks = ctx.blocks(_BORROWER_SUB_LABEL)
    except re.error:
        return [], []
    view = ctx.doc
    for b in blocks[:1]:
        lab = _label_line(b)
        lo = hi = lab.n  # the table is the unbroken run of lines around the label
        while lo > 0 and not view.lines[lo - 1].blank and view.lines[lo - 1].page == lab.page:
            lo -= 1
        while hi + 1 < len(view.lines) and not view.lines[hi + 1].blank and view.lines[hi + 1].page == lab.page:
            hi += 1
        header: list[str] = []
        rows: list[tuple[str, list[str]]] = []
        for ln in view.lines[lo:hi + 1]:
            cells = [c[2].strip() for c in fragments(ln.text, 3)]
            if ln.n == lab.n:
                cells = cells[1:]
            nums = [c for c in cells if _TABLE_AMOUNT_RE.match(c)]
            names = [c for c in cells if not _TABLE_AMOUNT_RE.match(c)]
            if nums and len(names) == 1:
                rows.append((names[0], nums))
            elif not nums and len(names) >= 2 and not rows:
                header = names
        if len(rows) < 2 or len({len(r[1]) for r in rows}) != 1:
            continue
        ncols = len(rows[0][1])
        cols = [h.lower() for h in header[-ncols:]] if len(header) > ncols else []
        items = []
        for name, nums in rows:
            vals = []
            for num in nums:
                m = _TABLE_AMOUNT_RE.match(num)
                value = float(m.group(1).replace(",", "")) * (1000 if m.group(2).lower() in ("bn", "billion") else 1)
                vals.append(fmt_money(value))
            items.append(f"{_ROW_MARK_RE.sub('', name)} {' / '.join(vals)}")
        head = "Borrower sublimits" + (f" ({' / '.join(cols)})" if cols else "") + ": "
        packed = _pack(items, 290 - len(head))
        q = _quote_text(ctx, rows[0][0] + " " + rows[0][1][0], pages=(lab.page,))
        if q:
            return [head + packed[0]] + packed[1:3], [q]
    return [], []


def _pack(items: list[str], limit: int = 230) -> list[str]:
    """Join short items with "; " into as few lines as the limit allows."""
    lines: list[str] = []
    for item in items:
        if lines and len(lines[-1]) + 2 + len(item) <= limit:
            lines[-1] += "; " + item
        else:
            lines.append(item)
    return lines


def _defined_party(ctx: Ctx, whos: list[str], own: Block) -> tuple[str, dict] | None:
    """Where a borrower is given only as "the Company" (or "the Parent", "Holdings") and the term sheet names that party
    in a row of its own - "Company: Acme Corporation, a Delaware corporation" - a line with that row's opening words."""
    for who in whos:
        m = _PARTY_REF_RE.match(who)
        if not m:
            continue
        spec = _label(r"(?:the\s+)?" + m.group("party").lower())
        for b in _find(ctx, spec, zone=False)[:1]:
            if _label_line(b).n == _label_line(own).n:
                continue
            c = _cell(ctx, b, spec)
            opening = _strip_name((_sents(_AS_DEFINED_RE.sub("", _drop_defined(c.text))) or [""])[0])
            if 3 <= len(opening) <= 160 and opening[:1].isupper() and not (_COMMON_OPENER_RE.match(opening) or _NOT_A_NAME_RE.match(opening)):
                q = _quote(ctx, c.block)
                if q:
                    return f"{_title(b.label)}: {_style(opening)}", q
    return None


def borrowers(ctx: Ctx) -> dict:
    """Each borrower by name with its entity type, then any right to add borrowers."""
    blocks = [b for b in _find(ctx, L_BORROWER, zone=False) if len(_strip_end(b.text)) >= 3]
    if not blocks:
        return not_stated()
    block = blocks[0]
    cell = _cell(ctx, block, L_BORROWER)
    if not cell.text:
        return not_stated()
    text = _AS_DEFINED_RE.sub("", _drop_defined(cell.text))
    sents = [part.strip() for s in _sents(text) for part in _PER_FACILITY_BREAK_RE.split(s) if part.strip()]
    first = sents[0].strip() if sents else ""
    if _defers(first.strip("[] ")):  # "Same as under the Existing Credit Agreement", "To be determined"
        return by_reference([_clip(_cap(_strip_end(_style(first))))], [_quote(ctx, cell.block)])
    ev = [_quote(ctx, cell.block)]
    lines: list[str] = []
    names: list[str] = []
    # a section that goes facility by facility: "With respect to the Euro Term Loan Facility, Acme B.V., a ... . With respect to ..."
    per_facility: list[tuple[str, str]] = []
    for s in sents[:6]:
        m = _PER_FACILITY_RE.match(s.strip()) or _FACILITY_LABEL_SENT_RE.match(s.strip())
        if not (m and _FACILITY_NAME_RE.search(m.group("fac"))):
            break
        per_facility.append((_strip_end(m.group("fac")), _strip_name(m.group("who"))))
    if per_facility:
        lines = [_clip(f"{_style(fac)}: {_style(who)}", 330) for fac, who in per_facility]
        if cell.same:
            lines[-1] += " (same as existing)"
        ev += [_quote(ctx, cell.block, who[:50]) for _, who in per_facility[1:3]]
        party = _defined_party(ctx, [who for _, who in per_facility], block)  # "the Company" is named in its own row
        if party:
            lines.append(party[0])
            ev.append(party[1])
        more = sents[len(per_facility):len(per_facility) + 4]
    else:
        names, tail = _entities(first, plain=block.mode == "plain")
        # an ordinary word in first place ("Initially, ...", "With respect to ...") is not a name: the sentence is then kept as it stands
        named = all(n.startswith("The ") or not (_COMMON_OPENER_RE.match(n) or _NOT_A_NAME_RE.match(n)) for n in names)
        # a sentence that ties borrowers to facilities, or whose close only qualifies the last name, is not a list to take apart
        listed = not _PER_FACILITY_PHRASE_RE.search(first) and not (tail and _QUALIFIER_TAIL_RE.match(tail))
        if names and named and listed and all(len(n) <= 230 for n in names):
            lines = names if len(names) <= 4 and sum(len(n) for n in names) > 110 else _pack(names)
            lines = lines[:5]
            party = _defined_party(ctx, [n for n in names if _PARTY_ONLY_RE.fullmatch(n)], block)  # "The Company" is named in its own row
            if party:
                lines.append(party[0])
                ev.append(party[1])
        else:
            lines = [_clip(_strip_name(first), 330)]
            names, tail = [], ""
        if cell.same:
            lines[-1] += " (same as existing)"
        if tail:
            prefix = "Right to add borrowers: " if _ADD_BORROWER_RE.search(tail) else ""
            lines.append(_clip(prefix + (tail if prefix else _cap(tail)), 330))
            ev.append(_quote(ctx, cell.block, tail[:50]))
        more = sents[1:3]
    for s in more:  # joint liability, designation mechanics
        if _JOINT_SEVERAL_RE.search(s) or _ADD_BORROWER_RE.search(s):
            lines.append(_clip(_strip_end(_style(s))))
            ev.append(_quote(ctx, cell.block, s[:50]))
    for b in _find(ctx, L_MORE_BORROWERS)[:2 if per_facility else 1]:
        c = _cell(ctx, b, L_MORE_BORROWERS)
        if not (_BORROWER_LABEL_RE.search(b.label) or _BORROW_TALK_RE.search((_sents(c.text) or [c.text])[0])):
            continue  # "Foreign Subsidiaries: ... shall not be required to provide guarantees": not about who may borrow
        if c.text and _label_line(b).n != _label_line(block).n:
            lines.append(_clip(f"{_title(b.label)}: {_lower_first(_strip_end(_style((_sents(c.text) or [c.text])[0])))}"))
            ev.append(_quote(ctx, c.block))
    if len(names) > 1 and not any(_JOINT_WORD_RE.search(x) for x in lines):
        m = _JOINT_LIABILITY_RE.search(_whole(ctx))  # joint liability stated elsewhere in the term sheet
        q = _quote_text(ctx, "jointly and severally liable") if m else None
        if m and q:
            lines.append(_clip(_cap(_strip_end(_style(m.group(0))))))
            ev.append(q)
    sub_lines, sub_ev = _borrower_sublimits(ctx)
    lines += [_clip(x, 330) for x in sub_lines]
    ev[1:1] = sub_ev
    return stated(lines[:8], [e for e in ev if e])


# ======================================================================================================
# 5. Lender commitments
# ======================================================================================================

_ROLE_WORD = (r"(?:sole|joint|left|lead|mandated|global|active|passive|senior|sr\.?|managing|administrative|admin\.?|facility|collateral|"
              r"security|syndication|documentation|co-?\s?documentation|co-?\s?syndication|co-?|paying|exclusive)")
_ROLE_NOUN = r"(?:agents?|arrangers?|book\s?-?runners?|bookrunner\(s\)|book\s?-?managers?|coordinators?)"
L_ROLE = _label(
    r"(?:[\w\-.]+\s+){0,5}(?:agents?|arrangers?|book\s?-?runners?|bookrunner\(s\)|book\s?-?managers?|coordinators?)(?:\s+and)?|"
    r"(?:administrative|admin\.?|joint|co-?\s?documentation|co-?\s?syndication|lead|sole|mandated)(?:\s+[\w\-]+){0,3}(?:\s+and)?",
    rf"(?:{_ROLE_WORD}\s*)*(?:and\s+)?(?:{_ROLE_WORD}\s*)*{_ROLE_NOUN}(?:\s*(?:and|&|/)\s*(?:{_ROLE_WORD}\s*)*{_ROLE_NOUN})*")
L_LENDERS = _label(r"(?:revolving\s+|initial\s+|original\s+|term\s+)?lenders?")
# Where the names stop in a role sentence: "... will act as sole administrative agent", "(in such capacity, ...", ", as ..."
_ROLE_VERB_RE = re.compile(
    r"\s+(?:will|shall|to)\s+(?:each\s+)?(?:act|serve|be)\b|\s+acting\s+|\s+\(in\s+(?:its|their|such)\s+capacit|,?\s+in\s+(?:its|their|such)\s+capacit|"
    r",\s+as\s+(?:sole|joint|lead|administrative|the)\b|\s+has\s+been\s+|\s+have\s+been\s+", re.IGNORECASE)
# A role given in passing, outside any labelled section: "First National Bank, N.A. (the “Lead Arranger”)", "(together, the “Active Arrangers”)"
_INLINE_ROLE_RE = re.compile(r"\((?:together|collectively|each)?,?\s*(?:in\s+such\s+capacit(?:y|ies),?\s*)?(?:the\s+)?[“\"]\s*"
                             r"(?P<role>(?:[A-Z][\w-]*\s+){0,4}(?:Arrangers?|Bookrunners?|Agent|Coordinators?))\s*[”\"]\s*\)")
# One token of a bank's name, walking backwards from such a bracket.
_NAME_TOKEN_RE = re.compile(r"^(?:[A-Z][\w.&'’\-]*,?|N\.A\.,?|of|and|&|de)$")
# A commitment table: rows of a bank's name and an amount under a header that says the figures are commitments,
# allocations or holds. ("Amount" alone is not enough: sources-and-uses and league tables have it too.)
_COMMIT_HEADER_RE = re.compile(r"\b(?:commitments?|allocations?|(?:final\s+|target\s+)?holds?)\b", re.IGNORECASE)
# The header gives the unit of bare figures: "Commitment ($mm)", "(in millions)", "US$ millions"
_TABLE_UNIT_RE = re.compile(r"\(\s*(?:US)?\$?\s*(?:in\s+)?(?:mm|mn|m|millions?)\s*\)|\$\s?(?:mm|mn|millions?)\b|\bin\s+(?:US\$\s*|\$\s*)?millions\b", re.IGNORECASE)
# The first cell of the Barclays row is the bank's name and nothing else: "Barclays", "Barclays Bank PLC", "Barclays Bank Ireland PLC"
_BARCLAYS_NAME_RE = re.compile(r"Barclays(?:\s+(?:Bank|Capital|Ireland|Europe|Securities|Delaware|Inc\.?|PLC|LLC|Limited|Ltd\.?|SE|AG|US|UK),?)*", re.IGNORECASE)
# A table cell that is only a figure: "150.0", "1,250"
_BARE_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?")
# A row that sums the table: "Total", "Total Commitments", "Aggregate"
_TOTAL_ROW_RE = re.compile(r"^(?:grand\s+)?(?:total|aggregate|sum)\b", re.IGNORECASE)
# "Barclays ... commits to provide $150,000,000", "Barclays' commitment of $150 million"
_BARCLAYS_COMMIT_RE = re.compile(
    rf"Barclays(?P<gap>[^.;]{{0,80}}?)\bcommit(?:s|ted|ment)?\s+(?:to\s+(?:provide|lend|fund|underwrite)\s+|of\s+|in\s+(?:an\s+)?(?:aggregate\s+)?"
    rf"(?:principal\s+)?amount\s+(?:of|equal\s+to)\s+|equal\s+to\s+)(?:up\s+to\s+)?(?P<amt>{_M})(?P<after>[^.;]{{0,40}})", re.IGNORECASE)
# The commitment is a condition or a threshold, not a commitment made: "if it provides a commitment of $100,000,000 or more",
# "a fee for commitments of at least ...", or a figure for several banks together ("in the aggregate")
_COMMIT_HEDGE_RE = re.compile(r"\b(?:if|fees?|least|minimum|any\s+lender|each\s+lender|lenders?\s+(?:with|providing|holding)|aggregate|total|together|"
                              r"collectively)\b|\bor\s+(?:more|greater)\b", re.IGNORECASE)
# Several banks are named before the verb ("Barclays and Citi have committed ...") and the figure is not said to be for each of them.
_SEVERAL_BANKS_RE = re.compile(r",|\band\b", re.IGNORECASE)
_EACH_RE = re.compile(r"\beach\b", re.IGNORECASE)  # "have each committed", "$100,000,000 each"

# The names ran on into the next label and stop on a dangling word: "... Inc. Joint Lead Arrangers and"
_DANGLING_WORD_RE = re.compile(r"\b(?:and|the|of|to)$")
# "(or any of its designated affiliates)", "(and/or its affiliates)" after a bank's name
_OR_AFFILIATES_RE = re.compile(r"\s*\((?:or|and/or)\s[^()]{0,80}\)")
# "To be agreed", "To be determined" instead of a name
_TO_BE_RE = re.compile(r"To\s+be\s")
# A defining bracket that also says the role is shared with others still to be named: "(in such capacity, together with any other
# joint lead arrangers appointed pursuant to ..., the “Lead Arrangers”)"
_ROLE_OTHERS_RE = re.compile(r"\((?:in\s+(?:such|its|their)\s+capacit(?:y|ies),?\s+)?(?:and\s+)?(?P<more>(?:together|collectively|along)\s+with\s+"
                             r"(?:any|such|certain|each|one\s+or\s+more)\s+(?:other|additional|further)\s+[^()“”\",]{3,120})", re.IGNORECASE)
_OTHERS_WORD_RE = re.compile(r"\b(?:other|additional|further)\b", re.IGNORECASE)  # the names already say there are more to come
# Barclays is named in the Lenders section, but not as one of the lenders: "... under the Credit Agreement dated ... with
# Barclays Bank PLC as agent"
_NOT_AS_LENDER_BEFORE_RE = re.compile(r"\b(?:Agreement|dated|under\s+the|party\s+to|agent\s+for|arranged\s+by|other\s+than|excluding|except)\b[^.;]{0,80}$",
                                      re.IGNORECASE)
_NOT_AS_LENDER_AFTER_RE = re.compile(r"^[^.;]{0,40}?\bas\s+(?:the\s+)?(?:sole\s+|joint\s+|lead\s+|administrative\s+|collateral\s+)*(?:agent|arranger|bookrunner)", re.IGNORECASE)
# What stands between "Barclays" and "commit" makes it an expectation or a proposal, not a commitment made
_COMMIT_INTENT_RE = re.compile(r"\b(?:expect\w*|anticipat\w*|propos\w*|intends?|may|might|could|would|invited|asked|target\w*|indicative|"
                               r"not|no)\b", re.IGNORECASE)
# An abbreviation in front of a title that the shared finder takes for an item number: "Sr. Managing Agents"
_TITLE_PREFIX_RE = re.compile(r"\s*((?:Sr|Jr|Co)\.)\s+")
# A role in the plural, to say what one bank is named as: "Joint Lead Arrangers" -> "Joint Lead Arranger"
_PLURAL_ROLE_RE = re.compile(r"\b(Agent|Arranger|Bookrunner|Manager|Coordinator)s\b")
# The agent's own row ("Administrative Agent", "Admin agent", "Facility Agent", "Agent") comes first in the line,
_AGENT_TITLE_RE = re.compile(r"admin|facility\s+agent|^agent", re.IGNORECASE)
# then the arrangers and bookrunners.
_ARRANGER_TITLE_RE = re.compile(r"arranger|bookrunner", re.IGNORECASE)
_BARCLAYS_RE = re.compile(r"\bbarclays\b", re.IGNORECASE)  # the bank whose template this is, among the names of a role
# On a page read without layout, the next label (in capitals) runs on in the same line: "... N.A. CO-DOCUMENTATION Barclays ..."
_CAPS_LABEL_RE = re.compile(r"\s+(?=[A-Z][A-Z/&-]{5,}\b)")


def _role_names(text: str, plain: bool = False, limit: int = 150) -> str:
    """The institutions named in a role section, without the boilerplate around them (cut to ``limit`` characters)."""
    t = _AS_DEFINED_RE.sub("", _drop_defined(_norm(text)))
    first = (_sents(t) or [t])[0]
    if plain:
        first = _CAPS_LABEL_RE.split(first)[0]
        if _DANGLING_WORD_RE.search(first):  # ran on into the next label: "... Inc. Joint Lead Arrangers and"
            first = first[:first.rfind(". ") + 1] if ". " in first else ""
    m = _ROLE_VERB_RE.search(first)
    if m and m.start() > 2:
        head, rest = first[:m.start()], first[m.end():].strip()
        if L_ROLE[1].fullmatch(_LEADING_THE_RE.sub("", _strip_end(head))):
            # "The Lead Arranger will be First National Bank": the sentence opens with the role and the name follows the verb
            first = rest if rest[:1].isupper() or rest[:1] == "[" else ""
        else:
            first = head
    first = _OR_AFFILIATES_RE.sub("", first)
    first = _strip_name(first).replace("[ ]", "[ ] (left blank in term sheet)")
    # the bracket that defines the role may say it is shared with others still to be appointed: the list of names is then not closed
    others = _ROLE_OTHERS_RE.search((_sents(_norm(text)) or [""])[0])
    if first and others and not _OTHERS_WORD_RE.search(first):
        first = f"{first}, {_strip_end(others.group('more'))}"
    return _clip(_lower_first(first) if _TO_BE_RE.match(first) else first, limit)


def _role_title(block: Block) -> str:
    """The role as a title. The shared finder reads "Sr." in "Sr. Managing Agents" as an item number; put it back."""
    title = _title(block.label)
    cells = fragments(_label_line(block).text, 3)
    m = _TITLE_PREFIX_RE.match(cells[0][2]) if cells else None
    return f"{m.group(1)} {title}" if m and not title.startswith(m.group(1)) else title


def _singular(title: str) -> str:
    """A role title in the singular, for what one bank is named as."""
    return _PLURAL_ROLE_RE.sub(r"\1", title)


def _inline_roles(ctx: Ctx) -> list[tuple[str, str, dict]]:
    """(role, names, quote) for roles defined in passing in the opening pages of a presentation."""
    out: list[tuple[str, str, dict]] = []
    for page, raw in enumerate(ctx.raw.pages[:4], 1):
        text = _norm(raw)
        for m in _INLINE_ROLE_RE.finditer(text):
            tokens = text[:m.start()].split()
            names: list[str] = []
            for tok in reversed(tokens[-40:]):
                if not _NAME_TOKEN_RE.match(tok):
                    break
                names.insert(0, tok)
            while names and names[0] in ("of", "and", "&", "de"):
                names.pop(0)
            if not names or not any(n[0].isupper() for n in names):
                continue
            role = m.group("role").strip()
            if any(r == role for r, _, _ in out):
                continue
            q = _quote_text(ctx, m.group(0), pages=(page,))
            if q:
                out.append((role, _strip_name(" ".join(names)), q))
    return out


def _table_amount(cell: str, unit_mm: bool) -> float | None:
    """Value in millions of a table cell that is only an amount; None for any other cell. ``unit_mm`` says the
    table's header gives its figures in millions ("Commitment ($mm)"), so "150" and "$150" are $150m."""
    cell = _norm(cell).strip()
    m = MONEY_RE.fullmatch(cell)
    if m:
        mm = money_mm(m)
        if mm is not None and unit_mm and not m.group("unit") and mm < 0.1:
            mm *= 1e6
        return mm
    if unit_mm and _BARE_NUMBER_RE.fullmatch(cell):
        return float(cell.replace(",", ""))
    return None


def _table_row(ln: Line, unit_mm: bool) -> tuple[str, list[float]] | None:
    """(name, amounts in millions) if the line is a row of a lender table: a short name cell followed by cells of
    which at least one is an amount of $1m or more (titles and percentages in between are skipped)."""
    cells = fragments(ln.text, 2)
    if len(cells) < 2:
        return None
    name = _norm(cells[0][2])
    if not name[:1].isupper() or len(name.split()) > 8 or name.endswith(":"):
        return None
    values = [v for v in (_table_amount(c[2], unit_mm) for c in cells[1:]) if v is not None]
    if not values or min(values) < 1:
        return None
    return name, values


def _commitment_table(ctx: Ctx) -> tuple[list[str], list[dict]]:
    """Lender-by-lender commitments, if the document prints a table that includes Barclays: a Barclays row under a
    header that says the figures are commitments (or allocations / holds), with the other lenders' rows around it."""
    lines_by_page: dict[int, list[Line]] = {}
    for ln in ctx.doc.lines:
        lines_by_page.setdefault(ln.page, []).append(ln)
    for page, lines in lines_by_page.items():
        for i, ln in enumerate(lines):
            cells = fragments(ln.text, 2)
            if len(cells) < 2 or not _BARCLAYS_NAME_RE.fullmatch(_norm(cells[0][2])):
                continue
            # the header: the nearest line above that names the figures, with nothing but rows (and at most two other lines) in between
            header, stray = None, 0
            for h in reversed(lines[max(0, i - 40):i]):
                if h.blank or _table_row(h, True) is not None:
                    continue
                if _COMMIT_HEADER_RE.search(h.text) and len(h.text.strip()) < 200:
                    header = h
                    break
                stray += 1
                if stray > 2:
                    break
            if header is None:
                continue
            unit_mm = bool(_TABLE_UNIT_RE.search(header.text))
            row = _table_row(ln, unit_mm)
            if row is None:
                continue
            mine = row[1]
            heads = [c[2].strip() for c in fragments(header.text, 2)][-len(mine):] if len(mine) > 1 else []
            if len(mine) > 1 and (len(heads) != len(mine) or any(len(h) > 40 for h in heads)):
                continue  # several amounts and no way to tell which is which

            def show(vals: list[float]) -> str:
                return " + ".join(f"{fmt_money(v)} ({h})" for v, h in zip(vals, heads)) if heads else fmt_money(vals[0])

            def neighbours(seq) -> list[str]:
                found, blanks = [], 0
                for other in seq:
                    if other.blank:
                        blanks += 1
                        if blanks > 1:
                            break
                        continue
                    blanks = 0
                    r = _table_row(other, unit_mm)
                    if r is None or len(r[1]) != len(mine) or _TOTAL_ROW_RE.match(r[0]):
                        break
                    found.append(f"{_strip_name(r[0])} = {show(r[1])}")
                return found
            above = neighbours(reversed(lines[max(0, i - 40):i]))[::-1]
            below = neighbours(lines[i + 1:i + 41])
            others = above + below
            out = [f"Barclays = {show(mine)}"] + others[:6]
            if len(others) > 6:
                out.append(f"(+ {len(others) - 6} other lenders listed in the term sheet)")
            ev = [_quote_text(ctx, tidy(ln.text), pages=(page,)), _quote_text(ctx, tidy(header.text), pages=(page,))]
            return [_clip(x) for x in out], [e for e in ev if e]
    return [], []


def _barclays_commitment(ctx: Ctx) -> tuple[str, dict] | None:
    """("Barclays = <amount>", quote) from a sentence that states the commitment Barclays has made."""
    for m in _BARCLAYS_COMMIT_RE.finditer(_whole(ctx)):
        around = m.group("gap") + " " + m.group("after")
        if _COMMIT_HEDGE_RE.search(around) or (_SEVERAL_BANKS_RE.search(m.group("gap")) and not _EACH_RE.search(around)):
            continue  # a condition, a threshold, or a figure for several banks together
        if _COMMIT_INTENT_RE.search(m.group("gap")):
            continue  # "is expected to commit", "has not committed": not a commitment made
        amt = _first_amount(m.group("amt"))
        q = _quote_text(ctx, m.group(0)[:len(m.group(0)) - len(m.group("after"))][-50:])
        if amt and q:
            return f"Barclays = {amt[1]}", q
    return None


def lender_commitments(ctx: Ctx) -> dict:
    """"Barclays = ..." first; other lenders' commitments if stated; otherwise the agent and arrangers, not_stated."""
    table, table_ev = _commitment_table(ctx)
    if table and table_ev:
        return stated(table, table_ev)
    committed = _barclays_commitment(ctx)
    if committed:
        return stated([committed[0]], [committed[1]])

    roles: list[tuple[str, str, bool]] = []  # (title, names, is the agent)
    ev: list[dict] = []
    barclays: list[str] = []
    for b in _find(ctx, L_ROLE, zone=False)[:8]:
        c = _cell(ctx, b, L_ROLE)
        if not c.text:
            continue
        title, names = _role_title(b), _role_names(c.text, plain=b.mode == "plain")
        if not names or (len(names.split()) < 2 and not _colon_style(ctx, ctx.doc, b.page)):
            continue  # a heading such as "Arranger  Counsel" on a contacts page is not a role
        if b.mode == "plain" and (names[0].islower() or not _starts_fresh(ctx.doc, b)):
            continue  # read without layout, "AGENT:" may be the tail of a wrapped label whose text began on the line above
        if L_ROLE[1].fullmatch(_strip_end(names.split(":")[0])):
            continue  # the "names" are another role label
        if c.old and not c.same:
            names += f" (existing: {_role_names(c.old)})"
        elif c.same:
            names += " (same as existing)"
        if any(t == title for t, _, _ in roles):
            continue
        is_agent = bool(_AGENT_TITLE_RE.search(title))
        roles.append((title, names, is_agent))
        q = _quote(ctx, c.block)
        if q:
            ev.append((0 if is_agent else 1 if _ARRANGER_TITLE_RE.search(title) else 2, q))
        if _BARCLAYS_RE.search(_role_names(c.text, plain=b.mode == "plain", limit=4000)):  # among the names, not elsewhere in the section
            barclays.append(_singular(title))
            if q:
                ev[-1] = (-1, q)
    among_lenders = False
    for b in _find(ctx, L_LENDERS, zone=False)[:2]:
        text = _norm(b.text)
        for m in _BARCLAYS_RE.finditer(text):  # named as a lender, not in passing as a party to some other agreement
            if not (_NOT_AS_LENDER_BEFORE_RE.search(text[:m.start()]) or _NOT_AS_LENDER_AFTER_RE.match(text[m.end():])):
                among_lenders = True
    if not roles:
        for role, names, q in _inline_roles(ctx)[:3]:
            roles.append((role, names, "agent" in role.lower()))
            ev.append((0, q))
            if _BARCLAYS_RE.search(names):
                barclays.append(_singular(role))
    seen_roles: list[tuple[str, str, bool]] = []
    for r in roles:  # the same institution under a longer and a shorter title ("Lead Arranger", "Arranger"): keep the first
        key = _NOT_ALNUM_RE.sub("", r[1].lower())
        if not any(key == _NOT_ALNUM_RE.sub("", o[1].lower()) and r[0].lower() in o[0].lower() for o in seen_roles):
            seen_roles.append(r)
    roles = seen_roles
    first = BARCLAYS_NOT_STATED
    if barclays or among_lenders:
        named = "named as " + ", ".join(barclays) if barclays else ""
        listed = "listed among the Lenders" if among_lenders else ""
        first += f" ({'; '.join(x for x in (named, listed) if x)})"
    if not roles:
        return {"lines": [first], "status": "not_stated", "evidence": [], "note": ""}
    roles.sort(key=lambda r: (not r[2], not _ARRANGER_TITLE_RE.search(r[0])))
    lines = [first] + _pack([f"{t}: {n}" for t, n, _ in roles], 250)[:3]
    lines[1] = "No commitments stated. " + lines[1]
    quotes = [q for _, q in sorted(ev, key=lambda x: x[0])][:3]
    return {"lines": [_clip(x, 400) for x in lines], "status": "not_stated", "evidence": quotes, "note": ""}


# ======================================================================================================
# 6. Purpose
# ======================================================================================================

L_PURPOSE = _label(r"purposes?(?:\s*(?:/|and)\s*use\s+of\s+proceeds)?|use\s+of\s+(?:proceeds|funds|loans)|application\s+of\s+proceeds")
# "... shall be used for", "will be used (i) ...", "may be utilised to"
_USED_RE = re.compile(r"\b(?:be|are|is)\s+(?:used|utili[sz]ed|applied|available)\b\s*(?:solely\s+|only\s+)?", re.IGNORECASE)
# "The proceeds of the Revolving Credit Facility shall ..."
_PROCEEDS_OF_RE = re.compile(r"proceeds\s+of\s+(?:the\s+)?(?P<subj>[^,;]{3,70}?)\s+(?:shall|will|may|are|is)\b", re.IGNORECASE)
# Numbered purposes: "(i) for working capital ...; (ii) to finance ...; and/or (iii) to refinance ..."
_ENUM_SPLIT_RE = re.compile(r"(?:^|[,;]?\s+(?:and(?:/or)?\s+|or\s+)?)\((?:[ivx]{1,4}|[a-f]|\d)\)\s+", re.IGNORECASE)
# "that certain Fourth Amended and Restated Credit Agreement dated as of June 2, 2022, among ... (as amended, the “Existing Credit Agreement”)"
_AGREEMENT_RE = re.compile(
    rf"(?:that\s+certain|the)\s+(?P<name>(?:[A-Z][\w-]*\s+|and\s+){{1,8}}?Agreement),?\s+dated\s+(?:as\s+of\s+)?(?P<date>{_DATE}),?\s+"
    r"(?:by\s+and\s+)?among\b[^()]{0,260}?\((?:as\s+amended,?\s+)?(?:the\s+)?[“\"]\s*(?P<term>[^”\"]{3,60}?)\s*[”\"]\)")
# Purpose stated in the introduction of a summary: "The proposed Facility will ... continue to be used for general corporate purposes."
_INTRO_USE_RE = re.compile(
    r"\b(?:Facilit(?:y|ies)|RCF|Revolver|Loans|Commitments)\b[^.]{0,200}?\b(?:continue\s+to\s+be|will\s+be|shall\s+be|to\s+be)\s+used\s+for\s+"
    r"(?P<rest>[^.]{5,160})\.", re.IGNORECASE)


# The existing facility is retired at closing, as a condition precedent: "repayment of amounts owing, and termination of
# commitments under the Existing Credit Agreements", "including the termination of the Existing Revolving Facility"
_REFI_CP_RE = re.compile(
    r"(?P<clause>(?:(?:re)?payment\s+of\s+[\w\s,]{3,40}?and\s+termination\s+of\s+commitments\s+under|\btermination\s+of)\s+the\s+(?-i:Existing)\s+"
    r"[\w\s-]{3,50}?(?:Agreements?|Facilit(?:y|ies)))\b", re.IGNORECASE)
# What an amendment presentation says the transaction is for: "is seeking to amend, extend and upsize its Revolving Credit Facility to ..."
_SEEKING_RE = re.compile(r"\b(?:is\s+seeking|seeks|proposes|is\s+proposing|intends|is\s+requesting|requests)\s+to\s+"
                         r"(?P<what>(?:amend|extend|upsize|increase|refinance|replace)\b[^.•–]{10,260})", re.IGNORECASE)


# The clause sits among the conditions precedent: "Conditions Precedent", "Conditions to Closing"
_CP_CONTEXT_RE = re.compile(r"conditions?\s+(?:precedent|to\s+(?:closing|effectiveness))", re.IGNORECASE)
# "for" in front of a purpose: "for working capital" -> "working capital"
_LEADING_FOR_RE = re.compile(r"^(?:for|in\s+order\s+to\s+provide\s+for)\s+")
# "and", "or", "and/or" left at the end of a numbered item
_TRAILING_AND_RE = re.compile(r"[,;]?\s*(?:and(?:/or)?|or)\s*$")
# The stated aim of the transaction is about the facility itself.
_FACILITY_MENTION_RE = re.compile(r"facilit|\bRCF\b|revolver", re.IGNORECASE)
_GCP_RE = re.compile(r"general\s+corporate\s+purposes", re.IGNORECASE)  # the purpose the template lists first
# The purposes already speak of refinancing or repaying something.
_REFINANCE_WORD_RE = re.compile(r"refinanc|repay|replace", re.IGNORECASE)


def _refinancing_condition(ctx: Ctx) -> tuple[str, dict] | None:
    """A line for the closing condition that retires the existing facility (it is not a stated use of proceeds)."""
    prev = ""
    for page, raw in enumerate(ctx.raw.pages, 1):
        text = _norm(raw)
        m = _REFI_CP_RE.search(text)
        if m and _CP_CONTEXT_RE.search((prev + " " + text[:m.start()])[-3000:]):
            clause = _strip_end(_style(m.group("clause")))
            needle = "termination of commitments" if "termination of commitments" in clause.lower() else "termination of the"
            q = _quote_text(ctx, needle, pages=(page,))
            if q:
                return _clip(f"Closing is conditional on {clause[0].lower()}{clause[1:]} (condition precedent; not stated as a use of proceeds)"), q
        prev = text
    return None


# A sentence that opens with the facility it is about: "Facility A: refinancing ...", "Term Loan Facility: to finance ..."
_LABELLED_SENT_RE = re.compile(r"^(?P<lab>Facility\s+[A-D1-4]|[A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,3}\s+(?:Facility|Loans?|Commitments)):\s+(?P<rest>.+)$")


# What stands between "used" and the first numbered purpose. A verb the items share is given back to each of them
# ("to finance (i) the Acquisition and (ii) ..."); anything else ("by the Borrower", "as follows:") is not a purpose.
_SHARED_VERB_RE = re.compile(r"(?:\bto\s+\w+|\bfor(?:\s+the)?|\bin\s+connection\s+with)$", re.IGNORECASE)
# An item that refers back to the one before it ("thereafter, for ..."): the order of the items is then part of what they say.
_SEQUENCE_RE = re.compile(r"^(?:thereafter|then|subsequently|following\s+(?:the|such|that)|after\s+(?:the|such|that))\b", re.IGNORECASE)
# A purpose given without "used": "Revolving Loans may be drawn after the Closing Date for working capital ..."
_DRAWN_FOR_RE = re.compile(r"\b(?:be|are|is)\s+(?:drawn|borrowed)\b(?=[^.;]{0,80}?\s(?:for|to)\s)\s*", re.IGNORECASE)
# The facility a sentence opens with, as its subject: "The Term Loans will ...", "Revolving Loans may ..."
_FACILITY_OPENS_RE = re.compile(r"^(?:The\s+)?(?P<subj3>[A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,3}\s+(?:Loans?|Facilit(?:y|ies)|Commitments))\s+(?:shall|will|may|are|is)\b")
# "Other" in front of the general corporate purposes when they are put first: "(iv) for other general corporate purposes"
_OTHER_GCP_RE = re.compile(r"^other\s+(?=general\s+corporate\s+purposes)", re.IGNORECASE)
# "may not be used", "shall not be applied", "no proceeds ... shall be used": the words in front of "be used" make it a restriction
_NEGATED_USE_RE = re.compile(r"\b(?:not|never)\s*$|\bno\s+(?:[\w-]+\s+){0,6}?(?:proceeds|loans?|borrowings?|advances|letters?\s+of\s+credit|part|portion)\b[^.;]{0,60}$",
                             re.IGNORECASE)
# The value is still open: "To be discussed", "[TBD]", "To be confirmed"
_TBD_RE = re.compile(r"^\W*(?:to\s+be\s+(?:discussed|confirmed|finali[sz]ed|specified|provided|completed|advised)|TBD|TBC)\b", re.IGNORECASE)
# The facility a statement of purpose is about, where it is not introduced by "proceeds of": "Loans under the Revolving
# Facility may be used ...", "The Term Loan proceeds will be used ..."
_LOANS_UNDER_RE = re.compile(r"(?:loans|advances|borrowings|drawings|letters\s+of\s+credit)\s+under\s+(?:the\s+)?(?P<subj>[^,;]{3,70}?)\s+(?:shall|will|may|are|is)\b|"
                             r"(?:the\s+)?(?P<subj2>(?-i:[A-Z])[^,;]{3,60}?)\s+proceeds\s+(?:shall|will|may|are|is)\b", re.IGNORECASE)


# Words between "used" and the first numbered purpose that are themselves a purpose: "to finance the Acquisition", "for working capital"
_PURPOSE_LEAD_RE = re.compile(r"(?:^|\s)to\s+(?:re)?(?:finance|fund|pay|repay|provide|support|consummate|effect|acquire|purchase|redeem|backstop)\b|^for\s+\w", re.IGNORECASE)


def _defers(text: str) -> bool:
    """The passage opens by pointing to another document, or leaves the term to be settled, instead of stating it."""
    ref = _refers(text)
    return bool(_SAME_AS_START_RE.match(text) or (ref and ref.start() <= 3) or _TBD_RE.match(text))


def _purpose_items(rest: str) -> list[str]:
    """The purposes in the part of a sentence after "used": numbered items, or the whole of it."""
    rest = _AGREEMENT_RE.sub(lambda m: f"the {m.group('term')} ({m.group('name').strip()} dated {m.group('date')})", rest)
    rest = _style(rest)
    first = _ENUM_SPLIT_RE.search(rest)
    lead = _strip_end(rest[:first.start()]) if first and first.start() > 0 else ""
    if first and first.start() > 0:
        rest = rest[first.start():]
    shared = _SHARED_VERB_RE.search(lead)
    verb = lead[shared.start():] + " " if lead and shared else ""
    parts = [p for p in _ENUM_SPLIT_RE.split(rest) if p and p.strip()]
    if lead and not shared and _PURPOSE_LEAD_RE.search(lead) and len(lead) >= 12:
        parts.insert(0, lead)  # a purpose stated before the numbered ones ("to finance the Acquisition and (ii) ..."): not to be lost
    items = []
    for p in parts:
        p = _LEADING_FOR_RE.sub("", _strip_end(_TRAILING_AND_RE.sub("", (verb + p.strip()).strip())))
        if p:
            items.append(p)
    return items


# "shall", "will", "may" left at the end of a subject when the sentence is cut in front of "be used"
_TRAILING_MODAL_RE = re.compile(r"\s+(?:shall|will|may|must|are\s+to|is\s+to)\s*$", re.IGNORECASE)


def _own_use_items(body: str) -> list[tuple[str, str, str]]:
    """(subject, what it is used for, the item as written) for a sentence whose numbered items each say what one thing is
    used for - "The proceeds of (i) the Term Loan Facilities shall be used ..., (ii) borrowings under the Revolving Credit
    Facility shall be used ... and (iii) ...": the numbering comes before the first "used" and every item has its own.
    Empty for any other sentence (numbered purposes after a single "shall be used" are read by ``_purpose_items``)."""
    used, enum = _USED_RE.search(body), _ENUM_SPLIT_RE.search(body)
    if not (used and enum and enum.start() < used.start()):
        return []
    out: list[tuple[str, str, str]] = []
    for piece in (p.strip() for p in _ENUM_SPLIT_RE.split(body[enum.start():]) if p and p.strip()):
        m = _USED_RE.search(piece)
        subject = _strip_end(_TRAILING_MODAL_RE.sub("", piece[:m.start()])) if m else ""
        if not m or not subject or len(subject) > 90:
            return []  # an item that does not say "<something> shall be used ...": not this shape
        out.append((subject, _TRAILING_AND_RE.sub("", piece[m.end():].strip()), piece))
    return out if len(out) >= 2 else []


def purpose(ctx: Ctx) -> dict:
    """Use of proceeds as the term sheet states it; general corporate purposes first."""
    blocks = _find(ctx, L_PURPOSE)
    if not blocks:
        m = _INTRO_USE_RE.search(" ".join(_norm(p) for p in ctx.raw.pages[:2]))
        if m and not _OTHER_DEBT_RE.search(m.group(0)[:m.start("rest") - m.start()]):  # not the proceeds of a notes offering
            rest = _strip_end(_style(m.group("rest")))
            q = _quote_text(ctx, "used for " + " ".join(m.group("rest").split()[:3]), pages=(1, 2))
            if q and rest:
                return stated([_cap(rest)], [q], note="No purpose section; taken from the introduction of the summary.")
        for page, raw in enumerate(ctx.raw.pages[:15], 1):  # an amendment presentation: what the transaction is for
            m = _SEEKING_RE.search(_norm(raw))
            if m and _FACILITY_MENTION_RE.search(m.group("what")):
                q = _quote_text(ctx, " ".join(m.group(0).split()[:5]), pages=(page,))
                if q:
                    what = _strip_end(_style(m.group("what")))
                    return stated([_clip(f"Transaction: to {what} (use of proceeds not otherwise stated)", 300)], [q],
                                  note="No purpose section; this is the stated aim of the transaction, not a use of proceeds.")
        return not_stated()
    cells = [c for c in (_cell(ctx, b, L_PURPOSE) for b in _top_level(blocks)[:3]) if c.text]
    if not cells:
        return not_stated()
    cell = cells[0]
    opening = _strip_end((_sents(_style(cell.text)) or [""])[0])
    if _defers(opening.strip("[] ")):  # "Same as under the Existing Credit Agreement", "Customary for facilities of this type", "[TBD]"
        return by_reference([_clip(_cap(opening))], [_quote(ctx, cell.block)])
    entries: list[tuple[str, list[str], str, _Cell]] = []  # (facility, purposes, wording to quote, where)
    subjects: list[str] = []  # the facility as the term sheet names it, used when two share a type ("U.S. Term Loan", "Euro Term Loan")
    for c in cells:  # one purpose section, or one for each facility
        section = _section_facility(ctx, c.block) if len(cells) > 1 else ""
        for n, s in enumerate(_sents(c.text)[:4]):
            lab = _LABELLED_SENT_RE.match(s)  # "Facility A: refinancing ..."
            body = lab.group("rest") if lab else s
            own = _own_use_items(body)  # "(i) the Term Loan Facilities shall be used ..., (ii) borrowings under ... shall be used ..."
            for subject, rest, piece in own:
                items = _purpose_items(rest)
                if items:
                    kind = _kind(subject)
                    entries.append(("" if kind in _SUB_KINDS + _GENERIC_KINDS else kind, items, piece[:60], c))
                    subjects.append(_cap(_LEADING_THE_RE.sub("", _strip_end(_style(subject)))))
            if own:
                continue
            m = _USED_RE.search(body) or _DRAWN_FOR_RE.search(body)  # "... shall be used to", or "Revolving Loans may be drawn ... for ..."
            numbered_subjects = bool(m) and bool(_ENUM_SPLIT_RE.search(body[:m.start()]))
            if m and (_NEGATED_USE_RE.search(body[:m.start()]) or numbered_subjects):
                # "may not be used for any purpose other than ...": a restriction, which turned into a purpose would say the
                # opposite; or numbered subjects that do not each have their own "shall be used": in both cases the sentence
                # is kept in the term sheet's own words (a restriction only if it is all the section says)
                if n == 0 or numbered_subjects:
                    entries.append(("", [_strip_end(_style(body))], s[:60], c))
                    subjects.append("")
                continue
            before = body[:m.start()] + " shall" if m else ""
            subj = _PROCEEDS_OF_RE.search(before) or _LOANS_UNDER_RE.search(before) or _FACILITY_OPENS_RE.match(before) if m else None
            subject = next((g for g in subj.groups() if g), "") if subj else ""
            rest = body[m.end():] if m else body
            if not m and not lab and n > 0:  # a further sentence that is not a statement of purpose
                continue
            items = _purpose_items(rest)
            if items:
                kind = _kind(lab.group("lab")) if lab else _kind(subject) if subject else section
                name = "" if kind in _SUB_KINDS else kind if kind not in _GENERIC_KINDS else lab.group("lab") if lab else ""
                entries.append((name, items, s[:60], c))
                subjects.append(_strip_end(_style(lab.group("lab") if lab else subject)))
    if not entries:
        return not_stated()
    lines: list[str] = []
    names = [e[0] for e in entries]
    if len(entries) > 1 and not (all(names) and len(set(names)) == len(names)):
        names = subjects  # the types do not tell the facilities apart: use their own names
    labelled = len(entries) > 1 and all(names) and len(set(names)) == len(names)
    for (_, items, _, _), kind in zip(entries, names):
        if not any(_SEQUENCE_RE.match(i) for i in items):  # general corporate purposes first, unless the items are a sequence
            first_item = items[0]
            items = sorted(items, key=lambda x: 0 if _GCP_RE.search(x) else 1)
            if items[0] is not first_item:  # moved to the front, "other general corporate purposes" has nothing before it to be other than
                items[0] = _OTHER_GCP_RE.sub("", items[0])
        joined = "; ".join(items)
        if labelled:
            lines.append(_clip(f"{kind}: {joined}", 330))
        elif len(joined) <= LINE_LIMIT:
            lines.append(_cap(joined))
        else:
            lines.extend(_clip(_cap(i)) for i in items)
    said: set[str] = set()  # the same purpose under a second label (an overview and the summary of terms) is given once
    lines = [x for x in lines if not (x.lower() in said or said.add(x.lower()))]
    if all(c.same for c in cells):
        lines[-1] += " (same as existing)"
    ev = [_quote(ctx, e[3].block, e[2]) for e in entries[:3]]
    if not _REFINANCE_WORD_RE.search(" ".join(lines)):
        condition = _refinancing_condition(ctx)
        if condition:
            lines.append(condition[0])
            ev.insert(1, condition[1])
    return stated(lines[:6], [e for e in ev if e])


# ======================================================================================================
# 7. Maturity
# ======================================================================================================

L_MATURITY = _label(
    r"(?:[\w\-]+\s+){0,3}maturity(?:\s+date)?(?:\s+and|\s*/\s*tenor)?|tenor|term|(?:[\w\-]+\s+){0,4}termination\s+date|expiry(?:\s+date)?",
    r"(?:(?:final|scheduled|stated|initial|facility|revolving|revolver|credit|term|loan|rcf|availability|and|commitment)\s+)*maturity"
    r"(?:\s+date)?(?:\s+and\s+amorti[sz]ation|\s*/\s*tenor)?|tenor|term|(?:(?:\d+-?\s?(?:day|year)|revolving|commitment|facility|scheduled|"
    r"credit|final|revolver)\s+)*termination\s+date|expiry(?:\s+date)?")
L_EXTENSION = _label(
    r"(?:maturity\s+|commitment\s+|facility\s+)?extensions?(?:\s+(?:options?|requests?|feature|provisions?))?|extension\s+of(?:\s+[\w]+){0,3}|"
    r"amend\s+and\s+extend(?:\s+(?:feature|provisions?))?",
    r"(?:maturity\s+|commitment\s+|facility\s+)?extensions?(?:\s+(?:options?|requests?|feature|provisions?))?|"
    r"extension\s+of(?:\s+(?:the|revolving|commitments?|maturity|facility|termination|credit|date|final|stated))+|"
    r"amend\s+and\s+extend(?:\s+(?:feature|provisions?))?")
L_TERM_OUT = _label(r"term-?\s?out(?:\s+option)?|term\s+loan\s+conversion(?:\s+option)?|conversion\s+option")
# "364 days from the Closing Date", "5 years after the Revolving Effective Date" (after number words are turned into digits)
# A tenor left open in square brackets keeps them: "[5] years from the Closing Date"
_TENOR_RE = re.compile(r"(?<![\w.$\]])\[?(?P<n>\d{1,3})\]?-?\s?(?P<unit>years?|days?|months?)\s+(?:after|from|following)\b", re.IGNORECASE)
# "[five] years", "[five (5)] years", "[5] years": a tenor in square brackets, before number words are turned into digits
_BRACKET_TENOR_RE = re.compile(rf"\[\s*(?:(?P<d>\d{{1,3}})|(?P<w>{_NUM_WORD}))(?:\s*\(\s*\d{{1,3}}\s*\))?\s*\](?=[\s-]*(?:years?|months?|days?)\b)", re.IGNORECASE)
# The same in the page text, before number words are turned into digits; used to place the quote.
_RAW_TENOR_RE = re.compile(rf"\b(?:\d{{1,3}}|{_NUM_WORD})\s*(?:\(\s*\d{{1,3}}\s*\)\s*)?-?\s?(?:years?|days?|months?)\s+(?:after|from|following)\b|"
                           rf"\banniversary\b|{_DATE}", re.IGNORECASE)
# "the fifth anniversary of the Closing Date", "fifth anniversary thereof"
_ANNIV_RE = re.compile(r"\b(?:the\s+)?(?P<ord>" + "|".join(_ORDINALS) + r"|\d{1,2}(?:st|nd|rd|th))\s+anniversary\s+(?:of\s+)?(?P<rest>thereof\b)?", re.IGNORECASE)
# "during the period commencing on the Closing Date and ending on the fifth anniversary thereof"
_COMMENCING_RE = re.compile(r"commencing\s+on\s+(?P<anchor>the\s+[\w\s]+?)\s+and\s+ending\s+on\s+", re.IGNORECASE)
# The words before the tenor are only the sentence's lead-in: "The Facility shall terminate, and all amounts ... in full,"
_LEAD_IN_RE = re.compile(r"\b(?:matur\w+|terminat\w+|expir\w+|payable|ending\s+on|end\s+on|available)\b", re.IGNORECASE)
# ... or say when the last of the loan falls due: "with the final payment of all amounts outstanding ..., plus accrued interest, being due"
_FINAL_DUE_RE = re.compile(r"\b(?:final\s+(?:payment|instal+ment)|balance|remainder|all\s+amounts\s+outstanding|outstanding\s+principal)\b[^.;]{0,140}?"
                           r"\b(?:being\s+|shall\s+be\s+|will\s+be\s+|is\s+|are\s+)?due\b", re.IGNORECASE)
# ... unless something else stands between the verb and the period (the period is then not the tenor),
_NOT_THE_TENOR_RE = re.compile(r"amorti[sz]|instal+ments?|commenc|beginning|interest\s+period|\bnotice\b|\band\b", re.IGNORECASE)
# "The Term Loans will mature on the Maturity Date": a facility tied to a date the section has already defined
_ON_DEFINED_DATE_RE = re.compile(
    r"\b(?:mature|terminate|expire|repaid|due|payable)\s+(?:in\s+full\s+)?on\s+(?P<date>the\s+(?:[A-Z0-9][\w-]*\s+){0,4}(?:Maturity|Termination)\s+Date)\b")
# ... or unless they qualify it.
_QUALIFIER_RE = re.compile(r"\b(?:provided|if|unless|but|earlier\s+of|later\s+of|earliest|latest|no\s+later\s+than|not\s+later\s+than)\b", re.IGNORECASE)
# "(the “Initial Maturity Date”)": in this row the defined name of the date is worth keeping.
_DEFINED_DATE_RE = re.compile(r"\((?:the\s+)?[“\"]\s*([^”\"()]{3,50}?)\s*[”\"]\)")
# "Two 1-year extension options", "two (2) successive one-year extensions", "up to two additional one-year periods"
_EXT_COUNT_RE = re.compile(
    rf"\b(?P<n>\d|{_NUM_WORD})\s*(?:\(\d\)\s*)?(?:additional\s+|consecutive\s+|successive\s+|separate\s+)*(?P<len>\d{{1,2}}|{_NUM_WORD})[\s-]*"
    r"(?P<unit>year|month)s?\s+(?:extension(?:\s+option)?s?|periods?)", re.IGNORECASE)
# "extended for additional one year periods", "for an additional one-year period", "by one year", "a further 12 months"
_EXT_LENGTH_RE = re.compile(
    rf"\b(?:(?:for|by)\s+(?:up\s+to\s+)?(?:an?\s+)?(?:additional\s+|further\s+)?|additional\s+|further\s+)(?P<len>\d{{1,2}}|{_NUM_WORD})[\s-]*"
    r"(?P<unit>year|month)(?P<plural>s)?(?:\s+(?P<periods>periods?))?\b", re.IGNORECASE)
# A cap on the number of extensions: "not more than twice", "on up to two occasions", "no more than two times" (but not
# "no more than once a year", which caps how often a request is made and not how many there may be)
_EXT_LIMIT_RE = re.compile(
    rf"\b(?:not|no)\s+more\s+than\s+(?P<a>once|twice|\d|{_NUM_WORD})\b(?!\s+(?:times?\s+)?(?:an?|per|each|every|in\s+any)\s)|"
    rf"\bon\s+(?:up\s+to\s+|no\s+more\s+than\s+)?(?P<b>\d|{_NUM_WORD})\s+(?:separate\s+)?occasions?\b|"
    rf"\bup\s+to\s+(?P<c>\d|{_NUM_WORD})\s+(?:times|occasions|extensions|requests)\b|\b(?P<d>twice)\b", re.IGNORECASE)
# "The Parent may request that the commitments of each Revolving Lender be extended": who asks, and for what
_EXT_WHO_RE = re.compile(r"^(?:The\s+)?(?P<who>[A-Z][\w]*(?:\s+[A-Z][\w]*)?)\s+may(?:,[^,]{0,60},)?\s+request\b")
_EXT_OBJECT_RE = re.compile(r"\brequest\s+that\s+(?P<what>[^,.;]{5,90}?)\s+be\s+extended\b")
# "no earlier than 60 days (...) but no later than 30 days (...) prior to an anniversary of the Revolving Effective Date"
_EXT_NOTICE_RE = re.compile(r"no\s+earlier\s+than\s+(?P<a>\d+)\s+days\b.{0,90}?no\s+later\s+than\s+(?P<b>\d+)\s+days\b.{0,90}?prior\s+to\s+"
                            r"(?P<which>an|any|each)\s+anniversary\s+of\s+(?P<anchor>the\s+[A-Z][\w\s-]*?Date)", re.IGNORECASE)
# "agrees, in its individual and sole discretion, to extend"
_EXT_DISCRETION_RE = re.compile(r"in\s+its\s+(?:individual\s+and\s+)?sole\s+discretion", re.IGNORECASE)
# "provided that more than 50% of the Facility Amount is extended or otherwise committed to"
_EXT_THRESHOLD_RE = re.compile(
    r"more\s+than\s+(?P<pct>\d+(?:\.\d+)?)\s*%\s+of\s+(?P<base>the\s+[\w\s-]{3,60}?)\s+(?:is|are)\s+extended(?P<or>\s+or\s+otherwise\s+committed)?",
    re.IGNORECASE)
# "converted ... into term loans that will mature on the date that is one year after the Initial Maturity Date"
_TERM_OUT_RE = re.compile(r"convert(?:ed)?\b[^.]{0,220}?\binto\s+(?:a\s+)?term\s+loans?\s+(?:(?:that|which)\s+(?:will|shall)\s+(?:mature|be\s+repaid(?:\s+in\s+full)?|"
                          r"be\s+(?:due|repayable|payable)(?:\s+in\s+full)?)|maturing|repayable|due)\s+(?:on\s+)?(?P<when>[^;.(]{5,140})", re.IGNORECASE)
# "a term-out fee of 50 basis points", "an upfront fee of 75 bps"
_TERM_OUT_FEE_RE = re.compile(r"(?:(?P<name>term-?\s?out|upfront|conversion|extension)\s+)?fee\s+(?:of|equal\s+to)\s+(?P<bps>\d+(?:\.\d+)?)\s*"
                              r"(?P<unit>bps|basis\s+points|%)", re.IGNORECASE)
# "Maturity of the RCF will be extended to May 2031"
_EXTENDED_TO_RE = re.compile(rf"\bmaturity\s+(?:of\s+the\s+(?P<subj>[\w\s]{{2,40}}?)\s+)?(?:will|is\s+to|to)\s+be\s+extended\s+to\s+(?P<when>{_DATE})",
                             re.IGNORECASE)
# Debt that is not the facility: what "currently scheduled to mature" may be said of instead
_OTHER_DEBT_RE = re.compile(r"\b(?:notes?|bonds?|debentures?)\b", re.IGNORECASE)
# "currently scheduled to mature on March 16, 2029"
_CURRENT_MATURITY_RE = re.compile(rf"currently\s+scheduled\s+to\s+mature\s+(?:on|in)\s+(?P<when>{_DATE})", re.IGNORECASE)


# The lead-in of a maturity sentence: "the date that is five years after ...", "On the date falling 5 years after ..."
_DATE_THAT_IS_RE = re.compile(r"^(?:On\s+)?the\s+date\s+(?:(?:that|which)\s+is|falling)\s+", re.IGNORECASE)
# An "Amend and Extend" section, and the turn of phrase that introduces its substance:
_AMEND_EXTEND_RE = re.compile(r"amend\s+and\s+extend", re.IGNORECASE)
# "... provisions consistent with those in the Existing Credit Agreement pursuant to which individual Lenders may ..."
_PURSUANT_RE = re.compile(r"\bpursuant\s+to\s+which\s+")
# "(it being understood that (x) no existing Lender will have any obligation ...)": the closing aside
_IT_BEING_UNDERSTOOD_RE = re.compile(r"\s*\(it\s+being\s+understood.*$")
_NO_OBLIGATION_RE = re.compile(r"no\s+(?:existing\s+)?Lender\s+will\s+have\s+any\s+obligation", re.IGNORECASE)
# "Any Lender that declines ... (a “Declining Lender”) will have its commitment terminated on the then existing ... Date"
_DECLINING_RE = re.compile(r"declin\w+\s+lender", re.IGNORECASE)
_TERMINATED_THEN_RE = re.compile(r"terminated\s+on\s+the\s+then\s+existing", re.IGNORECASE)
# What surrounds the date of a term-out: "on the date that is" before it, ", upon payment of ..." after it
_WHEN_LEAD_RE = re.compile(r"^(?:the\s+date\s+that\s+is\s+|on\s+)")
_WHEN_TAIL_RE = re.compile(r",\s+(?:upon|subject|provided)\b")
# A label that is just "Maturity" / "Final Maturity Date" / "Tenor", as against one that names a facility
_PLAIN_MATURITY_LABEL_RE = re.compile(r"(?:(?:final\s+)?maturity(?:\s+date)?|tenor|term)", re.IGNORECASE)
_FACILITY_LABEL_RE = re.compile(r"term\s+loan|revolv|facility\s+[A-D]\b|\btl[ab]\b|\brcf\b", re.IGNORECASE)
# A maturity line says something only if it has a tenor, a date or a year (or a blank left for one).
_TENOR_ANY_RE = re.compile(r"\b\d{1,3}[\s-]*(?:years?|months?|days?)\b|\[\d{1,3}\][\s-]*(?:years?|months?|days?)\b|\b(?:19|20)\d{2}\b|\banniversary\b|\[ \]",
                           re.IGNORECASE)
# "The Term Loan B will mature 7 years after ...", "The Revolving Facility shall terminate on ...": the facility a sentence is about
_MATURES_SUBJECT_RE = re.compile(
    r"^(?:The\s+|Each\s+)?(?P<subj>[A-Z][\w-]*(?:\s+(?:[A-Z0-9][\w-]*|and|the|under|of))*?)\s+(?:will|shall)\s+(?:mature|terminate|expire|be\s+(?:repaid|due|payable))\b")
# "Each New Term Loan Facility shall be subject to repayment ..., with the final payment ... being due five years after ...": a
# facility named at the head of a sentence that gives its maturity further on
_FACILITY_SUBJECT_RE = re.compile(r"^(?:The\s+|Each\s+)?(?P<subj>[A-Z][\w-]*(?:\s+(?:[A-Z0-9][\w-]*|and|the))*?)\s+(?:will|shall)\s+")
# A line of a table cell that opens with a sub-label of its own: "Term Loan B: 7 years", "Revolving Credit Facility: None"
_SUBLABEL_LINE_RE = re.compile(r"^[A-Z][\w/&\- ]{1,40}?:\s+\S")
# A line that is only a sub-heading for the paragraph under it: "3-Year Tranche:", "Term Loan Facility:"
_SUBHEAD_LINE_RE = re.compile(r"^[A-Z0-9][\w/&\- ]{1,48}:$")
# A calendar year in the line: the maturity is already a date.
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# "springing maturity", "the 91st day prior to the maturity of ..."
_SPRINGING_RE = re.compile(r"springing|\b\d{2,3}(?:st|nd|rd|th)?[\s-]days?\s+(?:prior\s+to|before|ahead\s+of|inside)\b", re.IGNORECASE)
# A lender's deadline to answer an extension request: "of its decision to do so no later than 20 days ... prior to such anniversary"
_EXT_RESPONSE_RE = re.compile(r"\bdecision\b[^.]{0,40}?no\s+later\s+than\s+(?P<d>\d+)\s+days\b", re.IGNORECASE)


def _changed_part(old: str, new: str) -> str:
    """The words of ``old`` that differ from ``new`` when the two share their opening and closing words ("July 2028"
    against "5 years from closing" inside the same sentence); otherwise the whole of ``old``."""
    a, b = old.split(), new.split()
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[-1 - j] == b[-1 - j]:
        j += 1
    mid = a[i:len(a) - j]
    return " ".join(mid) if mid and len(mid) <= 8 and i + j >= 4 else old


def _maturity_style(text: str) -> str:
    """De-noise a maturity passage, keeping the defined name of the date: (the “Termination Date”) -> (Termination Date)."""
    text = _DEFINED_DATE_RE.sub(lambda m: f"({m.group(1)})", _norm(text))
    text = _BRACKET_TENOR_RE.sub(lambda m: f"[{m.group('d') or _NUM_WORDS[m.group('w').lower()]}]", text)
    return _style(text)


def _tenor_line(sentence: str) -> str:
    """The tenor or date from the sentence that states it, without the sentence's lead-in."""
    s = _DATE_THAT_IS_RE.sub("", _strip_end(sentence))
    if len(_TENOR_RE.findall(s)) + len(_ANNIV_RE.findall(s)) > 1:
        return _cap(s)  # several tenors in one sentence (one per facility): keep the sentence as it stands
    m = _TENOR_RE.search(s)
    if m is None:
        a = _ANNIV_RE.search(s)
        if a is not None:
            n = _to_int(a.group("ord"))
            lead = s[:a.start()]
            if n and not _QUALIFIER_RE.search(lead):
                years = f"{n} year{'' if n == 1 else 's'}"
                tail = s[a.end():].strip()
                if a.group("rest"):  # "... commencing on the Closing Date and ending on the fifth anniversary thereof"
                    c = _COMMENCING_RE.search(lead)
                    if not c:
                        return _cap(s)
                    return _clip(f"{years}: {a.group('ord').lower()} anniversary of {c.group('anchor')} {tail}".strip())
                return _clip(f"{years}: {a.group('ord').lower()} anniversary of {tail}")
            return _cap(s)
        d = _DATE_RE.search(s)
        if d is not None and (_LEAD_IN_RE.search(s[:d.start()]) or _FINAL_DUE_RE.search(s[:d.start()])) and not _QUALIFIER_RE.search(s[:d.start()]):
            return _cap(s[d.start() - 1 if s[:d.start()].endswith("[") else d.start():])  # "[June 30, 2031]" keeps its brackets
        return _cap(s)
    lead = s[:m.start()]
    verbs = [v.end() for v in _LEAD_IN_RE.finditer(lead)] + [v.end() for v in _FINAL_DUE_RE.finditer(lead)]
    # the period must follow the verb of maturity directly: "... will mature on the Maturity Date and amortise in instalments
    # commencing 12 months after the Closing Date" gives the start of the amortisation, not the tenor
    if verbs and not _QUALIFIER_RE.search(lead) and not _NOT_THE_TENOR_RE.search(lead[max(verbs):]):
        s = s[m.start():]
    return _cap(s)


def _extension_shape(first: str) -> tuple[int | None, int, str, bool] | None:
    """(number of extensions or None, length, unit, open-ended?) of an extension option as its sentence words it."""
    m = _EXT_COUNT_RE.search(first)
    if m and _to_int(m.group("n")) and _to_int(m.group("len")):  # "two 1-year extension options"
        return _to_int(m.group("n")), _to_int(m.group("len")), m.group("unit").lower(), False
    m = _EXT_LENGTH_RE.search(first)
    length = _to_int(m.group("len")) if m else None
    if not m or not length:
        return None
    limit = _EXT_LIMIT_RE.search(first)
    word = next((g for g in limit.groups() if g), "") if limit else ""
    count = {"once": 1, "twice": 2}.get(word.lower()) or (_to_int(word) if word else None)
    # "additional one year periods", in the plural and with no cap on the number of requests
    open_ended = count is None and (m.group("periods") or "").lower() == "periods"
    return count, length, m.group("unit").lower(), open_ended


def _extension_prefix(shape: tuple[int | None, int, str, bool]) -> str:
    """The template's notation for an extension option: "+ 1 + 1" for two one-year options."""
    count, length, unit, open_ended = shape
    if unit != "year":
        return "Extension"
    if count and count <= 3:
        return " ".join([f"+ {length}"] * count)
    return f"+ {length} (repeatable; number of requests not capped in this section)" if open_ended else f"+ {length}"


def _extension_lines(ctx: Ctx) -> tuple[list[str], list[dict]]:
    """Lines for the extension-option and amend-and-extend sections, with their quotes."""
    lines: list[str] = []
    ev: list[dict] = []
    for b in _find(ctx, L_EXTENSION)[:2]:
        c = _cell(ctx, b, L_EXTENSION)
        if not c.text:
            continue
        t = _style(c.text)
        first = _strip_end((_sents(t) or [t])[0])
        same = " (same as existing)" if c.same else ""
        shape = _extension_shape(first)
        if _AMEND_EXTEND_RE.search(b.label):
            pw = _PURSUANT_RE.search(first)
            if pw:  # "... provisions consistent with those in the Existing Credit Agreement pursuant to which <the substance>"
                ref = _refers(first[:pw.start()])
                body = _IT_BEING_UNDERSTOOD_RE.sub("", first[pw.end():])
                if _NO_OBLIGATION_RE.search(first):
                    body += "; no existing Lender is obliged to extend"
                head = f"Amend and extend ({_ref_words(first[:pw.start()], ref)})" if ref else "Amend and extend"
                lines.append(_fit(f"{head}: {_lower_first(_strip_end(body))}", 400) + same)
            else:
                lines.append(_clip(f"Amend and extend: {_lower_first(first)}") + same)
        elif shape:
            body, compact = _lower_first(first), False
            who, what = _EXT_WHO_RE.search(first), _EXT_OBJECT_RE.search(first)
            if len(first) > 230 and who and what:  # a long sentence: who may ask, for what, and the notice window
                span = f"additional {shape[1]}-{shape[2]} periods" if shape[3] else f"an additional {shape[1]}-{shape[2]} period"
                body, compact = f"{who.group('who')} may request that {what.group('what')} be extended for {span}", True
                notice = _EXT_NOTICE_RE.search(t)
                if notice:
                    body += (f", by notice {notice.group('a')} to {notice.group('b')} days prior to {notice.group('which').lower()} "
                             f"anniversary of {notice.group('anchor')}")
            lines.append(_clip(f"{_extension_prefix(shape)}: {body}", 330) + same)
            more = []
            rest = t if compact else t[len(first):]  # what the section says beyond the words already in the line
            if _EXT_DISCRETION_RE.search(rest):
                answer = _EXT_RESPONSE_RE.search(rest)
                more.append("each Lender decides " + _EXT_DISCRETION_RE.search(rest).group(0).lower()
                            + (f" (answer no later than {answer.group('d')} days prior to the anniversary)" if answer else ""))
            th = _EXT_THRESHOLD_RE.search(rest)
            if th:
                more.append(f"extension takes effect only if more than {th.group('pct')}% of {th.group('base')} is extended"
                            + (" or otherwise committed" if th.group("or") else ""))
            if _DECLINING_RE.search(rest) and _TERMINATED_THEN_RE.search(rest):
                more.append("a declining Lender's commitment terminates on the then existing termination date")
            if more:
                lines.append(_clip(_cap("; ".join(more)), 330))
                if th:
                    ev.append(_quote(ctx, c.block, th.group(0)))
        else:
            lines.append(_clip(f"{_title(b.label)}: {_lower_first(first)}") + same)
        ev.insert(0, _quote(ctx, c.block))
    return lines, [e for e in ev if e]


def _term_out_line(ctx: Ctx, cells: list[_Cell]) -> tuple[str, dict | None]:
    """A term-out option: revolving loans outstanding at maturity may be converted into a term loan."""
    for c in cells:
        t = _style(c.text)
        m = _TERM_OUT_RE.search(t)
        if not m:
            continue
        when = _WHEN_TAIL_RE.split(_WHEN_LEAD_RE.sub("", _strip_end(m.group("when"))))[0]
        if when.lower().startswith("the "):  # "the first anniversary of the Termination Date"
            when = "on " + when
        line = f"Term-out option: outstanding loans may be converted into a term loan maturing {when}"
        fee = _TERM_OUT_FEE_RE.search(t)
        if fee:
            name = _norm(fee.group("name") or "").lower()
            line += f"; {name + ' ' if name else ''}fee of {fee.group('bps')}{'%' if fee.group('unit') == '%' else ' bps'}"
        clean = _ACC_NO_DEFAULT_RE.search(t)  # "no default or event of default", as the section words it
        if clean:
            line += "; subject to " + _SPLIT_EVENT_RE.sub("event", clean.group(0).lower())
        raw = _TERM_OUT_RE.search(_norm(c.block.text))
        return _clip(line), _quote(ctx, c.block, raw.group(0)[-90:] if raw else None)
    for c in cells:  # a term-out section worded some other way: its opening sentence
        if L_TERM_OUT[1].fullmatch(_norm(c.block.label).strip(" :")):
            first = _strip_end((_sents(_style(c.text)) or [""])[0])
            if len(first) >= 20:
                return _clip(f"Term-out option: {_lower_first(first)}", 330), _quote(ctx, c.block)
    return "", None


def _labelled_points(cell: _Cell) -> list[str]:
    """The lines of a table cell when each of them (two to six) opens with a sub-label of its own - "Term Loan B:
    7 years" / "Revolving Credit Facility: 5 years": one point per line. Empty for any other cell."""
    parts = [_norm(p) for p in cell.block.parts if tidy(p)]
    if not 2 <= len(parts) <= 6 or _norm(cell.block.text) != cell.text:
        return []
    return parts if all(_SUBLABEL_LINE_RE.match(p) for p in parts) else []


def _headed_paragraphs(cell: _Cell) -> list[tuple[str, str]]:
    """(sub-heading, paragraph) pairs of a section set out as paragraphs that each have a sub-heading on a line of its
    own - "3-Year Tranche:" / <paragraph> / "5-Year Tranche:" / <paragraph>. A sub-heading is the first line of a
    paragraph (it follows a blank line or opens the section), short, and ends with a colon. Empty unless the section
    has at least two of them."""
    block = cell.block
    if _norm(block.text) != cell.text:
        return []  # an amendment cell: the text read is not this block's
    groups: list[list[str]] = []
    prev: Line | None = None
    for ln, part in zip(block.lines, block.parts):
        text = _norm(part)
        if not text:
            continue
        gap = prev is None or (ln.n - prev.n > 1 and (ln.page == prev.page or bool(_CLOSED_RE.search(prev.text))))
        if gap:
            groups.append([])
        groups[-1].append(text)
        prev = ln
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(groups):
        group = groups[i]
        if _SUBHEAD_LINE_RE.match(group[0]):
            body = group[1:]
            if not body and i + 1 < len(groups) and not _SUBHEAD_LINE_RE.match(groups[i + 1][0]):
                i += 1
                body = groups[i]
            if body:
                out.append((group[0].rstrip(": "), " ".join(body)))
        i += 1
    return out if len(out) >= 2 else []


def _has_tenor(sentence: str) -> bool:
    """The sentence gives a tenor, an anniversary or a date."""
    return bool(_TENOR_RE.search(sentence) or _ANNIV_RE.search(sentence) or _DATE_RE.search(sentence))


# Wording of the period in which loans may be drawn: "available ... until", "may be drawn ...", "commitments ... will terminate"
_AVAILABLE_RE = re.compile(r"\bavailab(?:le|ility)\b|\bmay\s+be\s+(?:drawn|borrowed|made|requested)\b|\bcommitments?\b[^.;]{0,80}?\b(?:terminat|expir)", re.IGNORECASE)
# The sentence says when the loans fall due.
_FALLS_DUE_RE = re.compile(r"\bmatur\w+|\bdue\b|\bpayable\b|\brepaid\b|\brepayable\b|\brepayment\b", re.IGNORECASE)
# The end of the period is given a name that makes it the maturity: (the “Revolving Maturity Date”), (Termination Date)
_NAMED_END_DATE_RE = re.compile(r"\((?:the\s+)?[“\"]?[^()”\"]{0,50}?(?:Maturity|Termination|Expiry|Expiration)\s+Date[”\"]?\)", re.IGNORECASE)
# Drawing down a loan: "in a single drawing", "delayed draw", "may be drawn"
_DRAWING_RE = re.compile(r"\bdraw(?:n|ing|ings|s|down)?\b|delayed[\s-]draw", re.IGNORECASE)


def _availability_only(sentence: str, kinds: set[str]) -> bool:
    """The sentence gives the period in which a loan may be drawn, not when it matures: "Term Loans shall be available ...
    until the date that is 12 months after the Closing Date". A revolver is available until it matures, so a sentence about
    revolving loans - or one that names the end of the period the Maturity or Termination Date - is not one of these.
    ``kinds`` are the types of facility the sentence may be about."""
    m = _TENOR_RE.search(sentence) or _ANNIV_RE.search(sentence) or _DATE_RE.search(sentence)
    if not m:
        return False
    lead = sentence[:m.start()]
    if not _AVAILABLE_RE.search(lead) or _FALLS_DUE_RE.search(lead) or _NAMED_END_DATE_RE.search(sentence):
        return False
    if _TERM_LOAN_TALK_RE.search(lead):
        return True
    if _REVOLVING_RE.search(lead) or (kinds and all(k == "RCF" for k in kinds)):
        return False
    return any(k.startswith("Term Loan") for k in kinds) or bool(_DRAWING_RE.search(lead))


def _maturity_subject(sentence: str) -> tuple[str, str]:
    """(facility, opening words matched) where a sentence says of a facility when it matures: "The Term Loan B will mature
    ...", or a facility named at its head with the maturity given further on ("Each Term Loan Facility shall be subject to
    repayment ..., with the final payment ... being due five years after ..."). ("", "") for any other sentence."""
    m = _MATURES_SUBJECT_RE.match(sentence)
    if m:
        return m.group("subj"), m.group(0)
    m = _FACILITY_SUBJECT_RE.match(sentence)
    if m and _kind(m.group("subj")) not in _GENERIC_KINDS + _SUB_KINDS and _has_tenor(sentence):
        line = _tenor_line(sentence)
        if not line.startswith(sentence[:12]):  # the words before the tenor were only its lead-in: the tenor is the maturity
            return m.group("subj"), m.group(0)
    return "", ""


def _about_the_facility(whole: str, m: re.Match) -> bool:
    """The words before a match speak of the facility, and of no notes or bonds after it."""
    before = whole[max(0, m.start() - 200):m.start()]
    facility = [x.start() for x in _FACILITY_CONTEXT_RE.finditer(before)]
    other = [x.start() for x in _OTHER_DEBT_RE.finditer(before)]
    return bool(facility) and (not other or other[-1] < facility[-1])


# A tenor inside a summary row: "$600mm, 5 years, S + 175 bps", "364 days"
_ROW_TENOR_RE = re.compile(r"(?<![\w.$])(?:\d{1,2}|" + _NUM_WORD + r")[\s-]?years?\b|(?<![\w.$])364[\s-]?days?\b", re.IGNORECASE)
# "The Revolving Termination Date.": a maturity given only by the name of a date that another section defines
_DATE_NAME_RE = re.compile(r"^(?:The\s+)?(?P<name>(?:[A-Z0-9][\w-]*\s+){1,5}Date)\.?$")


def _defined_date(ctx: Ctx, text: str, own: _Cell) -> tuple[str, _Cell] | None:
    """(sentence, cell) that defines the date a maturity section names and gives its tenor - "... ending on the fifth
    anniversary thereof (the “Revolving Termination Date”)" in the Availability section - looked for in the
    availability and facility sections."""
    m = _DATE_NAME_RE.match(text.strip())
    if not m:
        return None
    words = r"\s+".join(re.escape(w) for w in m.group("name").split())
    defined = re.compile(r"\(\s*(?:the\s+)?[“\"]?\s*" + words + r"\s*[”\"]?\s*\)")
    pool = [_cell(ctx, b, L_AVAILABILITY) for b in _find(ctx, L_AVAILABILITY)[:4]] + _analyse(ctx).cells
    for c in pool:
        if c is own or not c.text or c.block.line.n == own.block.line.n:
            continue
        for s in _sents(_maturity_style(c.text)):
            if defined.search(s) and _has_tenor(s):
                return s, c
    return None


def maturity(ctx: Ctx) -> dict:
    """Tenor or maturity date, then extension options, term-out and springing maturity."""
    lines: list[str] = []
    ev: list[dict] = []
    cells: list[_Cell] = []
    deferred = 0  # maturity lines that only point to another document
    fac = _analyse(ctx)
    blocks = _find(ctx, L_MATURITY)[:3]
    for i, b in enumerate(blocks):
        c = _cell(ctx, b, L_MATURITY)
        if not c.text:
            continue
        cells.append(c)
        text = _maturity_style(c.text)
        labelled = [_maturity_style(p) for p in _labelled_points(c)]
        points = labelled or _bullets(text)
        old_points = [_strip_end(p) for p in _bullets(_maturity_style(c.old))] if c.old else []
        if len(points) > 1 or (points and text.lstrip()[:1] in _BULLET_CHARS):  # a bulleted table cell: one line per point
            for j, p in enumerate(points[:4]):
                p = _strip_end(p)
                if c.same:
                    p += " (same as existing)"
                elif old_points:
                    if p in old_points:
                        p += " (unchanged)"
                    elif j < len(old_points) and len(old_points[j]) <= 140:
                        p += f" (existing: {_lower_first(_changed_part(old_points[j], p))})"
                lines.append(_clip(_cap(p), 330))
            ev.append(_quote(ctx, c.block, _strip_bullet(c.text)[:60]))
            continue
        # sub-headed paragraphs, one for each tranche or facility ("3-Year Tranche:" / "5-Year Tranche:"): one line for each
        headed = [(h, p) for h, p in ((h, _maturity_style(p)) for h, p in _headed_paragraphs(c)) if _has_tenor(p)]
        if len(headed) >= 2:
            for h, p in headed[:5]:
                about = {_kind(h)} if _kind(h) not in _GENERIC_KINDS + _SUB_KINDS else fac.kinds
                # the period in which a term loan may be drawn is not its maturity
                dated_p = [s for s in _sents(p) if _has_tenor(s) and not _availability_only(s, about)]
                if dated_p:
                    s = next((x for x in dated_p if _LEAD_IN_RE.search(x)), dated_p[0])
                    lines.append(_clip(f"{h}: {_lower_first(_tenor_line(s))}", 330))
            for where in list(_RAW_TENOR_RE.finditer(_norm(c.block.text)))[:2]:
                ev.append(_quote(ctx, c.block, where.group(0)))
            continue
        sents = [s for s in _sents(text) if not _availability_only(s, fac.kinds)]  # when a term loan may be drawn is not when it matures
        if not sents:
            continue
        dated = [s for s in sents if _has_tenor(s)]  # the sentence that gives the tenor: one that speaks of maturity, if there is one
        pick = next((s for s in dated if _LEAD_IN_RE.search(s)), dated[0] if dated else sents[0])
        lab = _LABELLED_SENT_RE.match(pick)  # "Revolving Facility: The Revolving Facility will mature on ...": the sentence names its facility
        own_label = lab.group("lab") if lab and _kind(lab.group("lab")) not in _GENERIC_KINDS + _SUB_KINDS else ""
        line = _tenor_line(lab.group("rest") if own_label else pick)
        source = c  # where the tenor is quoted from
        if not _TENOR_ANY_RE.search(line):  # "The Revolving Termination Date": the tenor is where that date is defined
            elsewhere = _defined_date(ctx, text, c)
            if elsewhere:
                line, source = _tenor_line(elsewhere[0]), elsewhere[1]
        # further sentences that give another facility's maturity: "The Term Loan B will mature 7 years after the Closing Date"
        others = [s for s in sents if s is not pick and (_has_tenor(s) or _ON_DEFINED_DATE_RE.search(s)) and _maturity_subject(s)[0]
                  and not _SPRINGING_RE.search(s)]
        subject = _maturity_subject(pick)[0]
        names_one = bool(subject) and _kind(subject) not in _GENERIC_KINDS
        named = bool(subject and names_one and (others or len(fac.main) > 1) and not line.startswith(pick[:12]))
        if own_label:
            line, named = f"{own_label}: {_lower_first(line)}", True
        elif named:
            line = f"{subject}: {_lower_first(line)}"  # the sentence is about one facility: say which
        plain_label = _PLAIN_MATURITY_LABEL_RE.fullmatch(_norm(b.label))
        if not plain_label and (i > 0 or (len(blocks) > 1 and _FACILITY_LABEL_RE.search(b.label))):
            line = f"{_title(b.label)}: {_lower_first(line)}"  # "Term Loan Maturity Date: ..."
        elif plain_label and len(blocks) > 1 and not named:  # several sections all labelled "Maturity": one for each facility
            section = _section_facility(ctx, b)
            if section or i > 0:
                line = f"{section or _title(b.label)}: {_lower_first(line)}"
        if not _TENOR_ANY_RE.search(line):  # nothing that reads as a tenor or a date
            if not (_refers(text) or _SAME_AS_START_RE.match(text)):
                continue
            deferred += 1
        if c.same:
            line += " (same as existing)"
        elif c.old and len(c.old) <= 80:
            line += f" (existing: {_strip_end(_maturity_style(c.old))})"
        if i == 0 and len(fac.kinds) <= 1:  # what the rest of the document says about the same maturity
            whole = _whole(ctx)
            m = _EXTENDED_TO_RE.search(whole) if not _YEAR_RE.search(line) else None
            named = _kind(m.group("subj")) if m and m.group("subj") else ""
            if m and (not named or named in _GENERIC_KINDS or named in fac.kinds or not fac.kinds):
                q = _quote_text(ctx, m.group(0))
                if q:
                    whose = _strip_end(m.group("subj") or "") or "facility"
                    line += f" ({whose} maturity to be extended to {m.group('when')})"
                    ev.append(q)
            m = _CURRENT_MATURITY_RE.search(whole) if _YEAR_RE.search(line) else None
            if m and m.group("when") not in line and _about_the_facility(whole, m):
                q = _quote_text(ctx, m.group(0))
                if q:
                    line += f" (existing facility currently scheduled to mature on {m.group('when')})"
                    ev.append(q)
        if _clip(line, 330) in lines:
            continue  # the same maturity under a second label
        lines.append(_clip(line, 330))
        raw = _norm(source.block.text)  # quote the clause that carries the tenor - of the sentence read, not of an earlier one
        at = raw.find(pick[:25]) if source is c else -1
        where = _RAW_TENOR_RE.search(raw, at) if at > 0 else _RAW_TENOR_RE.search(raw)
        needle = (raw[max(where.start() - 40, at):where.end()] if at > 0 else where.group(0)) if where else None
        ev.insert(0 if i == 0 else len(ev), _quote(ctx, source.block, needle))
        for s in sents:
            if s is pick or len(lines) >= 5:
                continue
            if _SPRINGING_RE.search(s):  # a springing maturity stated in a later sentence
                lines.append(_clip("Springing maturity: " + _lower_first(_strip_end(s))))
            elif _LABELLED_SENT_RE.match(s) and _has_tenor(s):  # "Term Facility: 7 years after the Closing Date"
                own = _LABELLED_SENT_RE.match(s)
                if _kind(own.group("lab")) not in _GENERIC_KINDS + _SUB_KINDS:
                    lines.append(_clip(f"{own.group('lab')}: {_lower_first(_tenor_line(own.group('rest')))}", 300))
                else:
                    lines.append(_clip(_cap(_strip_end(s)), 300))
            elif s in others:
                (subj, opening), on = _maturity_subject(s), _ON_DEFINED_DATE_RE.search(s)
                when = f"on {on.group('date')}" if on else _lower_first(_tenor_line(s))
                lines.append(_clip(f"{subj}: {when}", 300))
                ev.append(_quote(ctx, c.block, opening))
    ext_lines, ext_ev = _extension_lines(ctx)
    if not lines:  # no maturity section that can be read: the tenor in the description of the facility ("5-year revolving credit facility")
        several = len(fac.main) > 1
        for t in fac.main[:4]:
            tenor = _tenor_desc(t.descs)
            if tenor and fac.evidence:
                n, unit = tenor.split("-")
                line = f"{t.kind + ': ' if several else ''}{n} {unit}{'' if n == '1' else 's'} (tenor as given in the description of the facility)"
                if line not in lines:  # two tranches of one type and tenor: one line
                    lines.append(line)
                    ev.append(_quote(ctx, t.cell.block, t.snippet) if t.cell else fac.evidence[0])
    if not lines:  # or a summary row that gives the tenor with the amount: "$600mm, 5 years, S + 175 bps"
        for t in fac.main[:4]:
            row = _norm(t.cell.text) if t.cell else ""
            m = _ROW_TENOR_RE.search(row) if 0 < len(row) <= 160 else None
            if m:
                lines.append(f"{t.kind + ': ' if len(fac.main) > 1 else ''}{_figures(m.group(0))} (as given in the facility row)")
                ev.append(_quote(ctx, t.cell.block, m.group(0)))
    term_cells = [_cell(ctx, b, L_TERM_OUT) for b in _find(ctx, L_TERM_OUT)[:1]] + cells + fac.cells
    out_line, out_q = _term_out_line(ctx, [c for c in term_cells if c.text])
    lines += ext_lines
    ev += ext_ev
    if out_line and out_q:
        lines.append(out_line)
        ev.insert(1, out_q)
    if not lines:
        return not_stated()
    if deferred and deferred == len(lines):
        return by_reference(lines[:8], [e for e in ev if e])
    return stated(lines[:8], [e for e in ev if e])


# ======================================================================================================
# 8. Repayment
# ======================================================================================================

L_AMORT = _label(
    r"(?:scheduled\s+)?amorti[sz]ation(?:\s*/\s*availability)?|(?:scheduled\s+)?repayments?(?:\s+(?:profile|schedule|terms))?|"
    r"(?:final\s+|scheduled\s+|stated\s+)?maturity\s+and(?:\s+amorti[sz]ation)?|(?:scheduled\s+|term\s+loan\s+|required\s+)?amorti[sz]ation\s*/|"
    r"(?:amorti[sz]ation|repayment)\s+and(?:\s+maturity)?",
    r"(?:scheduled\s+|term\s+loan\s+|required\s+)?amorti[sz]ation(?:\s*/\s*availability)?|(?:scheduled\s+)?repayments?(?:\s+(?:profile|schedule|terms))?|"
    r"(?:final\s+|scheduled\s+|stated\s+)?maturity\s+and\s+amorti[sz]ation|(?:amorti[sz]ation|repayment)\s+and\s+(?:final\s+)?maturity")
L_PREPAY = _label(
    r"(?:optional|voluntary)(?:\s+[\w/]+){0,4}|prepayments?(?:\s+and(?:\s+[\w]+){0,2})?|call\s+protection|reductions?(?:\s+in)?",
    r"(?:optional|voluntary)\s+(?:pre)?payments?(?:\s*(?:/|and)\s*[\w\s]{0,40})?|prepayments?(?:\s+and\s+commitment\s+reductions?)?|call\s+protection")
L_AVAILABILITY = _label(r"availability(?:\s+and\s+maturity)?|availability\s+period")
# "None", "None (same as existing ...)", "N/A", "Not applicable"
_NO_AMORT_CELL_RE = re.compile(r"^\W*(?:none|n/?a|nil|not\s+applicable)\b", re.IGNORECASE)
# "with no amortization", "no scheduled amortisation"
_NO_AMORT_RE = re.compile(r"\bno\s+(?:scheduled\s+|interim\s+|required\s+)?amorti[sz]ation\b|(?:will|shall|does)\s+not\s+amorti[sz]e|"
                          r"not\s+(?:be\s+)?subject\s+to\s+(?:any\s+)?(?:scheduled\s+)?amorti[sz]ation|without\s+amorti[sz]ation", re.IGNORECASE)
# "all amounts outstanding thereunder shall be due and payable in full" [on the Termination Date]
_DUE_RE = re.compile(r"all\s+amounts\s+outstanding\s+(?:thereunder\s+)?(?:shall\s+be\s+|will\s+be\s+|being\s+)?(?:due\s+and\s+)?payable(?P<full>\s+in\s+full)?"
                     r"(?:,?\s+on\s+(?P<when>the\s+(?-i:[A-Z])[\w\s-]*?Date)\b)?", re.IGNORECASE)
# "shall repay each Advance ... no later than on the 5-Year Commitment Termination Date"
_REPAY_BY_RE = re.compile(
    r"shall\s+repay\s+each\s+(?P<what>Advance|Loan|Borrowing)\b[^.;]{0,80}?no\s+later\s+than\s+(?:on\s+)?(?P<when>the\s+[^.;,]{3,70})", re.IGNORECASE)
# "Amounts repaid may be reborrowed", "borrow, repay and reborrow"
_REBORROW_RE = re.compile(r"(?:repaid\s+)?may\s+be\s+reborrowed|borrow,\s+repay\s+and\s+reborrow", re.IGNORECASE)
# In an amortisation section that deals with the term loan first: "None for the Revolving Facility."
_NONE_FOR_RCF_RE = re.compile(r"\bnone\s+(?:for|in\s+respect\s+of|with\s+respect\s+to|under)\s+the\s+[\w\s]{0,30}?revolv\w+(?:\s+(?:credit\s+)?facility)?",
                              re.IGNORECASE)
# LMA revolver: "Each Loan shall be repaid on the last day of its Interest Period"
_ROLLOVER_RE = re.compile(r"each\s+(?P<what>Loan|Advance|Utilisation)\s+(?:shall|will|is\s+to)\s+be\s+repaid\s+on\s+the\s+last\s+day\s+of\s+its\s+Interest\s+Period",
                          re.IGNORECASE)
# A repayment cell that says it in so many words: "Bullet repayment on the Termination Date", "repaid in full at maturity"
_BULLET_CELL_RE = re.compile(r"\bbullet\b|repa(?:id|yable|yment)\s+in\s+full\s+(?:on|at)\b", re.IGNORECASE)

# A term loan is said to amortise: "subject to quarterly amortization", "repayable in equal quarterly instalments"
_AMORT_VERB_RE = re.compile(r"\b(?:subject\s+to|repaid\s+in|repayable\s+in|payable\s+in|amorti[sz]e\s+in|amorti[sz]e\s+at)\s+(?P<how>(?:[^.]|\.(?=\d)){5,420})",
                            re.IGNORECASE)
# What is left at the end of an amortising loan: "with the remainder due on the Maturity Date", "with the balance payable at maturity"
_REMAINDER_RE = re.compile(r"with\s+the\s+(?:remainder|balance)\s+[^.;]{3,80}", re.IGNORECASE)
# One row of an amortisation table: "Each quarter commencing with ...", "Year 1", "Thereafter"
_AMORT_ROW_RE = re.compile(r"\b(?:Each\s+(?:fiscal\s+)?quarter|(?:Loan\s+)?Years?\s+\d(?:\s*(?:-|–|to|and|through)\s*\d)?|Thereafter)\b")
# "1.25% per annum", "0.625% per quarter"
_PCT_PER_RE = re.compile(r"(?P<pct>\d{1,2}(?:\.\d+)?)\s*%\s+(?:per\s+(?P<per>annum|quarter|year)|(?P<per2>annually|quarterly))", re.IGNORECASE)
_PCT = re.compile(r"(?<![\w.$])(\d{1,3}(?:\.\d+)?)\s*%")  # a percentage: "1.25%", "5.0 %"
# "without premium or penalty", "without penalty", "freely prepayable at par"
_NO_PENALTY_RE = re.compile(r"without\s+(?:premium\s+or\s+)?penalty|freely\s+prepayable(?:\s+at\s+par)?|at\s+par", re.IGNORECASE)
# A premium is payable on some prepayments: "101 soft call", "1.00% prepayment premium", "repricing transaction", "make-whole"
_CALL_PREMIUM_RE = re.compile(r"soft[\s-]call|call\s+protection|call\s+premium|prepayment\s+(?:premium|fee)|repricing|make-?\s?whole|\b10[1-5](?:\.\d+)?\s*%?\s+"
                              r"(?:soft|call|for|during|in)\b", re.IGNORECASE)
# breakage costs on a prepayment
_BREAKAGE_RE = re.compile(r"break(?:age|\s+funding)|funding\s+losses|redeployment|compensation\s+for\s+losses|costs?\s+(?:incurred|related)", re.IGNORECASE)
# "in minimum amounts of $10,000,000 and increments of $1,000,000"
_PREPAY_MIN_RE = re.compile(rf"minimum\s+amounts?\s+of\s+(?P<min>{_M})(?:[^.;]{{0,80}}?\b(?:increments|multiples?)\s+of\s+(?P<inc>{_M}))?", re.IGNORECASE)


# Words that say how often a term loan amortises, and where a schedule ends.
_QUARTER_RE = re.compile(r"quarter", re.IGNORECASE)
_THEREAFTER_RE = re.compile(r"thereafter", re.IGNORECASE)
# "may prepay ... at any time"
_ANY_TIME_RE = re.compile(r"at\s+any\s+time", re.IGNORECASE)
# The section talks about amortisation or repayment at all,
_AMORT_TALK_RE = re.compile(r"amorti[sz]|instal+ments?|repa(?:y|id)", re.IGNORECASE)
# the sentence that sets it out ("... subject to quarterly amortization", "... in equal quarterly installments"),
_AMORT_SENTENCE_RE = re.compile(r"amorti[sz]|instal+ments?", re.IGNORECASE)
# and whether it is about a term loan.
_TERM_LOAN_TALK_RE = re.compile(r"term\s+loan|term\s+facilit|\bterm\s+[AB]\s+(?:loans?|facilit)|\bTL[AB]\b", re.IGNORECASE)
# "Beginning with the first full fiscal quarter ending after the Closing Date, ..."
_BEGINNING_RE = re.compile(r"(Beginning|Commencing)\s+[^,]{5,90},")
# Labels: "Amortization" / "Amortisation"; "Repayment", "Scheduled Amortization"
_AMORT_LABEL_RE = re.compile(r"amorti[sz]", re.IGNORECASE)
_REPAY_LABEL_RE = re.compile(r"amorti|repay", re.IGNORECASE)
# "None", "N/A" at the start of a cell, to get at what follows it: "None (same as existing ...)"
_NONE_PREFIX_RE = re.compile(r"^\W*(?:none|n/?a|nil|not\s+applicable)\W*", re.IGNORECASE)
# "If the Term Loan Conversion Option is exercised by the Company, ..."
_IF_CLAUSE_RE = re.compile(r"\bIf\s+([^,.]{5,90}),")
# A detail that says in so many words how the revolver is repaid (as against "amounts repaid may be reborrowed").
_EXPRESS_DETAIL_RE = re.compile(r"amorti|payable|repayable|Interest Period")
# The clauses of a summary row: "$900mm, 7 years, S + 225 bps, 1% amortization per annum"
_CLAUSE_SPLIT_RE = re.compile(r"[,;]\s+")
# "Revolving Credit Facility: None": a labelled line or sentence that says the revolver does not amortise
_RCF_NONE_RE = re.compile(r"revolv\w*(?:\s+(?:credit\s+)?(?:facility|loans?|commitments?))?\s*:\s*(?:none|n/?a|nil|not\s+applicable)\b", re.IGNORECASE)
# "Term Loan B: 1.00% per annum": the facility a line or sentence of an amortisation section is about
_LEADING_LABEL_RE = re.compile(r"^(?P<lab>[A-Z][\w/&\- ]{1,40}?):\s+(?P<rest>\S.*)$")


def _amort_profile(text: str) -> str:
    """An amortisation table as one clause: "0.000% per quarter (quarters ending ... to ...); ...; 1.250% per quarter thereafter"."""
    starts = [m.start() for m in _AMORT_ROW_RE.finditer(text)]
    if len(starts) < 2:
        return ""
    rows = []
    quarterly = bool(_QUARTER_RE.search(text))
    per = " per quarter" if quarterly else ""
    for a, b in zip(starts, starts[1:] + [len(text)]):
        chunk = text[a:b]
        pct = _PCT.search(chunk)
        if not pct:
            continue
        dates = _DATE_RE.findall(chunk[:220])
        if b == len(text):
            chunk = chunk[:pct.end()]  # the last row ends at its percentage; running text follows the table
        label = tidy(chunk[:pct.start()] + " " + chunk[pct.end():])
        if _THEREAFTER_RE.search(label):
            rows.append(f"{pct.group(1)}%{per} thereafter")
        elif len(dates) >= 2 and quarterly:
            rows.append(f"{pct.group(1)}%{per} (quarters ending {dates[0]} to {dates[1]})")
        else:
            rows.append(f"{_strip_end(label)}: {pct.group(1)}%")
    return "; ".join(rows) if len(rows) >= 2 else ""


# A table cell that is only a percentage: "0.625%", "1.25 %"
_PCT_CELL_RE = re.compile(r"\d{1,3}(?:\.\d+)?\s?%")


def _pct_table(cell: _Cell) -> tuple[str, str]:
    """(profile, first words of the table) from a two-column table of percentages set out line by line under a sentence
    that ends with a colon - "First eight fiscal quarter payment dates   0.625%" / "Each fiscal quarter payment date
    thereafter   1.25%" / "Maturity Date   All remaining principal amounts" - as "label: value; label: value". A row's
    label may wrap round its value: a line that starts in lower case, or that follows a row still without a value,
    carries on that row. ("", "") unless the table reads cleanly and has at least two rows with a percentage."""
    entries = []
    for part in cell.block.parts:
        if tidy(part):
            entries.append((tidy(part), [c[2].strip() for c in fragments(part.strip(), 3)]))
    first_pct = next((i for i, (_, cells) in enumerate(entries) if len(cells) >= 2 and _PCT_CELL_RE.fullmatch(cells[-1])), None)
    if first_pct is None:
        return "", ""
    colon = next((i for i in range(first_pct - 1, max(-1, first_pct - 5), -1) if entries[i][0].endswith(":")), None)
    if colon is None:
        return "", ""  # no sentence that introduces a table
    rows: list[list[str]] = []
    head = ""
    for text, cells in entries[colon + 1:]:
        if len(cells) > 2:
            return "", ""  # more than two columns: not a table this reads
        if len(cells) == 1 and len(text) > 70:
            break  # running text after the table
        label, value = (cells[0], cells[1]) if len(cells) == 2 else (cells[0], "")
        if not rows and not head and value and not _DIGIT_RE.search(value) and len(value.split()) <= 3:
            head = label  # the header row: "Fiscal Quarter Payment Date   Percentage"
            continue
        if rows and (label[:1].islower() or not rows[-1][1]):
            if value and rows[-1][1]:
                return "", ""  # two values for one row
            rows[-1][0] += " " + label
            rows[-1][1] = rows[-1][1] or value
            continue
        if rows and not value:
            # a line without a value after a complete row: the wrapped end of that row's label ("Date Thereafter") or the start of
            # the next row - the layout does not say which. A sentence (it ends with a full stop) is running text after the table.
            if text.endswith("."):
                break
            return "", ""
        rows.append([label, value])
    while rows and not rows[-1][1]:
        rows.pop()
    if sum(1 for _, value in rows if _PCT_CELL_RE.fullmatch(value)) < 2 or any(len(label) > 90 or len(value) > 60 for label, value in rows):
        return "", ""
    profile = "; ".join(f"{_lower_first(_style(label))}: {_lower_first(_style(value)).replace(' %', '%')}" for label, value in rows)
    return profile, head or rows[0][0]


def _table_start(cell: _Cell) -> str:
    """The first line of a table set out under a sentence that ends with a colon (at least two of the four lines after the
    colon have two or more cells), as one string; "" if the section has no such table."""
    entries = [(tidy(part), fragments(part.strip(), 3)) for part in cell.block.parts if tidy(part)]
    for i, (text, _) in enumerate(entries[:-2]):
        if text.endswith(":") and sum(1 for _, cells in entries[i + 1:i + 5] if len(cells) >= 2) >= 2:
            return entries[i + 1][0]
    return ""


def _prepayment_line(ctx: Ctx) -> tuple[str, dict | None]:
    """A line on voluntary prepayment where the term sheet allows it without premium or penalty, with its quote."""
    for b in _find(ctx, L_PREPAY)[:3]:
        c = _cell(ctx, b, L_PREPAY)
        t = _style(c.text)
        m = _NO_PENALTY_RE.search(t)
        if not m:
            continue
        if len(t) <= 110:  # a table cell: its own words
            return f"Voluntary prepayment: {_lower_first(_strip_end(t))}" + (" (same as existing)" if c.same else ""), _quote(ctx, c.block)
        first = (_sents(t) or [t])[0]
        if _CALL_PREMIUM_RE.search(t):  # a premium applies in some cases: the section's own opening words, not a summary
            return "Voluntary prepayment: " + _clip(_lower_first(_strip_end(first)), 225), _quote(ctx, c.block)
        line = "Voluntary prepayment: permitted " + m.group(0).lower()
        if _ANY_TIME_RE.search(first):
            line = line.replace("permitted ", "permitted at any time ")
        mn = _PREPAY_MIN_RE.search(first)
        least = _first_amount(mn.group("min")) if mn else None
        step = _first_amount(mn.group("inc")) if mn and mn.group("inc") else None
        if least:
            line += f", minimum {least[1]}" + (f" and increments of {step[1]}" if step else "")
        if _BREAKAGE_RE.search(t):
            line += ", subject to breakage costs"
        raw = _NO_PENALTY_RE.search(_norm(c.block.text))
        return line, _quote(ctx, c.block, raw.group(0) if raw else None)
    return "", None


def _raw_wording(rx: re.Pattern, cell: _Cell) -> str:
    """The wording ``rx`` matches in the cell's page text; matching is done on the styled text, quoting on the page text."""
    m = rx.search(_norm(cell.block.text))
    return m.group(0) if m else ""


# A facility named as a label in the middle of a sentence: "... 2.50% Term Loan B: 1.00% per annum"
# (after a figure or a stop - "the original principal amount of the Term Loans:" introduces a table, it is not a label)
_INLINE_FACILITY_LABEL_RE = re.compile(r"(?<=[%.;)\d]\s)(?=(?P<lab>[A-Z][\w/&\-]*(?:\s+[A-Z0-9][\w/&\-]*){0,4}):\s+\S)")


def _amort_statements(cell: _Cell) -> list[tuple[str, str]]:
    """(facility named, statement) pairs from an amortisation section: its labelled lines ("Term Loan B: 1.00% per
    annum" / "Revolving Credit Facility: None") or its sentences; the name is "" where the statement has no label."""
    pieces = [_style(p) for p in _labelled_points(cell)]
    if not pieces:
        for s in _sents(_style(cell.text)):  # "Term Loan A: ... 2.50% Term Loan B: 1.00% per annum ...": one piece for each facility named
            cuts = [0] + [m.start() for m in _INLINE_FACILITY_LABEL_RE.finditer(s) if m.start() > 0 and _kind(m.group("lab")) not in _GENERIC_KINDS]
            pieces += [s[a:b].strip() for a, b in zip(cuts, cuts[1:] + [len(s)]) if s[a:b].strip()]
    out: list[tuple[str, str]] = []
    for p in pieces:
        m = _LEADING_LABEL_RE.match(p)
        if m and _kind(m.group("lab")) not in _GENERIC_KINDS:
            out.append((m.group("lab"), m.group("rest")))
        else:
            out.append(("", p))
    return out


def _term_name(text: str, kinds: set[str]) -> str:
    """The term loan a statement is about: the one it names, else the only one the facility has, else "Term Loans"."""
    terms = sorted(k for k in kinds if k.startswith("Term Loan"))
    named = _kind(text) if _TERM_LOAN_TALK_RE.search(text or "") else ""
    if named.startswith("Term Loan") and named != "Term Loan":
        return named  # "Term Loan B"
    if len(terms) == 1:
        return terms[0]
    return "Term Loans" if len(terms) > 1 else (named or "Term Loan")


def _term_amortisation(ctx: Ctx, amort: list[_Cell], kinds: set[str]) -> tuple[list[str], list[dict]]:
    """Lines for term loans that amortise: how each is repaid, then the profile if the term sheet sets one out."""
    has_rcf = "RCF" in kinds
    has_term = any(k.startswith("Term Loan") for k in kinds)
    lines: list[str] = []
    ev: list[dict | None] = []
    seen: set[str] = set()
    for c in amort:
        t = _style(c.text)
        if _NO_AMORT_CELL_RE.match(t) or not _AMORT_TALK_RE.search(t + " " + c.block.label):
            continue
        amort_label = bool(_AMORT_LABEL_RE.search(c.block.label))
        table_start = _style(_table_start(c))
        for label, first in _amort_statements(c):
            if _REVOLVING_RE.search(label) or _NO_AMORT_CELL_RE.match(first) or _NO_AMORT_RE.search(first):
                continue  # the revolver, or a statement that there is no amortisation
            cut = first.find(table_start) if table_start else -1
            stem = _strip_end(first[:cut]) if cut > 20 else first  # the statement without the table it runs on into
            about_term = bool(_TERM_LOAN_TALK_RE.search(label + " " + stem))
            if not label and _REVOLVING_RE.search(stem) and not about_term:
                continue
            if not (_AMORT_SENTENCE_RE.search(first) or ((amort_label or label) and _PCT.search(first))):
                continue  # not a statement of how a loan is repaid
            if has_rcf and not has_term and not about_term:
                continue  # the facility is a revolver only and the statement names no term loan
            who = _term_name(label or stem, kinds)
            if who in seen or (lines and not (about_term and (_AMORT_SENTENCE_RE.search(first) or label))):
                continue  # one statement for each term loan
            seen.add(who)
            how = _AMORT_VERB_RE.search(first) if len(first) > 220 else None  # a short sentence is kept whole
            detail = _strip_end(how.group("how") if how else first)
            lead = _BEGINNING_RE.match(first)
            if lead and how:
                detail += f" ({_lower_first(_strip_end(lead.group(0)))})"
            name = who if (has_rcf or len(kinds) > 1 or label or lines) else ""
            profile = _amort_profile(first if label else t) if not lines else ""
            row = _AMORT_ROW_RE.search(detail)
            if profile and row and row.start() > 20:  # the sentence runs on into the table: keep its opening and its close
                close = _REMAINDER_RE.search(detail, row.start())
                detail = _strip_end(detail[:row.start()]) + (f", {close.group(0)}" if close else "")
            elif profile and row:
                profile = ""  # the statement is the schedule itself: one line says it
            if not profile and not lines:  # a table of percentages under the statement, read line by line
                table, table_head = _pct_table(c)
                at = first.find(_style(table_head)[:30]) if table_head else -1
                if table and at > 20:  # the statement runs on into the table: keep the statement, give the table as the profile
                    sentence = _fit(_strip_end(first[:at]), 340)
                    said = _AMORT_VERB_RE.search(sentence)
                    detail, profile = _strip_end(said.group("how") if said else sentence), table
                elif stem is not first:  # a table the rules do not read: the statement alone, and the line says there is a table
                    sentence = _fit(stem, 300)
                    said = _AMORT_VERB_RE.search(sentence) if len(sentence) > 220 else None
                    detail = _strip_end(said.group("how") if said else sentence) + " (schedule set out in a table in the term sheet)"
            lines.append(_clip(f"Amortising{f' ({name})' if name else ''}: {_lower_first(detail)}", 300))
            ev.append(_quote(ctx, c.block, first[:50]))
            if profile:
                lines.append(_clip(f"{name or 'Amortisation'} profile: {profile}", 330))
                raw = _norm(c.block.text)
                pm = _PCT.search(raw)
                ev.append(_quote(ctx, c.block, raw[max(0, pm.start() - 40):pm.end()] if pm else None))
            elif len(lines) == 1 and not _PCT.search(detail):
                per = _PCT_PER_RE.search(t)
                if per:
                    lines.append(f"{name or 'Amortisation'} profile: {per.group(0)}")
            if len(lines) >= 4:
                break
        if lines:
            break
    return lines, ev


def _term_bullet(ctx: Ctx, amort: list[_Cell], kinds: set[str]) -> tuple[str, dict | None]:
    """A term loan the term sheet says is not amortised: "Amortization: None", "Term Loan B: None", "The Term Loan
    will be repaid in full on the Maturity Date"."""
    for c in amort:
        t = _style(c.text)
        if _NO_AMORT_CELL_RE.match(t) and len(t) <= 80 and _AMORT_LABEL_RE.search(c.block.label):
            return f"Bullet ({_term_name('', kinds)}; no amortisation)", _quote(ctx, c.block)
        for label, s in _amort_statements(c):
            if not _TERM_LOAN_TALK_RE.search(label or s) or (not label and _REVOLVING_RE.search(s)):
                continue
            who = _term_name(label or s, kinds)
            if _NO_AMORT_CELL_RE.match(s):
                return f"Bullet ({who}; no amortisation)", _quote(ctx, c.block, (label + ": " if label else "") + s[:30])
            if _NO_AMORT_RE.search(s) or _BULLET_CELL_RE.search(s):
                return _clip(f"Bullet ({who}): {_lower_first(_strip_end(s))}"), _quote(ctx, c.block, s[:50])
    return "", None


def _amort_reference(ctx: Ctx, amort: list[_Cell]) -> tuple[str, dict | None]:
    """An amortisation / repayment section that only points to another document or to later agreement."""
    for c in amort:
        t = _style(c.text)
        first = _strip_end((_sents(t) or [t])[0])
        if (_refers(first) or _SAME_AS_START_RE.match(first)) and len(first) <= 200 and not _PCT.search(first):
            return f"{_title(c.block.label)}: {_lower_first(first)}", _quote(ctx, c.block)
    return "", None


def _revolver_details(cells: list[_Cell]) -> tuple[list[str], list[tuple[_Cell, str]]]:
    """What the term sheet says about repaying the revolver, each point with the cell and wording that support it."""
    details: list[str] = []
    basis: list[tuple[_Cell, str]] = []

    def add(key: str, detail: str, cell: _Cell, wording: str) -> None:
        if not any(key in d for d in details):  # one statement of each kind is enough
            details.append(detail)
            basis.append((cell, wording))

    for c in cells:
        t = _style(c.text)
        raw = _norm(c.block.text)
        repay_label = _REPAY_LABEL_RE.search(c.block.label)
        term_only = bool(_TERM_LOAN_TALK_RE.search(t)) and not _REVOLVING_RE.search(t)  # a section about the term loan alone
        if _NO_AMORT_CELL_RE.match(t) and _AMORT_LABEL_RE.search(c.block.label):  # "Amortization: None (same as existing ...)"
            rest = _NONE_PREFIX_RE.sub("", t).strip(" ()")
            add("amorti", "no amortisation" + (f" - {rest}" if rest and len(rest) <= 80 else ""), c, raw[:60])
        for s in _sents(t):  # "with no amortization", unless the sentence is about a term loan and not the revolver
            if _NO_AMORT_RE.search(s) and not (_TERM_LOAN_TALK_RE.search(s) and not _REVOLVING_RE.search(s)):
                add("amorti", "no amortisation", c, _raw_wording(_NO_AMORT_RE, c))
        if (_NONE_FOR_RCF_RE.search(t) or _RCF_NONE_RE.search(t)) and repay_label:
            add("amorti", "no amortisation", c, _raw_wording(_NONE_FOR_RCF_RE, c) or _raw_wording(_RCF_NONE_RE, c))
        m = _DUE_RE.search(t)
        if m:
            when = f" on {m.group('when')}" if m.group("when") else " at maturity"
            add("payable", "all amounts outstanding due and payable" + (" in full" if m.group("full") else "") + when, c, _raw_wording(_DUE_RE, c))
        m = _REPAY_BY_RE.search(t)
        if m:
            detail = f"each {m.group('what')} repayable no later than {_strip_end(m.group('when'))}"
            m2 = _REPAY_BY_RE.search(t, m.end())  # "If the Term Loan Conversion Option is exercised ..., no later than on the Final Maturity Date"
            cond = _IF_CLAUSE_RE.search(t[m.end():m2.start()]) if m2 else None
            if m2 and cond and _strip_end(m2.group("when")) != _strip_end(m.group("when")):
                detail += f", or {_strip_end(m2.group('when'))} if {cond.group(1)}"
            add("repayable", detail, c, _raw_wording(_REPAY_BY_RE, c)[-80:])
        m = _ROLLOVER_RE.search(t)
        if m:
            add("Interest Period", f"each {m.group('what')} repayable on the last day of its Interest Period", c, _raw_wording(_ROLLOVER_RE, c))
        if _BULLET_CELL_RE.search(t) and len(t) <= 160 and repay_label and not term_only:
            add("payable", "repayable: " + _lower_first(_strip_end(t)), c, raw[:60])
        if _REBORROW_RE.search(t):
            add("reborrow", "amounts repaid may be reborrowed", c, _raw_wording(_REBORROW_RE, c))
    return details, basis


def _stated_bullet(ctx: Ctx, amort: list[_Cell]) -> tuple[str, dict | None]:
    """A repayment section that says there is no amortisation, for a facility that is not (known to be) a revolver."""
    for c in amort:
        t = _style(c.text)
        if _NO_AMORT_CELL_RE.match(t) or _NO_AMORT_RE.search(t):
            rest = _NONE_PREFIX_RE.sub("", t).strip(" ()")
            keep = rest and len(rest) <= 120 and _NO_AMORT_CELL_RE.match(t)  # "None (same as existing ...)": keep what follows
            line = "Bullet (no amortisation" + (f" - {_lower_first(_strip_end(rest))}" if keep else "") + ")"
            return line, _quote(ctx, c.block, _raw_wording(_NO_AMORT_RE, c) or None)
        if _BULLET_CELL_RE.search(t) and len(t) <= 200:
            return _clip(f"Bullet ({_lower_first(_strip_end(t))})"), _quote(ctx, c.block)
    return "", None


def repayment(ctx: Ctx) -> dict:
    """"Bullet" or "Amortising" with the profile; a revolver with no scheduled amortisation is a bullet."""
    fac = _analyse(ctx)
    kinds = fac.kinds
    amort = [c for c in (_cell(ctx, b, L_AMORT) for b in _find(ctx, L_AMORT)[:2]) if c.text]
    maturity_cells = [c for c in (_cell(ctx, b, L_MATURITY) for b in _find(ctx, L_MATURITY)[:2]) if c.text]
    avail_cells = [c for c in (_cell(ctx, b, L_AVAILABILITY) for b in _find(ctx, L_AVAILABILITY)[:1]) if c.text]
    has_term = any(k.startswith("Term Loan") for k in kinds)
    has_rcf = "RCF" in kinds
    note = ""
    deferred = False  # the repayment terms are only given by reference to another document

    lines, ev = _term_amortisation(ctx, amort, kinds)  # term loans: the amortisation the term sheet sets out
    if not lines and has_term:  # or the statement that a term loan does not amortise
        line, q = _term_bullet(ctx, amort, kinds)
        if line and q:
            lines.append(line)
            ev.append(q)
    if not lines and has_term:  # or a summary row that gives the amortisation with the amount: "$900mm, 7 years, 1% amortization per annum"
        for t in fac.main:
            row = _style(t.cell.text) if t.cell and t.kind.startswith("Term Loan") else ""
            clause = next((p.strip() for p in _CLAUSE_SPLIT_RE.split(row) if _AMORT_SENTENCE_RE.search(p) and _PCT.search(p)), "") if len(row) <= 200 else ""
            if clause:
                lines.append(_clip(f"Amortising ({t.kind}): {_strip_end(clause)} (as given in the facility row)"))
                ev.append(_quote(ctx, t.cell.block, _raw_wording(_AMORT_SENTENCE_RE, t.cell)))
    ref_line, ref_q = ("", None) if lines else _amort_reference(ctx, amort)
    if ref_line and ref_q and (has_term or not has_rcf):
        lines.append(_clip(ref_line))
        ev.append(ref_q)
        deferred = True
    if has_term and not lines:
        note = "The facility includes a term loan but no amortisation or repayment profile was read for it; check the term sheet."
    with_term = bool(lines) or has_term
    if has_rcf:  # revolvers: repayable at maturity
        details, basis = _revolver_details(amort + maturity_cells + avail_cells)
        express = any(_EXPRESS_DETAIL_RE.search(d) for d in details)
        name = "RCF - " if with_term else ""
        if express:
            lines.append(_clip(f"Bullet ({name}revolving; {'; '.join(details)})", 300))
        else:  # derived, and says so
            extra = "; " + "; ".join(details) if details else ""
            lines.append(_clip(f"Bullet ({name}revolving; repayable at maturity{extra}) (not stated expressly; the facility is revolving and "
                               f"the term sheet sets out no scheduled amortisation{' for it' if with_term else ''})", 300))
        ev += [_quote(ctx, c.block, wording or None) for c, wording in basis[:2]]
        if not express:  # the basis is the facility itself and its maturity
            ev += fac.evidence[:1] + [_quote(ctx, c.block) for c in maturity_cells[:1]]
        if ref_line and ref_q and not deferred:  # a revolver whose repayment section points to another document
            lines.append(_clip(ref_line))
            ev.append(ref_q)
    elif not lines:  # no facility type, or a term loan whose section only says there is no amortisation
        line, q = _stated_bullet(ctx, amort)
        if line:
            lines.append(line)
            ev.append(q)
    if not lines:
        if not note and not kinds:
            note = "The type of facility could not be established, so no repayment line was derived; check the term sheet."
        return not_stated(note=note)
    pre_line, pre_q = _prepayment_line(ctx)
    if pre_line and pre_q:
        lines.append(_clip(pre_line))
        ev.append(pre_q)
    entry = (by_reference if deferred else stated)(lines[:6], [e for e in ev if e], note)
    return entry


# ======================================================================================================
# 9. Accordion
# ======================================================================================================

L_ACCORDION = _label(
    r"(?:uncommitted\s+)?accordion(?:\s+(?:feature|option|facility))?|(?:uncommitted\s+)?incremental(?:\s+[\w/]+){0,4}|"
    r"(?:commitment|facility|revolver)\s+increases?|increase\s+option|increase\s+in\s+commitments|expansion\s+(?:feature|option)|"
    r"(?:uncommitted\s+)?(?:increase|upsize)(?:\s+option)?|optional\s+increases?|facility\s+increase|"
    r"additional\s+(?:commitments|facilit(?:y|ies))|increases?\s+(?:in|of|to)(?:\s+[\w]+){0,3}",
    r"(?!.*\bconditions?\b)(?:(?:uncommitted\s+)?accordion(?:\s+(?:feature|option|facility))?|additional\s+(?:commitments|facilit(?:y|ies))|"
    r"increases?\s+(?:in|of|to)\s+(?:the\s+)?(?:revolving\s+|aggregate\s+|total\s+)?(?:credit\s+)?(?:commitments|facilit(?:y|ies))|"
    r"(?:uncommitted\s+)?incremental(?:\s+(?:facilit(?:y|ies)|term|loans?|revolving|commitments?|option|feature|debt|capacity|increases?|"
    r"amount|and|/|senior|credit|facility))*|(?:[\w/\s]{0,60}\b)?(?:facility|commitment|revolver)\s+increases?|increase\s+option|"
    r"increase\s+in\s+commitments|expansion\s+(?:feature|option)|(?:uncommitted\s+)?(?:increase|upsize)(?:\s+option)?|optional\s+increases?)")
# "the greater of (i) $400,000,000 and (ii) 100% of Consolidated EBITDA"
_ACC_BASE = r"(?:(?:Consolidated|LTM|TTM|Adjusted|Pro\s+Forma|Total|Net|Tangible)\s+)*(?:EBITDA|Assets)"  # what the percentage is of
_ACC_GREATER_RE = re.compile(
    rf"greater\s+of\s+(?:\(?[ixa-z]{{1,3}}\)\s*)?(?P<amt>{_M})\s+and\s+(?:\(?[ixa-z]{{1,3}}\)\s*)?(?:an\s+amount\s+equal\s+to\s+)?"
    rf"(?P<pct>\d{{1,3}}(?:\.\d+)?)\s*%\s+of\s+(?P<base>{_ACC_BASE})", re.IGNORECASE)
# "the greater of (a) 100% of Consolidated EBITDA and (b) $400,000,000": the percentage first
_ACC_GREATER_PCT_RE = re.compile(
    rf"greater\s+of\s+(?:\(?[ixa-z]{{1,3}}\)\s*)?(?:an\s+amount\s+equal\s+to\s+)?(?P<pct>\d{{1,3}}(?:\.\d+)?)\s*%\s+of\s+(?P<base>{_ACC_BASE})"
    rf"[^$€£.;]{{0,80}}?\s+and\s+(?:\(?[ixa-z]{{1,3}}\)\s*)?(?P<amt>{_M})", re.IGNORECASE)
# "not to exceed the sum of (a) $500,000,000 plus (b) ...", "up to (x) $300,000,000 plus (y) ...": a fixed amount as the first limb of a sum
_ACC_SUM_RE = re.compile(
    rf"the\s+sum\s+of\s+\(?[a-z0-9]{{1,3}}\)\s*(?P<amt>{_M})|(?:up\s+to|not\s+(?:to\s+)?exceed(?:ing)?|equal\s+to)\s+\((?:[a-z]|[ivx]{{1,4}}|\d)\)\s*"
    rf"(?P<amt2>{_M})(?=\s+plus\b)", re.IGNORECASE)
# A ceiling on the facility after the increase, not the size of the increase: "the aggregate commitments under the Facilities after
# giving effect to any such increase shall not exceed $4,000,000,000", "increase the aggregate Commitments to an amount not to exceed ..."
_ACC_CEILING_RE = re.compile(
    rf"(?:aggregate|total)\s+(?:amount\s+of\s+(?:the\s+|all\s+)?)?(?P<mods>(?:[\w-]+\s+){{0,3}}?)commitments\b(?P<mid>[^.;$€£]{{0,140}}?)"
    rf"(?:not\s+(?:to\s+)?exceed(?:ing)?|no\s+(?:more|greater)\s+than|up\s+to(?:\s+a\s+maximum\s+of)?|"
    rf"not\s+be\s+increased\s+(?:to\s+(?:an?\s+)?(?:aggregate\s+)?(?:amount\s+)?(?:greater\s+than|in\s+excess\s+of|exceeding|above|more\s+than)|above|beyond))"
    rf"\s+(?:an?\s+)?(?:aggregate\s+)?(?:amount\s+)?"
    rf"(?:of\s+)?(?P<amt>{_M})|increase\s+(?:the\s+)?(?P<mods2>(?:[\w-]+\s+){{0,5}}?)to\s+(?:an?\s+)?(?:aggregate\s+)?(?:principal\s+)?"
    rf"(?:amount\s+)?(?:of\s+)?(?:up\s+to\s+|not\s+(?:to\s+)?exceed(?:ing)?\s+|not\s+in\s+excess\s+of\s+)(?P<amt2>{_M})", re.IGNORECASE)
# The same said of the facility: "after giving effect to any such increase, the Facility shall not exceed $1,500,000,000",
# "the aggregate amount of the Facility shall not exceed ..."
_ACC_FACILITY_CEILING_RE = re.compile(
    rf"(?:after|upon)\s+giving\s+effect\s+to\s+(?:any\s+|all\s+|the\s+|each\s+)?(?:such\s+)?(?:increases?|incremental\s+[\w-]+)\b(?P<mid>[^.;$€£]{{0,140}}?)"
    rf"(?:not\s+(?:to\s+)?exceed(?:ing)?|no\s+(?:more|greater)\s+than|up\s+to)\s+(?:an?\s+)?(?:aggregate\s+)?(?:principal\s+)?(?:amount\s+)?(?:of\s+)?(?P<amt>{_M})|"
    rf"\b(?:the\s+)?(?:(?:aggregate|total)\s+)?(?:(?:principal\s+)?amount\s+of\s+the\s+)?(?:(?:Revolving|Credit|Senior|Secured|Unsecured)\s+)*"
    rf"(?:Facility(?:\s+Amount)?|Facilities)\s+(?:\([^()]{{0,60}}\)\s*)?(?:shall|will|may|would|does|do)\s+not\s+exceed\s+(?:an?\s+)?(?:aggregate\s+)?"
    rf"(?:principal\s+)?(?:amount\s+)?(?:of\s+)?(?P<amt2>{_M})", re.IGNORECASE)
# ... unless the commitments spoken of are the new ones ("the aggregate amount of additional commitments shall not exceed"),
# or the amount is what the commitments are increased by ("the aggregate commitments may be increased by up to")
_ACC_NEW_COMMITMENTS_RE = re.compile(r"additional|incremental|increased|\bnew\b", re.IGNORECASE)  # between "aggregate" and "commitments"
_ACC_NEW_AMOUNT_RE = re.compile(r"additional|incremental|increases?\b|\bnew\b", re.IGNORECASE)        # what "shall not exceed" is said of
# The commitments a ceiling is put on, where they are those of one facility: "aggregate revolving commitments", "commitments under the Revolving Facility"
_CEILING_OF_RE = re.compile(r"^(?:revolving(?:\s+credit)?|term(?:\s+loan)?(?:\s+[ab])?|[\w-]+\s+tranche)$", re.IGNORECASE)
_CEILING_UNDER_RE = re.compile(r"^\s*under\s+the\s+(?P<name>(?:[A-Z0-9][\w-]*\s+){0,3}(?:Facility|Facilities|Tranche))\b")
_ACC_INCREASED_BY_RE = re.compile(r"\bby\s+(?:an?\s+|up\s+|not\s+)", re.IGNORECASE)                 # between "commitments" and the amount
# The amount is called the aggregate (of all increases): "in an aggregate principal amount of up to", "not to exceed in total"
_ACC_AGGREGATE_RE = re.compile(r"\baggregate\b|\btotal\b", re.IGNORECASE)
# A table cell written as running text has a verb of obligation or permission; a cell that is a phrase has none.
_MODAL_RE = re.compile(r"\b(?:may|shall|will|would|must)\b", re.IGNORECASE)
# "up to a maximum amount of $1,800,000,000", "up to a maximum Facility Amount of $4,500,000,000"
_ACC_MAX_RE = re.compile(rf"up\s+to\s+a\s+maximum\s+(?P<what>(?:Facility\s+|aggregate\s+)?amount)\s+of\s+(?P<amt>{_M})", re.IGNORECASE)
# "(or following the consummation of the Disposal, $3,500,000,000)"
_ACC_ALT_RE = re.compile(rf"^\s*\(\s*or\s+(?P<cond>[^$()]{{3,80}}?),?\s*(?P<amt>{_M})\s*\)", re.IGNORECASE)
# "in an aggregate principal amount of up to $1.0 billion", "by an amount up to, when taken together with ..., $2,000,000,000"
_ACC_UPTO_RE = re.compile(
    rf"(?:not\s+(?:to\s+)?exceed(?:ing)?|up\s+to|not\s+be\s+increased\s+by\s+more\s+than|by\s+(?:no|not)\s+more\s+than)\s*(?:(?:an?|the)\s+)?(?:additional\s+)?"
    rf"(?:aggregate\s+)?(?:total\s+)?(?:principal\s+)?(?:amount\s+)?"
    rf"(?:of\s+)?(?P<gap>,\s*[^$€£.;]{{0,240}}?,\s*)?(?P<amt>{_MX})", re.IGNORECASE)
# "may increase the commitments by an aggregate amount of $500,000,000" (no "up to")
_ACC_BY_RE = re.compile(
    rf"(?:increase[sd]?|incremental|additional\s+commitments)\b[^.;$€£]{{0,160}}?\b(?:by|of)\s+(?:an?\s+)?(?:additional\s+)?(?:aggregate\s+)?(?:principal\s+)?"
    rf"(?:amount\s+)?(?:of\s+)?(?P<gap>)(?P<amt>{_MX})", re.IGNORECASE)
# The ratio test of the ratio-based tranche: "the Secured Net Leverage Ratio ... is less than or equal to 3.00x"
_ACC_RATIO_RE = re.compile(
    r"(?P<name>(?:[A-Z][\w-]*\s+){1,6}Ratio|ratio\s+of\s+[^.;]{5,120}?)\s*(?:\([^()]{0,80}\)\s*)?(?:is|shall\s+be|would\s+be|being|shall|will|would|does)?\s*"
    r"(?P<neg>not\s+)?(?P<op>less\s+than\s+or\s+equal\s+to|no\s+greater\s+than|greater\s+than|exceed|less\s+than)\s+(?P<r>\d{1,2}\.\d{2})x")
# "in minimum increments of $10,000,000", "in a minimum amount of $20,000,000 and in increments of $5,000,000"
_ACC_MIN_RE = re.compile(
    rf"minimum\s+(?P<what>increments?|amounts?)\s+of\s+(?P<min>{_M})(?:\s+and\s+(?:in\s+)?(?:increments|integral\s+multiples)\s+of\s+(?P<inc>{_M}))?",
    re.IGNORECASE)
# "no more than once a year"
_ACC_FREQ_RE = re.compile(r"no\s+more\s+than\s+(?:once|twice|\w+\s+times?)\s+(?:a|per|each|in\s+any)\s+(?:calendar\s+|fiscal\s+)?year", re.IGNORECASE)
# "no default or event of default", "no Default or Event of Default", "no default or unmatured default"
_ACC_NO_DEFAULT_RE = re.compile(r"no\s+(?:unmatured\s+)?default(?:\s+or\s+(?:e\s?vent\s+of\s+default|unmatured\s+default))?", re.IGNORECASE)
# new lenders must take a minimum share: "the commitment of each such new third party institution equals or exceeds $5,000,000"
_ACC_NEW_LENDER_RE = re.compile(
    rf"commitment\s+of\s+each\s+such\s+[^.;$€£]{{0,60}}?(?:equals\s+or\s+exceeds|is\s+at\s+least|is\s+not\s+less\s+than)\s+(?P<amt>{_M})", re.IGNORECASE)
# bring-down of representations
_ACC_REPS_RE = re.compile(r"representations\s+and\s+warranties[^.;]{0,200}?(?:true\s+and\s+correct|accura)", re.IGNORECASE)
# ... with the representations the term sheet leaves out of the bring-down, and the standard it sets
_ACC_REPS_EXCEPT_RE = re.compile(r"\(other\s+than\s+(?:the\s+|those\s+)?(?:representations?\s+and\s+warrant(?:y|ies)\s+)?(?:as\s+to|relating\s+to|regarding|with\s+respect\s+to|"
                                 r"concerning)\s+(?P<what>[^()]{3,90}?)\)", re.IGNORECASE)
_ACC_REPS_MATERIAL_RE = re.compile(r"\s*in\s+all\s+material\s+respects", re.IGNORECASE)
# lenders are not obliged to take part
_ACC_UNCOMMITTED_RE = re.compile(
    r"uncommitted|right,?\s+but\s+(?:no|not\s+the)\s+obligation,?\s+to\s+commit|no\s+(?:existing\s+)?Lender\s+(?:will|shall)\s+be\s+"
    r"(?:required|obligated|obliged)\s+to\s+(?:participate|provide|commit)|entitled\s+to\s+agree\s+or\s+decline\s+to\s+participate|"
    r"Lenders?\s+(?:are|is|shall\s+be|will\s+be)\s+under\s+no\s+obligation", re.IGNORECASE)
# "at the Borrowers' election", "MK may, at its option"
_ACC_ELECTION_RE = re.compile(r"at\s+(?:the\s+)?(?:Borrowers?[’']s?|Company[’']s|its|their)\s+(?:election|option|request)", re.IGNORECASE)
# "None", "N/A", "Not applicable", "No accordion": the term sheet says there is no increase option
_ACC_NONE_RE = re.compile(r"^\W*(?:none|n/?a|nil|not\s+applicable|not\s+(?:permitted|available)|removed|eliminated|deleted|"
                          r"no\s+(?:accordion|incremental|increase)\b)", re.IGNORECASE)
# The section says in a sentence that there is no increase option: "The Facility will not include an incremental or accordion feature",
# "There will be no accordion"
_ACC_NEGATIVE_RE = re.compile(
    r"\b(?:will|shall|does|do|would)\s+not\s+(?:include|have|contain|provide\s+for|permit|allow|benefit\s+from|be\s+(?:permitted|available|included|subject\s+to))\b"
    r"(?:\s+(?:an?|any|the|for|to))*(?:\s+[\w-]+){0,2}?\s+(?:incremental|accordion|increases?|upsize|expansion)\b|"
    r"\bthere\s+(?:will|shall)\s+be\s+no\s+(?:[\w-]+\s+){0,3}?(?:incremental|accordion|increase|upsize|expansion)\b|"
    r"\bno\s+(?:incremental|accordion|increase|upsize|expansion)\s+(?:facilit(?:y|ies)|feature|option|provisions?|capacity)\s+(?:will|shall|is|are)\b", re.IGNORECASE)
# ... unless it goes on to allow one: "other than", "except", "unless"
_ACC_EXCEPTION_RE = re.compile(r"\bother\s+than\b|\bexcept\b|\bunless\b|\bprovided\b|\bsave\s+(?:for|as)\b|\bwithout\b", re.IGNORECASE)
_NEGATION_RE = re.compile(r"\bnot\b|\bno\b|\bnone\b|\bneither\b|\bnor\b", re.IGNORECASE)
# The amount is left blank: "up to $[●]", "$[ ] million"
_ACC_BLANK_RE = re.compile(r"[$€£]\s?\[[^\]\d]{0,8}\]")
# The same wording in the page text (ratios still written "3.00 to 1.00"), to place the quotes:
_ACC_GREATER_QUOTE_RE = re.compile(r"greater\s+of\s+(?:\(?[ixa-z]{1,3}\)\s*)?" + _M + r".{0,60}?%\s+of\s+[\w\s]{3,30}", re.IGNORECASE)
_ACC_RATIO_QUOTE_RE = re.compile(
    r"(?:less\s+than\s+or\s+equal\s+to|not\s+exceed|no\s+greater\s+than|less\s+than)\s+\d{1,2}\.\d{2}\s*(?:to|:)\s*1", re.IGNORECASE)
_ACC_MAX_QUOTE_RE = re.compile(r"up\s+to\s+a\s+maximum\s+[\w\s]{0,20}?amount\s+of\s+" + _M, re.IGNORECASE)
# More follows a plain cap: "up to $300,000,000 plus an unlimited amount subject to ..."
_ACC_PLUS_AFTER_RE = re.compile(r"^\s*(?:\([^()]{0,90}\)\s*)?,?\s*(?:in\s+the\s+aggregate\s*,?\s*)?plus\b", re.IGNORECASE)
# The ratio test belongs to the cap only if it follows "plus ...", "additional amounts", "unlimited".
_ACC_PLUS_RE = re.compile(r"plus|additional|unlimited", re.IGNORECASE)
# "(A)", "(B)" inside "the ratio of (A) ... to (B) ..."
_ENUM_MARK_RE = re.compile(r"\(\w\)\s*")
# The amount is a minimum or an increment, not the cap: "minimum increments of", "integral multiples of"
_ACC_MIN_CUE_RE = re.compile(r"\bminimum\b|\bincrements?\b|\bmultiples?\b", re.IGNORECASE)  # whole words: "Incremental" is not "increment"
# "e vent" for "event" where extraction split the word
_SPLIT_EVENT_RE = re.compile(r"e\s+vent")
# How the lenders' freedom not to take part is worded:
_ACC_RIGHT_BUT_RE = re.compile(r"right,?\s+but", re.IGNORECASE)             # "the right, but no obligation, to commit"
_ACC_NO_LENDER_RE = re.compile(r"no\s+(?:existing\s+)?Lender|under\s+no\s+obligation", re.IGNORECASE)  # "no existing Lender will be required to participate"
_ACC_DECLINE_RE = re.compile(r"agree\s+or\s+decline", re.IGNORECASE)        # "entitled to agree or decline to participate"
# The other document a by-reference clause points to is an existing agreement (not "to be agreed").
_EXISTING_DOC_RE = re.compile(r"Existing|Prior|Current")
# A sentence that is about an increase at all.
_ACC_TALK_RE = re.compile(r"increase|incremental|accordion|additional\s+commitments", re.IGNORECASE)
# The cap is shared with something else: "when taken together with ..."
_ACC_TOGETHER_RE = re.compile(r"(?:when\s+)?taken\s+together\s+with\s+(?P<what>[^$]{5,200})", re.IGNORECASE)
# A figure of the other document that this term sheet changes: "the fixed dollar-based component of the grower cap in the definition
# of “Permitted Incremental Amount” ... shall be increased to $1,400,000,000 (from $1,000,000,000)"
_ACC_RESET_RE = re.compile(
    rf"(?:^|[.;:,]\s+|\b(?:that|and)\s+)(?:\((?:[ivx]{{1,4}}|[a-z]|\d)\)\s+)?(?P<what>the\s+[^.;,$€£]{{8,220}}?)\s+(?:shall|will|is\s+to|to)\s+be\s+"
    rf"(?P<verb>increased|reduced|decreased|raised|lowered|reset|upsized)"
    rf"\s+to\s+(?P<amt>{_M})(?:\s*\(\s*from\s+(?P<old>{_M})\s*\))?", re.IGNORECASE)
# A further numbered item after the one read: "... and (ii) the ratio-based incremental amount shall ..."
_NEXT_ITEM_RE = re.compile(r"(?:\band\s+|[,;]\s*)\((?:ii|iii|b|c|2|3|B|C)\)\s")
# One limb of a ratio test that depends on the kind of debt: "(1) in the case of indebtedness that is secured on a pari passu lien
# basis ..., the Consolidated First Lien Net Leverage Ratio shall not exceed 3.50x, (2) in the case of ..."
# (or "(x) if such incremental facility is secured on a pari passu basis, ...", "(a) with respect to ..., ...")
_CASE_LEAD = r"(?:in\s+the\s+case\s+of|if|with\s+respect\s+to|in\s+respect\s+of|to\s+the\s+extent(?:\s+that)?|where|for)"
_TIER_RE = re.compile(
    r"\((?P<mark>\d|[a-z]|[ivx]{1,4})\)\s+(?P<lead>" + _CASE_LEAD + r")\s+(?P<when>[^,;.]{5,160}),\s+(?P<test>.+?)"
    r"(?=,?\s+(?:and\s+|or\s+)?\((?:\d|[a-z]|[ivx]{1,4})\)\s+" + _CASE_LEAD + r"\b|;|$)", re.IGNORECASE | re.DOTALL)
# The ratio test is said to apply only in one case: "in the case of indebtedness that is secured ..., the ... Ratio shall not exceed",
# "if such Incremental Facility is unsecured, ...", "with respect to junior lien debt, ..."
_IN_CASE_RE = re.compile(
    r"\bin\s+the\s+case\s+of\b|(?<!as\s)\bif\s+(?:such|the|any|an?|it|secured|unsecured)\b|"
    r"\b(?:with\s+respect\s+to|in\s+respect\s+of|to\s+the\s+extent|where)\s+(?:(?:any|such|the|an?)\s+)?(?:[\w-]+\s+){0,3}?"
    r"(?:secured|unsecured|pari\s+passu|junior|senior|subordinated|indebtedness|debt|incremental)\b", re.IGNORECASE)
# An alternative to the ratio straight after it: "does not exceed 4.00x or, in the case of an acquisition, the ratio immediately prior"
_ACC_ALT_TEST_RE = re.compile(r"^\s*(?:\([^()]{0,120}\)\s*)?,?\s*(?:\(\s*)?or\b", re.IGNORECASE)
# A paragraph that defines a term, inside a longer section: "“Consolidated EBITDA” shall be calculated ...", "“X” means ..."
_DEFINITION_RE = re.compile(r"(?<=[.;:)])\s+[“\"](?P<term>[^”\"]{3,60})[”\"]\s+(?:shall\s+)?(?:means?|be\s+calculated|have\s+the\s+meaning|refers?\s+to)\b")
# ... unless what it defines is the increase itself ("“Incremental Cap” means ...")
_ACC_TERM_RE = re.compile(r"increment|increase|accordion|\bcap\b|amount", re.IGNORECASE)
# The section points to another document by its defined name, whatever that name is: "Substantially the same as the Precedent
# Credit Agreement" (the shared pattern knows "Existing / Prior / Current" agreements only)
_NAMED_DOC_REF_RE = re.compile(
    r"(?:(?i:substantially)\s+)?(?i:similar|consistent|(?:the\s+)?same|identical)\s+(?i:to|with|as)\s+(?:(?i:those|that)\s+(?:(?i:set\s+forth|contained|provided)\s+)?"
    r"(?i:in|under)\s+)?(?i:the)\s+(?P<doc>(?:[A-Z0-9][\w-]*\s+){1,5}?(?:Agreement|Indenture))\b")


# The rest of a document's name after the word a reference pattern stops at: "the Existing" + " Credit Agreement"
_DOC_NAME_TAIL_RE = re.compile(r"(?:\s+[A-Z0-9][\w-]*){0,5}")


def _ref_words(text: str, ref: re.Match) -> str:
    """The wording of a reference with the name of the document it points to in full ("same as the Existing" is followed
    on the page by "Credit Agreement")."""
    words = ref.group(0)
    if _EXISTING_DOC_RE.search(words.split()[-1]):
        words += _DOC_NAME_TAIL_RE.match(text[ref.end():]).group(0)
    return _strip_end(words)


def _refers(text: str) -> re.Match | None:
    """The passage points to another document - by "Existing ...", or by any other defined name of an agreement - or to
    later agreement, instead of stating the term: the first such wording in it."""
    found = [m for m in (points_elsewhere(text), _NAMED_DOC_REF_RE.search(text)) if m]
    return min(found, key=lambda m: m.start()) if found else None


_ROMAN_MARKS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}


def _mark_number(mark: str) -> int:
    """Place of a list marker in its series: "(2)" -> 2, "(ii)" -> 2, "(b)" -> 2."""
    mark = mark.lower()
    if mark.isdigit():
        return int(mark)
    return _ROMAN_MARKS.get(mark) or (ord(mark[0]) - 96 if len(mark) == 1 else 0)


def _next_mark(prev: str, mark: str) -> bool:
    """``mark`` is the list marker that follows ``prev`` in a series: "2" after "1", "ii" after "i", "y" after "x"."""
    prev, mark = prev.lower(), mark.lower()
    if prev.isdigit() or mark.isdigit():
        return prev.isdigit() and mark.isdigit() and int(mark) == int(prev) + 1
    if prev in _ROMAN_MARKS and _ROMAN_MARKS.get(mark) == _ROMAN_MARKS[prev] + 1:
        return True
    return len(prev) == 1 and len(mark) == 1 and ord(mark) == ord(prev) + 1


def _ratio_tiers(text: str) -> list[str]:
    """The limbs of a ratio test that depends on the kind of debt, each as "<case>: <test>": the test in house style where
    it is a ratio ("Consolidated Secured Net Leverage Ratio <= 4.00x"), otherwise in the term sheet's own words. Empty
    unless at least two limbs are read."""
    # the limbs of one test are numbered in sequence - (1), (2), (3) - and at least one of them is a ratio: other clauses worded
    # "in the case of ..." earlier in the section are not part of it
    runs: list[list[re.Match]] = []
    for m in _TIER_RE.finditer(text[:4000]):
        if runs and _next_mark(runs[-1][-1].group("mark"), m.group("mark")):
            runs[-1].append(m)
        else:
            runs.append([m])
    run = next((r for r in runs if len(r) >= 2 and any(_ACC_RATIO_RE.search(m.group("test")) for m in r)), [])
    out: list[str] = []
    for m in run:
        test = _strip_end(m.group("test"))
        r = _ACC_RATIO_RE.search(test)
        shown = ""
        if r and len(test) - r.end() <= 2:  # the ratio is the whole of the test (nothing such as "or, if greater, ..." after it)
            wording = _norm(r.group("op")).lower()
            at_most = wording in ("less than or equal to", "no greater than") or (r.group("neg") and wording in ("exceed", "greater than"))
            op = "<=" if at_most else "<" if wording == "less than" and not r.group("neg") else ""
            if op:
                shown = f"{_LEADING_THE_RE.sub('', _ENUM_MARK_RE.sub('', _strip_end(r.group('name'))))} {op} {r.group('r')}x"
        if not shown:  # not a ratio the rules can restate: the limb's own words, without its bracketed asides
            shown = test
            for _ in range(4):  # brackets inside brackets go first
                shown = _BRACKET_RE.sub("", shown)
            shown = _strip_end(tidy(shown))
            if len(shown) > 140 or len(shown) < 8 or "(" in shown or ")" in shown:
                return []
        out.append(f"{shown} ({tidy(m.group('lead')).lower()} {_strip_end(m.group('when'))})")
    return out if len(out) >= 2 else []


def _ratio_name(r: re.Match) -> str:
    """The name of the ratio in a match of ``_ACC_RATIO_RE``, without article or list markers."""
    return _LEADING_THE_RE.sub("", _ENUM_MARK_RE.sub("", _strip_end(r.group("name"))))


def _ratio_tranche(text: str, r: re.Match) -> str:
    """What follows "Yes = <fixed amount>" for a ratio-based tranche whose first ratio test is ``r``. One test that simply
    applies is given as such. Where the sentence has more than one ratio, or says the ratio applies in one case only, no one
    ratio is printed as the test: the limbs are read one by one if they can be (the caller lists them), otherwise the
    ratios are named with their levels and the reader is sent to the term sheet for when each applies."""
    end = next((m.start() for m in _SENT_BREAK_RE.finditer(text, r.end())), len(text))
    tests = list(_ACC_RATIO_RE.finditer(text, r.start(), end))
    levels = list(dict.fromkeys(f"{_ratio_name(t)} {t.group('r')}x" for t in tests))
    conditional = bool(_IN_CASE_RE.search(text[max(0, r.start() - 220):r.start()]))
    if len(levels) > 1 or conditional:
        if _ratio_tiers(text):
            return ", plus further amounts set out in the term sheet, including additional amounts subject to the ratio tests below"
        listed = "; ".join(levels[:4])
        if len(levels) > 1:
            return (", plus further amounts set out in the term sheet, including additional amounts subject to more than one ratio test "
                    f"({listed}; see term sheet for when each applies)")
        return (", plus further amounts set out in the term sheet, including additional amounts subject to a ratio test that applies in "
                f"stated cases only ({listed}; see term sheet)")
    wording = _norm(r.group("op")).lower()
    at_most = wording in ("less than or equal to", "no greater than") or (r.group("neg") and wording in ("exceed", "greater than"))
    op = "<=" if at_most else "<" if wording == "less than" and not r.group("neg") else ""
    if not op:
        return ""
    alt = " (or an alternative test set out in the term sheet)" if _ACC_ALT_TEST_RE.match(text[r.end():r.end() + 140]) else ""
    return f", plus additional amounts subject to {_ratio_name(r)} {op} {r.group('r')}x{alt}"


def accordion(ctx: Ctx) -> dict:
    """"Yes = <amount>" with the key conditions, or "None stated in term sheet"."""
    fallback = None
    for block in _find(ctx, L_ACCORDION)[:3]:
        cell = _cell(ctx, block, L_ACCORDION)
        if not cell.text:
            continue
        entry, firm = _accordion_entry(ctx, cell)
        if entry is not None and firm:
            return entry
        fallback = fallback or entry
    return fallback or not_stated(NONE_STATED)


def _ceiling_cap(ctx: Ctx, amount: str, worded: str, alt: str) -> str:
    """The cap where the term sheet gives a ceiling on the facility after the increase rather than the size of the
    increase. With one facility of a known size below the ceiling the increase is the difference, and the line
    says it is derived and from what; otherwise the ceiling is given in the term sheet's own terms."""
    ceiling = _first_amount(amount)
    main = _analyse(ctx).main
    if ceiling and len(main) == 1 and main[0].mm > 0 and not main[0].upto:
        cur = _currency_of(main[0])
        if cur in ("$", "EUR ", "GBP ") and ceiling[1].startswith(cur) and ceiling[0] > main[0].mm + 1e-6:
            return f"{fmt_money(ceiling[0] - main[0].mm, cur)} (derived: the {main[0].money} facility may be increased {worded} {amount}{alt})"
    return f"{worded} {amount}{alt}"


def _accordion_cap(ctx: Ctx, cell: _Cell, text: str, raw: str) -> tuple[str, list[dict | None]]:
    """(the cap as it goes after "Yes = ", quotes for it) from one increase section; "" when no amount can be read."""
    def quote_of(rx: re.Pattern) -> dict | None:
        m = rx.search(raw)
        return _quote(ctx, cell.block, m.group(0)[:110]) if m else None

    short = _strip_bullet(text)
    start = _AMOUNT_START_RE.match(short)
    change_amt = _first_amount(_style(cell.change)) if cell.change else None
    if cell.change and change_amt:  # the amendment restates the capacity: "Reduce incremental capacity to $100 million ..."
        cap = f"{change_amt[1]} (proposed: {_lower_first(_strip_end(_style(cell.change)))}; existing: {_lower_first(_strip_end(short))})"
        return cap, [_quote(ctx, cell.block, cell.change[:60])]
    old = _first_amount(cell.old) if cell.old else None
    start_amt = _first_amount(start.group("amt")) if start else None
    if start and start_amt and len(short) <= 60:  # a table cell that is just the figure, perhaps with a word or two
        cap = ("up to " if start.group("upto") else "") + start_amt[1]
        rest = short[start.end():].strip(" ,;.")
        if rest and not SAME_AS_EXISTING_RE.match(rest):
            cap += (" " if rest.startswith("(") else ", ") + _lower_first(rest)
        if cell.same:
            cap += " (same as existing)"
        elif old and old[1] not in cap:
            cap += f" (existing: {old[1]})"
        return cap, [_quote(ctx, cell.block, start.group(0))]
    if len(short) <= 220 and len(_sents(short)) == 1 and _first_amount(short) and not _MODAL_RE.search(short):
        # a table cell that is a phrase, not a sentence ("Greater of $300mm and 100% of LTM EBITDA, plus ..."): its own words
        cap = _lower_first(_strip_end(short))
        if cell.same:
            cap += " (same as existing)"
        elif old and old[1] not in cap and len(cell.old) <= 80:
            cap += f" (existing: {_lower_first(_strip_end(_style(cell.old)))})"
        return cap, [_quote(ctx, cell.block)]
    cap, ev = "", []
    g = _ACC_GREATER_RE.search(text) or _ACC_GREATER_PCT_RE.search(text)
    sm = _ACC_SUM_RE.search(text)
    mx = _ACC_MAX_RE.search(text)
    ceil = next((m for m in _ACC_CEILING_RE.finditer(text)
                 if not _ACC_NEW_COMMITMENTS_RE.search(m.group("mods") or m.group("mods2") or "")
                 and not _ACC_INCREASED_BY_RE.search(m.group("mid") or "")), None)
    if ceil is None:  # the ceiling put on the facility itself: "after giving effect to any such increase, the Facility shall not exceed ..."
        ceil = next((m for m in _ACC_FACILITY_CEILING_RE.finditer(text)
                     if not _ACC_NEW_AMOUNT_RE.search(m.group("mid") or "")
                     and not (m.group("amt2") and _ACC_NEW_AMOUNT_RE.search(text[max(0, m.start() - 40):m.start()]))), None)
    ceil_amt = (ceil.group("amt") or ceil.group("amt2")) if ceil else ""
    # a plain cap: the first "up to" / "not to exceed" amount that is not a minimum, an increment or the ceiling, and for
    # preference one the wording calls the aggregate ("in an aggregate principal amount of up to ...")
    ups = sorted((m for rx in (_ACC_UPTO_RE, _ACC_BY_RE) for m in rx.finditer(text)
                  if not _ACC_MIN_CUE_RE.search(text[max(0, m.start("amt") - 45):m.start("amt")])
                  and _DIGIT_RE.search(m.group("amt"))), key=lambda m: m.start())  # (a blank left for the amount is dealt with below)
    plain = [m for m in ups if m.group("amt") != ceil_amt]
    up = next((m for m in plain if _ACC_AGGREGATE_RE.search(text[max(0, m.start() - 60):m.end()])), (plain or ups or [None])[0])
    if up and len(text) > 400 and not (_ACC_TALK_RE.search(text[max(0, up.start() - 300):up.end() + 60]) or "aggregate" in up.group(0).lower()):
        up = None  # an amount in some other clause of a long section, not the size of the increase
    blank = _ACC_BLANK_RE.search(text)
    if g or sm:  # a fixed basket, perhaps with a ratio-based tranche on top
        cap = f"greater of {g.group('amt')} and {g.group('pct')}% of {g.group('base')}" if g else (sm.group("amt") or sm.group("amt2"))
        ev.append(quote_of(_ACC_GREATER_QUOTE_RE if g and g.re is _ACC_GREATER_RE else _ACC_GREATER_PCT_RE if g else _ACC_SUM_RE))
        r = _ACC_RATIO_RE.search(text)
        if r and _ACC_PLUS_RE.search(text[max(0, r.start() - 500):r.start()]):
            tranche = _ratio_tranche(text, r)  # one ratio that simply applies, or tests that depend on the case
            if tranche:
                cap += tranche
                ev.append(quote_of(_ACC_RATIO_QUOTE_RE))
        tail = text[(g or sm).end():(g or sm).end() + 160]
        if "plus" not in cap and (not g or _ACC_PLUS_RE.search(tail)):  # further limbs of the cap that are not read here
            cap += " plus the further amounts set out in the term sheet"
    elif mx:  # a ceiling on the facility after the increase: "up to a maximum Facility Amount of ..."
        alt = _ACC_ALT_RE.match(text[mx.end():])
        cap = _ceiling_cap(ctx, mx.group("amt"), f"up to a maximum {mx.group('what')} of",
                           f" (or {alt.group('amt')} {_strip_end(alt.group('cond'))})" if alt else "")
        ev.append(quote_of(_ACC_MAX_QUOTE_RE))
    elif ceil and (not up or up.group("amt") == ceil_amt):  # "the aggregate commitments ... shall not exceed ..."
        # with several facilities, the commitments the ceiling is put on are named as the term sheet names them
        groups = ceil.groupdict()
        of = tidy(groups.get("mods") or "").lower()
        under = _CEILING_UNDER_RE.match(groups.get("mid") or "") if ceil.re is _ACC_CEILING_RE else None
        whose = ""
        if len(_analyse(ctx).main) > 1:
            whose = (of + " " if _CEILING_OF_RE.match(of) else "") + "commitments" + (f" under the {under.group('name')}" if under else "")
        cap = _ceiling_cap(ctx, ceil_amt, f"to total {whose or 'commitments'} of up to", "")
        if "derived" not in cap:
            what = "those commitments" if whose and whose != "commitments" else "the facility"
            cap = f"increase {cap} (a ceiling on {what} after the increase, not the size of the increase)"
        raw_ceil = _ACC_CEILING_RE.search(raw) or _ACC_FACILITY_CEILING_RE.search(raw)
        ev.append(_quote(ctx, cell.block, raw_ceil.group(0)[-90:]) if raw_ceil else None)
    elif up and not _ACC_MIN_CUE_RE.search(text[max(0, up.start("amt") - 45):up.start("amt")]):  # a plain cap
        cap = f"up to {_open_amount(up.group('amt')) or up.group('amt')}"
        if _ACC_PLUS_AFTER_RE.match(text[up.end():up.end() + 120]):  # "up to $300m plus an unlimited amount subject to ...": not the whole cap
            cap += " plus further amounts set out in the term sheet"
        election = _ACC_ELECTION_RE.search(text)
        if election:
            cap += " " + _lower_first(election.group(0).replace("’", "'"))
        tg = _ACC_TOGETHER_RE.search(up.group("gap") or "")
        if tg:
            cap += f", when taken together with {_clip(_strip_end(tg.group('what')), 215)}"
        if ceil and ceil_amt != up.group("amt"):
            cap += f" (total commitments not to exceed {ceil_amt})"
        raw_up = _ACC_UPTO_RE.search(raw) or _ACC_BY_RE.search(raw)
        if raw_up:  # where the cap begins, and the figure itself (a long proviso may separate them)
            ev.append(_quote(ctx, cell.block, raw_up.group(0)[:110]))
            ev.append(_quote(ctx, cell.block, raw_up.group(0)[-70:]))
    if not cap:  # a figure of another document that this term sheet changes: "<what> shall be increased to $X (from $Y)"
        reset = _ACC_RESET_RE.search(text) if _refers(text) else None  # only where the section takes its terms from another document
        if reset and not _ACC_MIN_CUE_RE.search(reset.group("what")):
            what = _LEADING_THE_RE.sub("", _strip_end(reset.group("what")))
            verb = reset.group("verb").lower()
            cap = f"{reset.group('amt')} {what} (" + (f"{verb} from {reset.group('old')}" if reset.group("old") else f"as {verb}") + ")"
            if _NEXT_ITEM_RE.search(text[reset.end():]):  # "(i) ... shall be increased to $X and (ii) ...": not the only change
                cap += "; further changes set out in the term sheet"
            raw_reset = _ACC_RESET_RE.search(raw)
            ev.append(_quote(ctx, cell.block, raw_reset.group(0)[-110:]) if raw_reset else None)
    if not cap and blank:  # the amount is a blank still to be filled in
        cap = "$[ ] - amount left blank in term sheet"
        ev.append(_quote(ctx, cell.block, blank.group(0)))
    if cell.same and cap:
        cap += " (same as existing)"
    return cap, ev


def _accordion_conditions(text: str) -> list[str]:
    """The conditions of an increase, each from its own wording."""
    conds: list[str] = []
    m = _ACC_FREQ_RE.search(text)
    if m:
        conds.append(m.group(0).lower())
    m = _ACC_MIN_RE.search(text)
    if m:
        conds.append(f"minimum {m.group('what').lower()} of {m.group('min')}" + (f" and increments of {m.group('inc')}" if m.group("inc") else ""))
    m = _ACC_REPS_RE.search(text)
    if m:
        excepted = _ACC_REPS_EXCEPT_RE.search(m.group(0))  # "(other than the representations and warranties as to ... and litigation)"
        material = _ACC_REPS_MATERIAL_RE.match(text[m.end():m.end() + 40])
        conds.append("representations and warranties" + (f" (other than as to {_strip_end(excepted.group('what'))})" if excepted else "")
                     + " true and correct" + (" in all material respects" if material else ""))
    m = _ACC_NO_DEFAULT_RE.search(text)
    if m:
        conds.append(_SPLIT_EVENT_RE.sub("event", m.group(0).lower()))
    return conds


def _accordion_lenders(text: str, cap: str) -> str:
    """Whether lenders must take part in an increase, and what new lenders must commit."""
    line = ""
    if _ACC_UNCOMMITTED_RE.search(text) and "uncommitted" not in cap.lower():
        line = "Uncommitted: " + ("existing Lenders have the right but no obligation to commit" if _ACC_RIGHT_BUT_RE.search(text)
                                  else "no existing Lender is required to participate" if _ACC_NO_LENDER_RE.search(text)
                                  else "existing Lenders may agree or decline to participate" if _ACC_DECLINE_RE.search(text)
                                  else "the increase is uncommitted")
    m = _ACC_NEW_LENDER_RE.search(text)
    if m:
        new = f"new lenders must each commit at least {m.group('amt')}"
        line = f"{line}; {new}" if line else _cap(new)
    return line


def _accordion_entry(ctx: Ctx, cell: _Cell) -> tuple[dict | None, bool]:
    """(entry, firm) for one increase section: firm when it gives the amount or says there is none."""
    text = _style(cell.text, defined=False)
    # definitions of financial terms set out inside the section ("“Consolidated EBITDA” shall be calculated ...") are not its terms
    definition = next((m for m in _DEFINITION_RE.finditer(text) if not _ACC_TERM_RE.search(m.group("term"))), None)
    if definition and definition.start() > 200:
        text = text[:definition.start()]
    raw = _norm(cell.block.text)
    short = _strip_bullet(text)
    if _ACC_NONE_RE.match(short) and len(short) <= 60:  # the term sheet says there is none
        q = _quote(ctx, cell.block)
        if q:
            return stated(["No" + (" (same as existing)" if cell.same else "")], [q]), True
    opening = _strip_end((_sents(short) or [short])[0])
    if _ACC_NEGATIVE_RE.search(opening) and not _ACC_EXCEPTION_RE.search(opening) and not _first_amount(opening):
        q = _quote(ctx, cell.block)
        if q:  # "The Facility will not include an incremental or accordion feature": none, in the term sheet's words
            return stated([_clip(f"No ({_lower_first(opening)})" + (" (same as existing)" if cell.same else ""), 300)], [q]), True
    cap, ev = _accordion_cap(ctx, cell, text, raw)
    conds = _accordion_conditions(text)
    lender = _accordion_lenders(text, cap)
    wording = _raw_wording(_ACC_UNCOMMITTED_RE, cell)
    if lender.startswith("Uncommitted") and wording:
        ev.append(_quote(ctx, cell.block, wording[:110]))
    ref = _refers(text)
    ref_line = ""
    if ref and (ref.re is _NAMED_DOC_REF_RE or _EXISTING_DOC_RE.search(ref.group(0))):  # the conditions are those of another document
        ref_line = "Terms and conditions " + _lower_first(_ref_words(text, ref))
        ev.append(_quote(ctx, cell.block, ref.group(0)[:60]))
    if not cap:
        first = _strip_end((_sents(text) or [text])[0])
        q = _quote(ctx, cell.block)
        if not q or len(first) < 12:
            return None, False  # not a readable statement of an increase option
        # the figures the section does mention, so that the line never says the section has no amount when the rules could not read it
        figures: list[str] = []
        for _, money, _ in amounts(text):
            if money not in figures:
                figures.append(money)
        unread = f"amount not read from the section, which mentions {', '.join(figures[:4])}" if figures else ""
        note = "An increase section was found but no amount could be read from it; check the term sheet."
        if ref:  # the section only points to another document, or leaves the terms to be agreed
            line = f"{_title(cell.block.label)}: {_lower_first(_clip(first, 200))} ({unread or 'amount not stated in term sheet'})"
            return by_reference([_clip(line, 330)], [q] + [e for e in ev if e], note), False
        if len(first) < 40 or not (_ACC_TALK_RE.search(first) or _first_amount(first)):
            return None, False
        if _NEGATION_RE.search(first):  # the sentence denies or restricts something: its own words, without a "Yes"
            return stated([_clip(f"{_title(cell.block.label)}: {_lower_first(first)}" + (f" ({unread})" if unread else ""), 300)], [q], note), False
        return stated([_clip(f"Yes ({unread or 'no amount read in the section'}): {_lower_first(first)}", 300)], [q], note), False
    lines = [_clip("Yes = " + cap, 330)]
    if "the ratio tests below" in cap:  # a ratio test that depends on the kind of debt: one limb after the other
        tiers = _pack(_ratio_tiers(text), 385)
        lines += [_clip(("Ratio tests: " if i == 0 else "Ratio tests (continued): ") + t, 400) for i, t in enumerate(tiers[:2])]
    if conds:
        lines.append(_clip("Conditions: " + "; ".join(conds)))
    if lender:
        lines.append(lender)
    if ref_line:
        lines.append(_clip(ref_line))
    quotes = [e for e in ev if e] or [_quote(ctx, cell.block)]
    return stated(lines, [e for e in quotes if e]), True


# ======================================================================================================

# A value in square brackets in a finished line: "[$500m]", "$[750][800]m", "[5] years", "[June 30, 2031]"
_BRACKETED_VALUE_RE = re.compile(r"\[[^\[\]]*\d[^\[\]]*\]")


def _guarded(rule):
    """A rule never raises: a failure is reported in the row's note and the row reads "not stated"."""
    def run(ctx: Ctx) -> dict:
        try:
            entry = rule(ctx)
            lines = [_mend(ctx, line) for line in entry["lines"]]
            if entry["status"] != "not_stated":  # a value the term sheet leaves blank is flagged, not dropped
                lines = ["[ ] - left blank in term sheet" if x.strip() == "[ ]" else
                         x + " ([ ] = left blank in term sheet)" if "[ ]" in x and "blank" not in x else x for x in lines]
                # ... and so is a figure it leaves in square brackets: printed as it stands, and said to be open
                lines = [x + f" ({_BRACKETS_NOTE})" if _BRACKETED_VALUE_RE.search(x) and "square brackets" not in x else x for x in lines]
            entry["lines"] = lines
            return entry
        except Exception as exc:  # noqa: BLE001 - one awkward document must not stop the run
            text = BARCLAYS_NOT_STATED if rule is lender_commitments else NONE_STATED if rule is accordion else None
            note = f"The rule for this row failed ({type(exc).__name__}: {exc})."
            return not_stated(text, note=note) if text else not_stated(note=note)
    run.__name__ = rule.__name__
    run.__doc__ = rule.__doc__
    return run


RULES: dict = {
    "facility": _guarded(facility),
    "borrowers": _guarded(borrowers),
    "lender_commitments": _guarded(lender_commitments),
    "purpose": _guarded(purpose),
    "maturity": _guarded(maturity),
    "repayment": _guarded(repayment),
    "accordion": _guarded(accordion),
}
