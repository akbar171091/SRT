"""Rules for the Other Terms/Conditions and Information Requirements rows.

Fields: events_of_default, conditions_subsequent, mandatory_prepayment, transferability,
info_annual_consolidated, info_annual_obligor, info_quarterly, info_budget.

How the rules work
------------------
Each rule starts from the labelled section that deals with its subject ("Events of Default:",
"Mandatory Prepayments:", "Assignments and Participations:", "Affirmative Covenants:" and their usual
synonyms, in US, LMA and summary-table spelling). The section text is cut into its list items
("(i) ...; (ii) ...", "(1) ...", bullets, semicolons outside brackets, one paragraph per sub-heading, or
the commas of a one-line list), each item is recognised by its wording (cross-default, insolvency,
judgments, asset sales, excess cash flow, financial statements ...) and the line for the row is assembled
from the items that were found, with amounts restyled and extraction noise repaired. A figure is read
from the item it stands in and from nowhere else: a delivery period belongs to the statements named in
the same list item, a threshold to its own event of default.

The list a section is made of is the one that starts first and keeps to one style of marker ("1. ... 2.
...", "(a) ... (b) ...", markers at the start of source lines). Markers that stand inside a bracket, inside
one item of a semicolon list, or after words that already name an event ("failure to pay (i) interest ...
or (ii) fees ...") belong to a list within an item and do not cut the section; a figure repeated in
brackets ("three (3) business days") is not a marker; and an item that runs on over sentences naming other
events is cut back to its own sentence. Where the section speaks of a cross-default or of insolvency
outside the items that could be read, the row says so (with a reviewer note) instead of "not stated".

Three things are read outside the labelled sections, because term sheets put them in unpredictable
places: the change of control clause and its ownership trigger, an obligation to prepay or cash
collateralise when exposure exceeds the commitments (currency fluctuation) or when a collateral coverage
test is failed, and security or other deliverables that a closing condition or a covenant leaves for after
closing. For those the document is read as running text (``_Flow``: the value column with
the label column, page numbers and running headers removed) and whole sentences are matched. A sentence
never runs across the start of a labelled section or of a table row, so a table of one-line rows, which
has no full stops, is read row by row; and what is said of other debt (notes, an indenture) or in a
voting provision is not taken for a term of the facility.

Sections are found with ``blocks.find_blocks`` on a copy of the document in which running headers and
footers are blanked (``_state``; a footer that differs from page to page only by its page number counts as
one), so that a section runs on across a page break and a footer never ends up inside a quote; ``_own`` undoes the label wrapping that block finding applies to tables of one-line
rows, where it would attach the neighbouring rows' values.

Nothing is assumed. A row whose subject is not found is "not stated" in the wording the brief gives for
it; a section that only points elsewhere ("substantially similar to the Existing Credit Agreement",
"consistent with the Documentation Principles", "customary for facilities of this type", "to be agreed")
is "by reference" and says what it points to; a value the term sheet leaves blank ("$[●]", "within [ ]
days") is reported as blank; and every stated or by-reference entry carries quotes cut by ``ctx.quote``,
which returns only text that is on the page. Where the rule has fixed wording for only part of what the
term sheet says (a numbered list of cases in which consent is not needed, a sentence that sweeps two
kinds of proceeds at once, a condition attached to a delivery period), the term sheet's own words are
carried into the line instead of being flattened. On an amendment slide the proposed column is read, and
a cell that says "Same as existing" is read from the existing column and marked as unchanged.

A term is taken from the clause that states it and from no other: the default that lifts the borrower's
consent to an assignment from a sentence that speaks of consent (not from a buy-back or voting provision
of the same section), each minimum assignment amount with the facility its sentence names, the lead-in of
a "Reporting" sub-heading from the covenants section it stands in. The words with which a section points
elsewhere are embedded as the clause that does the pointing, never as a fragment of a long lead-in. A
closed list of covenants shows that there is no budget requirement only if its reporting item is itself
closed ("reporting requirements (including ...)" and "... and other information" are not). A long item is
shortened by its brackets that carry no figure ("(…)") before anything is cut off its end, so that a
threshold or a period at the end of the item survives; a row that has more to say than eight lines keeps
the line that says whether its list is complete.

Extraction noise is dealt with in two ways. Consent terms in the assignments section are detected on the
text with all whitespace removed, so "10business days" and "e vent of default" read the same as their
clean forms; a consent is taken as required only where it is asked for ("without the consent of", "no
consent ... shall be required" and a party that is merely the addressee of a notice do not count). Text
that is shown in a line goes through ``_fix``, which repairs hyphens and brackets that gained a space,
amounts glued to the next word, words split in two ("deliver y", "D ebt") where the whole word occurs
elsewhere in the same document, and a connecting word glued to a defined term ("Companythereafter").
"""
from __future__ import annotations

import contextvars
import functools
import re
import weakref
from collections import Counter

from ..textmodel import Doc, Line, clip, fragments, is_footer, normalise, tidy
from .blocks import Block, find_blocks
from .common import LINE_LIMIT, MONEY_RE, Ctx, by_reference, money_mm, not_stated, points_elsewhere, restyle_money, stated

NS = "not stated in term sheet"
# appended to a row that an amendment slide leaves as it is
_UNCHANGED = " (unchanged from existing terms)"

# Wording for rows the term sheet is silent on (first line as the brief gives it).
_EOD_BLANK = (f"Cross default: {NS}", f"Insolvency / creditors' process: {NS}")
_CS_BLANK = ("None stated in term sheet",)
_MP_BLANK = (f"Change of Control: {NS}", f"Other mandatory prepayment events: {NS}")
_TRANSFER_BLANK = ("Not stated in term sheet",)
_ANNUAL_BLANK = (f"Annual audited consolidated accounts - {NS}",)
_OBLIGOR_BLANK = (f"Annual obligor accounts - {NS}",)
_QUARTERLY_BLANK = (f"Quarterly accounts - {NS}",)
_BUDGET_BLANK = (f"Annual budget - {NS}",)


# ---- entries -----------------------------------------------------------------------------------------

def _blank(*lines: str, note: str = "") -> dict:
    """A not-stated entry with the row's own wording (one or more lines)."""
    entry = not_stated(lines[0] if lines else "Not stated in term sheet", note=note)
    if len(lines) > 1:
        entry["lines"] = [tidy(x) for x in lines if tidy(x)]
    return entry


# How often each word occurs in the document a rule is reading (as printed, and in lower case), for repairing words that
# extraction split or glued together.
_WORDS: contextvars.ContextVar = contextvars.ContextVar("kct_terms_words", default={})
_LOWER_WORDS: contextvars.ContextVar = contextvars.ContextVar("kct_terms_lower_words", default={})


def _safe(blank: tuple):
    """Decorator: a rule that meets input it cannot handle answers "not stated", with the reason in the note."""
    def wrap(rule):
        @functools.wraps(rule)
        def run(ctx: Ctx) -> dict:
            tokens = []
            try:
                state = _state(ctx)
                tokens = [(_WORDS, _WORDS.set(state["words"])), (_LOWER_WORDS, _LOWER_WORDS.set(state["lower"]))]
                return rule(ctx)
            except Exception as exc:  # a rule never raises
                return _blank(*blank, note=f"The rule for this row failed ({type(exc).__name__}: {exc}).")
            finally:
                for var, token in reversed(tokens):
                    var.reset(token)
        return run
    return wrap


def _entry(lines: list[str], evidence: list, referred: bool, blank: tuple, same: bool = False) -> dict:
    """stated / by_reference entry; falls back to the row's not-stated wording if no quote could be verified.

    ``same`` marks a row of an amendment slide whose proposed cell repeats the existing terms.
    """
    evidence = [e for e in evidence if e]
    lines = [x for x in lines if x]
    if same and lines:
        lines[0] += _UNCHANGED
    entry = (by_reference if referred else stated)(lines, evidence)
    return entry if entry.get("status") != "not_stated" else _blank(*blank)


# ---- text clean-up -----------------------------------------------------------------------------------

# "30-   day", "cross -default", "non-     payment": a hyphen that gained a space in extraction (ratings such as "BBB- by" are left alone)
_HYPHEN_GAP_RE = re.compile(r"(?<=[a-z0-9])-\s+(?=[a-z]|Day|Year|Month)|(?<=[a-z0-9])\s+-(?=[a-z]|Day|Year|Month)")
# "providedthat", "providedfurther": italic run-ins that lost their space
_RUN_IN_RE = re.compile(r"\b(provided)(?=(?:that|further|however)\b)", re.IGNORECASE)
# a space before closing punctuation or after an opening bracket ("( i)", "Guarantor )", "date .")
_PUNCT_GAP_RE = re.compile(r"\s+(?=[,;:)”]|\.(?!\d))|(?<=[(“])\s+")
# "75/ 120 days": a slash between figures that gained a space
_SLASH_GAP_RE = re.compile(r"(?<=\d)\s*/\s+(?=\d)")
# "12 month period" -> "12-month period"
_PERIOD_ADJ_RE = re.compile(r"\b(\d{1,3})\s+(day|month|year)\s+(?=period\b)", re.IGNORECASE)
# "$500,000,000individually": an amount glued to the next word (MONEY_RE would read it as "$500,000" and leave ",000individually")
_GLUED_AMOUNT_RE = re.compile(r"((?:US\$|U\.S\.\s?\$|\$|€|£)\s?\d{1,3}(?:\s?,\s?\d{3})+)(?=[A-Za-z])(?!(?:billion|bn|million|mm|mn|m|thousand|k)(?![A-Za-z0-9]))")
# what follows an amount that MONEY_RE cut short: more digit groups, or a digit
_CUT_SHORT_RE = re.compile(r"\s?,\s?\d{3}|\d")
# two neighbouring word pieces, as candidates for a word that extraction split ("e vent", "D ebt", "increm ental", "deliver y")
_SPLIT_WORD_RE = re.compile(r"(?<![\w'’(\-])([A-Za-z]+)\s+(?=([a-z]+)\b)")
# a capitalised term with a connecting word glued to it, as a candidate for a lost space ("Companythereafter", "Companyor", "Lendershall")
_GLUED_WORD_RE = re.compile(r"\b([A-Z][a-z]{3,}?)(thereafter|thereunder|hereunder|within|shall|will|must|under|which|that|with|from|have|and|the|may|has|are|for|or|of|to|in|is|by|on|at|as)\b")
# words that end in one of those connecting words by construction, not by accident of extraction
_COMPOUND_WORDS = frozenset(
    "herein hereof hereto hereby hereunder hereon hereat herewith heretofore therein thereof thereto thereby thereunder thereon thereat therewith therefor "
    "therefore thereafter wherein whereof whereby whereas whereon whereat wherewith whereupon within without into onto upon forthwith notwithstanding "
    "goodwill format standby".split())
# "[ ]", "[●]", "$[___]": a value the term sheet leaves blank
_BLANK_RE = re.compile(r"\[\s*[●•_.\s]*\]")
# (the "Facility"), (each, a "Lender"), (as defined below): defined-term brackets that add nothing to a summary line
_DEFINED_TERM_RE = re.compile(
    r"\s*\((?:the\s+|each,?\s+an?\s+|collectively,?\s+the\s+|together,?\s+the\s+)?[“\"][^”\"]{1,60}[”\"]\)"
    r"|\s*\(\s*(?:as\s+)?(?:hereinafter\s+)?defined\s+(?:below|above|herein)\s*\)", re.IGNORECASE)
# "50 per cent. of the voting shares", "50 percent": the LMA spelling of a percentage (the full stop of "cent." is kept when a
# new sentence follows it)
_PER_CENT_RE = re.compile(r"(?<=\d)\s*per\s?cent\b(?:\.(?=\s+[a-z(\d]|[,;)]))?", re.IGNORECASE)
# a percentage in either spelling
_PCT_RE = re.compile(r"\d\s?%|\d\s*per\s?cent\b", re.IGNORECASE)
# end of a sentence: a full stop after a lower-case word, digit or bracket, before a capital ("U.S. Dollars" is kept whole)
_SENT_RE = re.compile(r"(?<=[a-z0-9\)\]”\"%’'])\.\s+(?=[A-Z(“\"•\[])")
# a bullet glyph that opens a new point (not the dot of a blank such as "[●]")
_BULLET_GLYPH = r"(?<![\[(]\s)(?<![\[(])[•·▪●◼‣](?!\s?[\])])"
# where one point ends and the next begins: the end of a sentence, or a bullet
_UNIT_RE = re.compile(_SENT_RE.pattern + r"|\s*" + _BULLET_GLYPH + r"\s*")
# a bullet at the very start of a passage
_LEAD_BULLET_RE = re.compile(r"^\s*" + _BULLET_GLYPH + r"\s*")
# what a line ends with when its sentence runs on into the next line: a comma, an open bracket or a connecting word
_RUNS_ON_RE = re.compile(r"(?:[,(]|\b(?:and|or|of|the|to|in|a|an|for|with|by|on|at|as|that|which|is|are|be|not|any|its|their|such|each|if))$", re.IGNORECASE)
# what a line ends with when it closes a sentence or a list item
_LINE_STOP_RE = re.compile(r"[.;:]$")
# "; provided that", ", provided, however, that", ", except to the extent": where a proviso or carve-out starts
_PROVISO_RE = re.compile(r"[;,]\s*(?:and\s+)?provided\b|[;,]\s*except\s+(?:that|to\s+the\s+extent)\b|\s+except\s+to\s+the\s+extent\b", re.IGNORECASE)
# an inline sub-heading at the start of a sentence ("Participations:  Lenders will ...")
_INLINE_LABEL_RE = re.compile(r"^[A-Z][A-Za-z /&\-]{2,34}:\s+(?=[A-Z])")
# a long bracket that only lists exclusions or inclusions ("(other than the Company, any subsidiary ...)")
_ASIDE_RE = re.compile(r"\s*\((?:other\s+than|excluding|including|and\s+shall|after\s+giving\s+effect)[^()]{30,}\)", re.IGNORECASE)
# an abbreviation whose final full stop belongs to it
_ABBREVIATION_RE = re.compile(r"\b(?:[A-Z]\.|Inc|Ltd|Corp|Co|etc)\.$")


def _rejoin(m: re.Match) -> str:
    """Close the gap inside a word that extraction split, judged by the words the document itself uses.

    The two pieces are joined when the joined word occurs elsewhere in the document and the first piece is not a
    word there ("e vent", "D ebt", "increm ental"), or the second is a stray final letter ("deliver y").
    """
    words = _WORDS.get()
    first, second = m.group(1), m.group(2)
    if len(first + second) < 4 or not words.get(first + second):
        return m.group(0)
    is_word = first in "aAI" if len(first) == 1 else words.get(first, 0) >= 2
    stray_letter = len(second) == 1 and second not in "ai"
    return first if (not is_word or stray_letter) else m.group(0)


def _unglue(m: re.Match) -> str:
    """Put back the space between a defined term and the word that extraction glued to it ("Companythereafter").

    Only where the first part is a capitalised word the document uses often (and far more often than the glued form), and the
    second is one of a few connecting words; "-or" after a consonant is left alone (Creditor, Auditor, Lessor).
    """
    words, lower = _WORDS.get(), _LOWER_WORDS.get()
    whole, first, second = m.group(0), m.group(1), m.group(2)
    if whole.lower() in _COMPOUND_WORDS or words.get(first, 0) < max(5, 8 * lower.get(whole.lower(), 0)):
        return whole
    if second == "or" and first[-1] not in "aeiouy":
        return whole
    return f"{first} {second}"


def _fix(text: str) -> str:
    """Collapse whitespace and repair the usual extraction noise."""
    text = _HYPHEN_GAP_RE.sub("-", tidy(text or ""))
    text = _GLUED_AMOUNT_RE.sub(r"\1 ", _RUN_IN_RE.sub(r"\1 ", text))
    if _WORDS.get():
        text = _GLUED_WORD_RE.sub(_unglue, _SPLIT_WORD_RE.sub(_rejoin, text))
    text = _PERIOD_ADJ_RE.sub(r"\1-\2 ", _SLASH_GAP_RE.sub("/", text))
    return _PER_CENT_RE.sub("%", _PUNCT_GAP_RE.sub("", text))


def _restyle(text: str) -> str:
    """House-style amounts ("$5,000,000" -> "$5m"); a small amount that is not a round figure keeps its digits ("$3,500")."""
    def sub(m: re.Match) -> str:
        mm = money_mm(m)
        if not mm or mm <= 0 or _CUT_SHORT_RE.match(m.string, m.end()):
            return m.group(0)  # not an amount, or only the front of one: left as printed
        gap = " " if m.group(0)[-1:].isspace() else ""  # MONEY_RE takes the space after a bare amount with it
        if mm < 1 and (abs(mm * 1000 - round(mm * 1000)) > 1e-9 or (not m.group("unit") and round(mm * 1000) < 100)):
            return re.sub(r"\s+", "", m.group(0)) + gap  # "$3,500", "$25,000": small fees read better in full
        return restyle_money(m.group(0).strip()) + gap
    return MONEY_RE.sub(sub, text)


def _elide(text: str, limit: int) -> str:
    """``text`` with its longest brackets that carry no figure replaced by "(…)", one at a time, until it is at most ``limit``
    long (or there is none left): what a long item says after such a bracket (its threshold, its period) is worth more than the
    bracket, and the mark shows that something was left out."""
    while len(text) > limit:
        spans, opened = [], []
        for i, ch in enumerate(text):
            if ch == "(":
                opened.append(i)
            elif ch == ")" and opened:
                start = opened.pop()
                if not opened:
                    spans.append((start, i + 1))
        spans = [(a, b) for a, b in spans if b - a >= 30 and not _has_figure(text[a:b]) and not _BLANK_RE.search(text[a:b])]
        if not spans:
            break
        a, b = max(spans, key=lambda sp: sp[1] - sp[0])
        text = text[:a] + "(…)" + text[b:]
    return text


def _squeeze(text: str, limit: int = LINE_LIMIT, elide: bool = False) -> str:
    """A passage as a line: noise repaired, amounts in house style, defined-term brackets dropped, cut at a word.

    With ``elide``, a passage that is too long first loses its long brackets that carry no figure ("(…)").
    """
    text = _DEFINED_TERM_RE.sub("", _restyle(_fix(text)))
    text = _PUNCT_GAP_RE.sub("", text).strip(" ;,")
    if text.endswith(".") and not _ABBREVIATION_RE.search(text):
        text = text[:-1]
    if text.endswith(")") and text.count(")") > text.count("("):
        text = text[:-1].rstrip(" ;,")  # the bracket that closed a list this item was the last of
    if text.endswith("("):
        text = text[:-1].rstrip(" ;,")
    if len(text) <= limit:
        return text
    if elide:
        text = _elide(text, limit)
        if len(text) <= limit:
            return text
    return clip(text, max(20, limit - 2)).rstrip(" ,;:(") + " …"


def _sq(text: str) -> str:
    """Lower-case text with all whitespace removed and quote / dash styles unified, for noise-proof matching."""
    return re.sub(r"\s+", "", normalise(text or "")).lower()


def _lower_first(text: str) -> str:
    """Lower-case the first letter of a clause that is about to be embedded in a line (acronyms are left alone)."""
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _sentences(text: str) -> list[tuple[int, int]]:
    """Spans of the points of ``text``: its sentences, and the bullets of a bulleted cell."""
    spans, start = [], 0
    for m in _UNIT_RE.finditer(text):
        spans.append((start, m.start() + 1 if m.group(0).startswith(".") else m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _line_spans(block, text: str) -> list[tuple[int, int]]:
    """Spans of the lines of a table cell that sets out its points one per line, without bullets or punctuation ("Non-payment
    (3 days grace)" / "Cross default (EUR 10m)" / "Insolvency"); [] if the cell reads as running text.

    Running text wraps at the right-hand edge and mostly carries on in lower case; a list has lines of uneven length that
    all start with a capital or a figure and none of which ends in a comma or a connecting word.
    """
    return _listed_lines(block, text, lead=False)[1]


def _listed_lines(block, text: str, lead: bool = True) -> tuple[int, list[tuple[int, int]]]:
    """(end of the lead-in, spans of the lines) of a cell that sets out its points one per line; (0, []) if it reads as running text.

    With ``lead``, the list may stand under a line or two that open it and end in a colon ("Customary for facilities of this
    type, including:" / "Non-payment (3 days grace)" / "Cross default (EUR 10m)" / ...): those lines are the lead-in.
    """
    if block is None:
        return 0, []
    parts = [tidy(p) for p in block.parts if tidy(p)]
    if len(parts) < 3 or " ".join(parts) != text:
        return 0, []
    skip = 0
    if lead and not _lines_listed(parts):
        skip = next((i + 1 for i, p in enumerate(parts[:2]) if p.endswith(":")), 0)
        if not skip or len(parts) - skip < 3:
            return 0, []
    if not _lines_listed(parts[skip:]):
        return 0, []
    spans, pos = [], 0
    for p in parts:
        spans.append((pos, pos + len(p)))
        pos += len(p) + 1
    return (spans[skip][0] if skip else 0), spans[skip:]


def _lines_listed(parts: list[str]) -> bool:
    """The lines read as a list of points, one per line, not as running text that wraps."""
    if len(parts) < 3 or any(not (p[0].isupper() or p[0].isdigit() or p[0] in "$€£<>≤≥") or _RUNS_ON_RE.search(p) for p in parts):
        return False
    return not (any(_LINE_STOP_RE.search(p) for p in parts[:-1]) or min(len(p) for p in parts[:-1]) >= 0.75 * max(len(p) for p in parts))


def _points(text: str, block=None) -> list[tuple[int, int]]:
    """Spans of the points of a passage: the lines of a cell that lists one point per line, otherwise its sentences and bullets."""
    lead_end, lines = _listed_lines(block, text)
    if lines:
        return ([(0, lead_end - 1)] if lead_end > 1 else []) + lines
    return _sentences(text)


def _first_sentence(text: str) -> str:
    """The first sentence (or first bullet) of ``text``, without its full stop."""
    lead = _LEAD_BULLET_RE.match(text)
    start = lead.end() if lead else 0
    m = _UNIT_RE.search(text, start)
    return text[start:m.start()] if m else text[start:]


def _in_number(text: str, i: int) -> bool:
    """The comma at ``text[i]`` is a thousands separator ("20,000,000", "$5 ,000,000")."""
    return bool(re.search(r"\d\s?$", text[max(0, i - 2):i]) and re.match(r"\s?\d{3}(?!\d)", text[i + 1:i + 6]))


def _depth_at(text: str, pos: int) -> int:
    """Bracket depth of ``text`` at offset ``pos``."""
    depth = 0
    for ch in text[:pos]:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
    return depth


def _main_clause(text: str) -> str:
    """The sentence up to its first proviso or carve-out."""
    for m in _PROVISO_RE.finditer(text):
        if m.start() >= 25 and _depth_at(text, m.start()) == 0:
            return text[:m.start()]
    return text


def _depth0(text: str, chars: str, start: int = 0) -> list[int]:
    """Offsets (from ``start``) of the characters in ``chars`` that sit outside every bracket."""
    out, depth, opened = [], 0, 0
    for i in range(max(0, start), len(text)):
        ch = text[i]
        if ch in "([":
            depth += 1
            opened = i
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth and i - opened > 500:
            depth = 0  # a bracket that never closes (lost in extraction) must not swallow the rest
        if depth == 0 and ch in chars and not (ch == "," and _in_number(text, i)):
            out.append(i)
    return out


def _pack(prefix: str, pieces: list[str], limit: int = LINE_LIMIT + 20, max_lines: int = 2, fit: bool = False, elide: bool = False) -> list[str]:
    """Join pieces with semicolons under a prefix, starting a second line (same prefix) rather than cutting one off.

    With ``fit``, a piece goes on the first line that has room for it, so that a long piece in the middle does not push a
    short one off the end; with ``elide``, a line that is still too long loses its brackets without figures before its end.
    """
    pieces = [p for p in pieces if p]
    if fit:
        rows: list[str] = []
        for piece in pieces:
            at = next((i for i, row in enumerate(rows) if len(prefix) + len(row) + 2 + len(piece) <= limit), None)
            if at is not None:
                rows[at] += "; " + piece
            elif len(rows) < max_lines:
                rows.append(piece)
            else:
                rows[-1] += "; " + piece
        return [_squeeze(prefix + row, limit, elide) for row in rows]
    lines, current = [], ""
    for piece in pieces:
        joined = f"{current}; {piece}" if current else piece
        if current and len(prefix) + len(joined) > limit and len(lines) < max_lines - 1:
            lines.append(prefix + current)
            current = piece
        else:
            current = joined
    if current:
        lines.append(prefix + current)
    return [_squeeze(x, limit, elide) for x in lines]


# ---- numbers -----------------------------------------------------------------------------------------

# counts written out in words, as term sheets write periods ("thirty (30) days", "within five business days")
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty-five": 45, "forty five": 45,
                 "sixty": 60, "ninety": 90, "one hundred twenty": 120, "one hundred and twenty": 120, "one hundred eighty": 180}
# the one-word counts, as a regex alternation
_SIMPLE_NUMBER_WORDS = "|".join(w for w in _NUMBER_WORDS if " " not in w)


def _num(tag: str = "") -> str:
    """Regex for a count as term sheets write it: "45", "forty-five (45)", "ten". Groups n<tag> / p<tag> / w<tag>."""
    words = "|".join(sorted((re.escape(w).replace(r"\ ", r"\s+") for w in _NUMBER_WORDS), key=len, reverse=True))
    return rf"(?:(?P<n{tag}>\d{{1,3}})|(?:[A-Za-z]+[\s-]+){{0,3}}[A-Za-z]+\s*\(\s*(?P<p{tag}>\d{{1,3}})\s*\)|(?P<w{tag}>{words}))"


def _num_value(m: re.Match, tag: str = "") -> int | None:
    """The count matched by ``_num(tag)``."""
    try:
        for name in (f"n{tag}", f"p{tag}"):
            if m.group(name):
                return int(m.group(name))
        word = m.group(f"w{tag}")
    except (IndexError, ValueError):
        return None
    return _NUMBER_WORDS.get(re.sub(r"\s+", " ", word.lower())) if word else None


def _unit(text: str, n: int | None) -> str:
    """"business days" / "days" / "months", in the plural that fits ``n``."""
    unit = re.sub(r"\s+", " ", (text or "days").lower()).rstrip("s")
    return unit if n == 1 else unit + "s"


# an amount, a percentage or a period: the figures a row is read for
_FIGURE_RE = re.compile(r"\d\s?%|\d\s*per\s?cent\b|\b\d{1,3}[\s-]*(?:business\s+)?(?:day|month)|\b(?:" + _SIMPLE_NUMBER_WORDS + r")\s+(?:\(\d+\)\s*)?(?:business\s+)?(?:day|month)",
                        re.IGNORECASE)


def _has_figure(text: str) -> bool:
    return bool(MONEY_RE.search(text) or _FIGURE_RE.search(text))


# ---- lists -------------------------------------------------------------------------------------------

# "(i)", "(iv)", "(a)", "(12)" at the start of a list item (not "Section 6.05(a)")
_ENUM_RE = re.compile(r"(?<![\w)])\(\s?(\d{1,2}|[ivxl]{1,5}|[a-z])\s?\)\s*")
# "1. ", "2. " in front of a list item: a number and a full stop at the very start, or after the punctuation that ends the lead-in
# or the item before it ("... limited to: 1. Liens. 2. Mergers."), with a capital, a quote or a bracket after it (not "Section 2. of")
_DOT_ENUM_RE = re.compile(r"(?:^\s*|(?<=[.:;)”\"]\s))(\d{1,2})\.\s+(?=[A-Z“\"(\[‘'])")
# a number written out in front of its figure in brackets: "three (3)", "sixty (60)", "forty-five (45)"
_NUMBER_BEFORE_RE = re.compile(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
                               r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)(?:[\s-]+(?:one|two|three|four|five|six|seven|eight|nine))?\s*$", re.IGNORECASE)
# "1. ", "2) ", "a. ", "b) ", "ii. " at the start of a source line
_LINE_ENUM_RE = re.compile(r"(\d{1,2}|[ivxl]{1,5}|[a-z])[.)]\s+(?=\S)", re.IGNORECASE)
# a bullet glyph (not the dot of a blank such as "[●]"), with the space around it
_BULLET_RE = re.compile(r"\s*" + _BULLET_GLYPH + r"\s*")
# a lead-in of a few words that does nothing but open a list ("To include:", "Limited to the following:")
_SHORT_OPENER_RE = re.compile(r"^\W*(?:to\s+include|including|includes?|limited\s+to|comprising|consisting\s+of|as\s+follows|(?:only\s+)?the\s+following)"
                              r"(?:\s+(?:only\s+)?the\s+following)?\W*$", re.IGNORECASE)
# "Customary for facilities of this type, including non-payment, ...": the words before a list that has no colon
_INLINE_OPENER_RE = re.compile(r"^[^;:]{0,170}?(?:,\s*|\s+)(?:including|to\s+include|limited\s+to|comprising|consisting\s+of)(?:,?\s*(?:but\s+not\s+limited\s+to|without\s+limitation))?"
                               r",?\s+(?:the\s+following\s+)?", re.IGNORECASE)
# the three ways list items are numbered: (i) (ii) (iii) ..., (a) (b) (c) ..., (1) (2) (3) ...
_SEQUENCES = (
    ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx",
     "xxi", "xxii", "xxiii", "xxiv", "xxv", "xxvi", "xxvii", "xxviii", "xxix", "xxx"],
    list("abcdefghijklmnopqrstuvwxyz"),
    [str(i) for i in range(1, 60)],
)


def _line_starts(block, text: str) -> frozenset:
    """Offsets of ``text`` at which a source line of ``block`` begins (empty if ``text`` is not the block's text as joined)."""
    if block is None:
        return frozenset()
    parts = [tidy(p) for p in block.parts if tidy(p)]
    if " ".join(parts) != text:
        return frozenset()
    starts, pos = [], 0
    for p in parts:
        starts.append(pos)
        pos += len(p) + 1
    return frozenset(starts)


def _markers(text: str, line_starts: frozenset = frozenset()) -> list[tuple[int, int, str, str]]:
    """Everything that may be a list marker, in text order: (start, end, token, style).

    "(i)" / "(a)" / "(1)" anywhere (style "()"); "1." after the punctuation that ends the lead-in or the item before it, and
    "1." / "a." / "ii." at the start of a source line (style "."); "1)" / "a)" at the start of a source line (style ")").
    A figure repeated in brackets after its word ("three (3) business days", "sixty (60) days") is not a marker.
    """
    found = {}
    for m in _ENUM_RE.finditer(text):
        if m.group(1).isdigit() and _NUMBER_BEFORE_RE.search(text, max(0, m.start() - 24), m.start()):
            continue
        found[m.start()] = (m.start(), m.end(), m.group(1).lower(), "()")
    for m in _DOT_ENUM_RE.finditer(text):
        found.setdefault(m.start(1), (m.start(1), m.end(), m.group(1), "."))
    for at in line_starts:
        m = _LINE_ENUM_RE.match(text, at)
        if m:
            found.setdefault(at, (at, m.end(), m.group(1).lower(), m.group(0).strip()[-1]))
    return [found[k] for k in sorted(found)]


def _enumerators(text: str, line_starts: frozenset = frozenset()) -> list[tuple[int, int]]:
    """Spans of the markers of the outermost "(i) ... (ii) ..." / "(a) ... (b) ..." / "(1) ... (2) ..." / "1. ... 2. ..." list in
    ``text``: of the lists that are found, the one that starts first. A list keeps to one style of marker: "(3)" does not
    carry on from "1." and "2."."""
    found = []
    candidates = _markers(text, line_starts)
    for style in ("()", ".", ")"):
        for seq in _SEQUENCES:
            marks, want = [], 0
            for start, end, token, kind in candidates:
                if kind == style and want < len(seq) and token == seq[want]:
                    marks.append((start, end))
                    want += 1
            if len(marks) >= 2:
                found.append(marks)
    return min(found, key=lambda marks: marks[0][0]) if found else []


# "and " / "or " in front of the last item of a list
_LEADING_AND_RE = re.compile(r"(?:and|or)\s+", re.IGNORECASE)
# "; and" / ", or" left at the end of the item before it
_TRAILING_AND_RE = re.compile(r"(?:[;,]\s*|\s)(?:and|or)$", re.IGNORECASE)
# the "and" that closes a list written as one sentence ("cross-default and cross-acceleration" is one event, not two)
_CLOSING_AND_RE = re.compile(r"\sand\s(?!cross)")


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    """Shrink a span past list punctuation and a leading / trailing "and"."""
    while s < e and text[s] in " ;,.:":
        s += 1
    m = _LEADING_AND_RE.match(text[s:e])
    if m:
        s += m.end()
    while True:
        while e > s and text[e - 1] in " ;,.":
            e -= 1
        m = _TRAILING_AND_RE.search(text[s:e])
        if not m:
            return s, e
        e = s + m.start()


def _lead_colon(text: str) -> int:
    """End of a lead-in such as "... will include only the following events of default:" or "To include:" (0 if there is none).

    The colon must sit in the first sentence and follow a clause of some length or a bare list opener, so that the
    sub-heading of a paragraph ("Illegality: a Lender may ...") is not taken for a lead-in.
    """
    for p in _depth0(text[:450], ":"):
        before = text[:p].rstrip()
        if _SENT_RE.search(before):
            break
        if not before or text[p + 1:p + 2] not in (" ", ""):
            continue
        if _SHORT_OPENER_RE.match(before) or ((before[-1].isalpha() or before[-1] == ")") and len(before.split()) >= 4):
            return p + 1
    return 0


def _sub_list(text: str, marks: list[tuple[int, int]]) -> bool:
    """The numbered list found in ``text`` is a list inside one of its items, not the list the passage is made of.

    That is so where the markers stand inside a bracket and the passage has items of its own outside it ("... unqualified (other
    than (i) ... or (ii) ...); annual budgets; quarterly ..."), or where they all stand in one item of a list cut by semicolons
    ("non-payment; cross-default to (i) debt ... or (ii) hedging ...; insolvency").
    """
    first, last = marks[0][0], marks[-1][0]
    semis = _depth0(text, ";")
    if _depth_at(text, first) > 0:
        return bool(semis) or len(list(_BULLET_RE.finditer(text))) >= 2
    before = [p for p in semis if p < first]
    if not before or any(first < p < last for p in semis):
        return False
    opener = text[before[-1] + 1:first].strip()  # the words between the semicolon and the first marker
    return bool(opener) and not opener.endswith(":") and not _SHORT_OPENER_RE.match(opener) and not _LIST_OPENER_RE.fullmatch(opener)


def _items(text: str, block=None) -> tuple[int, list[tuple[int, int]]]:
    """Cut a list-like passage into its lead-in and items: (end of lead-in, spans of the items).

    ``block`` is the section the passage is the text of, if it is: its line starts help to find list markers.
    """
    marks = _enumerators(text, _line_starts(block, text))
    if marks and _sub_list(text, marks):
        marks = []
    if marks:
        lead_end = marks[0][0]
        spans = [(marks[i][1], marks[i + 1][0] if i + 1 < len(marks) else len(text)) for i in range(len(marks))]
    else:
        bullets = list(_BULLET_RE.finditer(text))
        if len(bullets) >= 2:
            lead_end = bullets[0].start()
            spans = [(bullets[i].end(), bullets[i + 1].start() if i + 1 < len(bullets) else len(text)) for i in range(len(bullets))]
        else:
            # a single bullet in front of the passage is decoration: the passage is read as running text after it
            base = bullets[0].end() if bullets and not text[:bullets[0].start()].strip() else 0
            body = text[base:]
            semis = _depth0(body, ";")
            lead_end = _lead_colon(body)
            if semis and lead_end > semis[0]:
                lead_end = 0
            if not lead_end:
                m = _INLINE_OPENER_RE.match(body)
                if m and _depth_at(body, m.end()) == 0 and _defers(m.group(0)):  # "Customary for ..., including non-payment, ..."
                    lead_end = m.end()
                elif _LEADING_OPENER_RE.match(body) and _LEADING_OPENER_RE.match(body).end() < len(body):  # "Including, without limitation, non-payment ...; ..."
                    lead_end = _LEADING_OPENER_RE.match(body).end()
            cuts = [lead_end] + [p + 1 for p in semis if p >= lead_end] + [len(body)]
            spans = [(base + cuts[i], base + cuts[i + 1]) for i in range(len(cuts) - 1)]
            lead_end += base if lead_end else 0
    spans = [_trim(text, s, e) for s, e in spans]
    return lead_end, [(s, e) for s, e in spans if e - s >= 3]


def _comma_items(text: str, s: int, e: int, ands: bool = False) -> list[tuple[int, int]]:
    """Cut one item at the commas outside brackets and, if asked, at the "and" that closes the list
    ("non-payment, cross default (EUR 10m), insolvency and material adverse change").

    Only the last "and" of the last comma item is a cut: "representations and warranties" in the middle of a list stays
    whole, and so does "cross-default and cross-acceleration".
    """
    cuts = {p + 1 for p in _depth0(text[:e], ",", s)}
    if ands:
        tail = max(cuts) if cuts else s
        closing = [m for m in _CLOSING_AND_RE.finditer(text[tail:e]) if _depth_at(text[tail:e], m.start()) == 0]
        if closing:
            cuts.add(tail + closing[-1].start() + 1)
    edges = [s] + sorted(cuts) + [e]
    spans = [_trim(text, edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    return [(a, b) for a, b in spans if b - a >= 3]


# ---- pointing elsewhere ------------------------------------------------------------------------------

# "similar to (and no less favorable to the Company than) the Existing 5-Year Agreement", "the Documentation Principles":
# wider than common.BY_REFERENCE_RE, which needs "similar to" and "the Existing ..." to be adjacent
_SIMILAR_RE = re.compile(
    r"(?:similar|consistent|the\s+same|identical)\s+(?:to|with|as)\b[^.;:]{0,90}?\b(?:Existing|Prior|Current|Precedent)\s+[\w\- ]{0,40}?"
    r"(?:Agreements?|Facilit(?:y|ies)|Documentation|Indenture)|Documentation\s+Principles?|Precedent\s+(?:Documentation|Agreement)", re.IGNORECASE)
# other ways of pointing elsewhere that summaries and LMA-style term sheets use: "Customary", "customary for a facility of this
# nature", "as per the existing facility agreement", "in line with existing RCF", "LMA standard", "TBD", "to be discussed"
_ELSEWHERE_RE = re.compile(
    r"\bcustomar(?:y|ily)\b|\b(?:usual|standard|typical)\s+for\s+(?:an?\s+)?(?:facilit|transaction|financing|credit|loan|deal)|\bmarket\s+(?:standard|practice)\b|\bLMA\b|"
    r"\bTB[DCA]\b|to\s+be\s+(?:mutually\s+)?(?:agreed|determined|confirmed|discussed|negotiated|specified)|"
    # ... a pointer to an existing document: the word "existing" must be followed by the document, or stand at the end ("Same as existing")
    r"\b(?:as\s+per|in\s+line\s+with|per|based\s+on|consistent\s+with|same\s+as|similar\s+to|in\s+accordance\s+with|as\s+in|as\s+under|unchanged\s+from|subject\s+to|"
    r"governed\s+by|pursuant\s+to|as\s+(?:set\s+(?:out|forth)|provided)\s+in|see)\s+(?:(?:section|article|clause|schedule|paragraph)\s+[\w.()]{1,12}\s+of\s+)?"
    r"(?:the\s+|its\s+|their\s+)?(?:existing|current|prior|precedent)\b"
    r"(?:\s*$|\s*[.;,)]|\s+[\w\- ]{0,40}?\b(?:agreements?|facilit(?:y|ies)|documentation|documents?|indentures?|terms|RCF|loans?))", re.IGNORECASE)
# "(as defined in the Existing Credit Agreement)": a single term that is defined elsewhere
_AS_DEFINED_RE = re.compile(r"as\s+(?:provided|set\s+forth|defined)\s+in\s+the\s+(?:Existing|Prior|Current)\s", re.IGNORECASE)
# "limited to", "only the following": the list that follows is closed ("including, but not limited to" is not)
_CLOSED_RE = re.compile(r"(?<!not )(?<!not be )limited\s+to|only\s+the\s+following|consist(?:s|ing)?\s+(?:solely\s+|only\s+)?of", re.IGNORECASE)
# the words that open a list at the end of a lead-in: "... and limited to the following:", "..., including, without limitation:", "... the following:"
_LIST_OPENER_RE = re.compile(
    r"[,;]?\s*(?:and\s+|but\s+)?(?:(?:shall\s+|will\s+|to\s+)?(?:be\s+)?limited\s+to|(?:and\s+)?(?:to\s+|will\s+|shall\s+)?includ(?:e|es|ing)"
    r"(?:,?\s*(?:but\s+not\s+limited\s+to|without\s+limitation))?|consisting\s+of|comprising)?(?:,?\s*(?:only\s+)?the\s+following)?[\s:,]*$", re.IGNORECASE)
# the same words at the start of a lead-in ("Limited to the following (subject to ...)")
_LEADING_OPENER_RE = re.compile(r"^(?:limited\s+to|including|to\s+include|consisting\s+of)(?:,?\s*(?:but\s+not\s+limited\s+to|without\s+limitation))?(?:,?\s+the\s+following)?"
                                r"[\s,:]*", re.IGNORECASE)


def _defers(text: str) -> bool:
    """The passage points to another document, to custom or to later agreement for its terms."""
    return bool(text) and bool(points_elsewhere(text) or _SIMILAR_RE.search(text) or _ELSEWHERE_RE.search(text))


# what may follow the words that point elsewhere and still belongs to them: "(customary) for facilities of this type", "in transactions of this nature"
_POINTER_TAIL_RE = re.compile(r"\s+(?:in|for)\s+(?:an?\s+)?(?:facilit(?:y|ies)|transactions?|financings?|credit\s+facilit(?:y|ies)|loans?)\s+of\s+this\s+(?:type|nature|kind|size)\b", re.IGNORECASE)


def _defer_match(text: str) -> re.Match | None:
    """The first words with which ``text`` points to another document, to custom or to later agreement."""
    hits = [m for m in (points_elsewhere(text), _SIMILAR_RE.search(text), _ELSEWHERE_RE.search(text)) if m]
    return min(hits, key=lambda m: m.start()) if hits else None


def _clause_around(text: str, start: int, end: int, limit: int) -> str:
    """The clause of ``text`` that holds text[start:end], at most ``limit`` long: the bracket it stands in, or the stretch between
    the commas around it."""
    lo, hi, opened = 0, len(text), []
    for i, ch in enumerate(text[:start]):
        if ch in "([":
            opened.append(i)
        elif ch in ")]" and opened:
            opened.pop()
    if opened:  # inside a bracket: the clause is (part of) what the bracket says
        lo, depth = opened[-1] + 1, 0
        for i in range(lo, len(text)):
            if text[i] in "([":
                depth += 1
            elif text[i] in ")]":
                if depth == 0:
                    hi = i
                    break
                depth -= 1
    inner = text[lo:hi]
    commas = _depth0(inner, ",;")
    a = 0
    if end - lo > limit:
        a = min((c + 1 for c in commas if c < start - lo and end - lo - (c + 1) <= limit), default=max(0, start - lo))
    b = len(inner)
    if b - a > limit:
        b = max((c for c in commas if end - lo <= c and c - a <= limit), default=min(len(inner), max(end - lo, a + limit)))
    return inner[a:b].strip(" ,;")


def _ref_clause(lead: str, limit: int = 150) -> str:
    """The words with which a section points elsewhere, short enough to embed: its lead-in without the list opener.

    A lead-in that is too long is cut to the clause that does the pointing ("... (subject to exceptions to be agreed in the
    Facilities Documentation)"), so that what is embedded always says where the section points.
    """
    text = _fix(_first_sentence(lead)).rstrip(" :")
    colon = _lead_colon(text)
    if colon:  # what follows the colon is the list, or what is left of it
        text = text[:colon - 1]
    text = _LIST_OPENER_RE.sub("", text.rstrip(" (")).rstrip(" ,;:(")
    text = _LEADING_OPENER_RE.sub("", text)
    if text.startswith("(") and text.endswith(")") and text.count("(") == 1:
        text = text[1:-1]
    if len(text) > limit:
        ends = [m.end() for m in _SIMILAR_RE.finditer(text) if 15 <= m.end() <= limit and _depth_at(text, m.end()) == 0]
        m = points_elsewhere(text)
        if m and 15 <= m.end() <= limit:
            ends.append(m.end())
        pointer = _defer_match(text)
        if ends:
            cut = max(ends)
            tail = _POINTER_TAIL_RE.match(text, cut)  # "... customary | in transactions of this type"
            text = text[:tail.end() if tail and tail.end() <= limit else cut]
        elif pointer:
            text = _clause_around(text, pointer.start(), pointer.end(), limit)
        else:
            text = clip(text, limit - 2).rstrip(" ,;:(") + " …"
    return _squeeze(text, limit)


# ---- sections and quotes -----------------------------------------------------------------------------

# per-document working state (see _state); an entry lives as long as its Ctx
_STATE: "weakref.WeakKeyDictionary[Ctx, dict]" = weakref.WeakKeyDictionary()
# how many lines at the top and at the bottom of a page are looked at for running headers and footers
_EDGE_LINES = 4


def _numberless(text: str) -> str:
    """A line with its figures masked, for recognising a running footer that carries the page number ("Confidential  5  Bank
    Securities, Inc."); "" for a line without words, which is left to the page-number test."""
    text = tidy(text)
    return re.sub(r"\d+", "#", text) if re.search(r"\d", text) and len(re.findall(r"[A-Za-z]", text)) >= 4 else ""


def _edge_lines(doc: Doc) -> dict[int, list[Line]]:
    """The first and last few non-blank lines of each page, where running headers and footers stand."""
    by_page: dict[int, list[Line]] = {}
    for ln in doc.lines:
        if not ln.blank:
            by_page.setdefault(ln.page, []).append(ln)
    return {page: lines[:_EDGE_LINES] + lines[-_EDGE_LINES:] for page, lines in by_page.items()}


def _furniture(doc: Doc) -> set[str]:
    """Running headers and footers: short lines that recur, among the first or last few lines of the page, on at least half of
    the pages (a value that merely repeats down a table, such as "Same as existing", is not page furniture). A footer that
    differs from page to page only by its page number recurs too: it is entered with its figures masked."""
    n_pages = len(doc.pages)
    if n_pages < 3:
        return set()
    pages_of: dict[str, set[int]] = {}
    for page, lines in _edge_lines(doc).items():
        for ln in lines:
            text = tidy(ln.text)
            if len(text) <= 80:
                pages_of.setdefault(text, set()).add(page)
                if _numberless(text):
                    pages_of.setdefault(_numberless(text), set()).add(page)
    need = max(3, (n_pages + 1) // 2)
    return {text for text, pages in pages_of.items() if len(pages) >= need}


def _without(doc: Doc, furniture: set[str]) -> Doc:
    """A copy of ``doc`` with running headers and footers blanked (line numbers unchanged). A line is matched as printed
    anywhere on its page, and with its figures masked only at the top or bottom of the page."""
    if not furniture:
        return doc
    edge = {ln.n for lines in _edge_lines(doc).values() for ln in lines}
    clean = Doc(doc.pages)
    clean.lines = [Line(page=ln.page, n=ln.n, qstart=ln.qstart,
                        text="" if tidy(ln.text) in furniture or (ln.n in edge and _numberless(ln.text) in furniture) else ln.text) for ln in doc.lines]
    return clean


def _state(ctx: Ctx) -> dict:
    """Per-document working state: the views without page furniture, and what has been found in them so far."""
    state = _STATE.get(ctx)
    if state is None:
        furniture = _furniture(ctx.raw)
        words = Counter(re.findall(r"[A-Za-z]+", ctx.text))
        lower: Counter = Counter()
        for word, n in words.items():
            lower[word.lower()] += n
        state = _STATE[ctx] = {"doc": _without(ctx.doc, furniture), "existing": _without(ctx.existing, furniture), "blocks": {},
                               "words": words, "lower": lower}
    return state


@functools.lru_cache(maxsize=256)
def _label_re(pattern: str) -> re.Pattern:
    """A label at the start of a line, as blocks.find_blocks reads it."""
    return re.compile(r"^\s*(?:[•·▪●\-–]\s*|\(?[a-zA-Z0-9]{1,3}[.)]\s+)?(?P<label>" + pattern + r")(?P<term>\s*:|\s+[-–]\s|\s{2,}|\s*$)", re.IGNORECASE)


def _own(block: Block, pattern: str) -> Block:
    """The block cut back to its own row.

    A label without a colon may wrap, so block finding joins up to two label-column lines above and below it.
    In a table of one-line rows ("Accordion  $100mm" / "Anti cash hoarding  $250mm") that attaches the neighbouring
    rows. Lines are kept only while the joined label still reads as the label that was asked for; a label that wraps
    on into different words ends in a colon there, and is returned empty (it is some other section).
    """
    if block.mode != "column" or len(block.lines) < 2:
        return block
    rx = _label_re(pattern)
    k = next((i for i, ln in enumerate(block.lines[:3]) if rx.match(ln.text)), None)
    if k is None:
        return block
    m = rx.match(block.lines[k].text)
    if m.group("term").strip().startswith(":"):
        return block
    indent = block.lines[k].indent

    def cell(ln) -> str:
        cells = fragments(ln.text, 3)
        return cells[0][2] if cells else ""

    def reads(label: str) -> bool:
        return bool(re.fullmatch(pattern, tidy(label).rstrip(": "), re.IGNORECASE))

    label = tidy(m.group("label"))
    last, best = (k, label) if reads(label) else (None, "")
    joined = label
    for i in range(k + 1, min(k + 3, len(block.lines))):
        if abs(block.lines[i].indent - indent) > 1 or block.lines[i].page != block.lines[k].page:
            break
        joined = f"{joined} {cell(block.lines[i])}"
        if reads(joined):
            last, best = i, joined
    if last is None:
        return block
    after = block.lines[last + 1] if last + 1 < min(k + 3, len(block.lines)) else None
    if after is not None and abs(after.indent - indent) <= 1 and after.page == block.lines[k].page and cell(after).rstrip().endswith(":"):
        return Block(label="", line=block.line, lines=[], parts=[], inline=block.inline, mode=block.mode)  # "Mandatory" / "Costs:": another label
    start = k
    for i in range(k):
        if reads(" ".join(cell(ln) for ln in block.lines[i:k]) + " " + best):
            start, best = i, " ".join(cell(ln) for ln in block.lines[i:k]) + " " + best
            break
    end = len(block.lines)
    for i in range(last + 1, min(k + 3, len(block.lines))):
        if abs(block.lines[i].indent - indent) <= 1 and block.lines[i].page == block.lines[k].page:
            end = i
            break
    if start == 0 and end == len(block.lines):
        return block
    return Block(label=tidy(best).rstrip(": "), line=block.lines[start], lines=block.lines[start:end], parts=block.parts[start:end],
                 inline=block.inline, mode=block.mode)


def _find(doc: Doc, pattern: str, tails: tuple = ()) -> list[Block]:
    """Sections of ``doc`` whose label matches ``pattern``, in document order.

    ``tails`` are patterns for the last line of a label that wraps ("Mandatory" / "Prepayments:"): block finding joins the
    lines above it, and the section is kept if the joined label reads as ``pattern``.
    """
    found: dict[int, Block] = {}
    try:
        rx = _label_re(pattern)
        for whole in find_blocks(doc, pattern):
            block = _own(whole, pattern)
            if block.text:
                found.setdefault(block.line.n, block)
            # a row just below with a label of the same kind ("Quarterly accounts" / "Management accounts") was taken for the second
            # line of this label and is not found on its own: read it with the lines above it blanked
            for ln in whole.lines[1:4]:
                if ln.n not in found and ln not in block.lines and abs(ln.indent - whole.line.indent) <= 1 and rx.match(ln.text):
                    view = Doc(doc.pages)
                    view.lines = [Line(page=x.page, n=x.n, text="" if x.page == ln.page and x.n < ln.n else x.text, qstart=x.qstart) for x in doc.lines]
                    for below in find_blocks(view, pattern):
                        below = _own(below, pattern)
                        if below.line.n == ln.n and below.text:
                            found.setdefault(ln.n, below)
        for tail in tails:
            for block in find_blocks(doc, tail):
                if block.text and re.fullmatch(pattern, block.label.rstrip(": "), re.IGNORECASE):
                    found.setdefault(block.line.n, block)
    except (re.error, IndexError, ValueError):
        return []
    return [found[n] for n in sorted(found)]


def _sections(ctx: Ctx, pattern: str, tails: tuple = ()) -> list[Block]:
    """Sections whose label matches ``pattern`` and that have value text: top-level ones first, then inline sub-labels."""
    state = _state(ctx)
    key = (pattern, tails)
    if key not in state["blocks"]:
        found = _find(state["doc"], pattern, tails)
        state["blocks"][key] = [b for b in found if not b.inline] + [b for b in found if b.inline]
    return state["blocks"][key]


def _section(ctx: Ctx, pattern: str, tails: tuple = (), want: re.Pattern | None = None) -> Block | None:
    """The first section labelled ``pattern`` (whose text matches ``want``, if given)."""
    for block in _sections(ctx, pattern, tails):
        if want is None or want.search(block.text):
            return block
    return None


def _read(ctx: Ctx, block: Block, pattern: str) -> tuple[str, Block, bool]:
    """(text to read, block to quote from, unchanged from existing terms?).

    On an amendment slide a proposed cell that says "Same as existing" is read from the existing column.
    """
    try:
        if ctx.is_same_as_existing(block):
            twins = [b for b in _find(_state(ctx)["existing"], pattern) if b.line.n == block.line.n and b.text]
            if twins:
                return twins[0].text, twins[0], True
    except (AttributeError, IndexError):
        pass
    return block.text, block, False


def _span(text: str, start: int, end: int) -> re.Match | None:
    """A match object covering text[start:end], which is what ``ctx.quote`` takes as a needle."""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    if end == start:
        return None
    return re.compile(r"(?s).{%d}" % (end - start)).match(text, start)


def _exact(ctx: Ctx, quote: dict | None) -> bool:
    return bool(quote) and ctx.raw.has_quote(quote["quote"], quote["page"])


def _quote(ctx: Ctx, block: Block | None, start: int = 0, end: int | None = None) -> dict | None:
    """Evidence cut from ``block`` around block.text[start:end]; None if nothing verifiable can be cut.

    ``ctx.quote`` widens the needle to its clause, which may reach across a label fragment or a dropped line and
    then only matches loosely; in that case the clause is cut again from the needle's own lines.
    """
    if block is None or not block.text:
        return None
    try:
        if end is None:
            start, end = 0, min(len(block.text), 80)  # what ctx.quote takes when it is given no needle
        end = min(end, start + 140)
        needle = _span(block.text, start, end)
        quote = ctx.quote(block, needle) if needle else ctx.quote(block)
        if needle and quote and not _exact(ctx, quote):
            first, last = block.line_at(needle.start()), block.line_at(max(needle.start(), needle.end() - 1))
            starts, pos = [], 0  # where each line starts in block.text
            for part in block.parts:
                starts.append(pos)
                pos += len(tidy(part)) + 1 if tidy(part) else 0

            def figure(i: int) -> bool:  # the needle's stretch of line i carries a figure
                return bool(re.search(r"\d", block.text[max(starts[i], needle.start()):min(starts[i] + len(tidy(block.parts[i])), needle.end())]))

            # the needle's lines together, then one line alone: the first that carries a figure, else the first
            singles = sorted(range(first, last + 1), key=lambda i: (not figure(i), i))
            for lo, hi in dict.fromkeys([(first, last)] + [(i, i) for i in singles]):
                near = Block(label=block.label, line=block.lines[lo], lines=block.lines[lo:hi + 1], parts=block.parts[lo:hi + 1],
                             inline=block.inline, mode=block.mode)
                again = ctx.quote(near, _span(near.text, max(0, needle.start() - starts[lo]), needle.end() - starts[lo]))
                if _exact(ctx, again):
                    return _one_bullet(ctx, again, needle.group(0))
        return _one_bullet(ctx, quote, needle.group(0) if needle else "")
    except Exception:  # a quote that cannot be cut is simply not offered
        return None


def _one_bullet(ctx: Ctx, quote: dict | None, needle: str) -> dict | None:
    """A quote that runs over several bullets of a cell, cut back to the bullet that holds the needle (if that still verifies)."""
    if not quote or not re.search(_BULLET_GLYPH, quote["quote"]):
        return quote
    probe = _sq(needle)[:12]
    for piece in re.split(_BULLET_GLYPH, quote["quote"]):
        piece = tidy(piece)
        if len(piece) >= 8 and (not probe or probe in _sq(piece)) and ctx.raw.has_quote(piece, quote["page"]):
            return {"quote": piece, "page": quote["page"]}
    return quote


def _quote_item(ctx: Ctx, block: Block, s: int, e: int, prefer: re.Pattern = MONEY_RE) -> dict | None:
    """Evidence for the list item block.text[s:e], centred on its first amount (or ``prefer`` match) when it has one."""
    m = prefer.search(block.text, s, e)
    if m:
        return _quote(ctx, block, max(s, m.start() - 30), m.end())
    return _quote(ctx, block, s, min(e, s + 70))


def _quote_with_label(ctx: Ctx, block: Block) -> dict | None:
    """Evidence for a one-line table row, label included ("Anti cash hoarding • $250mm"), else the plain value quote."""
    try:
        first = next((i for i, part in enumerate(block.parts) if tidy(part)), None)
        if first is not None and len(block.text) <= 160:
            # the label as joined by block finding, then the source line as printed (a label that wraps keeps its first line only)
            for head in (f"{block.label} {block.parts[first]}" if block.label else "", block.lines[first].text):
                if not tidy(head):
                    continue
                row = Block(label=block.label, line=block.lines[first], lines=block.lines[first:], parts=[head] + list(block.parts[first + 1:]),
                            inline=block.inline, mode=block.mode)
                quote = ctx.quote(row)
                if _exact(ctx, quote):
                    return quote
    except Exception:
        pass
    return _quote(ctx, block)


# ---- the document as running text --------------------------------------------------------------------

def _value_column(lines: list) -> int:
    """Column at which the value text of a two-column page starts (the commonest start of a value line)."""
    starts: Counter = Counter()
    for ln in lines:
        if ln.blank or is_footer(ln.text):
            continue
        cells = fragments(ln.text, 3)
        if not cells:
            continue
        first = cells[0]
        if len(cells) >= 2 and first[0] < 30 and len(first[2]) <= 44 and len(first[2].split()) <= 6:
            starts[cells[1][0]] += 1  # label cell followed by value text
        elif first[0] >= 8:
            starts[first[0]] += 1
    if not starts:
        return 0
    return max(starts.items(), key=lambda kv: (kv[1], -kv[0]))[0]


def _is_table(lines: list, vcol: int) -> bool:
    """The page is a table of short rows ("Maturity    5 years"): labels at the left margin, values in one column, and too few
    wrapped lines for the page to count as a two-column layout."""
    body = [ln for ln in lines if not ln.blank and not is_footer(ln.text)]
    if vcol <= 0 or len(body) < 3:
        return False
    rows = 0
    for ln in body:
        cells = fragments(ln.text, 3)
        if len(cells) >= 2 and cells[0][0] < vcol - 3 and abs(cells[1][0] - vcol) <= 2 and len(cells[0][2]) <= 44 and len(cells[0][2].split()) <= 6:
            rows += 1
    return rows >= 3 and rows >= 0.3 * len(body)


def _label_and_value(ln, vcol: int) -> tuple[str, str]:
    """(label cell, value text) of a layout line; the label is "" when the line has none in the left-hand column."""
    cells = fragments(ln.text, 3)
    if not cells:
        return "", ""
    first = cells[0]
    if ln.qstart:  # an amendment slide: the proposed cell, with the label in front of the existing column
        label = first[2] if first[0] < ln.qstart and first[1] <= ln.qstart and len(first[2]) <= 44 else ""
        return label, ln.text[ln.qstart:]
    if first[0] >= vcol - 3:
        return "", ln.text
    label_like = len(first[2]) <= 44 and len(first[2].split()) <= 6 and not first[2].rstrip().endswith((".", ",", ";"))
    if label_like and len(cells) >= 2 and (first[2].rstrip().endswith(":") or cells[1][0] >= vcol - 6):
        return first[2].strip(), ln.text[first[1]:]
    if label_like and len(cells) == 1:
        return first[2].strip(), ""  # a label line with no value beside it
    return "", ln.text


# a "Label: value" line on a page that was extracted without layout
_PLAIN_ROW_RE = re.compile(r"^\s*[A-Z][A-Za-z /&\-()’']{2,44}:(?:\s|$)")
# the end of a finished line: a full stop, semicolon or colon (and a closing bracket or quote after it)
_LINE_END_RE = re.compile(r"[.;:][)\]”\"']?$")


class _Flow:
    """The term sheet as running text: value column only, without page numbers and running headers.

    ``text`` is searched for whole sentences; ``quote`` turns a span of it back into evidence from the page.
    ``breaks`` are the offsets at which a new labelled section or table row starts: a sentence never runs across
    one, so that in a table of one-line rows (which has no full stops) each row is read on its own.
    """

    def __init__(self, doc: Doc):
        by_page: dict[int, list] = {}
        for ln in doc.lines:
            by_page.setdefault(ln.page, []).append(ln)
        self.lines: list = []
        self.parts: list[str] = []
        self.starts: list[int] = []
        self.breaks: list[int] = [0]
        pos = 0
        for page in sorted(by_page):
            lines = by_page[page]
            vcol = _value_column(lines)
            columns = doc.has_columns(page) or _is_table(lines, vcol)
            margin = max((len(ln.text) for ln in lines), default=0)  # right-hand edge of the text on this page
            pending = ""  # label line(s) with no value beside them, waiting for the first value line
            open_label = ""  # label of the line just above, if that line also carried value text
            above_full = False  # the line just above runs to the right-hand edge without ending its sentence
            for ln in lines:
                if ln.blank:
                    open_label, above_full = "", False
                    continue
                if is_footer(ln.text):
                    continue
                if columns:
                    label, value = _label_and_value(ln, vcol)
                else:
                    value = ln.text[ln.qstart:] if ln.qstart else ln.text
                    label = "plain" if _PLAIN_ROW_RE.match(ln.text) else ""
                part = _PUNCT_GAP_RE.sub("", tidy(value))
                if not part:
                    pending = label or pending
                    continue
                label = label or pending
                if label and self.parts and self._starts_section(label, part, open_label, above_full):
                    self.breaks.append(pos)
                open_label = label if (columns and label and not pending) else ""
                pending = ""
                above_full = len(ln.text) >= 0.85 * margin and not _LINE_END_RE.search(part)
                self.lines.append(ln)
                self.parts.append(part)
                self.starts.append(pos)
                pos += len(part) + 1
        self.text = " ".join(self.parts)

    def _starts_section(self, label: str, part: str, open_label: str, above_full: bool) -> bool:
        """A line with a label cell starts a new section, unless it is the second line of a label that wraps."""
        if label == "plain":
            return True
        colon = label.rstrip().endswith(":")
        if open_label and colon and not open_label.rstrip().endswith(":"):
            return False  # "Assignments and  <value>" / "Participations:  <value>"
        if part[:1].islower() and not _LINE_END_RE.search(self.parts[-1]):
            return False  # the value carries on the sentence of the line above
        if open_label and not colon and above_full:
            return False  # a label without a colon that wraps beside a paragraph
        return True

    def _segment(self, pos: int) -> tuple[int, int]:
        """The section or table row (span between two breaks) that holds offset ``pos``."""
        lo, hi = 0, len(self.breaks) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.breaks[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        end = self.breaks[lo + 1] - 1 if lo + 1 < len(self.breaks) else len(self.text)
        return self.breaks[lo], max(self.breaks[lo], end)

    def sentence(self, pos: int, end: int | None = None) -> tuple[int, int]:
        """Span of the sentence (or bullet) that holds text[pos:end], kept inside its section or table row."""
        end = pos if end is None else end
        seg_lo, seg_hi = self._segment(pos)
        lo, hi = max(seg_lo, pos - 1500), min(max(seg_hi, end), end + 1500, len(self.text))
        start = lo
        for m in _UNIT_RE.finditer(self.text, lo, min(len(self.text), pos + 1)):  # one character more, for the lookahead
            if m.end() <= pos:
                start = m.end()
        m = _UNIT_RE.search(self.text, end, hi)
        stop = hi if m is None else (m.start() + 1 if m.group(0).startswith(".") else m.start())
        stray = _STRAY_NUMBER_RE.search(self.text, start, stop)  # "... covenant. 2.": the number of the next item of a numbered list
        return start, (stray.start() if stray and stray.start() >= end else stop)

    def _line_at(self, offset: int) -> int:
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def quote(self, ctx: Ctx, start: int, end: int) -> dict | None:
        """Evidence for text[start:end], cut from the source lines that hold it."""
        if not self.lines or end <= start:
            return None
        first = max(0, self._line_at(start) - 2)
        last = min(len(self.lines) - 1, self._line_at(max(start, end - 1)) + 2)
        lines, parts = self.lines[first:last + 1], self.parts[first:last + 1]
        block = Block(label="", line=lines[0], lines=lines, parts=parts, inline=True, mode="flow")
        return _quote(ctx, block, start - self.starts[first], end - self.starts[first])


def _flow(ctx: Ctx) -> _Flow:
    state = _state(ctx)
    if "flow" not in state:
        state["flow"] = _Flow(state["doc"])
    return state["flow"]


# ======================================================================================================
# Events of Default
# ======================================================================================================

# "Events of Default:", "Event of Default:", "Events of Default and Remedies:", "EoDs" in a summary table
_EOD_LABEL = r"events?\s+of\s+defaults?(?:\s*(?:and|/|&)\s*remedies)?|eods?"
# the last line of that label when it wraps ("Events of" / "Default:")
_EOD_TAILS = (r"defaults?(?:\s*(?:and|/|&)\s*remedies)?",)
# what an event of default is about, first match wins (a cross-default item also speaks of "payment defaults")
_EOD_KINDS = (
    ("cross", re.compile(r"cross[\s-]*(?:defaults?|acceleration)|(?:defaults?|acceleration)\s+(?:under|of|on|in\s+respect\s+of|with\s+respect\s+to|to)\s+"
                         # "default in respect of (i) Indebtedness above ...", "default under any other Financial Indebtedness" (not "inability to pay debts")
                         r"(?:\(\s?[a-z0-9]{1,4}\s?\)\s*)?(?:any\s+|its\s+|their\s+)?(?:other\s+(?:material\s+)?agreements?|"
                         r"(?:(?:other|material|financial|certain|any)\s+)*(?:indebtedness|debt)\b)|"
                         r"(?:non[\s-]*payment|default\s+in\s+(?:the\s+)?payment)\s+of\s+(?:any\s+)?(?:other|material)\s+(?:indebtedness|debt)|\bMaterial\s+Indebtedness\b",
                         re.IGNORECASE)),
    ("judgment", re.compile(r"(?<!reasonable )(?<!sole )(?<!business )(?<!faith )(?<!credit )judge?ments?", re.IGNORECASE)),  # not "in its reasonable judgment"
    ("insolvency", re.compile(r"bankruptc|insolven|winding[\s-]up|receiver|liquidat|creditors['’]?\s+process|attachment|moratorium|reorgani[sz]ation|"
                              r"dissolution", re.IGNORECASE)),
    ("payment", re.compile(r"non[\s-]*payment|fail(?:s|ure)?\s+to\s+(?:pay|make\s+(?:any\s+)?payment)|payment\s+defaults?|default\s+in\s+(?:the\s+)?payment",
                           re.IGNORECASE)),
    ("covenant", re.compile(r"covenants?|undertakings?|other\s+obligations?", re.IGNORECASE)),
    ("rep", re.compile(r"representations?|warrant(?:y|ies)|misrepresentation", re.IGNORECASE)),
    ("control", re.compile(r"change\s+(?:of|in)\s+control", re.IGNORECASE)),
)
# a definition paragraph that follows the list ("Debt" means ...): not part of the events
_DEFINITION_RE = re.compile(r"[“\"][A-Z][^”\"]{1,40}[”\"]\s+(?:means|shall\s+mean|is\s+defined|has\s+the\s+meaning)", re.IGNORECASE)
# a sentence that qualifies the event before it rather than naming a new one ("This cross default provision shall not apply to ...")
_QUALIFIES_RE = re.compile(r"^\W*(?:this|such|the\s+foregoing|provided|notwithstanding|for\s+(?:the\s+)?purposes|no\s+event\s+of\s+default)\b|shall\s+not\s+apply|"
                           r"does\s+not\s+apply|will\s+not\s+apply|\bexclud|carve[\s-]?out", re.IGNORECASE)
# "... when due. 2": the number of the next list item at the end of a sentence
_STRAY_NUMBER_RE = re.compile(r"(?<=[.;])\s*\(?\d{1,2}[.)]?$")
# a figure worth keeping when a row has to be shortened: an amount, a percentage, or a period in digits or words ("sixty consecutive days")
_COUNTED_RE = re.compile(MONEY_RE.pattern + r"|\d\s?%|\b(?:\d{1,3}|" + _SIMPLE_NUMBER_WORDS + r")\b(?:\s*\(\d+\))?(?:[\s-]+\w+){0,2}?[\s-]+(?:days?|months?|years?)\b", re.IGNORECASE)
# the words by which a section speaks of a cross-default, and of insolvency, wherever they stand
_CROSS_WORD_RE = re.compile(r"cross[\s-]*(?:defaults?|acceleration|payment)", re.IGNORECASE)
_INSOLVENCY_WORD_RE = re.compile(r"bankruptc|insolven", re.IGNORECASE)
# a bracket of the lead-in that says where thresholds and grace periods come from ("(with such grace periods and materiality
# thresholds to be consistent with the Existing Credit Agreement)")
_LEAD_TERMS_RE = re.compile(r"\((?:with|subject\s+to)\b[^()]{0,60}?(?:thresholds?|grace|cure\s+periods?|materiality|qualifications?)[^()]{0,140}\)", re.IGNORECASE)
# "cross-default" at the start of an item: redundant under the "Cross default:" prefix
_CROSS_HEAD_RE = re.compile(r"^(?:an?\s+)?cross[\s-]*defaults?\s*", re.IGNORECASE)
# what follows "cross-default" when the item goes straight on to its threshold: "threshold of $75mm", "in excess of ...", "above $20mm"
_THRESHOLD_HEAD_RE = re.compile(r"threshold|in\s+excess|above|over\b|of\b|at\b|with\b", re.IGNORECASE)
# a second sentence of the cross-default item that takes something out of it
_CARVE_OUT_RE = re.compile(r"shall\s+not\s+apply|does\s+not\s+apply|will\s+not\s+apply|exclud|carve[\s-]?out|"
                           # the LMA way of setting the threshold: "No Event of Default will occur under this paragraph if the aggregate amount ... is less than ..."
                           r"no\s+event\s+of\s+default\s+(?:will|shall)\s+(?:occur|arise)|(?:shall|will)\s+not\s+(?:constitute|be|give\s+rise\s+to)\s+an\s+event\s+of\s+default", re.IGNORECASE)
# the part of a payment-default item worth quoting: its grace period
_GRACE_RE = re.compile(r"grace|days?", re.IGNORECASE)
# where one proviso ends and the next begins ("; provided that ... and provided further ...")
_PROVISO_SPLIT_RE = re.compile(r"(?:[;,]\s*|\s+and\s+)provided(?:\s+further)?(?:,?\s+however,?)?(?:\s+that)?\s+", re.IGNORECASE)
# what a payment default is a failure to pay, where a comma list has cut it off its event: "interest or fees (...)", "other amounts"
_PAYMENT_OBJECT_RE = re.compile(r"(?:(?:and|or)\s+)?(?:(?:of|any|all|the)\s+)*(?:principal|interest|premium|(?:commitment\s+|facility\s+|letter\s+of\s+credit\s+)?fees?|"
                                r"reimbursement\s+obligations?|(?:other\s+)?amounts?)\b", re.IGNORECASE)
# the words by which a section speaks of judgments
_JUDGMENT_WORD_RE = re.compile(r"judge?ments?", re.IGNORECASE)
# the sub-heading of a list item or paragraph: "Non-payment: failure to pay ...", "Creditors' process: any attachment ..."
_ITEM_LABEL_RE = re.compile(r"^\s*([A-Z][A-Za-z /&'’\-]{2,40}):\s+(?=\S)")


def _eod_kind(item: str) -> str:
    for kind, rx in _EOD_KINDS:
        if rx.search(item):
            return kind
    return "other"


def _swallowed(body: str, spans: list[tuple[int, int]]) -> list[int]:
    """The items (by index) that run on over a sentence naming an event of another kind: what follows the first sentence of
    such an item is not part of it. A sentence that only qualifies the item ("This provision shall not apply to ...") does not count."""
    out = []
    for i, (s, e) in enumerate(spans):
        points = _sentences(body[s:e])
        if len(points) < 2:
            continue
        own = _eod_kind(body[s:e])
        if any(_eod_kind(body[s + a:s + b]) not in ("other", own) and not _QUALIFIES_RE.search(body[s + a:s + b]) for a, b in points[1:]):
            out.append(i)
    return out


def _event_units(body: str) -> tuple[int, list[tuple[int, int]]]:
    """An events-of-default passage read sentence by sentence: each sentence is one event, unless it is itself a list of events
    (a numbered list whose opening words do not name an event)."""
    start = _lead_colon(body)
    points = [(start + a, start + b) for a, b in _sentences(body[start:])]
    headed = [i for i, (a, b) in enumerate(points) if _ITEM_LABEL_RE.match(body[a:b])]
    if len(headed) >= 2:
        # one paragraph per event, each under its own sub-heading ("Non-payment: ...  Cross default: ..."): the sentences of a
        # paragraph stay together
        bounds = headed + [len(points)]
        return (points[headed[0]][0] if headed[0] else start), [(points[bounds[i]][0], points[bounds[i + 1] - 1][1]) for i in range(len(headed))]
    units: list[tuple[int, int]] = []
    for a, b in points:
        marks = _enumerators(body[a:b])
        if marks and _depth_at(body[a:b], marks[0][0]) == 0 and _eod_kind(body[a:a + marks[0][0]]) == "other":
            _, inner = _items(body[a:b])
            units += [(a + s, a + e) for s, e in inner]
        else:
            a, b = _trim(body, a, b)
            stray = _STRAY_NUMBER_RE.search(body[a:b])  # the number of the next item, left behind where the sentence was cut
            units.append((a, a + stray.start()) if stray else (a, b))
    return start, [(s, e) for s, e in units if e - s >= 3]


def _eod_items(text: str, block=None) -> tuple[int, list[tuple[int, int]]]:
    """Lead-in end and item spans of an events-of-default passage (definitions after the list are left out)."""
    m = _DEFINITION_RE.search(text, 150)
    body = text[:m.start()] if m else text
    lead_end, spans = _items(body, block if body == text else None)
    swallowed = _swallowed(body, spans) if len(spans) >= 2 else []
    if swallowed:
        ends = [m.end() for m in _UNIT_RE.finditer(body, 0, lead_end)]
        start = ends[-1] if ends else 0
        opening = body[start + _lead_colon(body[start:lead_end]):lead_end]  # the words in front of the first marker, in its own sentence
        if _eod_kind(opening) != "other":
            # the markers belong to a list inside one event ("Failure to pay (i) interest ... or (ii) fees ...  Cross-default ..."):
            # the passage is read sentence by sentence
            start, units = _event_units(body)
            if sum(1 for a, b in units if _eod_kind(body[a:b]) != "other") >= 2:
                return start, units
        else:
            # a list of events, one of whose items is followed by further sentences: each of those is read on its own
            units = []
            for i, (s, e) in enumerate(spans):
                units += [_trim(body, s + a, s + b) for a, b in _sentences(body[s:e])] if i in swallowed else [(s, e)]
            return lead_end, [(s, e) for s, e in units if e - s >= 3]
    if len(spans) != 1:
        return lead_end, spans
    s, e = spans[0]
    points = [(s + a, s + b) for a, b in _sentences(body[s:e])]
    headed = [i for i, (a, b) in enumerate(points) if _ITEM_LABEL_RE.match(body[a:b])]
    if len(headed) >= 2:
        # one paragraph per event, each under its own sub-heading ("Non-payment: ...  Cross default: ...")
        bounds = headed + [len(points)]
        return (points[headed[0]][0] if headed[0] else lead_end), [(points[bounds[i]][0], points[bounds[i + 1] - 1][1]) for i in range(len(headed))]
    if len(points) >= 2 and sum(1 for a, b in points if _eod_kind(body[a:b]) != "other") >= 2:
        # one sentence per event; a sentence that only names events of several kinds ("... including payment default, cross-default,
        # bankruptcy and change of control.") is a list, and is cut into them
        units: list[tuple[int, int]] = []
        for a, b in points:
            named = _payment_whole(body, _comma_items(body, a, b, ands=True))
            kinds = {_eod_kind(body[x:y]) for x, y in named} - {"other"}
            units += named if len(kinds) >= 3 and sorted(y - x for x, y in named)[len(named) // 2] <= 60 else [(a, b)]
        return lead_end, units
    parts = _payment_whole(body, _comma_items(body, *points[0], ands=True)) if points else []  # a list written as one sentence
    if sum(1 for a, b in parts if _eod_kind(body[a:b]) != "other") >= 2:
        first = body[parts[0][0]:parts[0][1]]
        if not lead_end and _eod_kind(first) == "other" and _defers(first):
            lead_end, parts = parts[0][1], parts[1:]  # "Customary for an investment grade borrower, with a cross-default threshold of ..."
        spans = parts
    return lead_end, spans


def _payment_whole(body: str, parts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Comma items with a payment default put back together: "non-payment of principal, interest or fees (...)" is one event,
    not a payment default followed by two events called "interest" and "fees"."""
    out: list[tuple[int, int]] = []
    for a, b in parts:
        if out and _PAYMENT_OBJECT_RE.match(body[a:b]) and _eod_kind(body[a:b]) == "other" and _eod_kind(body[out[-1][0]:out[-1][1]]) == "payment":
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def _kind_start(text: str, s: int, e: int, kind: str) -> int:
    """Where the item text[s:e] comes to the event of its ``kind``: an item may open with a sentence that only leads up to it
    ("Customary for investment grade facilities. There will be no cross-default ..."). Only sentences that name no event and
    carry no figure are passed over; an item under a sub-heading stays whole."""
    rx = dict(_EOD_KINDS).get(kind)
    if rx is None or _ITEM_LABEL_RE.match(text[s:e]):
        return s
    for a, b in _sentences(text[s:e]):
        sentence = text[s + a:s + b]
        if rx.search(sentence):
            return s + a
        if _eod_kind(sentence) != "other" or _has_figure(sentence):
            break
    return s


def _own_heading(item: str, kinds: tuple) -> str:
    """An item without its sub-heading when the row's prefix already says it ("Cross-default: any Financial Indebtedness ..."
    under "Cross default: ")."""
    m = _ITEM_LABEL_RE.match(item)
    if m and (_ENUM_RE.match(item, m.end()) or _LINE_ENUM_RE.match(item, m.end())):
        return item  # "Failure to pay: (a) interest ...; or (b) fees ...": the words before the colon govern a list
    return item[m.end():] if m and _eod_kind(m.group(1)) in kinds else item


def _cross_text(item: str) -> str:
    """A cross-default item as it reads after "Cross default: ": "cross-default to X" -> "X", "cross default (subject to ...)" -> "subject to ..."."""
    text = _first_sentence(_own_heading(item, ("cross",)))
    m = _CROSS_HEAD_RE.match(text)
    if not m:
        return text
    rest = text[m.end():]
    if rest[:3].lower() == "to ":
        return rest[3:]
    if rest.startswith("(") and rest.endswith(")") and rest.count("(") == 1:
        return rest[1:-1]
    if _THRESHOLD_HEAD_RE.match(rest):
        return rest  # "cross-default threshold of $75mm"
    return text if rest else ""


def _cross_lines(text: str, cross: list[tuple[int, int]], elsewhere: bool = False) -> list[str]:
    """Lines for the cross-default items: the trigger, then a carve-out made in the sentence that follows it (and the proviso
    of that carve-out which carries an amount). ``elsewhere``: another item of the section gives a figure for the cross-default."""
    body = "; ".join(p for p in (_cross_text(_fix(text[s:e])) for s, e in cross) if len(p) >= 8 or _has_figure(p)) or "listed as an event of default"
    if any(_BLANK_RE.search(text[s:e]) for s, e in cross):
        body += " (threshold left blank in term sheet)"
    elif not any(_has_figure(text[s:e]) for s, e in cross) and not elsewhere:
        body += f" (threshold {NS})"
    lines = [_squeeze("Cross default: " + body, LINE_LIMIT + 80)]
    item = _fix(text[cross[0][0]:cross[0][1]])
    rest = item[len(_first_sentence(item)):].lstrip(". ")
    if rest and _CARVE_OUT_RE.search(rest[:200]):
        sentence = _first_sentence(rest)
        main = _main_clause(sentence)
        lines.append(_squeeze("Cross default carve-out: " + main, LINE_LIMIT + 20) + (" (subject to the provisos in the term sheet)" if len(main) < len(rest) else ""))
        with_amount = [p for p in _PROVISO_SPLIT_RE.split(sentence[len(main):]) if p and MONEY_RE.search(p)]
        if with_amount:
            lines.append(_squeeze("Carve-out condition: " + with_amount[0], LINE_LIMIT + 20))
    return lines


def _first_sentences(text: str, spans: list[tuple[int, int]], each: int, said: tuple = (), elide: bool = False) -> list[str]:
    """The first sentence of each item, squeezed (without a sub-heading of one of the kinds in ``said``, which the row's
    prefix already gives)."""
    return [p for p in (_squeeze(_first_sentence(_own_heading(_fix(text[s:e]), said)), each, elide) for s, e in spans) if p]


def _eod_item_kind(item: str) -> str:
    """What an event of default is about: by its sub-heading when it has one that says so, otherwise by its wording."""
    m = _ITEM_LABEL_RE.match(item)
    kind = _eod_kind(m.group(1)) if m else "other"
    return kind if kind != "other" else _eod_kind(item)


def _eod_read(ctx: Ctx) -> dict | None:
    """The events-of-default section, cut into items by kind (shared with the change-of-control line)."""
    state = _state(ctx)
    if "eod" in state:
        return state["eod"]
    state["eod"] = None
    top = [b for b in _sections(ctx, _EOD_LABEL, _EOD_TAILS) if not b.inline]
    block = max(top, key=lambda b: len(b.text), default=None) or _section(ctx, _EOD_LABEL, _EOD_TAILS)
    if block is None:
        return None
    text, src, same = _read(ctx, block, _EOD_LABEL)
    lead_end, lines = _listed_lines(src, text)  # a cell that lists the events one per line, without bullets or punctuation
    if sum(1 for s, e in lines if _eod_kind(text[s:e]) != "other") >= 2:
        spans = lines
    else:
        lead_end, spans = _eod_items(text, src)
    kinds: dict[str, list[tuple[int, int]]] = {}
    for s, e in spans:
        kind = _eod_item_kind(_fix(text[s:e]))
        kinds.setdefault(kind, []).append((_kind_start(text, s, e, kind), e))
    listed = any(k != "other" for k in kinds)
    lead = text[:lead_end] if lead_end else text[:spans[0][1]] if spans else text
    state["eod"] = {"block": src, "text": text, "kinds": kinds if listed else {}, "lead": lead, "defers": _defers(lead[:400]),
                    "closed": bool(_CLOSED_RE.search(lead[:400])), "same": same}
    return state["eod"]


@_safe(_EOD_BLANK)
def events_of_default(ctx: Ctx) -> dict:
    eod = _eod_read(ctx)
    if eod is None:
        return _blank(*_EOD_BLANK)
    block, text, kinds = eod["block"], eod["text"], eod["kinds"]
    ref = _ref_clause(eod["lead"], 200)
    if not kinds:  # no event is named: the section only points elsewhere, or says something the rule cannot place
        if eod["defers"]:
            return _entry([f"Cross default: not detailed in term sheet - events of default: {_lower_first(ref)}",
                           "Insolvency / creditors' process: not detailed in term sheet"], [_quote(ctx, block)], True, _EOD_BLANK, eod["same"])
        return _entry([f"Cross default: {NS}", f"Insolvency / creditors' process: {NS}", "Events of default: " + _squeeze(text, 200)],
                      [_quote(ctx, block)], False, _EOD_BLANK, eod["same"])

    evidence = []
    unread = []  # subjects the section speaks of outside the items that were read: the row says so instead of "not stated"
    cross = kinds.get("cross", [])
    process = kinds.get("insolvency", []) + kinds.get("judgment", [])
    # figures that an item of another kind gives for these subjects ("The threshold for the cross-default and judgment default will
    # be $50,000,000"): where there is one, the row does not say that the threshold is not stated
    spans = [sp for group in kinds.values() for sp in group]
    cross_elsewhere = any(_has_figure(text[s:e]) and _CROSS_WORD_RE.search(text, s, e) for s, e in spans if (s, e) not in cross)
    process_elsewhere = any(_has_figure(text[s:e]) and (_JUDGMENT_WORD_RE.search(text, s, e) or _INSOLVENCY_WORD_RE.search(text, s, e))
                            for s, e in spans if (s, e) not in process)
    if cross:
        cross_lines = _cross_lines(text, cross, cross_elsewhere)
        evidence.append(_quote_item(ctx, block, *cross[0]))
    elif _CROSS_WORD_RE.search(text):
        cross_lines = ["Cross default: referred to in the events of default section; its terms were not read by the rules (see term sheet)"]
        unread.append("cross-default")
    else:
        cross_lines = [f"Cross default: {NS}"]
    pieces: list[str] = []
    if process:
        pieces = _first_sentences(text, process, 200, elide=True)
        if any(_BLANK_RE.search(text[s:e]) for s, e in process):
            pieces[-1] += " (figures left blank in term sheet)"
        elif not any(_has_figure(text[s:e]) for s, e in process) and not process_elsewhere:
            pieces[-1] += f" (thresholds and grace periods {NS})"
        with_amount = [sp for sp in process if MONEY_RE.search(text, sp[0], sp[1])]
        evidence.append(_quote_item(ctx, block, *(with_amount or process)[0]))
    elif _INSOLVENCY_WORD_RE.search(text):
        unread.append("insolvency")
    payment = _first_sentences(text, kinds.get("payment", []), LINE_LIMIT + 30, ("payment",))
    if kinds.get("payment"):
        evidence.append(_quote_item(ctx, block, *kinds["payment"][0], prefer=_GRACE_RE))
    duties = [_first_sentences(text, kinds.get(k, []), LINE_LIMIT + 62, elide=True) for k in ("covenant", "rep")]
    duty_lines = _pack("Covenants / representations: ", duties[0] + duties[1], LINE_LIMIT + 20, 1)
    if not (duty_lines and len(duty_lines[0]) <= LINE_LIMIT + 20 and not duty_lines[0].endswith("…")):
        duty_lines = _pack("Covenants: ", duties[0], LINE_LIMIT + 80, 1, elide=True) + _pack("Representations: ", duties[1], LINE_LIMIT + 80, 1, elide=True)
    others = _first_sentences(text, kinds.get("control", []) + kinds.get("other", []), 160)
    ref_lines = []
    if eod["defers"] and ref:
        closing = ("Closed list; otherwise " if eod["closed"] else "List not exhaustive; otherwise ") + _lower_first(ref)
        lead_terms = _LEAD_TERMS_RE.search(_fix(eod["lead"]))  # where the thresholds and grace periods come from, if the lead-in says
        if lead_terms and _sq(lead_terms.group(0)) not in _sq(closing) and len(closing) + len(lead_terms.group(0)) <= LINE_LIMIT + 20:
            closing += " " + lead_terms.group(0)
        ref_lines = [_squeeze(closing, LINE_LIMIT + 20)]

    def assemble(condition: bool, carve_out: bool, process_lines: int, payment_lines: int, other_lines: int) -> list[str]:
        """The row at a level of detail."""
        head = [x for x in cross_lines if not (x.startswith("Carve-out condition: ") and not condition) and not (x.startswith("Cross default carve-out: ") and not carve_out)]
        if pieces:
            body = _pack("Insolvency / creditors' process: ", pieces, LINE_LIMIT + 60, process_lines, elide=True)
        elif "insolvency" in unread:
            body = ["Insolvency / creditors' process: referred to in the events of default section; its terms were not read by the rules (see term sheet)"]
        else:
            body = [f"Insolvency / creditors' process: {NS}"]
        pay = _pack("Payment: ", payment, LINE_LIMIT + 40, payment_lines, fit=True)
        return head + body + pay + duty_lines + _pack("Other: ", others, max_lines=other_lines) + ref_lines

    # everything; then without the carve-out's condition; without the carve-out; then with one line for a subject that had two
    levels = ((True, True, 2, 2, 2), (False, True, 2, 2, 2), (False, False, 2, 2, 2), (False, False, 2, 2, 1), (False, False, 1, 2, 1),
              (False, False, 2, 1, 1), (False, False, 1, 1, 1))
    rows = [assemble(*level) for level in levels]
    fits = [x for x in rows[:3] if len(x) <= 8][:1] or [x for x in rows[3:] if len(x) <= 8]
    if fits:
        # of the shorter forms that fit, the one that cuts the fewest lines short and keeps the most figures
        lines = min(fits, key=lambda x: (sum(1 for y in x if y.endswith("…")), -sum(len(_COUNTED_RE.findall(y)) for y in x)))
    else:
        lines = rows[-1]
    if len(lines) > 8 and ref_lines:
        lines = lines[:7] + ref_lines  # the line that says whether the list is complete is never the one that is dropped
    if not any(evidence):
        evidence.append(_quote(ctx, block))
    figures = any(_has_figure(text[s:e]) or _BLANK_RE.search(text[s:e]) for s, e in cross + process)
    entry = _entry(lines, evidence, eod["defers"] and not figures, _EOD_BLANK, eod["same"])
    if unread and entry.get("status") != "not_stated":
        entry["note"] = (f"The events of default section mentions {' and '.join(unread)} outside the list items the rules could read; "
                         "check the section against the term sheet.")
    return entry


# ======================================================================================================
# Conditions Subsequent
# ======================================================================================================

# "Conditions Subsequent:", "Post-Closing Obligations:", "Post-closing covenants"
_CS_LABEL = (r"conditions?\s+subsequent|post[\s-]*closing(?:\s+(?:obligations?|covenants?|undertakings?|matters|requirements?|deliverables?|"
             r"actions?|items|conditions?|collateral))?")
# the last line of a wrapped "Conditions" / "Subsequent:"
_CS_TAILS = (r"subsequent",)
# "within 90 days after the Closing Date", "no later than sixty (60) days following the Effective Date"
_AFTER_CLOSING_RE = re.compile(
    r"(?:within|not?\s+later\s+than|on\s+or\s+(?:prior\s+to|before)\s+the\s+date\s+that\s+is)\s+" + _num() + r"\s*(?P<u>business\s+days?|days?|months?)\s+"
    r"(?:(?:after|following|of|from)\s+(?:the\s+)?(?:(?:Closing|Effective|Funding|Signing|Restatement|Amendment)(?:\s+(?:No\.?\s*\d+\s+)?Effective)?\s+Date|closing\b)|"
    r"post[\s-]closing\b)", re.IGNORECASE)
# "on a post-closing basis", "post-closing period", "after the Closing Date (or such later date as the Agent may agree)"
_POST_CLOSING_RE = re.compile(
    r"post[\s-]closing\s+(?:basis|obligations?|covenants?|undertakings?|deliver\w+|period|requirements?|matters|items|actions?)|on\s+a\s+post[\s-]closing|"
    r"(?:after|following)\s+the\s+Closing\s+Date\s+\(or\s+such\s+(?:later|longer)", re.IGNORECASE)
# "may be delivered post-closing", "subject to customary post-closing relief", "to be provided on a post-closing basis": something a
# closing condition allows to follow after closing
_POST_DELIVERY_RE = re.compile(
    r"(?:deliver(?:ed|y)|provided|satisfied|completed|perfect(?:ed|ion)|obtained|executed|granted|furnished)\s+(?:on\s+a\s+)?post[\s-]closing\b|"
    r"post[\s-]closing\s+(?:relief|grace|flexibility)", re.IGNORECASE)
# "Guarantors and Collateral not provided ... on the Effective Date": guarantees or security that are not in place at closing
_NOT_AT_CLOSING_RE = re.compile(
    r"\bnot\s+(?:been\s+)?(?:provided|delivered|granted|perfected|completed|obtained|in\s+place)\b[^.;]{0,160}?\b(?:on|at|as\s+of|by|prior\s+to)\s+(?:the\s+)?"
    r"(?:Closing|Effective|Funding|Signing)\s+Date", re.IGNORECASE)
# a period after closing, in any wording, in an item that is carried into the row
_CS_PERIOD_RE = re.compile(r"\b\d{1,3}\s*\)?\s*(?:business\s+|calendar\s+)?(?:days?|weeks?|months?)\b|\b(?:" + _SIMPLE_NUMBER_WORDS + r")\s+(?:business\s+|calendar\s+)?(?:days?|weeks?|months?)\b",
                           re.IGNORECASE)
# what a condition subsequent is about: security, perfection and the documents that go with it
_CS_SUBJECT_RE = re.compile(
    r"mortgage|control\s+agreements?|\bDACAs?\b|perfect|security\s+(?:interests?|documents?|agreements?)|collateral|pledge|guarant(?:y|ee|ies|ees)\b|"
    r"insurance\s+(?:certificates?|endorsements?)|certificates?\s+of\s+insurance|loss\s+payee|additional\s+insured|give\s+security|"
    r"\bsecurity\s+(?:over|in|on)\b|share\s+(?:pledges?|charges?)|\bcharges?\s+over\b|\bdebentures?\b|first[\s-]priority\s+(?:security|liens?)|"
    r"landlord|title\s+(?:insurance|polic)|surveys?|legal\s+opinions?|accession|joinder|"
    r"hedging\s+(?:agreements?|arrangements?|transactions?|strategy|policy)|interest\s+rate\s+(?:hedg|protection|swaps?|caps?)", re.IGNORECASE)
# sentences that speak of the closing date for other reasons (pricing, fees, covenant test dates, incremental facilities, syndication and
# market flex, clean-up periods for acquired companies)
_CS_NOISE_RE = re.compile(r"fiscal\s+quarter|interest\s+period|pricing|applicable\s+(?:margin|rate)|commitment\s+fee|incremental|anniversary|syndicat|\bflex\b|"
                          r"clean[\s-]?up|events?\s+of\s+default|\bratings?\b", re.IGNORECASE)
# the wording of a condition precedent: something that has been received or done by closing, or a document dated shortly before it
# ("the Agent shall have received lien searches dated within 30 days of the Closing Date")
_CP_WORDING_RE = re.compile(r"shall\s+have\s+(?:been\s+)?(?:received|delivered|executed|satisfied|obtained|paid)|\bdated\s+(?:within|not?\s+(?:more|earlier|later))",
                            re.IGNORECASE)
# the wording of a representation about accounts already delivered ("the financial statements fairly present ...")
_REP_WORDING_RE = re.compile(r"fairly\s+present|have\s+been\s+prepared|has\s+been\s+prepared|true\s+and\s+(?:fair|correct|complete)|no\s+material\s+adverse\s+change\s+since",
                             re.IGNORECASE)
# a section that says there is nothing ("None.", "N/A", "Not applicable")
_NONE_RE = re.compile(r"^\W*(?:none|n\s?/\s?a|not\s+applicable|nil)\b\W*", re.IGNORECASE)
# where the operative clause of a long sentence starts
_CLAUSE_START_RE = re.compile(r"[;,]\s+(?:but|and|provided(?:\s+that)?|then)\s+|;\s+", re.IGNORECASE)


def _cs_clause(sentence: str, at: int, limit: int = LINE_LIMIT + 70) -> str:
    """A long sentence cut down to the post-closing obligation: its opening clause (what it is about), then the clause that holds
    ``at`` (the period). The opening gives way to the clause: what is cut to fit ``limit`` is never the period itself."""
    lead = _ENUM_RE.match(sentence) or _DOT_ENUM_RE.match(sentence)
    if lead and lead.end() <= at:  # the marker of the list item the obligation is: "(c) perfection of ..."
        sentence, at = sentence[lead.end():], at - lead.end()
    if len(sentence) <= LINE_LIMIT + 30:
        return sentence
    starts = [m.end() for m in _CLAUSE_START_RE.finditer(sentence[:at]) if at - m.end() <= 190]
    start = starts[0] if starts else max(0, sentence.rfind(" ", 0, max(0, at - 150)) + 1)
    if start == 0:
        return sentence
    tail_end = min([p for p in (sentence.find(". ", at), sentence.find("; ", at)) if p >= 0] + [len(sentence)])  # end of the period's clause
    if tail_end - start > limit - 60:  # the clause alone is too long: begin nearer the period
        start = max(start, sentence.rfind(" ", 0, max(0, at - 90)) + 1)
    opening = _ASIDE_RE.sub("", sentence[:start])
    commas = _depth0(opening, ",")
    room = max(40, min(170, limit - (tail_end - start) - 12))
    opening = clip(opening[:commas[0]] if commas else opening, room).rstrip(" ,;")
    return f"{opening} … {sentence[start:]}"


def _cs_mention(item: str) -> str:
    """An item that leaves something for after closing, as a line: the item itself if it is short, otherwise its opening words
    (what it is about) and the bracket or clause that says what is left for later."""
    item = _fix(item)
    lead = _ENUM_RE.match(item) or _DOT_ENUM_RE.match(item)
    body = item[lead.end():] if lead else item
    if len(body) <= LINE_LIMIT + 70:
        return body
    mentions = [m for rx in (_POST_DELIVERY_RE, _NOT_AT_CLOSING_RE, _POST_CLOSING_RE, _AFTER_CLOSING_RE) for m in rx.finditer(body)]
    if not mentions:
        return body
    clauses = [(_clause_around(body, m.start(), m.end(), 240), m) for m in mentions]
    # the mention that sits in a bracket of its own reads best ("... (subject to customary post-closing relief)")
    whole = [(c, m) for c, m in clauses if f"({c})" in body]
    clause, m = min(whole, key=lambda cm: len(cm[0])) if whole else clauses[0]
    at = body.find(clause)
    stops = [x for x in (body.find(" ("), body.find(",")) if x >= 25]
    opening = clip(body[:min(stops)] if stops else body, 170).rstrip(" ,;(")
    if at <= len(opening):
        return clip(body[:at + len(clause)], LINE_LIMIT + 60)
    return f"{opening} … " + (f"({clause})" if (clause, m) in whole else clause)


def _denied(before: str) -> bool:
    """The words that lead up to a mention deny it: a negative stands in the same clause, with no comma, bracket or conjunction
    between it and the mention ("shall not be subject to any | post-closing relief"; not "need not be delivered at closing and
    may be | delivered post-closing")."""
    clause = re.split(r"[,;()]|\b(?:and|but|or)\b", before)[-1]
    return bool(_NEGATION_RE.search(clause) or re.search(r"\bwithout\b", clause, re.IGNORECASE))


def _item_span(sentence: str, start: int, end: int) -> tuple[int, int]:
    """Span of the list item of a long sentence that holds sentence[start:end]: the text between the semicolons outside brackets."""
    semis = _depth0(sentence, ";")
    a = max((p + 1 for p in semis if p < start), default=0)
    b = min((p for p in semis if p >= end), default=len(sentence))
    return _trim(sentence, a, b)


def _item_at(sentence: str, start: int, end: int) -> str:
    """The list item of a long sentence that holds sentence[start:end]."""
    a, b = _item_span(sentence, start, end)
    return sentence[a:b]


@_safe(_CS_BLANK)
def conditions_subsequent(ctx: Ctx) -> dict:
    block = _section(ctx, _CS_LABEL, _CS_TAILS)
    if block is not None:
        text, src, same = _read(ctx, block, _CS_LABEL)
        if _NONE_RE.match(text) and len(text) < 40:
            return _entry(["None (term sheet: '" + _squeeze(text, 40) + "')"], [_quote_with_label(ctx, src)], False, _CS_BLANK, same)
        _, spans = _items(text, src)
        if len(spans) == 1:  # no list: one obligation per sentence
            spans = [(spans[0][0] + a, spans[0][0] + b) for a, b in _sentences(text[spans[0][0]:spans[0][1]])] or spans
        lines = [_upper_first(_squeeze(_first_sentence(_fix(text[s:e])))) for s, e in spans[:4]]
        evidence = [_quote(ctx, src, s, e) for s, e in spans[:3]]
        referred = _defers(text[:300]) and not _has_figure(text)
        return _entry(lines, evidence or [_quote(ctx, src)], referred, _CS_BLANK, same)

    flow = _flow(ctx)
    lines, evidence, seen = [], [], set()
    periods = False
    for rx in (_AFTER_CLOSING_RE, _POST_CLOSING_RE, _POST_DELIVERY_RE, _NOT_AT_CLOSING_RE):
        # a closing condition or a covenant that leaves a deliverable for after closing is carried in its own words
        left_open = rx in (_POST_DELIVERY_RE, _NOT_AT_CLOSING_RE)
        for m in rx.finditer(flow.text):
            s, e = flow.sentence(m.start(), m.end())
            if s in seen or len(lines) >= 3:
                continue
            sentence = flow.text[s:e]
            # in a long list the obligation is one item; what the other items speak of says nothing about it
            a, b = _item_span(sentence, m.start() - s, m.end() - s) if len(sentence) > LINE_LIMIT + 70 or left_open else (0, len(sentence))
            if a > m.start() - s or b < m.end() - s:
                a, b = 0, len(sentence)
            item = sentence[a:b]
            if any(a + s <= x < b + s for x in seen) or not _CS_SUBJECT_RE.search(item) or _CS_NOISE_RE.search(item):
                continue
            if rx in (_POST_CLOSING_RE, _POST_DELIVERY_RE) and _denied(sentence[:m.start() - s]):
                continue  # "... which shall not be subject to any post-closing relief": nothing is left for after closing
            if _CP_WORDING_RE.search(item) and not left_open:
                continue
            quote = flow.quote(ctx, m.start(), m.end())
            if not quote:
                continue
            seen.update((s, s + a))
            if left_open:
                lines.append(_upper_first(_squeeze(_cs_mention(item), LINE_LIMIT + 70)))
            else:
                lines.append(_squeeze(_cs_clause(item, m.start() - s - a), LINE_LIMIT + 70))
            periods = periods or not left_open or bool(_CS_PERIOD_RE.search(item))
            evidence.append(quote)
    if not lines:
        return _blank(*_CS_BLANK)
    if not periods:  # deliverables are left for after closing, but no period is given for any of them
        lines.append("No post-closing period is stated for these items in the term sheet")
    return _entry(lines, evidence, not periods, _CS_BLANK)


# ======================================================================================================
# Mandatory Prepayment Events
# ======================================================================================================

# "Mandatory Prepayments:", "Mandatory Prepayments and Commitment Reductions:", "Mandatory Repayment / Cancellation:", or "Mandatory:" under "Prepayments"
_MP_LABEL = (r"mandatory\s+(?:pre|re)payments?(?:\s+events?)?(?:\s*(?:and|/|&)(?:\s*(?:commitment\s+)?(?:reductions?|cancellations?))?)?|"
             r"mandatory\s+(?:commitment\s+)?(?:reductions?|cancellations?)(?:\s*(?:and|/|&)(?:\s*(?:pre|re)payments?)?)?|mandatory|"
             r"(?:pre|re)payments?\s*(?:and|/|&)\s*cancellations?")  # the LMA heading, under which the voluntary prepayment is also found
# the last line of a wrapped "Mandatory" / "Prepayments:" or "Mandatory Prepayments and" / "Commitment Reductions:"
_MP_TAILS = (r"(?:pre|re)payments?(?:\s+events?)?", r"(?:commitment\s+)?(?:reductions?|cancellations?)")
# "Change of Control:", "Change in Control:", "Change of Control Put:"
_COC_LABEL = r"change\s+(?:of|in)\s+control(?:\s+(?:put|prepayment|offer|event))?"
# the last line of a wrapped "Change of" / "Control:"
_COC_TAILS = (r"control(?:\s+(?:put|prepayment|offer|event))?",)
# "Anti cash hoarding", "Anti-Cash Hoarding:", "Cash hoarding"
_HOARDING_LABEL = r"anti[\s-]*cash[\s-]*hoarding|cash\s+hoarding"
# any mention of a change of control
_COC_RE = re.compile(r"change\s+(?:of|in)\s+control", re.IGNORECASE)
# 'A Change of Control shall occur if ...', '"Change of Control" means ...'
_COC_DEFINITION_RE = re.compile(
    r"[“\"]?change\s+(?:of|in)\s+control[”\"]?\s+(?:shall\s+(?:occur|mean|be\s+deemed\s+to\s+(?:have\s+)?occur(?:red)?)|means|occurs\s+(?:if|when|upon)|"
    r"(?:is|will\s+be|shall\s+be|to\s+be)\s+defined(?:\s+(?:as|to\s+mean|to\s+include|to))?)\s*(?:if|when|upon|that|[:,])?\s*", re.IGNORECASE)
# what is left of a definition that only points elsewhere: "... shall be defined | in a manner consistent with the Existing Credit Agreement"
_DEFINED_ELSEWHERE_RE = re.compile(r"in\s+(?:a\s+manner|accordance|the\s+same|substantially)|consistent|substantially|by\s+reference|as\s+(?:set|provided|in)\b", re.IGNORECASE)
# '"Control" means the ownership of more than 50 per cent. of ...': the LMA way of giving the ownership trigger
_CONTROL_MEANS_RE = re.compile(r"[“\"]control[”\"]\s+(?:means|shall\s+mean)\s+", re.IGNORECASE)
# what happens on a change of control
# "each Lender may ...", "any Lender shall have the right to ...", "lenders may cancel ...": a right of the lenders, not an automatic prepayment
_COC_LENDER_RIGHT_RE = re.compile(r"(?:(?:each|any|the|a)\s+)?Lenders?\s+(?:may|shall\s+(?:have\s+the\s+right|be\s+entitled)|will\s+have\s+the\s+right|ha(?:s|ve)\s+the\s+right|"
                                  r"(?:is|are)\s+entitled)", re.IGNORECASE)
# "shall be prepaid", "must repay", "mandatory prepayment", "become immediately due and payable"
_COC_PREPAY_RE = re.compile(r"(?:shall|will|must|required\s+to)\s+(?:be\s+)?(?:immediately\s+|promptly\s+)?(?:pre|re)pa(?:y|id)|mandatory\s+(?:pre|re)payment|"
                            r"become\s+(?:immediately\s+)?due\s+and\s+payable", re.IGNORECASE)
# "cancel its Commitments", "the commitments will terminate"
_COC_CANCEL_RE = re.compile(r"cancel|terminat", re.IGNORECASE)
# "offer to prepay", "offer to repurchase", "prepayment offer"
_COC_OFFER_RE = re.compile(r"offer\s+to\s+(?:pre|re)pa(?:y|id)|offer\s+to\s+(?:re)?purchase|prepayment\s+offer", re.IGNORECASE)
# "shall constitute an Event of Default", "will be an Event of Default"
_COC_DEFAULT_RE = re.compile(r"(?:constitutes?|be|is|as)\s+an\s+event\s+of\s+default", re.IGNORECASE)
# a sentence about other debt (notes, bonds, an indenture): its change of control terms are not this facility's
_OTHER_DEBT_RE = re.compile(r"\bnotes\b|\bindentures?\b|\bbonds?\b|\bdebentures?\b|\bnoteholders?\b", re.IGNORECASE)
# sentences about amendments and voting mention the change of control without saying what happens on one
_COC_VOTING_RE = re.compile(r"\bwaive|\bamend|consent\s+of\s+(?:each|all)\s+", re.IGNORECASE)
# "If a Change of Control occurs,", "Upon the occurrence of a Change of Control,", "Change of control - ": dropped after the "Change of Control:"
# prefix (not when the sentence goes on "... or a sale of all or substantially all of the assets")
_COC_OPENING_RE = re.compile(r"^(?:(?:if|upon|on|following|in\s+the\s+event\s+of)\s+(?:an?\s+|any\s+|the\s+occurrence\s+of\s+an?\s+)?change\s+(?:of|in)\s+control"
                             r"(?!(?:\s+occurs|\s+shall\s+occur|\s+has\s+occurred)?\s*,?\s*(?:or|and)\b)(?:\s+occurs|\s+shall\s+occur|\s+has\s+occurred)?,?\s*|"
                             r"change\s+(?:of|in)\s+control\s*[:–—-]\s*)", re.IGNORECASE)
# "[ ]%", "[●] per cent.": a percentage the term sheet leaves blank
_BLANK_PCT_RE = re.compile(r"\[\s*[●•_.\s]*\]\s?(?:%|per\s?cent)", re.IGNORECASE)
# a percentage below 100, which in a change of control line is a share of ownership ("35%"; "101%" is the price of a put)
_SHARE_PCT_RE = re.compile(r"(?<![\d.,])\d{1,2}(?:\.\d+)?\s?(?:%|per\s?cent)", re.IGNORECASE)
# what a definition of "Control" speaks of when it gives the ownership trigger
_OWNERSHIP_RE = re.compile(r"\bshares?\b|share\s+capital|voting|equity|\bown(?:s|ership)?\b", re.IGNORECASE)
# kinds of prepayment event; first match wins within an item
_MP_KINDS = (
    ("Excess cashflow", re.compile(r"excess\s+cash\s*flow|\bECF\b", re.IGNORECASE)),
    ("Debt issuance proceeds", re.compile(
        r"(?:issuances?|incurrences?|offerings?)\s+(?:or\s+(?:issuances?|incurrences?)\s+)?of\s+(?:any\s+)?(?:[\w-]+\s+)?(?:debt|indebtedness|notes)|"
        r"(?:debt|indebtedness)\s+(?:issuances?|incurrences?|offerings?|proceeds)|proceeds\s+(?:of|from)\s+(?:any\s+)?(?:[\w-]+\s+){0,3}?(?:debt|indebtedness)\b|"
        r"refinancing\s+(?:debt|indebtedness|facilit)", re.IGNORECASE)),
    ("Disposal proceeds", re.compile(
        r"asset\s+(?:sales?|dispositions?|disposals?)|dispositions?|disposals?|"
        r"\bsales?\b(?!\s+of\s+(?:the\s+)?(?:company|group|business)\b)[^.;,]{0,40}?\b(?:assets?|property|properties|collateral|vessels?|rigs?|aircraft|real\s+estate)\b",
        re.IGNORECASE)),
    ("Insurance proceeds", re.compile(r"insurance|casualty|condemnation|recovery\s+events?|total\s+loss|expropriation", re.IGNORECASE)),
    ("Other", re.compile(r"exceeds?|in\s+excess\s+of|borrowing\s+base|\bcurrenc|exchange\s+rates?|illegal|unlawful|hoard|equity\s+(?:issuances?|offerings?|proceeds)|"
                         r"\bIPO\b|flotation|sale\s+of\s+(?:the\s+)?(?:company|group|business)|all\s+or\s+substantially\s+all|sanction|loan[\s-]to[\s-]value|\bLTV\b|"
                         r"collateral\s+(?:coverage|shortfall)", re.IGNORECASE)),
)
# "Voluntary prepayment: ...", "optional prepayments": not a mandatory prepayment event
_VOLUNTARY_RE = re.compile(r"\bvoluntar|\boptional", re.IGNORECASE)
# ... unless the sentence speaks of mandatory prepayments as well
_MANDATORY_WORD_RE = re.compile(r"\bmandator", re.IGNORECASE)
# where the next sweep of a one-sentence list starts: "100% of ... asset sales, 100% of ... debt and 50% of Excess Cash Flow"
_PCT_ITEM_RE = re.compile(r"(?:,\s*(?:and\s+)?|\s+and\s+)(?=\d[\d.]*\s?%\s+of\b)")
# a negative in front of the events a sentence names: it says that there is no such prepayment, and is carried into the line whole
_NEGATION_RE = re.compile(r"\b(?:no|not|none|neither|never)\b", re.IGNORECASE)
# what follows an opening "None" when the section goes on to make an exception ("None, except that ...")
_EXCEPT_RE = re.compile(r"(?:except|other\s+than|save|unless|provided|but|subject)\b", re.IGNORECASE)
# a sale of the whole business is an exit, treated with the change of control, not a sweep of disposal proceeds
_EXIT_RE = re.compile(r"all\s+or\s+substantially\s+all", re.IGNORECASE)
# the order of the brief
_MP_ORDER = ("Disposal proceeds", "Insurance proceeds", "Debt issuance proceeds", "Excess cashflow", "Other")
# "exceeds 103% of the Facility Amount ... shall make a mandatory prepayment", "exceeds 105% of the sublimit ... will cash collateralize"
_OVER_LIMIT_RE = re.compile(r"(?:exceeds?|in\s+excess\s+of|greater\s+than|more\s+than)\b[^.]{0,120}?\b1[01]\d(?:\.\d+)?\s?%", re.IGNORECASE)
# "Advances in excess of the aggregate commitments ... shall be repaid", "if the exposure exceeds the commitments, the Borrower shall prepay"
_OVER_COMMITMENT_RE = re.compile(
    r"in\s+excess\s+of\s+the\s+(?:aggregate\s+|total\s+)?(?:\w+\s+){0,2}(?:commitments|facility\s+amount)[^.]{0,160}?(?:shall|will|must)\s+be\s+(?:promptly\s+|immediately\s+)?(?:re|pre)paid|"
    r"exceeds?\s+the\s+(?:aggregate\s+|total\s+)?(?:\w+\s+){0,2}(?:commitments|facility\s+amount|borrowing\s+base|line\s+cap)[^.]{0,200}?(?:shall|will|must|required\s+to)\s+"
    r"(?:be\s+)?(?:promptly\s+|immediately\s+)?(?:(?:re|pre)pa(?:y|id)|cash\s+collaterali[sz]e)", re.IGNORECASE)
# "shall promptly make a mandatory prepayment", "shall be mandatorily prepaid": an obligation stated outside a prepayment section
_MANDATORY_RE = re.compile(r"(?:shall|will|must|required\s+to)\s+(?:promptly\s+|immediately\s+)?(?:make\s+(?:a\s+)?mandatory\s+(?:pre|re)payments?|be\s+mandatorily\s+(?:pre|re)paid|"
                           r"mandatorily\s+(?:pre|re)pay)", re.IGNORECASE)
# "the Borrower shall, within 60 days, (i) deliver additional collateral or (ii) prepay the Loans, in an amount sufficient to comply with
# the Coverage Ratio": a prepayment that cures a shortfall under a collateral coverage or loan-to-value test
_COVERAGE_CURE_RE = re.compile(
    r"(?:shall|will|must|required\s+to)\b[^.;]{0,220}?\b(?:pre|re)pay\s+(?:the\s+)?(?:[\w-]+\s+){0,3}?(?:loans?|advances|facilit(?:y|ies)|borrowings)\b[^.;]{0,200}?"
    r"\b(?:sufficient|necessary|required|needed)\s+(?:to|for|so\s+that)\b[^.;]{0,120}?\b(?:compl(?:y|iance)|cure|restore[sd]?|eliminate|remedy)", re.IGNORECASE)
# an equity cure or another right (not a duty) to put a covenant breach right
_CURE_RIGHT_RE = re.compile(r"right\s+to\s+cure|cure\s+right|equity\s+cure|cure\s+amount|\bat\s+(?:its|the\s+\w+['’]s)\s+(?:option|election)\b|\bmay\b[^.;]{0,40}\b(?:pre|re)pay", re.IGNORECASE)
# an obligation to pay back or to cover: "prepay", "repaid", "prepayment", "cash collateralize"
_DUTY_RE = re.compile(r"(?:pre|re)pa(?:y|id|yment)|cash\s+collaterali[sz]e", re.IGNORECASE)
# sentences about amendments, waivers and fees mention prepayments without imposing one
_NOT_AN_EVENT_RE = re.compile(r"\bwaive|\bamend|consent\s+of\s+(?:each|all|the\s+Required)\s+|\bpremium\b|\bfees?\b|optional|voluntar", re.IGNORECASE)
# currency proviso of an over-advance prepayment: "caused by fluctuations in foreign currency exchange rates ... not more than 105%"
_FX_RE = re.compile(r"(?:fluctuations?|movements?|changes?)\s+in\s+(?:foreign\s+)?(?:currency\s+)?exchange\s+rates?|currency\s+fluctuations?|exchange\s+rate\s+fluctuations?",
                    re.IGNORECASE)
# "no such prepayment will be required to the extent ... is not more than 105% of the aggregate commitments": headroom before a
# currency excess must be prepaid, and what the percentage is taken of
_FX_HEADROOM_RE = re.compile(r"no\s+(?:such\s+)?prepayment\s+(?:will|shall)\s+be\s+required[^.;]{0,160}?(?:not\s+more\s+than|does\s+not\s+exceed|not\s+in\s+excess\s+of|"
                             r"less\s+than\s+or\s+equal\s+to)\s+(?P<pct>1\d\d(?:\.\d+)?)\s?%(?P<of>\s+of\s+[^.;,()]{3,70})?", re.IGNORECASE)
# "Consistent with the Existing Credit Agreement, ..." in front of a provision
_LEADING_REF_RE = re.compile(r"^(?:(?:substantially\s+)?(?:consistent\s+with|similar\s+to|the\s+same\s+as|same\s+as(?:\s+under)?)\s+the\s+[^,]{3,60}?,\s+)", re.IGNORECASE)
# "If, as a result of any such recalculation, the exposure exceeds ...": the connective refers to a sentence that is not quoted
_RESULT_OPENING_RE = re.compile(r"^If,\s+as\s+a\s+result\s+of\s+[^,]{3,60},\s*", re.IGNORECASE)
# a sentence that leans on the one before it ("after giving effect to the foregoing commitment reduction")
_BACK_REFERENCE_RE = re.compile(r"\bforegoing\b|such\s+(?:commitment\s+)?reduction|as\s+so\s+reduced", re.IGNORECASE)
# the sentence before speaks of a reduction ("the commitments shall be reduced to ...")
_REDUCTION_RE = re.compile(r"\breduc(?:ed|tion)\b", re.IGNORECASE)
# the figure of a prepayment event, for the quote: a percentage or an amount
_PCT_OR_MONEY_RE = re.compile(r"\d[\d.,]*\s?%|" + MONEY_RE.pattern, re.IGNORECASE)
# "the commitments shall be automatically and permanently reduced"
_MP_REDUCTION_RE = re.compile(r"commitments?\s+(?:shall|will)\s+(?:be\s+)?(?:(?:automatically|permanently|and)\s+)*(?:reduced|terminated?|cancell?ed)", re.IGNORECASE)
# how prepayments are applied or declined, rather than when they are required
_MP_MECHANICS_RE = re.compile(r"\bappl(?:ied|ication|y)\b|\bdeclin|\bnotice\b|without\s+(?:premium|penalty)|breakage|pro\s+rata|ratabl", re.IGNORECASE)
# a list item written as a name and its terms in brackets: "Disposal Proceeds (100% of Net Disposal Proceeds ...)"
_LABELLED_ITEM_RE = re.compile(r"^([A-Z][A-Za-z /\-]{3,34}?)\s*\((.+)\)$")
# ... or as a name, a colon or dash, and its terms: "Disposal Proceeds: 100% of Net Disposal Proceeds ..."
_HEADED_ITEM_RE = re.compile(r"^([A-Z][A-Za-z /\-]{3,34}?)\s*(?::|\s[–—-])\s+(.+)$")
# text in round brackets, for telling whether a figure stands inside or outside them
_BRACKETED_RE = re.compile(r"\([^()]*\)")


def _mp_kind(item: str) -> str:
    """The kind of prepayment event an item is about ("" if none): the first of _MP_KINDS that matches."""
    if _EXIT_RE.search(item):
        return "Other"
    for kind, rx in _MP_KINDS:
        if rx.search(item):
            return kind
    return ""


def _mp_key(item: str) -> str:
    """The prefix an item goes under: its kind, or "Disposal proceeds / Insurance proceeds" for one provision that covers both."""
    if _EXIT_RE.search(item):
        return "Other"
    named = [kind for kind in _MP_ORDER[:4] if dict(_MP_KINDS)[kind].search(item)]
    return " / ".join(named) if named else _mp_kind(item)


def _unlabel(item: str, key: str) -> str:
    """"Disposal Proceeds (100% of ...)" / "Disposal Proceeds: 100% of ..." -> "100% of ...": an item that opens with the name of its own kind."""
    for rx in (_LABELLED_ITEM_RE, _HEADED_ITEM_RE):
        m = rx.match(item)
        if m and _mp_kind(m.group(1)) in _MP_ORDER[:4] and _mp_kind(m.group(1)) in key:
            return m.group(2)
    return item


def _figure_in_the_open(text: str) -> bool:
    """A percentage, amount or period stands outside brackets: in a list it applies to every item that follows it."""
    return _has_figure(_BRACKETED_RE.sub(" ", text))


def _over_advance_lines(sentence: str, before: str = "", limit: int = LINE_LIMIT + 50) -> list[str]:
    """Line(s) for an obligation to prepay exposure above the commitments.

    The currency headroom gets a line of its own if the proviso gives one; ``before`` is the preceding sentence, used
    when this one leans on it ("the foregoing commitment reduction").
    """
    text = _upper_first(_NOTWITHSTANDING_RE.sub("", _RESULT_OPENING_RE.sub("If ", _fix(sentence))))
    lead = _LEADING_REF_RE.match(text)
    if lead:
        text = text[lead.end():]
    main = _main_clause(text)
    rest = text[len(main):]
    head = _FX_HEADROOM_RE.search(rest)
    more = ""
    if rest and _FX_RE.search(rest) and head:
        line = _squeeze(main, LINE_LIMIT - 30)
        base = re.sub(r"\s+(?:and|or)$", "", (head.group("of") or "").rstrip())  # "of the aggregate commitments thereunder", as the term sheet has it
        more = f"Other: if that excess is caused by exchange rate fluctuations, no prepayment is required while exposure is not more than {head.group('pct')}%{base}"
    elif before and _BACK_REFERENCE_RE.search(text) and _REDUCTION_RE.search(before):
        line = f"{_squeeze(_ASIDE_RE.sub('', _main_clause(_fix(before))), 170)}; {_lower_first(_squeeze(_ASIDE_RE.sub('', text), 150))}"
    else:
        line = _squeeze(text, limit, elide=True)
    if not line:
        return []
    if lead:
        line += f" ({_lower_first(lead.group(0).rstrip(', '))})"
    return ["Other: " + _upper_first(line)] + ([more] if more else [])


def _trigger(definition: str) -> str:
    """The ownership trigger from a change-of-control definition, without long carve-out brackets and exceptions."""
    text = _fix(definition)
    m = _COC_DEFINITION_RE.search(text)
    if m:
        text = text[m.end():]
        if _DEFINED_ELSEWHERE_RE.match(text):
            text = "to be defined " + text
    text = _ASIDE_RE.sub("", text)
    main = _main_clause(text)
    # an exception or proviso that follows the trigger is not carried into the line, but the line says that there is one
    return _squeeze(main, 300) + (" (subject to the exceptions in the term sheet)" if len(main) < len(text.rstrip(" .")) else "")


def _coc_treatment(text: str) -> str:
    """How a passage treats a change of control: prepayment offer, lender put, mandatory prepayment (and cancellation), event of
    default, or ""."""
    if _COC_OFFER_RE.search(text):
        return "prepayment offer"
    if _COC_LENDER_RIGHT_RE.search(text) and (_COC_CANCEL_RE.search(text) or _DUTY_RE.search(text)):
        return "lender put / cancellation right"
    if _COC_PREPAY_RE.search(text):
        return "mandatory prepayment" + (" and cancellation" if _COC_CANCEL_RE.search(text) else "")
    if _COC_DEFAULT_RE.search(text):
        return "event of default"
    return ""


def _coc_clause(sentence: str, start: int, end: int) -> str:
    """The part of a sentence that deals with the change of control mentioned at sentence[start:end]: the sentence itself when it
    is short, otherwise the list item around the mention, otherwise the words around it."""
    if len(sentence) <= LINE_LIMIT + 30:
        return sentence
    item = _item_at(sentence, start, end)
    if len(item) <= LINE_LIMIT + 130:
        return item
    a = sentence.rfind(" ", 0, max(0, start - 100)) + 1
    return sentence[a:end + 240]


def _coc_phrase(kind: str, clause: str) -> str:
    """How the change of control is treated, in the words of the clause that says so."""
    body = _squeeze(_COC_OPENING_RE.sub("", _fix(clause).lstrip(" ,;:")), 190)
    if kind == "event of default":  # the clause says no more than that, unless it also gives the trigger
        return kind + (f" ('{body}')" if _PCT_RE.search(body) or _BLANK_RE.search(body) else "")
    if not kind or not body:
        return kind or body
    if body.lower().startswith(kind.split(" /")[0].split(" and ")[0]):
        return _lower_first(body)  # "Mandatory prepayment at 35% ownership"
    return f"{kind} - {body}"


def _trigger_note(line: str) -> str:
    """What to say about the ownership trigger when the term sheet has no definition of a change of control."""
    if _BLANK_PCT_RE.search(line):
        return "; ownership trigger left blank in term sheet"
    return "" if _SHARE_PCT_RE.search(line) else f"; ownership trigger {NS}"


def _change_of_control(ctx: Ctx, flow: _Flow, eod: dict | None, mp_text: str, mp_src: Block | None) -> tuple[str, str, list, bool]:
    """(first line, trigger line or "", evidence, only by reference?) for the change of control.

    What happens on a change of control is looked for in a sentence that says so anywhere in the term sheet, then in a section
    of its own, then among the events of the mandatory prepayment section (``mp_text``, quoted from ``mp_src``), and last in the
    list of events of default; the ownership trigger comes from the definition, wherever that is.
    """
    treatment = trigger = ""
    evidence: list = []
    eod_sq = _sq(eod["text"]) if eod else ""
    sentences: list[tuple[int, int, int, int]] = []
    for m in _COC_RE.finditer(flow.text):
        s, e = flow.sentence(m.start(), m.end())
        if not any(x[0] == s for x in sentences):
            sentences.append((s, e, m.start() - s, m.end() - s))
    for s, e, at, upto in sentences:
        sentence = flow.text[s:e]
        if len(sentence) > 1400 or (eod_sq and _sq(sentence[:120]) in eod_sq):
            continue  # the events-of-default list is dealt with below
        if _OTHER_DEBT_RE.search(sentence):
            continue  # the terms of notes or bonds, not of this facility
        d = _COC_DEFINITION_RE.search(sentence)
        if d:
            if not trigger:
                trigger = _trigger(sentence[d.start():])
                evidence.append(flow.quote(ctx, s + d.start(), s + min(len(sentence), d.end() + 60)))
            continue
        clause = _coc_clause(sentence, at, upto)
        if treatment or _COC_VOTING_RE.search(clause):
            continue
        near = _COC_RE.search(clause)
        kind = _coc_treatment(clause[max(0, near.start() - 220):near.end() + 260]) if near else ""
        if kind:
            treatment = _coc_phrase(kind, clause)
            evidence.insert(0, flow.quote(ctx, s + at, s + upto))
    block = _section(ctx, _COC_LABEL, _COC_TAILS)
    if block is not None and not treatment:
        text, src, same = _read(ctx, block, _COC_LABEL)
        points = [text[a:b] for a, b in _sentences(text)]
        says = [p for p in points if not _COC_DEFINITION_RE.search(p) and not _CONTROL_MEANS_RE.search(p)]
        treatment = _coc_phrase(_coc_treatment(text), says[0] if says else "")
        if treatment:
            treatment += _UNCHANGED if same else ""
            evidence.insert(0, _quote(ctx, src))
        d = _COC_DEFINITION_RE.search(text)
        if d and not trigger:
            trigger = _trigger(_first_sentence(text[d.start():]))
            evidence.append(_quote(ctx, src, d.start(), d.end() + 60))
    if not treatment and mp_src is not None and _COC_RE.search(mp_text):
        own = _coc_in_section(mp_text, mp_src)  # one of the mandatory prepayment section's own events
        if own:
            treatment = own[0]
            evidence.insert(0, _quote(ctx, mp_src, own[1], own[2]))
    if treatment and not trigger and not _SHARE_PCT_RE.search(treatment):
        # LMA style: the event speaks of "control" and a separate definition of "Control" gives the percentage
        for d in _CONTROL_MEANS_RE.finditer(flow.text):
            s, e = flow.sentence(d.start(), d.end())
            sentence = flow.text[s:e]
            if _PCT_RE.search(sentence) and _OWNERSHIP_RE.search(sentence) and len(sentence) <= 600:
                trigger = _squeeze(_main_clause(_ASIDE_RE.sub("", _fix(sentence[d.start() - s:]))), 300)
                evidence.append(flow.quote(ctx, d.start(), min(e, d.end() + 60)))
                break
    referred = False
    default_item = ""
    if eod and eod["kinds"].get("control"):
        s, e = eod["kinds"]["control"][0]
        item = _first_sentence(_fix(eod["text"][s:e]))
        default_item = "event of default" + (f" ('{_squeeze(item, 170)}')" if len(item) > 26 else " (listed among the events of default)")
        if not treatment:
            evidence.insert(0, _quote_item(ctx, eod["block"], s, e, prefer=_COC_RE))
            referred = eod["defers"] or bool(_AS_DEFINED_RE.search(item))
    if not treatment and not default_item and not trigger:
        return f"Change of Control: {NS}", "", [], False
    also = "" if not default_item or treatment.startswith("event of default") else "also an " + default_item
    parts = [p for p in ((treatment, also) if treatment else (default_item,)) if p]
    line = "Change of Control: " + ("; ".join(parts) if parts else f"treatment {NS}")
    if not trigger:  # no definition: the trigger is "not stated" unless the line itself gives a percentage
        return line + _trigger_note(line), "", evidence, referred
    if len(line) + len(trigger) + 11 <= LINE_LIMIT + 20:
        return f"{line}; trigger: {trigger}", "", evidence, False
    return line, "Change of Control trigger: " + trigger, evidence, False


def _coc_in_section(text: str, block: Block | None = None) -> tuple[str, int, int] | None:
    """The change of control as one of the mandatory prepayment section's own events: (how it is treated, start and end of its
    clause in ``text``)."""
    for s, e in _points(text, block):
        sentence = text[s:e]
        m = _COC_RE.search(sentence)
        if not m or _OTHER_DEBT_RE.search(sentence) or _COC_VOTING_RE.search(sentence):
            continue
        names = _comma_items(sentence, 0, len(sentence), ands=True)
        name = next(((a, b) for a, b in names if a <= m.start() < b), None)
        if name and len(_BRACKETED_RE.sub(" ", sentence[name[0]:name[1]]).split()) <= 5 and not _coc_treatment(sentence):
            # an event listed by name: "Change of control (50%), sale of all or substantially all assets, illegality"
            aside = _BRACKETED_RE.search(sentence, name[0], name[1])
            return ("mandatory prepayment event (listed in the mandatory prepayment section)" + (f" {_fix(aside.group(0))}" if aside else ""),
                    s + name[0], s + name[1])
        clause = _coc_clause(sentence, m.start(), m.end())
        at = sentence.find(clause)
        return _coc_phrase(_coc_treatment(clause) or "mandatory prepayment", clause), s + max(at, 0), s + max(at, 0) + len(clause)
    return None


# a list marker at the start of an item: "(a) ", "(ii) ", "2. "
_ITEM_MARKER_RE = re.compile(r"\s*(?:\(\s?(?:\d{1,2}|[ivxl]{1,5}|[a-z])\s?\)|\d{1,2}\.(?=\s+[A-Z“\"(\[]))\s*")
# ", subject to reinvestment rights ...", "; provided that ...": where the conditions of a long prepayment event start
_SUBJECT_TO_RE = re.compile(r",\s+subject\s+to\b|[;,]\s*(?:and\s+)?provided\b", re.IGNORECASE)


def _mp_pieces(sentence: str) -> list[tuple[str, str]]:
    """The prepayment events of one sentence of a mandatory-prepayment passage: (prefix, text) for each, without the words that
    only open a list ("... the following shall be applied to the prepayment of the Facilities: (a) ...") and without list markers."""
    colon = _lead_colon(sentence)
    if colon and _ITEM_MARKER_RE.match(sentence, colon) and not _has_figure(sentence[:colon]) and not _NEGATION_RE.search(sentence[:colon]):
        sentence = sentence[colon:]  # (a figure or a "no" in the lead-in applies to every item, and stays)
    out = []
    for key, item in _mp_cut(sentence):
        marker = _ITEM_MARKER_RE.match(item)
        out.append((key, item[marker.end():] if marker and len(item) - marker.end() >= 3 else item))
    return out


def _mp_cut(sentence: str) -> list[tuple[str, str]]:
    """The prepayment events of one sentence: (prefix, text) for each.

    A sentence that lists several events is cut into them ("(a) 100% of ... asset sales; (b) 50% of Excess Cash Flow"), unless
    a figure in front of the list applies to every item: then it stays whole under a joint prefix.
    """
    if _VOLUNTARY_RE.search(sentence) and not _MANDATORY_WORD_RE.search(sentence):
        return []  # a voluntary prepayment under a joint heading ("Prepayment and Cancellation")
    duty = bool(_DUTY_RE.search(sentence))
    named = [kind for kind, rx in _MP_KINDS if rx.search(sentence)]
    coc = bool(_COC_RE.search(sentence))
    if not named and not coc:  # an obligation of no particular kind (collateral shortfall, automatic commitment reduction)
        return [("Other", sentence)] if (duty or _MP_REDUCTION_RE.search(sentence)) and not _MP_MECHANICS_RE.search(sentence) else []
    first_kind = min((rx.search(sentence).start() for _, rx in _MP_KINDS if rx.search(sentence)), default=len(sentence))
    denied = bool(_NEGATION_RE.search(sentence[:first_kind]))  # "there shall be no mandatory prepayment from asset sales, debt issuances or ..."
    if (len(named) >= 2 or coc) and not denied:
        lead_end, spans = _items(sentence)
        marked = len(spans) >= 2  # numbered, bulleted or separated by semicolons
        if not marked:
            # "100% of ... asset sales, 100% of ... debt and 50% of Excess Cash Flow": each sweep opens with its own percentage
            cuts = [m for m in _PCT_ITEM_RE.finditer(sentence) if _depth_at(sentence, m.start()) == 0]
            edges = [0] + [x for m in cuts for x in (m.start(), m.end())] + [len(sentence)]
            sweeps = [sentence[edges[i]:edges[i + 1]] for i in range(0, len(edges), 2)]
            if len(sweeps) >= 2 and all(_PCT_RE.search(x) for x in sweeps) and len({_mp_key(x) for x in sweeps}) >= 2:
                return [(_mp_key(x) or "Other", x) for x in sweeps if not _COC_RE.search(x)]
        if marked and _figure_in_the_open(sentence[:lead_end]):
            spans = []
        elif not marked:
            spans = [] if _figure_in_the_open(sentence) else _comma_items(sentence, 0, len(sentence), ands=coc)
        events = [(a, b) for a, b in spans if _mp_kind(sentence[a:b]) or _COC_RE.search(sentence[a:b])]
        if len(events) >= 2:
            # in a marked list every item is an event; a comma list is only cut into the items that name one
            return [(_mp_key(sentence[a:b]) or "Other", sentence[a:b]) for a, b in (spans if marked else events) if not _COC_RE.search(sentence[a:b])]
    key = _mp_key(sentence)
    named_only = len(sentence.split()) <= 4  # an event listed by its name alone ("Illegality")
    if not key or (key == "Other" and (coc or (not duty and not named_only and "hoard" not in sentence.lower()))):
        return []  # the change of control has its own line; prose about amounts "in excess of" something is not an event
    if key != "Other" and _MP_MECHANICS_RE.search(sentence) and not _has_figure(sentence) and not duty:
        return []  # how proceeds are applied or declined, not when they are swept
    return [(key, sentence)]


def _mp_units(text: str, block: Block | None = None) -> list[tuple[int, int, bool]]:
    """The passages of a mandatory-prepayment section that are read one at a time: (start, end, opens an item of the section's list?).

    They are the section's sentences (or lines, or bullets); or, where the section is a numbered list under words that only open
    it ("... shall be applied to the prepayment of the Facilities: (a) ...  (b) ..."), the sentences of each item, without those
    opening words. Opening words that carry a figure, a negative or the name of an event say something of every item, and stay
    with them.
    """
    marks = _enumerators(text, _line_starts(block, text))
    if not marks or _sub_list(text, marks) or _depth_at(text, marks[0][0]) > 0:
        return [(s, e, False) for s, e in _points(text, block)]
    lead = text[:marks[0][0]]
    last = max((m.end() for m in _UNIT_RE.finditer(lead)), default=0)  # the opening words are the last sentence before the first marker
    opening = lead[last:]
    if _figure_in_the_open(opening) or _NEGATION_RE.search(opening) or _mp_kind(opening) or _COC_RE.search(opening):
        return [(s, e, False) for s, e in _points(text, block)]
    units = [(s, e, False) for s, e in _points(lead[:last])] if lead[:last].strip() else []
    for i, (_, start) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        for k, (x, y) in enumerate(_sentences(text[start:end])):
            x, y = _trim(text, start + x, start + y)
            if y - x >= 3:
                units.append((x, y, k == 0))
    return units


def _mp_events(text: str, block: Block | None = None) -> dict[str, list[str]]:
    """Prepayment events in a mandatory-prepayment passage, by kind: {prefix: [text of each event]}."""
    events: dict[str, list[str]] = {}
    for s, e, listed in _mp_units(text, block):
        passage = text[s:e]
        pieces = _mp_pieces(passage)
        if not pieces and listed and len(passage.split()) >= 4 and not _COC_RE.search(passage) and not _MP_MECHANICS_RE.search(passage) and not (
                _VOLUNTARY_RE.search(passage) and not _MANDATORY_WORD_RE.search(passage)):
            pieces = [("Other", passage)]  # an item of the section's own list is one of its events, whatever it is about
        for key, item in pieces:
            events.setdefault(key, []).append(item)
    return events


@_safe(_MP_BLANK)
def mandatory_prepayment(ctx: Ctx) -> dict:
    flow = _flow(ctx)
    eod = _eod_read(ctx)
    block = _section(ctx, _MP_LABEL, _MP_TAILS)
    mp_text, mp_src, mp_same = "", None, False
    if block is not None:
        mp_text, mp_src, mp_same = _read(ctx, block, _MP_LABEL)
    coc_line, trigger_line, evidence, coc_referred = _change_of_control(ctx, flow, eod, mp_text, mp_src)
    lines: list[str] = []
    more: list = []
    referred_events = False

    if mp_src is not None:
        events = _mp_events(mp_text, mp_src)
        none = _NONE_RE.match(mp_text)
        if none and not _EXCEPT_RE.match(mp_text, none.end()):  # "None.", "None. For the avoidance of doubt, no ..." (not "None, except that ...")
            lines.append("No mandatory prepayments (term sheet: '" + _squeeze(mp_text, 50 if len(mp_text) < 60 else 200) + "')")
            more.append(_quote_with_label(ctx, mp_src))
        elif events:
            for key in sorted(events, key=lambda k: _MP_ORDER.index(k.split(" / ")[0])):
                items = events[key]
                if key == "Other":
                    names = [x for x in items if len(x) <= 70 and not _DUTY_RE.search(x)]  # events listed by name
                    for x in [x for x in items if x not in names][:3]:
                        lines += _over_advance_lines(x)
                    lines += _pack("Other: ", [_lower_first(_squeeze(x, 90)) for x in names], max_lines=1)
                else:
                    pieces = [_unlabel(_first_sentence(_fix(x)), key) for x in items]
                    room = LINE_LIMIT + 130 - len(key) - 2  # (a sweep and its reinvestment terms are the heart of the row: they get the room they need)
                    if len(pieces) == 1 and len(_squeeze(pieces[0], 10000)) > room:
                        # one long event: the sweep on one line and its conditions ("subject to reinvestment ...") on the next, each
                        # shortened by its brackets without figures before anything is cut off its end
                        cut = next((m for m in _SUBJECT_TO_RE.finditer(pieces[0]) if m.start() >= 60 and _depth_at(pieces[0], m.start()) == 0), None)
                        parts = [pieces[0][:cut.start()], pieces[0][cut.start():].lstrip(" ,;")] if cut else pieces
                        lines += [f"{key}: {_squeeze(x, room, elide=True)}" for x in parts if x]
                    else:
                        lines += _pack(f"{key}: ", [_squeeze(x, 300) for x in pieces], LINE_LIMIT + 80, 1)
                for x in items[:1]:
                    at = mp_text.find(x)
                    more.append(_quote_item(ctx, mp_src, at, at + len(x), prefer=_PCT_OR_MONEY_RE) if at >= 0 else None)
        elif _defers(mp_text):
            lines.append("Other: mandatory prepayments " + _lower_first(_squeeze(mp_text, 180)))
            more.append(_quote(ctx, mp_src))
            referred_events = True
        elif not _COC_RE.search(mp_text):
            lines.append("Other: " + _squeeze(_first_sentence(mp_text), 220))
            more.append(_quote(ctx, mp_src))

    if mp_same and lines:
        lines[0] += _UNCHANGED

    # obligations to prepay or cash collateralise that sit outside a mandatory prepayment section
    mp_sq = _sq(mp_text)
    seen: set[int] = set()
    outside = False  # an obligation to prepay is stated outside the section
    for rx in (_OVER_LIMIT_RE, _OVER_COMMITMENT_RE, _MANDATORY_RE, _COVERAGE_CURE_RE):
        for m in rx.finditer(flow.text):
            s, e = flow.sentence(m.start(), m.end())
            sentence = flow.text[s:e]
            if rx is _COVERAGE_CURE_RE and _CURE_RIGHT_RE.search(sentence):
                continue
            if rx is _COVERAGE_CURE_RE:
                # the cure is a proviso of the covenant it belongs to: only that proviso is carried, in its own words
                cuts = [x for x in _PROVISO_SPLIT_RE.finditer(sentence) if _depth_at(sentence, x.start()) == 0]
                a = max((x.end() for x in cuts if x.end() <= m.start() - s), default=0)
                b = min((x.start() for x in cuts if x.start() >= m.end() - s), default=len(sentence))
                s, e = s + a, s + b
                sentence = flow.text[s:e]
            if s in seen or len(sentence) > 900 or not _DUTY_RE.search(sentence) or (mp_sq and _sq(sentence[:100]) in mp_sq):
                continue
            if _COC_RE.search(sentence) or _NOT_AN_EVENT_RE.search(sentence) or len(lines) >= 5:
                continue
            quote = flow.quote(ctx, m.start(), m.end())
            if not quote:
                continue
            seen.add(s)
            if rx is _COVERAGE_CURE_RE:
                lines += _over_advance_lines(sentence, limit=LINE_LIMIT + 150)
            else:
                before = flow.text[slice(*flow.sentence(s - 2))] if s >= 2 else ""
                lines += _over_advance_lines(sentence, before)
            more.append(quote)
            outside = True

    # an anti-cash hoarding row counts only if it says that loans are to be prepaid (a bare amount may be a draw-stop: see other covenants)
    hoard = _section(ctx, _HOARDING_LABEL)
    if hoard is not None and not any("hoard" in x.lower() for x in lines):
        text, src, same = _read(ctx, hoard, _HOARDING_LABEL)
        value = _squeeze(_BULLET_RE.sub(" ", text), 190)
        if value and _DUTY_RE.search(text):
            lines.append(f"Other: anti-cash hoarding - {value}" + (" (unchanged from existing terms)" if same else ""))
            more.append(_quote_with_label(ctx, src))

    lines = [x for x in lines if x]
    if not lines and coc_line.endswith(NS) and not trigger_line and not evidence:
        return _blank(*_MP_BLANK)
    head = [coc_line or f"Change of Control: {NS}"] + ([trigger_line] if trigger_line else [])
    if not lines:
        lines = [f"Other mandatory prepayment events: {NS}"]
    stated_events = (any(more) and not referred_events) or outside
    referred = not stated_events and (coc_referred or referred_events)
    return _entry(head + lines, [e for e in evidence if e][:2] + [e for e in more if e], referred, _MP_BLANK)


# ======================================================================================================
# Transferability
# ======================================================================================================

# "Assignments and Participations:", "Assignments:", "Transfers:", "Transferability:", "Changes to the Lenders:", "Successors and Assigns:"
_TRANSFER_LABEL = (r"(?:lender\s+)?assignments?(?:\s*(?:and|/|&|,))?(?:\s*participations?)?|transfers?(?:\s*(?:and|/|&)(?:\s*assignments?)?)?|transferability|"
                   r"assignability|assignments?\s+and\s+transfers?|(?:assignments?|transfers?)(?:\s+(?:and|/|&)\s+(?:assignments?|transfers?))?\s+by\s+(?:the\s+)?lenders?|"
                   r"transfers?\s+(?:provisions?|rights?|restrictions?)|changes?\s+to\s+(?:the\s+)?lenders?|lender\s+transfers?|successors\s+and\s+assigns")
# the section must actually speak of assignments, transfers or participations
_TRANSFER_WORD_RE = re.compile(r"assign|transfer|participation", re.IGNORECASE)
# the borrower side, as assignments provisions name it (whitespace-free text)
_PARTY_SQ = r"(?:leadborrower|borrowerrepresentative|borrowers?|company|parent|holdings|obligors'?agent|issuer)"
# the patterns below run on whitespace-free lower-case text (see _sq)
_SQ_COUNT = r"(?:(?P<n{0}>\d{{1,3}})|[a-z\-]{{3,22}}?\((?P<p{0}>\d{{1,3}})\)|(?P<w{0}>" + _SIMPLE_NUMBER_WORDS + r"))(?P<u{0}>businessdays?|calendardays?|days?)"
# "not to be unreasonably withheld", "shall not be unreasonably withheld or delayed", "(not unreasonably withheld)"
_SQ_UNREASONABLY_RE = re.compile(r"not(?:tobe|be)?unreasonablywithheld(?P<more>(?:,|or|and|conditioned|delayed)*)")
# "shall be deemed to have consented ... unless it shall object ... within ten (10) business days"; "consent deemed given after 5 Business Days";
# "deemed consent after 5 business days", "deemed after 5 business days", "deemed consent if no response within 10 Business Days"
_SQ_DEEMED_RE = re.compile(r"deemedtohave(?:consented|approved|given(?:its|their)(?:consent|approval))[^.;]{0,330}?within" + _SQ_COUNT.format("")
                           + r"|deemed(?:tohavebeen|tobe)?(?:given|granted|provided|obtained)[^.;]{0,200}?" + _SQ_COUNT.format("2")
                           + r"|deemed(?:consent|approval)?(?:after|within|if[^.;]{0,60}?within|absent[^.;]{0,60}?within)" + _SQ_COUNT.format("3"))
# "deemed consent after [ ] Business Days": the period is left blank
_SQ_DEEMED_BLANK_RE = re.compile(r"deemed[^.;]{0,330}?\[[●•_.]*\]\)?(?:business|calendar)?days")
# "to another Lender, an affiliate of a Lender or an Approved Fund", "to other Lenders or to any affiliate of a Lender"
_SQ_TO_LENDER_RE = re.compile(r"(?:another|other|a|any|existing)lenders?(?:,|or)[^.;]{0,40}?affiliates?of(?:a|any|such)lender"
                              r"(?P<fund>[^.;]{0,30}?(?:approvedfund|relatedfund|fundmanagedbyalender(?:oranaffiliateofalender)?))?")
# the shorthand of a summary table: "no consent to affiliates, other lenders ...", "to Lenders and their affiliates"
_SQ_TO_LENDER_SHORT_RE = re.compile(r"(?:to|for)(?:other|existing|another)?(?:lenders?(?:,|or|and)(?:their|its|lender)?affiliates?|affiliates?(?:,|or|and)(?:other|existing)?lenders?)"
                                    r"(?P<fund>(?:,|or|and)(?:related|approved)funds?)?")
# "without the consent of the Company ... to any of its affiliates"
_SQ_OWN_AFFILIATE_RE = re.compile(r"withoutthe(?:prior)?(?:written)?consent[^.]{0,260}?toanyofitsaffiliates")
# the kind of default that lifts the consent requirement ("payment or bankruptcy", "payment, bankruptcy or insolvency", "specified"), as a named group
_SQ_EOD_KIND = r"(?P<kind{0}>(?:(?:payment|bankruptcy|insolvency|specified|certain|major)(?:,|or|and|/)*)+)?(?:\([^)]{{0,60}}\))?"
# a kind of default named with its own "event of default", before or after another: "a payment event of default or (a bankruptcy event of default ...)"
_SQ_EOD_EACH = r"(?:payment|bankruptcy|insolvency)(?:eventsofdefault|eventofdefault|eod|defaults?)"
# "unless a payment or bankruptcy Event of Default has occurred and is continuing", "none during a payment or bankruptcy EoD",
# "if a payment event of default or bankruptcy event of default has occurred and is continuing"
_SQ_EOD_RE = re.compile(
    r"(?P<pre>(?:" + _SQ_EOD_EACH + r"(?:,|or|and|/)+(?:an?)?)+)?"
    + _SQ_EOD_KIND.format("") + r"(?P<dflt>defaultor)?(?:eventofdefault|eod)"
    r"(?P<qual>\([^)]{0,80}\)|(?:under|pursuantto|describedin|referredtoin|specifiedin|setforthin)(?:[^.;]|\.(?=\d)){0,90}?)?"  # "... under clause (a), (b) or (f) of ...", "... under Section 7.01(a) ..."
    r"(?:hasoccurredandiscontinuing|iscontinuing|exists|thenexists|shallhaveoccurredandbecontinuing|continues)"
    r"|(?:during|upon|following)(?:the)?(?:continuanceof)?(?:a|an|any)?" + _SQ_EOD_KIND.format("2") + r"(?:eventofdefault|eod)"
    r"(?P<post>(?:(?:,|or|and|/)+(?:an?)?" + _SQ_EOD_EACH + r")*)")
# ", so long as no", ", unless an", "and, if a" in front of a default: the condition is put before the party it is said of
# ("... the swing line lender and, so long as no event of default is continuing, the Company")
_SQ_CONDITION_AHEAD_RE = re.compile(r",(?:and)?(?:solongas|aslongas|unless|if|when|while|absent|except(?:if|when|while|during)?|provided(?:that)?)(?:thereisno|thereexistsno|no|an?|any)?$")
# a sentence that goes on about a requirement stated just before it ("This requirement shall not apply while ...")
_SQ_BACK_REF_RE = re.compile(r"(?:this|such|that|theforegoing)(?:consent)?(?:requirement|restriction|condition)")
# the kind of default named after the words "Event of Default": "... under the payment or bankruptcy provisions", "... (payment or insolvency only)"
_SQ_EOD_TAIL_RE = re.compile(r"(?:\(|under|pursuantto|describedin|referredtoin|specifiedin|setforthin|arising|resulting|relatingto|withrespectto|inrespectof|dueto|ofthetype)"
                             r"[^.;]{0,70}?(?:payment|bankruptcy|insolvency)[^.;)]{0,40}")
# a currency, in whitespace-free text
_SQ_CURRENCY = r"(?:us\$|\$|€|£|eur|gbp|usd)"
# an amount in whitespace-free text: "$5,000,000", "us$10million", "eur5,000,000"
_SQ_AMOUNT = _SQ_CURRENCY + r"[\d,]*\d(?:\.\d+)?(?:million|mm|bn|billion|m(?![a-z]))?"
# the words between "minimum" and its amount: "minimum amount of", "minimum assignment amount shall be", "minimum transfer amount equal to"
_SQ_MINIMUM = r"minimum(?:aggregate)?(?:assignment|transfer)?(?:amounts?|levels?)(?:shallbe|of|equalto|is|:)?(?:notlessthan)?"
# "minimum amount of $5,000,000", "minimum assignment amount shall be $5,000,000", "minimum ... level of $10,000,000 and increments of $1,000,000"
_SQ_MINIMUM_RE = re.compile(_SQ_MINIMUM + r"(?P<amt>" + _SQ_AMOUNT + r")(?:(?:and|,)?(?:in)?(?:integral)?(?:increments|multiples)of(?P<inc>" + _SQ_AMOUNT + r"))?")
# "minimum amounts of $[●]": the amount is left blank
_SQ_MINIMUM_BLANK_RE = re.compile(_SQ_MINIMUM + _SQ_CURRENCY + r"?\[[●•_.]*\]")
# "... of $5,000,000 for the Revolving Facility and $1,000,000 for the Term Facility": a second minimum for another facility
_SQ_FOR = r"(?:for|inthecaseof|withrespectto|inrespectof)"
# (matched directly after the first minimum)
_SQ_SECOND_MINIMUM_RE = re.compile(_SQ_FOR + r"[a-z()]{3,45}?and(?P<amt>" + _SQ_AMOUNT + r")" + _SQ_FOR)
# "... of $5,000,000 and $1,000,000, respectively", "... of $5,000,000 (in the case of the Revolving Facility) and $1,000,000 (...)":
# a second minimum directly after the first (matched there)
_SQ_PAIRED_AMOUNT_RE = re.compile(r"(?:\([^)]{0,60}\))?(?:,|and|or)+(?P<amt>" + _SQ_AMOUNT + r")")
# an amount in whitespace-free text, on its own
_SQ_AMOUNT_RE = re.compile(_SQ_AMOUNT)
# what stands in front of an amount that is not a minimum: a fee, or the increments above the minimum
_SQ_NOT_A_MINIMUM_RE = re.compile(r"fee|increments?|multiples?|inexcess")
# "... $3,500 processing fee": the amount of a fee, named after it
_SQ_FEE_AFTER_RE = re.compile(r"[a-z]{0,24}fee")
# "assignment fee in the amount of $3,500", "administrative fee of $3,500"
_SQ_FEE_RE =re.compile(r"(?:assignment|administrative|processing|recordation|transfer|service)fee(?:intheamount)?of(?P<amt>" + _SQ_CURRENCY + r"[\d,]*\d)")
# a sentence that speaks of consent or approval
_SQ_CONSENT_WORD_RE = re.compile(r"consent|approv")
# "without the consent of", "without consent": a carve-out, not a requirement
_SQ_NO_CONSENT_RE = re.compile(r"without(?:the|any)?(?:prior)?(?:written)?(?:consent|approval)")
# "the consent of", "consent, not to be unreasonably withheld, of", "approved by": consent that is asked of someone
_SQ_ASKED_RE = re.compile(r"(?<!without)(?<!withoutthe)(?:consent|approval)s?(?:,[^,]{0,60},)?of|approvedby")
# the words in front of "consent of the Borrower" that turn it into its opposite
_SQ_NEGATED_RE = re.compile(r"(?:no|without(?:the|any)?(?:prior)?(?:written)?|neitherthe|notsubjecttothe|norequirementfor(?:the)?)$")
# ... and the words after it that do the same ("... shall not be required")
_SQ_NOT_REQUIRED_RE = re.compile(r"(?:\([^)]{0,80}\))?(?:shall|will|is|are)?not(?:be)?(?:required|needed|necessary)")
# a verb right after a party named in a list: the party starts a clause of its own ("... and the Borrower shall be notified") ...
_SQ_NEW_CLAUSE_RE = re.compile(r"s?(?:shall|will|may|must|has|have|agrees?|is|are)(?!sue)")
# ... unless the clause says that its consent is needed ("... and the Borrower shall be required")
_SQ_IS_REQUIRED_RE = re.compile(r"s?(?:shall|will|must|is|are)?(?:each)?(?:be)?(?:required|necessary|needed|obtained)")
# "(but not the Company)", "other than the Borrower": the party is named to leave it out
_SQ_NOT_PARTY_RE = re.compile(r"(?:not|no|nor|otherthan|excluding|except(?:for)?)(?:of)?(?:the|any|each)?$")
# "no consent of the Borrower shall be required (i) ...", "the approval of the Borrowers shall not be required (a) ...", "... the Borrower, unless (i) ...":
# the cases in which consent is not needed, where the term sheet sets them out as a numbered list (ordinary text)
_NO_CONSENT_LIST_RE = re.compile(
    r"(?P<clause>no\s+(?:such\s+)?(?:consent|approval)\b[^.;]{0,80}?(?:shall|will)\s+be\s+(?:required|necessary)|"
    r"(?:consent|approval)\b[^.;]{0,80}?(?:shall|will)\s+not\s+be\s+(?:required|necessary)|(?:consent|approval)\b[^.;]{0,40}?\bnot\s+required|\bunless)"
    r"\s+(?=\(\s?(?:i|a|1)\s?\))", re.IGNORECASE)
# where such a list ends: a semicolon, the end of the sentence, a proviso, or the next consenting party ("..., (b) the Administrative Agent")
_NO_CONSENT_END_RE = re.compile(r";|\.\s|\.$|,?\s+provided\b|,\s+(?:and\s+)?\([a-z]\)\s+(?:the|each)\s|,\s+and\s+the\s", re.IGNORECASE)
# the borrower side, in ordinary text
_BORROWER_WORD_RE = re.compile(r"\b(?:Borrowers?|Company|Parent|Holdings|Issuer|Obligors['’]?\s+Agent)\b", re.IGNORECASE)
# "no consent of the", "without the approval of the" directly in front of a party: its consent is not needed
_SQ_WAIVED_FOR_RE = re.compile(r"(?:no|without(?:the|any)?(?:prior)?(?:written)?|neither(?:the)?)(?:consent|approval)s?of(?:the|each|any)?$")
# "... Agent's prior written consent", "... Agent consent": the words after a party that make it a consenting one
_SQ_OWN_CONSENT_RE = re.compile(r"(?:'s)?(?:prior)?(?:written)?(?:consent|approval)")
# an exception for transfers within the lender side ("to a Lender", "to its affiliates", "to an Approved Fund")
_SQ_LENDER_SIDE_RE = re.compile(r"lender|affiliate|approvedfund")
# the party is named as the addressee of a notice or a fee, not as someone whose consent is needed
_SQ_ADDRESSEE_RE = re.compile(r"(?:noticeto|notify|deliveredto|deliveryto|copyto|payableto|paidto|feeto|recordedby|acceptedby|determinedby|discretionof|waivedby)"
                              r"(?:the|each|any)?$")
# "to", "to the", "to each" directly in front of a party: the party is where something goes, not one of those whose consent is asked
_SQ_TO_PARTY_RE = re.compile(r"to(?:the|each|any|an?)?$")
# the agent, as a consenting party
_SQ_AGENT_RE =re.compile(r"administrativeagent|facilityagent|theagent|agent(?=consent|approval)")
# the letter of credit issuers, as consenting parties ("each Issuing Bank", "the Fronting Bank", "each letter of credit issuing bank")
_SQ_ISSUER_RE = re.compile(r"issuingbanks?|issuinglenders?|frontingbanks?|l/cissuers?|letterofcreditissu(?:ers?|ingbanks?)")
# the swingline lender, as a consenting party
_SQ_SWING_RE = re.compile(r"swing(?:line)?lenders?|lenderofanyswinglineloan|swinglinebanks?")
# "freely assignable", "without the consent of the Borrower"
_SQ_UNRESTRICTED_RE = re.compile(r"freely(?:assignable|transferable)|without(?:the)?(?:prior)?(?:written)?consentof(?:the|any)?" + _PARTY_SQ + r"(?!or)|"
                                 r"noconsentof(?:the|any)?" + _PARTY_SQ + r"(?:shall|will|is)?(?:be)?(?:required|needed|necessary)|"
                                 r"(?:consent|approval)of(?:the|any)?" + _PARTY_SQ + r"(?:shall|will|is)?not(?:be)?(?:required|needed|necessary)|"
                                 r"(?:no|without)" + _PARTY_SQ + r"consent|" + _PARTY_SQ + r"consent(?:is|shallbe|willbe)?not(?:be)?(?:required|needed)")
# the sentence is about participations (and, unless it also speaks of assignments, says nothing about consent to those)
_PARTICIPATION_WORD_RE = re.compile(r"participation", re.IGNORECASE)
# an assignment by way of security (to a Federal Reserve Bank, a pledge): free of consent in any case, and no sign of free transferability
_SQ_SECURITY_RE = re.compile(r"assecurity|federalreserve|pledge|centralbank")
# transferee restrictions and participations (ordinary text)
_ELIGIBLE_RE = re.compile(r"(?:certain\s+|one\s+or\s+more\s+)?eligible\s+assignees?(?:\s*\(\s*as\s+defined[^)]{0,80}\))?", re.IGNORECASE)
# "to other financial institutions", "to banks and financial institutions"
_INSTITUTIONS_RE = re.compile(r"(?:other\s+|another\s+)?(?:banks?(?:\s+(?:and|or)|,)\s+)?financial\s+institutions?"
                              r"(?:(?:,|,?\s+and|,?\s+or)\s+(?:other\s+)?(?:institutional\s+)?(?:funds|lenders|investors))*", re.IGNORECASE)
# "customary disqualified Lenders provisions", "Disqualified Institutions"
_DISQUALIFIED_RE = re.compile(r"(?:customary\s+)?disqualified\s+(?:lenders?|institutions?)(?:\s+(?:provisions?|list))?", re.IGNORECASE)
# the mention reads as a provision in its own right ("customary disqualified Lenders provisions", "Disqualified Lender list")
_PROVISION_WORD_RE = re.compile(r"customary|provisions?$|list$", re.IGNORECASE)
# "competitors", "a person engaged in a similar line of business"
_COMPETITOR_RE = re.compile(r"competitors?|similar\s+line\s+of\s+business", re.IGNORECASE)
# who a transfer may not be made to, and the words that make a sentence a bar on transfers
_BARRED_RE = re.compile(r"natural\s+persons?|disqualified\s+(?:lenders?|institutions?)|competitors?|defaulting\s+lenders?|distressed\s+(?:debt\s+)?funds?|"
                        r"(?:Borrowers?|Company|Parent|Holdings)[^.;]{0,25}?(?:or|and)\s+(?:any\s+of\s+)?(?:its|their)\s+(?:respective\s+)?(?:affiliates|subsidiaries)",
                        re.IGNORECASE)
# "(other than Disqualified Institutions, natural persons, the Company or any of its affiliates)": who is left out of the permitted transferees
_EXCLUDED_RE = re.compile(r"(?:assignees?|institutions?|persons?|entit(?:y|ies)|lenders?|banks?|funds?)\s*\(\s*(?:other\s+than|excluding|but\s+not)\s+(?:to\s+)?"
                          r"(?!with\s+respect|in\s+the\s+case|in\s+respect)([^()]{5,200})\)", re.IGNORECASE)
# the negative that makes a sentence a bar ("No assignments ...", "... are not permitted", "prohibited")
_BAR_WORD_RE = re.compile(r"\bno\b|\bnot\b|prohibit", re.IGNORECASE)
# the sentence is about assignments or transfers
_ASSIGN_WORD_RE = re.compile(r"assign|transfer", re.IGNORECASE)
# "Notwithstanding the foregoing, ...": dropped from the front of a sentence that is carried into a line
_NOTWITHSTANDING_RE = re.compile(r"^notwithstanding\s+[^,]{3,40},\s*", re.IGNORECASE)
# "Lenders will be permitted to sell participations", "each Lender selling a participation", "participations will be ..."
_PARTICIPATION_RE = re.compile(r"(?:sell|grant|sales?\s+of|selling)\s+(?:a\s+)?participations?|participations?\s+(?:will|shall|may|are)\b|"
                               r"^participations?\s+(?:to|in)\b[^.;]{0,90}?\b(?:will|shall|may|are)\s+(?:be\s+)?(?:permitted|allowed|made)", re.IGNORECASE)
# the facility a clause of the assignments provision is about, in whitespace-free text ("... in respect of the Revolving Credit Facility")
_SQ_FACILITY_RE = re.compile(r"(?:revolving(?:credit)?|delayed-?draw(?:term)?(?:loan)?|incremental(?:term)?(?:loan)?|term(?:loan)?[ab]?\d?|letterofcredit|swing-?line)"
                             r"(?:facilit(?:y|ies)|loans?|commitments?)")
# "(it being understood that ...)", "(it being acknowledged and agreed that ...)": an explanation in brackets, left out of a line
_UNDERSTOOD_RE = re.compile(r"\s*\(it\s+being\s+(?:understood|acknowledged|agreed)(?:[^()]|\([^()]*\))*\)", re.IGNORECASE)
# a defined name in quotes: (the "Borrower"), (the "Company")
_DEFINED_NAME_RE = re.compile(r"[“\"]\s*([^”\"]{2,40}?)\s*[”\"]")
# defined names in the Borrower section that are not the borrower (the "Guarantee", the "Facility", the "Lenders")
_OTHER_PARTY_PREFIXES = ("guarant", "facilit", "lender", "loan", "commitment", "agent", "arranger")


def _aliases(ctx: Ctx) -> str:
    """Whitespace-free regex of the names the term sheet defines for its borrower(s) in the Borrower section (a short name in
    quotes, "the Company"), so that "with the consent of <that name>" reads as Borrower consent."""
    names: list[str] = []
    for block in _sections(ctx, r"borrowers?")[:2]:
        for m in _DEFINED_NAME_RE.finditer(block.text[:900]):
            name = _sq(m.group(1))
            if len(name) >= 2 and not name.startswith(_OTHER_PARTY_PREFIXES):
                names.append(re.escape(name))
    return "|".join(sorted(set(names), key=len, reverse=True))


def _sq_amount(text: str) -> str:
    """A whitespace-free amount ("$5,000,000", "us$10million", "gbp5,000,000") in house style."""
    text = text.replace("us$", "$").rstrip(",.")
    return _restyle(re.sub(r"(?<=\d)(?=million|billion)", " ", text))


def _sq_fee(text: str) -> str:
    """A whitespace-free fee ("$3,500", "gbp3,000") as printed, with its currency code set off."""
    text = text.replace("us$", "$").rstrip(",.")
    m = re.match(r"[a-z]{3}", text)
    return f"{m.group(0).upper()} {text[3:]}" if m else text


def _asks_borrower(sq: str, party: str) -> bool:
    """The provision makes an assignment subject to the borrower's consent or approval ("no consent of the Borrower shall be
    required" and "without the consent of the Borrower" are the opposite and do not count)."""
    # "consent of the Borrower"; "consent, not to be unreasonably withheld, of the Agent and, so long as ..., the Company" (the borrower
    # at the end of a list of consenting parties, after a comma or "and"); "approved by the Agent and the Borrowers"; "Borrower consent"
    asks = (rf"(?:consent|approval)s?(?:,[^,]{{0,60}},)?of(?:\(\w\))?(?:the|each|any)?(?P<who>{party})|"
            rf"(?:consent|approval)s?(?:,[^,]{{0,60}},)?of(?:(?!without)[^.;]){{1,260}}?(?:,|and|or)(?:\(\w\))?(?:the|each|any)?(?P<listed>{party})|"
            rf"approvedby[^.;]{{0,70}}?(?P<who2>{party})|(?P<who3>{party})(?:'s|s')?(?:prior)?(?:written)?(?:consent|approval)")
    for m in re.finditer(asks, sq):
        # ("Borrower shall" is read as "Borrowers" + "hall": what follows the party is looked at from its last letter as well)
        if _SQ_NEGATED_RE.search(sq[max(0, m.start() - 26):m.start()]) or any(_SQ_NOT_REQUIRED_RE.match(sq, at) for at in (m.end(), m.end() - 1)):
            continue
        if m.group("listed"):
            who, end = m.start("listed"), m.end("listed")
            if _SQ_ADDRESSEE_RE.search(sq[max(0, who - 30):who]) or _SQ_WAIVED_FOR_RE.search(sq[max(0, who - 60):who]) or _SQ_NOT_PARTY_RE.search(sq[max(0, who - 20):who]):
                continue  # "... upon notice to the Company", "... but no consent of the Company", "... (but not the Company)"
            if any(_SQ_NEW_CLAUSE_RE.match(sq, at) and not _SQ_IS_REQUIRED_RE.match(sq, at) for at in (end, end - 1)):
                continue  # "... of the Agent, and the Borrower shall be notified": the borrower is the subject of another clause
        return True
    return "deemedtohaveconsented" in sq


def _consenting(clause: str, rx: re.Pattern) -> re.Match | None:
    """The party matched by ``rx`` is one whose consent the (whitespace-free) clause asks for, not merely the addressee of a notice."""
    for m in rx.finditer(clause):
        before = clause[max(0, m.start() - 600):m.start()]  # "consent ... of (a) the Borrower, unless ...; provided that ..., and (b) the Agent"
        if _SQ_ADDRESSEE_RE.search(before) or _SQ_WAIVED_FOR_RE.search(before) or any(_SQ_NOT_REQUIRED_RE.match(clause, at) for at in (m.end(), m.end() - 1)):
            continue
        if _SQ_OWN_CONSENT_RE.match(clause, m.end()):
            return m
        if _SQ_TO_PARTY_RE.search(before):
            continue  # "... a processing fee of $3,500 to the Agent", "assignments to an Issuing Bank": someone a thing goes to
        if _SQ_ASKED_RE.search(before):
            return m
    return None


def _party_name(rx: re.Pattern, word: str) -> str:
    """The consenting party matched by ``rx``, named as the term sheet names it."""
    if rx is _SQ_SWING_RE:
        return "Swingline Lender"
    if rx is _SQ_ISSUER_RE:
        return "Fronting Bank" if "fronting" in word else "L/C Issuer" if "issuer" in word else "Issuing Lender" if "issuinglender" in word else "Issuing Bank"
    return "Facility Agent" if "facility" in word else "Administrative Agent" if "administrative" in word else "Agent"


def _fund_words(fund: str) -> str:
    """The fund that may take an assignment without consent, as the (whitespace-free) provision names it."""
    if "managedby" in fund:
        return "a fund managed by a Lender" + (" or an affiliate of a Lender" if "oranaffiliate" in fund else "")
    return "a related fund" if "relatedfund" in fund else "an approved fund"


def _eod_kind_words(m: re.Match, sq: str) -> str:
    """The kind of event of default that lifts the consent requirement, as it reads in a line ("payment or bankruptcy ", "specified ", "")."""
    named = (m.group("pre") or "") + (m.group("kind") or m.group("kind2") or m.group("qual") or "") + (m.group("post") or "")
    if not named:
        tail = _SQ_EOD_TAIL_RE.match(sq, m.end())
        named = tail.group(0) if tail else ""
    words = [w for w in ("payment", "bankruptcy", "insolvency") if w in named]
    if not words:
        return "specified " if named else ""
    return (", ".join(words[:-1]) + " or " + words[-1] if len(words) > 1 else words[0]) + " "


def _lifting_default(text: str, block: Block | None, party: str) -> tuple[re.Match, str, int] | None:
    """The "event of default has occurred and is continuing" that lifts the borrower's consent requirement: (match, the
    whitespace-free sentence it was found in, start of that sentence in ``text``).

    It is read from a sentence that speaks of consent: the borrower's, or nobody's in particular ("No consent ... during an event
    of default", "This requirement shall not apply while ..."). An event of default named in another provision of the section (a
    condition of borrower buy-backs, a voting right of participants) lifts nothing, and neither does one in a sentence that is
    about the consent of another party only ("The consent of the Agent shall be required unless ...").
    """
    hits = []
    for s, e in _points(text, block):
        clause = _sq(text[s:e])
        if not (_SQ_CONSENT_WORD_RE.search(clause) or "consult" in clause or _SQ_BACK_REF_RE.search(clause)):
            continue
        for m in _SQ_EOD_RE.finditer(clause):
            whose = _default_said_of(clause, m, party)
            if whose != "other":  # (a default that lifts the consent of the Agent or an Issuing Bank alone lifts nothing of the borrower's)
                hits.append((whose != "borrower", s, m, clause))
                break
    if not hits:
        return None
    _, s, m, clause = min(hits, key=lambda h: (h[0], h[1]))
    return m, clause, s


def _default_said_of(clause: str, m: re.Match, party: str) -> str:
    """Whose consent the default matched at ``m`` lifts in a (whitespace-free) sentence: "borrower", "other" (the agent, an issuing
    bank or the swingline lender, and not the borrower) or "" (nobody in particular).

    It is the party named between the last mention of consent before the default and the default itself ("... provided that the
    consent of the Agent shall not be required if an Event of Default ..."), or, where the condition stands in front of the party
    it is said of ("... and, so long as no Event of Default is continuing, the Company"), the party named right after it.
    """
    def who(stretch: str) -> str:
        if re.search(party, stretch):
            return "borrower"
        for rx in (_SQ_AGENT_RE, _SQ_ISSUER_RE, _SQ_SWING_RE):
            for x in rx.finditer(stretch):
                if not (_SQ_ADDRESSEE_RE.search(stretch[:x.start()]) or _SQ_TO_PARTY_RE.search(stretch[:x.start()])):
                    return "other"  # (the addressee of a notice is not a party whose consent is spoken of)
        return ""

    if _SQ_CONDITION_AHEAD_RE.search(clause[:m.start()]):  # a condition set off by commas in front of the party it is said of
        ahead = re.match(r",(?:the|each|any)?(?:(?P<b>" + party + r")|(?P<o>(?:administrative|facility)?agent|issuing|fronting|swing|l/c|letterofcredit))", clause[m.end():])
        if ahead:
            return "borrower" if ahead.group("b") else "other"
    edges = [w.start() for w in re.finditer(r"consent|approv|consult", clause[:m.start()])] + [m.start()]
    for i in range(len(edges) - 2, -1, -1):
        found = who(clause[edges[i]:edges[i + 1]])
        if found:
            return found
    return who(clause[:edges[0]])


def _facility_of(clause: str, at: int, end: int) -> str:
    """The facility a minimum amount at clause[at:end] is said of: the one named last before it in its (whitespace-free)
    sentence, else the first named after it; "" if the sentence names none."""
    before = list(_SQ_FACILITY_RE.finditer(clause, 0, at))
    m = before[-1] if before else _SQ_FACILITY_RE.search(clause, end)
    if not m:
        return ""
    word = m.group(0)
    return next(name for key, name in (("revolv", "Revolving"), ("delayed", "Delayed Draw"), ("incremental", "Incremental"), ("letter", "Letters of Credit"),
                                       ("swing", "Swingline"), ("term", "Term Loan")) if key in word)


def _minimums(text: str, block: Block | None) -> str:
    """The minimum assignment amount(s), in house style: one amount, or each amount with the facility its sentence names when the
    term sheet sets more than one ("$5m (Revolving) / $1m (Term Loan)")."""
    found: list[tuple[str, str]] = []  # (amount, facility)
    single = ""
    for s, e in _points(text, block):
        if _PARTICIPATION_WORD_RE.search(text[s:e]) and not _ASSIGN_WORD_RE.search(text[s:e]):
            continue  # a minimum set for participations is not a minimum for assignments
        clause = _sq(text[s:e])
        for m in _SQ_MINIMUM_RE.finditer(clause):
            amount = _sq_amount(m.group("amt"))
            second = None if m.group("inc") else _SQ_SECOND_MINIMUM_RE.match(clause, m.end())
            if not single:
                single = amount + (f" (increments of {_sq_amount(m.group('inc'))})" if m.group("inc") else
                                   f" / {_sq_amount(second.group('amt'))} (by facility)" if second else "")
            if amount not in [x for x, _ in found]:
                found.append((amount, _facility_of(clause, m.start("amt"), m.end("amt"))))
            # a further amount in the rest of the sentence ("... (or $1,000,000 in the case of Term Loans)", "...; $1,000,000 for Term
            # Loans", "... and $1,000,000, respectively") is another minimum, unless it is a fee or an increment; which amount goes
            # with which facility is left to the term sheet
            for x in _SQ_AMOUNT_RE.finditer(clause, m.end(), m.end() + 220):
                if _SQ_NOT_A_MINIMUM_RE.search(clause, max(m.end(), x.start() - 45), x.start()) or _SQ_FEE_AFTER_RE.match(clause, x.end()):
                    continue
                if _sq_amount(x.group(0)) not in [a for a, _ in found]:
                    found.append((_sq_amount(x.group(0)), ""))
    if len(found) <= 1 or "(by facility)" in single:
        return single
    if all(name for _, name in found) and len({name for _, name in found}) == len(found):
        return " / ".join(f"{amount} ({name})" for amount, name in found)
    return " / ".join(amount for amount, _ in found) + " (more than one minimum is set: see the assignments provision)"


def _unread_exceptions(text: str, alias: str) -> str:
    """The numbered list of cases in which the borrower's consent is not needed, as written, if it holds a case the rule has no
    wording for ("(i) after the Closing Date, (ii) ..."); "" if every case is one the rule reads (a default, a transfer to a Lender
    or its affiliate) or there is no such list."""
    fixed = _fix(text)
    names = re.compile(_BORROWER_WORD_RE.pattern + (rf"|\b(?:{alias})\b" if alias else ""), re.IGNORECASE)
    for m in _NO_CONSENT_LIST_RE.finditer(fixed):
        said_of = fixed[max(0, m.start() - 200):m.end()] if m.group("clause").lower() == "unless" else m.group("clause")
        if not names.search(said_of):
            continue  # the consent of someone else (the Agent, an Issuing Bank)
        rest = fixed[m.end():m.end() + 460]
        marks = _enumerators(rest)
        if len(marks) < 2:
            continue
        stop = _NO_CONSENT_END_RE.search(rest, marks[-1][1])
        rest = rest[:stop.start()] if stop else rest
        items = [rest[marks[i][1]:marks[i + 1][0] if i + 1 < len(marks) else len(rest)] for i in range(len(marks))]
        read = [bool(_SQ_EOD_RE.search(_sq(x)) or _SQ_TO_LENDER_RE.search(_sq(x)) or _SQ_TO_LENDER_SHORT_RE.search(_sq(x))
                     or _SQ_LENDER_SIDE_RE.search(_sq(x))) for x in items]
        if not all(read):
            return _squeeze(rest, 240)
    return ""


def _consent_terms(ctx: Ctx, text: str, block: Block | None = None) -> dict:
    """What an assignments provision says about consents, read from whitespace-free text."""
    sq = _sq(text)
    alias = _aliases(ctx)
    party = f"(?:{_PARTY_SQ}|{alias})" if alias else _PARTY_SQ
    out: dict = {"consent": _asks_borrower(sq, party), "unread": _unread_exceptions(text, alias)}
    out["consultation"] = bool(re.search(rf"consultationwith(?:the)?{party}|consult(?:ing)?with(?:the)?{party}|{party}(?:'s|s')?consultation", sq))
    m = _SQ_UNREASONABLY_RE.search(sq)
    out["unreasonably"] = ("not to be unreasonably withheld" + (" or delayed" if "delayed" in m.group("more") else "")) if m else ""
    m = _SQ_DEEMED_RE.search(sq)
    out["deemed"] = ""
    if m:
        raw = next((m.group(g + t) for t in ("", "2", "3") for g in ("n", "p") if m.group(g + t)), None)
        n = int(raw) if raw else _NUMBER_WORDS.get(next((m.group("w" + t) for t in ("", "2", "3") if m.group("w" + t)), ""))
        unit = "business day" if "business" in next((m.group("u" + t) for t in ("", "2", "3") if m.group("u" + t)), "") else "day"
        if n:
            out["deemed"] = f"deemed given absent objection within {n} {unit}{'' if n == 1 else 's'}"
    if not out["deemed"] and _SQ_DEEMED_BLANK_RE.search(sq):
        out["deemed"] = "deemed consent period left blank in term sheet"
    m = _SQ_TO_LENDER_RE.search(sq) or _SQ_TO_LENDER_SHORT_RE.search(sq)
    out["to_lender"] = (f"for assignments to a Lender, an affiliate of a Lender or {_fund_words(m.group('fund'))}" if m and m.group("fund")
                        else "for assignments to a Lender or an affiliate of a Lender" if m
                        else "for assignments by a Lender to its own affiliates" if _SQ_OWN_AFFILIATE_RE.search(sq) else "")
    lifted = _lifting_default(text, block, party)
    out["eod"], out["eod_at"] = "", None
    if lifted:
        m, clause, at = lifted
        kind = _eod_kind_words(m, clause)
        article = "a " if kind or m.group("dflt") else "an "
        out["eod"] = f"while {article}{kind}{'default or ' if m.group('dflt') else ''}event of default is continuing"
        out["eod_at"] = at
    # "without the consent of the Borrower" makes transfers unrestricted only if it is said without conditions: not for particular
    # transferees, not for the time of a default, and not of assignments by way of security
    # ... and said of assignments or transfers, not of participations ("Lenders may sell participations without the consent of the Borrower")
    free = [text[s:e] for s, e in _points(text, block) if _SQ_UNRESTRICTED_RE.search(_sq(text[s:e]))]
    out["waived"] = not out["consent"] and any((_ASSIGN_WORD_RE.search(x) or not _PARTICIPATION_WORD_RE.search(x)) and not _SQ_SECURITY_RE.search(_sq(x)) for x in free)
    out["unrestricted"] = out["waived"] and not out["consultation"] and not out["to_lender"] and not out["eod"]
    others = []
    for s, e in _points(text, block):
        clause = _sq(text[s:e])
        if not _SQ_CONSENT_WORD_RE.search(clause) or (_SQ_NO_CONSENT_RE.search(clause) and not _SQ_ASKED_RE.search(clause)):
            continue
        for rx in (_SQ_AGENT_RE, _SQ_ISSUER_RE, _SQ_SWING_RE):
            hit = _consenting(clause, rx)
            if not hit:
                continue
            name = _party_name(rx, hit.group(0))
            if name not in others:
                others.append(name)
    out["others"] = others
    out["minimum"] = _minimums(text, block)
    if not out["minimum"] and _SQ_MINIMUM_BLANK_RE.search(sq):
        out["minimum"] = "left blank in term sheet"
    m = _SQ_FEE_RE.search(sq)
    out["fee"] = _sq_fee(m.group("amt")) if m else ""
    return out


def _transferee_lines(text: str, block: Block | None = None) -> list[str]:
    """Restrictions on who may take a transfer, and participations, from the wording of the provision."""
    who: list[str] = []
    m = _ELIGIBLE_RE.search(text)
    if m:
        who.append("assignments to " + _squeeze(m.group(0), 110))
    elif _INSTITUTIONS_RE.search(text):
        who.append("assignments to " + _lower_first(_squeeze(_INSTITUTIONS_RE.search(text).group(0), 60)))
    left_out = next((x for x in _EXCLUDED_RE.finditer(text) if _BARRED_RE.search(x.group(1))), None)
    if left_out:
        who.append("not to " + _squeeze(_fix(left_out.group(1)), 170))
    bar, barred_at = "", None
    for s, e in _points(text, block):  # a sentence that bars transfers to someone, as written
        sentence = _INLINE_LABEL_RE.sub("", text[s:e].strip())
        if _BAR_WORD_RE.search(sentence) and _ASSIGN_WORD_RE.search(sentence) and _BARRED_RE.search(sentence) and len(sentence) < 400 and not (
                left_out and left_out.group(0) in sentence):
            bar = _lower_first(_squeeze(_NOTWITHSTANDING_RE.sub("", _main_clause(_UNDERSTOOD_RE.sub("", _fix(sentence)))), 190))
            barred_at = s
            break
    said = " ".join(who + [bar]).lower()
    m = _DISQUALIFIED_RE.search(text)
    if m and "disqualified" not in said:
        named = _squeeze(m.group(0), 80)
        who.append(_lower_first(named) if _PROVISION_WORD_RE.search(named) else f"'{named}' addressed")
    if bar:
        who.append(bar)
    elif _COMPETITOR_RE.search(text) and "competitor" not in said:
        who.append("competitors addressed ('" + _COMPETITOR_RE.search(text).group(0).lower() + "')")
    parts = []
    for s, e in _points(text, block):
        sentence = _INLINE_LABEL_RE.sub("", text[s:e].strip())
        if _PARTICIPATION_RE.search(sentence) and len(parts) < 2 and s != barred_at:
            parts.append(_squeeze(re.sub(r"^participations\s+(?=to\b|in\b)", "", _main_clause(_fix(sentence)), flags=re.IGNORECASE), 270))
    line = ("Transferees: " + "; ".join(who)) if who else ""
    part = ("Participations: " + "; ".join([parts[0]] + [_lower_first(p) for p in parts[1:]])) if parts else ""
    if line and part and len(line) + len(part) <= LINE_LIMIT + 30:
        return [f"{line}. {part}"]
    return [x for x in (line, part) if x]


def _cite(ctx: Ctx, block: Block, rx: re.Pattern, start: int | None = None) -> dict | None:
    """Evidence for a match on whitespace-free text: the clause is located in the spaced text by its first characters (from
    offset ``start`` of the section, if given: the sentence the term was read in)."""
    text = block.text
    base = start if start is not None and 0 <= start < len(text) else 0
    sq_text = _sq(text[base:])
    m = rx.search(sq_text)
    if not m:
        return None
    probe = sq_text[m.start():m.start() + 14]
    for at in range(base, len(text)):
        if text[at] != " " and _sq(text[at:at + 60]).startswith(probe):
            return _quote(ctx, block, at, at + 60)
    return None


@_safe(_TRANSFER_BLANK)
def transferability(ctx: Ctx) -> dict:
    block = _section(ctx, _TRANSFER_LABEL, want=_TRANSFER_WORD_RE) or _section(ctx, _TRANSFER_LABEL)
    if block is None:
        return _blank(*_TRANSFER_BLANK)
    text, src, same = _read(ctx, block, _TRANSFER_LABEL)
    t = _consent_terms(ctx, text, src)
    lead = _first_sentence(text)[:260]
    defers = _defers(lead)
    ref = _ref_clause(text)
    detail = bool(t["unreasonably"] or t["deemed"] or t["to_lender"] or t["minimum"] or t["others"])
    # the cases in which consent is not needed: in the rule's own words, or as the term sheet lists them when it lists more
    exceptions = t["unread"] or " or ".join(x for x in (t["to_lender"], t["eod"]) if x)
    placed = bool(t["consent"] or t["consultation"] or t["unrestricted"])
    pointer = None
    if not detail and not placed and not defers:
        # nothing the rule can place in the opening sentence: a later one may point elsewhere ("Other assignments as per the Existing Agreement")
        pointer = next(((s, e) for s, e in _points(text, src) if _defers(text[s:e])), None)
        if pointer:
            defers, ref = True, _ref_clause(text[pointer[0]:pointer[1]])

    if not detail and (defers or not placed):
        # nothing but a pointer (and perhaps one carve-out)
        head = f"Borrower consent: not required {exceptions}; other terms not detailed in term sheet" if exceptions else f"Borrower consent: {NS}"
        head += f" ({_lower_first(ref)})" if defers and ref else f" ('{_squeeze(text, 120)}')" if not defers else ""
        lines = [head] + (_transferee_lines(text, src) or (["Transferee restrictions and participations: not detailed in term sheet"] if defers else []))
        evidence = [_quote(ctx, src, *pointer) if pointer else _quote(ctx, src), _cite(ctx, src, _SQ_EOD_RE, t["eod_at"]) if t["eod"] else None]
        return _entry(lines, evidence, defers, _TRANSFER_BLANK, same)

    if t["consent"]:
        head = "Borrower consent required"
    elif t["consultation"]:
        head = "Borrower consultation required"
    elif t["unrestricted"]:
        head = "Unrestricted: no Borrower consent required"
    elif t["waived"] and exceptions:
        head = f"Borrower consent: not required {exceptions}; otherwise not stated in the assignments provision"
    else:
        head = "Borrower consent: not mentioned in the assignments provision"
    # "not to be unreasonably withheld" and the deemed consent qualify the borrower's consent, or the other parties' if only theirs is asked
    quals = "; ".join(x for x in (t["unreasonably"], t["deemed"]) if x)
    if quals and (t["consent"] or t["consultation"]):
        head += f" ({quals})"
    carve_out = ""
    if exceptions and (t["consent"] or t["consultation"]):
        if len(head) + len(exceptions) > LINE_LIMIT + 10:  # a long list (quoted from the term sheet) gets a line of its own
            carve_out = ("Borrower consent not required " if t["consent"] else "Borrower consultation not required ") + exceptions
        else:
            head += f"; not required {exceptions}"
    extras = []
    if t["others"]:
        extras.append("other consents: " + ", ".join(t["others"]) + (f" ({quals})" if quals and not (t["consent"] or t["consultation"]) else ""))
    if t["minimum"]:
        extras.append(f"minimum assignment {t['minimum']}")
    if t["fee"]:
        extras.append(f"assignment fee {t['fee']}")
    extra = "; ".join(extras)
    lines = [f"{head}; {extra}"] if extra and len(head) + len(extra) <= LINE_LIMIT + 30 else [head, _upper_first(extra)]
    lines[1:1] = [carve_out] if carve_out else []
    lines += _transferee_lines(text, src)
    if defers and ref:
        lines.append("Otherwise " + _lower_first(ref))
    evidence = []
    for rx in (_SQ_UNREASONABLY_RE, _SQ_DEEMED_RE, _SQ_EOD_RE, _SQ_MINIMUM_RE):
        quote = _cite(ctx, src, rx, t["eod_at"] if rx is _SQ_EOD_RE else None) if len(evidence) < 3 else None
        if quote and quote not in evidence:
            evidence.append(quote)
    return _entry(lines, evidence or [_quote(ctx, src)], False, _TRANSFER_BLANK, same)


# ======================================================================================================
# Information Requirements
# ======================================================================================================

# "Financial Reporting:", "Reporting Requirements:", "Information Undertakings:", "Financial Statements:"
_INFO_LABEL = (r"(?:financial\s+)?reporting(?:\s+(?:requirements?|covenants?|undertakings?))?|information(?:\s+(?:undertakings?|covenants?|requirements?|rights))?|"
               r"financial\s+(?:statements|information)(?:\s+and\s+other\s+information)?")
# the last line of such a label when it wraps ("Information" / "Undertakings:")
_INFO_TAILS = (r"reporting", r"undertakings?", r"requirements?", r"statements")
# "Affirmative Covenants:", "Positive Covenants:", "General Undertakings:"
_AFFIRMATIVE_LABEL = r"affirmative\s+covenants?|positive\s+covenants?|general\s+undertakings?"
# the last line of a wrapped "Affirmative" / "Covenants:"
_AFFIRMATIVE_TAILS = (r"covenants?", r"undertakings?")
# "Covenants:", "Undertakings:": the section that holds the affirmative, negative and financial covenants
_COVENANTS_LABEL = r"covenants?|undertakings?"
# an item of a covenant list that is about financial reporting
_REPORT_RE = re.compile(
    r"financial\s+statements|financial\s+reporting|reporting\s+requirements?|financial\s+information|management\s+accounts|annual\s+(?:budget|accounts|reports?)|"
    r"(?:annual|quarterly|monthly|interim|semi-annual)\s+(?:audited\s+|unaudited\s+|consolidated\s+)*(?:financial|accounts|management)|"
    r"(?:audited|unaudited)\s+(?:consolidated\s+)?(?:financial|accounts)", re.IGNORECASE)
# a financial covenant that merely mentions the statements it is tested on is not a reporting item
_TEST_RE = re.compile(r"\bratio\b|leverage|coverage|\d\.\d{1,2}\s*(?:x\b|:\s?1|to\s+1)", re.IGNORECASE)
# ... unless it says that they are delivered
_DELIVERY_RE = re.compile(r"deliver|furnish|provide|report", re.IGNORECASE)
# the words that introduce a delivery period: "within", "no later than", "not later than", "not more than"
_WITHIN = r"(?:within|not?\s+later\s+than|not\s+more\s+than)\s+"
# the unit of a delivery period
_PERIOD_UNIT = r"\s*(?P<u>business\s+days|days|months)"
# the same lead-in, optional where the words that follow ("after the end of each fiscal year") already make it a deadline
_WITHIN_OPT = r"(?:(?:within|not?\s+later\s+than|not\s+more\s+than|on\s+or\s+(?:before|prior\s+to)(?:\s+the\s+date\s+that\s+is)?)\s+)?"
# a deadline that belongs to something other than the financial statements
_NOT_STATEMENTS_RE = re.compile(r"\bbudgets?\b|\bprojections\b|\bforecasts?\b|business\s+plan|certificates?", re.IGNORECASE)
# "within 90 days after the end of each fiscal year", "within 120 days of each financial year end"
_ANNUAL_AFTER_RE = re.compile(_WITHIN_OPT + _num() + _PERIOD_UNIT + r"\s+(?:after|of|following)\s+(?:the\s+)?(?:(?:end|close|last\s+day)\s+of\s+)?(?:(?:each|the|its|any|such)\s+)?"
                              r"(?:such\s+)?(?:(?:fiscal|financial)\s+year(?:[\s-]end)?|year[\s-]end)", re.IGNORECASE)
# "annual audited financial statements within 90 days" (nothing about quarters or budgets in between)
_ANNUAL_BEFORE_RE = re.compile(r"(?<!semi-)(?<!semi)\b(?:annual|audited|fiscal\s+year|financial\s+year|year[\s-]end)"
                               r"(?:(?!quarter|month|interim|semi|half|budget|projection|forecast|certificate)[^.;]){0,160}?" + _WITHIN + _num() + _PERIOD_UNIT, re.IGNORECASE)
# "within 45 days after the end of each of the first three fiscal quarters", "within 45 days of each quarter end"
_QUARTER_AFTER_RE = re.compile(_WITHIN_OPT + _num() + _PERIOD_UNIT + r"\s+(?:after|of|following)\s+(?:the\s+)?(?:(?:end|close|last\s+day)\s+of\s+)?(?:(?:each|the|any|such)\s+)?"
                               r"(?:of\s+the\s+)?(?P<first3>first\s+three\s+)?(?:such\s+)?(?:fiscal\s+|financial\s+)?quarters?(?:[\s-]ends?)?", re.IGNORECASE)
# "quarterly unaudited financial statements within 45 days" (nothing about annual accounts or budgets in between)
_QUARTER_BEFORE_RE = re.compile(r"\bquarter(?:ly|s)?\b(?:(?!annual|\baudited|fiscal\s+year|financial\s+year|month|budget|projection|forecast|certificate)[^.;]){0,160}?"
                                + _WITHIN + _num() + _PERIOD_UNIT, re.IGNORECASE)
# "monthly management accounts within 30 days", "within 30 days after the end of each month"
_MONTH_RE = re.compile(r"\bmonthly\b(?:(?!annual|quarter|budget)[^.;]){0,140}?" + _WITHIN + _num() + _PERIOD_UNIT + r"|" + _WITHIN + _num("b") + r"\s*(?P<ub>business\s+days|days)"
                       r"\s+(?:after|of|following)\s+(?:the\s+)?end\s+of\s+each\s+(?:calendar\s+|fiscal\s+)?month", re.IGNORECASE)
# "... after the end of each month", directly after a monthly delivery period
_MONTH_END_RE = re.compile(r"\s+(?:after|of|following)\s+(?:the\s+)?end\s+of\s+(?:each|the|such)\s+(?:calendar\s+|fiscal\s+)?month", re.IGNORECASE)
# "semi-annual financial statements within 90 days", "half-year accounts within 90 days"
_HALF_RE = re.compile(r"\b(?:semi[\s-]?annual|half[\s-]year(?:ly)?|interim)\b(?:(?!quarter|budget)[^.;]){0,140}?" + _WITHIN + _num() + _PERIOD_UNIT, re.IGNORECASE)
# "within 75/120 days", "within 45 and 90 days, respectively": one figure each for the two kinds of statement named before it
_PAIR_RE = re.compile(_WITHIN + r"(?P<a>\d{1,3})\s*(?:days\s*)?(?:/|and)\s*(?P<b>\d{1,3})\s*(?P<u>business\s+days|days)", re.IGNORECASE)
# "annual" (not "semi-annual")
_ANNUAL_WORD_RE = re.compile(r"(?<!semi-)(?<!semi)\bannual", re.IGNORECASE)
# "quarterly", "fiscal quarter"
_QUARTER_WORD_RE = re.compile(r"\bquarter", re.IGNORECASE)
# qualifiers of the accounts, carried into the line when the term sheet uses them
_AUDITED_RE = re.compile(r"\baudited\b", re.IGNORECASE)
_UNAUDITED_RE = re.compile(r"\bunaudited\b", re.IGNORECASE)
_CONSOLIDATED_RE = re.compile(r"\bconsolidated\b", re.IGNORECASE)
_MANAGEMENT_RE = re.compile(r"management\s+accounts", re.IGNORECASE)
# "budget", "projections", "forecast", "business plan"
_BUDGET_WORD_RE = re.compile(r"\bbudgets?\b|\bprojections\b|\bforecasts?\b|business\s+plan", re.IGNORECASE)
# "annual budget within 60 days after the beginning of each fiscal year", "annual budget no later than 30 days ..."
_BUDGET_RE = re.compile(r"(?:\bbudgets?\b|\bprojections\b|\bforecasts?\b|business\s+plan)(?:(?!quarter|audited)[^.;]){0,140}?" + _WITHIN + _num() + _PERIOD_UNIT
                        + r"(?P<tail>[^.;]{0,70})", re.IGNORECASE)
# "within 60 days after the beginning of each fiscal year, an annual budget"
_BUDGET_AFTER_RE = re.compile(_WITHIN + _num() + _PERIOD_UNIT + r"(?P<tail>\s+(?:after|of|following|prior\s+to|before)\s+(?:the\s+)?(?:beginning|start|commencement|end)\s+of\s+"
                              r"each\s+(?:fiscal|financial)\s+year)[^.;]{0,80}?(?:budget|projections|forecast|business\s+plan)", re.IGNORECASE)
# what the budget period runs from: after the start of the year, before it, or after the year end
_AFTER_START_RE = re.compile(r"(?:after|following|of)\s+(?:the\s+)?(?:beginning|start|commencement)", re.IGNORECASE)
_BEFORE_START_RE = re.compile(r"(?:prior\s+to|before)\s+(?:the\s+)?(?:beginning|start|commencement)", re.IGNORECASE)
_AFTER_END_RE = re.compile(r"(?:after|following|of)\s+(?:the\s+)?(?:(?:fiscal\s+|financial\s+)?year[\s-])?end", re.IGNORECASE)
# "or such later date as otherwise permitted by the SEC, if applicable, for delivery of quarterlies"
_LATER_DATE_RE = re.compile(r"or\s+such\s+later\s+date[^;)]{0,110}?(?=\s+and\s+with\b|[;)]|$)", re.IGNORECASE)
# "with a requirement regarding the absence of going concern qualifications", "without a going concern qualification"
_GOING_CONCERN_RE = re.compile(r"(?:(?:and\s+)?with\s+a\s+requirement\s+regarding|without|not\s+subject\s+to|unqualified\s+as\s+to)[^.;()]{0,60}going\s+concern", re.IGNORECASE)
# standalone accounts of obligors
_OBLIGOR_RE = re.compile(
    r"(?:unconsolidated|non-consolidated|stand[\s-]?alone|individual|separate)\s+(?:annual\s+)?(?:audited\s+)?(?:financial\s+statements|accounts)|"
    r"(?:financial\s+statements|accounts)\s+of\s+each\s+(?:Obligor|Borrower|Guarantor|Loan\s+Party|Material\s+Subsidiary)|"
    r"each\s+(?:Obligor|Guarantor)['’]s\s+(?:annual\s+)?(?:audited\s+)?(?:financial\s+statements|accounts)", re.IGNORECASE)
# other reporting worth a mention on the budget row
_OTHER_REPORTS = (
    re.compile(r"SEC\s+filings", re.IGNORECASE),
    re.compile(r"compliance\s+certificates?", re.IGNORECASE),
    re.compile(r"notices?\s+of\s+(?:(?:default|material\s+events|litigation)(?:\s+and\s+other\s+events)?|[a-z]+(?:\s+[A-Za-z]+){0,8}?(?=\s*(?:[;,.)]|$)))", re.IGNORECASE),
    re.compile(r"information\s+requests?", re.IGNORECASE),
    re.compile(r"ratings?\s+changes?|changes?\s+in\s+ratings?", re.IGNORECASE),
)
# a period in days, as the part of a reporting item worth quoting: "90 days", "75/120 days"
_DAYS_FIGURE_RE = re.compile(r"\d{1,3}\s*(?:/\s*\d{1,3}\s*)?(?:business\s+)?days", re.IGNORECASE)
# the periods a reporting section speaks of
_PERIOD_WORD_RE = re.compile(r"\bannual|\bquarter|\bmonthly|\baudited|\bfiscal\s+year|\bfinancial\s+year", re.IGNORECASE)
# "within [●] days": the period is left blank
_BLANK_DAYS_RE = re.compile(_WITHIN + r"\[\s*[●•_.\s]*\]\s*(?:business\s+)?days[^.;,]{0,60}", re.IGNORECASE)
# a condition or an alternative period that follows a delivery period and belongs in the line with it: "... during a Reporting
# Trigger Period", "... if utilisation exceeds 50%", "... (or 120 days in the case of the first fiscal year)"
_CONDITION_RE = re.compile(r"\s*(?:\((?!or\s+such\s+later)(?:(?:or|and|except|other\s+than|provided)\b[^()]{3,100}|[^()]{0,60}?\d+\s*(?:business\s+)?days\b[^()]{0,70})\)|,?\s*(?:during|if|only|while|so\s+long\s+as|to\s+the\s+extent|unless|except)\b[^.;,()]{3,90})",
                           re.IGNORECASE)
# the label "Information" with nothing after it
_BARE_INFO_LABEL_RE = re.compile(r"information\s*$", re.IGNORECASE)
# a label that names the accounts themselves ("Financial Statements", "Financial Information") rather than the duty to report
_ACCOUNTS_LABEL_RE = re.compile(r"financial\s+(?:statements|information)", re.IGNORECASE)
# what makes a passage about accounts a reporting requirement: delivery, a period, or a pointer to where the requirement is set out
_INFO_DUTY_RE = re.compile(r"deliver|furnish|provide|suppl(?:y|ied)|within|later\s+than|\bdays\b|customary|existing|to\s+be\s+agreed|\[\s*[●•_.\s]*\]", re.IGNORECASE)
# where the clause that holds a delivery period ends
_CLAUSE_END_RE = re.compile(r";|\.\s")
# a few plain words with no "and" and no punctuation: all that may stand between a period and its condition ("after the end of each month")
_PLAIN_WORDS_RE = re.compile(r"(?:(?!\band\b)[\w\s-]){0,45}")
# "2024A  2025A  2026E": the value of a row of figures in a financial table, not of a term
_YEAR_COLUMNS_RE = re.compile(r"\d{4}[AE]?\s+\d{4}")
# "financial statements": what a closed list of covenants must name before the absence of a budget is read off it
_STATEMENTS_RE = re.compile(r"financial\s+statements", re.IGNORECASE)
# the reporting item opens a list of its own ("reporting requirements (including quarterly ...)", "certain reporting requirements",
# "financial statements and other information"): what it does not name may still be required
_OPEN_ITEM_RE = re.compile(r"\binclud(?:e|es|ing)\b|\bsuch\s+as\b|\bamong\s+other|\be\.g\.|\betc\b|without\s+limitation|\bcertain\b|"
                           r"\b(?:and|or)\s+(?:such\s+)?other\s+(?:\w+\s+)?(?:information|reports?|reporting|documents|deliverables|materials|items)\b", re.IGNORECASE)
# a report whose timing the term sheet gives in words rather than in days ("no later than the deadline for delivery of such
# financial statements", "together with each set of financial statements", "promptly")
_TIMING_RE = re.compile(r"\bdeadline|\bno\s+later\s+than|\bnot\s+later\s+than|\bwithin\b|\btogether\s+with\b|\bconcurrent|\bsimultaneous|\bat\s+the\s+(?:same\s+)?time\b|"
                        r"\bprompt(?:ly)?\b|\bwith\s+each\b|\baccompan", re.IGNORECASE)
# what a delivery period is said of: the year, a quarter or a month
_PERIOD_OF_RE = re.compile(r"(?:fiscal|financial)\s+year|year[\s-]end|\bannual|\baudited|\bquarter\w*|\bmonth\w*", re.IGNORECASE)
# a set of accounts, as opposed to a certificate or a report on something else
_ACCOUNTS_RE = re.compile(r"\baccounts\b|financial\s+statements|\bfinancials\b|management\s+reports?|reporting\s+package", re.IGNORECASE)
# "annual", "fiscal year": the words of the annual accounts
_YEAR_WORD_RE = re.compile(r"annual|(?:fiscal|financial)\s+year", re.IGNORECASE)
# "semi-annual", "half-year", "interim"
_HALF_WORD_RE = re.compile(r"semi[\s-]?annual|half[\s-]year|\binterim", re.IGNORECASE)
# "monthly", "each month"
_MONTH_WORD_RE = re.compile(r"\bmonth", re.IGNORECASE)


def _reporting(ctx: Ctx) -> dict | None:
    """Where the term sheet deals with financial reporting.

    {"block", "text", "spans" (reporting items), "all" (every item), "lead", "defers", "ref", "closed", "generic"}; ``generic`` means
    no reporting item is named and the covenants as a whole are by reference to another document.
    """
    state = _state(ctx)
    if "reporting" in state:
        return state["reporting"]
    result = None
    parents = _sections(ctx, _COVENANTS_LABEL)
    for pattern, tails in ((_INFO_LABEL, _INFO_TAILS), (_AFFIRMATIVE_LABEL, _AFFIRMATIVE_TAILS), (_COVENANTS_LABEL, ())):
        for block in _sections(ctx, pattern, tails):
            text, block, same = _read(ctx, block, pattern)
            if pattern == _INFO_LABEL and (_CP_WORDING_RE.search(text[:600]) or _REP_WORDING_RE.search(text[:600])):
                continue  # "Financial Statements: the Arrangers shall have received ...": a condition precedent or a representation, not reporting
            if pattern == _INFO_LABEL and _ACCOUNTS_LABEL_RE.match(block.label or "") and not _INFO_DUTY_RE.search(text):
                continue  # a row that describes accounts (a data-room item, a set of figures) without any duty to deliver them
            if pattern == _INFO_LABEL and _BARE_INFO_LABEL_RE.match(block.label or "") and not (_DAYS_FIGURE_RE.search(text) or _BLANK_DAYS_RE.search(text)):
                continue  # "Information" on its own heads many things; it is read as reporting only where it gives a delivery period
            lead_end, spans = _items(text, block)
            if len(spans) == 1 and _line_spans(block, text):  # a cell that lists its requirements one per line
                lead_end, spans = 0, _line_spans(block, text)
            report = [(s, e) for s, e in spans if _REPORT_RE.search(text[s:e]) and not (_TEST_RE.search(text[s:e]) and not _DELIVERY_RE.search(text[s:e]))]
            if pattern == _INFO_LABEL and not report and _PERIOD_WORD_RE.search(text) and _INFO_DUTY_RE.search(text):
                report = spans  # a section of its own: every item is a reporting item ("Annual within 90 days; quarterly within 45 days")
            if not report:
                continue
            lead, lead_block = (text[:lead_end] if lead_end else text[:spans[0][1]]), block
            sub_heading = pattern == _AFFIRMATIVE_LABEL or (pattern == _INFO_LABEL and block.inline)
            if sub_heading and not (_defers(lead[:400]) or _CLOSED_RE.search(lead[:400])):
                # a sub-section: the lead-in sits in the covenants section just above it (for a "Reporting" sub-heading, the one it is in)
                above = [p for p in parents if 0 < block.line.n - p.line.n <= 150 and (_defers(p.text[:400]) or _CLOSED_RE.search(p.text[:400]))
                         and (pattern == _AFFIRMATIVE_LABEL or p.end >= block.line.n)]
                if above:
                    lead_block = max(above, key=lambda p: p.line.n)
                    lead = lead_block.text
            result = {"block": block, "text": text, "spans": report, "all": spans, "lead": lead, "lead_block": lead_block, "defers": _defers(lead[:400]),
                      "ref": _ref_clause(lead), "closed": bool(_CLOSED_RE.search(lead[:400])), "generic": False, "same": same,
                      "where": "in the reporting section" if pattern == _INFO_LABEL else "among the covenants"}
            break
        if result:
            break
    if result is None:
        for block in _sections(ctx, _AFFIRMATIVE_LABEL, _AFFIRMATIVE_TAILS) + parents:
            # the section opens by pointing elsewhere ("Substantially similar to the Existing Credit Agreement ...") and names no reporting item
            if not block.inline and _defers(block.text[:160]) and not _CLOSED_RE.search(block.text[:400]):
                result = {"block": block, "text": block.text, "spans": [], "all": [], "lead": block.text, "defers": True, "ref": _ref_clause(block.text),
                          "closed": False, "generic": True, "same": False}
                break
    state["reporting"] = result
    return result


def _report_text(rep: dict) -> str:
    """The reporting items as one passage."""
    return rep["text"][rep["spans"][0][0]:rep["spans"][-1][1]]


def _period(m: re.Match, tag: str = "") -> tuple[int | None, str]:
    n = _num_value(m, tag)
    try:
        unit = m.group("u" + tag)
    except IndexError:
        unit = "days"
    return n, _unit(unit, n)


def _statements_period(rx: re.Pattern, text: str) -> re.Match | None:
    """The first "N days after the end of each fiscal year / quarter" that is said of financial statements, not of a budget
    or a certificate named earlier in the same clause."""
    for m in rx.finditer(text):
        clause = text[max(0, m.start() - 110):m.start()]
        clause = clause[max(clause.rfind(";"), clause.rfind(". ")) + 1:]
        if not _NOT_STATEMENTS_RE.search(clause):
            return m
    return None


def _deadlines(passage: str) -> dict:
    """Delivery periods in one reporting item: {"annual" / "quarterly" / "monthly" / "half": (n, unit, basis, clause)}.

    ``clause`` is the part of the item the period is said of (from the end of the period before it), which is where the
    qualifiers of those accounts are looked for ("audited", "consolidated", "unaudited", "management accounts").
    """
    found: dict = {}  # key -> (n, unit, basis, match)
    text = _fix(passage)
    pair = _PAIR_RE.search(text)
    a, q = _ANNUAL_WORD_RE.search(text), _QUARTER_WORD_RE.search(text)
    if pair and a and q and max(a.start(), q.start()) < pair.start():
        first, second = (("quarterly", "annual") if q.start() < a.start() else ("annual", "quarterly"))
        unit = _unit(pair.group("u"), 2)
        note = f"term sheet: '{_squeeze(pair.group(0), 40)}' for {first} / {second} statements"
        found[first] = (int(pair.group("a")), unit, note, pair)
        found[second] = (int(pair.group("b")), unit, note, pair)
    if "annual" not in found:
        m = _statements_period(_ANNUAL_AFTER_RE, text)
        if m:
            found["annual"] = (*_period(m), "of financial year end", m)
        else:
            m = _ANNUAL_BEFORE_RE.search(text)
            if m:
                found["annual"] = (*_period(m), "", m)
    if "quarterly" not in found:
        m = _statements_period(_QUARTER_AFTER_RE, text)
        if m:
            found["quarterly"] = (*_period(m), "of each of the first three quarter ends" if m.group("first3") else "of each quarter end", m)
        else:
            m = _QUARTER_BEFORE_RE.search(text)
            if m:
                found["quarterly"] = (*_period(m), "", m)
    m = _MONTH_RE.search(text)
    if m:
        after_end = bool(m.group("ub")) or bool(_MONTH_END_RE.match(text, m.end()))  # said so, not assumed
        found["monthly"] = (*(_period(m) if m.group("u") else _period(m, "b")), "of each month end" if after_end else "", m)
    m = _HALF_RE.search(text)
    if m:
        found["half"] = (*_period(m), "", m)
    out: dict = {}
    for key, (n, unit, basis, m) in found.items():
        if not n:
            continue
        start = max((x[3].end() for x in found.values() if x[3].end() <= m.start()), default=0)
        clause = text[start:m.end()]
        if key == "monthly" and not (_ACCOUNTS_RE.search(clause) and not _NOT_STATEMENTS_RE.search(clause)):
            continue  # a monthly borrowing base certificate or report is not a set of accounts
        # "... during a Reporting Trigger Period", "... (or 120 days for the first fiscal year)": said right after the period, with
        # at most "after the end of each month" in between
        tail = _CLAUSE_END_RE.split(text[m.end():], maxsplit=1)[0][:150]
        when = _CONDITION_RE.search(tail)
        if when and not basis.startswith("term sheet") and _PLAIN_WORDS_RE.fullmatch(tail[:when.start()]):
            basis = (basis + " " + _squeeze(when.group(0), 100)).strip()
        out[key] = (n, unit, basis, clause)
    return out


def _item_deadlines(rep: dict) -> dict:
    """Delivery periods of the reporting items, each read from its own item: {key: (n, unit, basis, clause, item span)}.

    Reading item by item keeps a period with the statements it belongs to; the accounts of individual obligors have a row of
    their own and are left out here.
    """
    if "deadlines" not in rep:
        out: dict = {}
        if not rep["generic"]:
            for s, e in rep["spans"]:
                item = rep["text"][s:e]
                if _OBLIGOR_RE.search(item):
                    continue
                for key, value in _deadlines(item).items():
                    out.setdefault(key, value + ((s, e),))
        rep["deadlines"] = out
    return rep["deadlines"]


def _within(deadline: tuple) -> str:
    n, unit, basis = deadline[:3]
    if basis.startswith("term sheet"):
        return f"within {n} {unit} ({basis})"
    return f"within {n} {unit}" + (f" {basis}" if basis else "")


def _blank_period(rep: dict, key: str) -> str:
    """The words with which the term sheet leaves the delivery period of the annual or quarterly accounts blank ("within [ ] days
    after the end of each fiscal year"), or ""."""
    text = _fix(_report_text(rep))
    for b in _BLANK_DAYS_RE.finditer(text):
        after = _PERIOD_OF_RE.search(b.group(0))
        before = text[max(0, b.start() - 110):b.start()]
        before = list(_PERIOD_OF_RE.finditer(before[max(before.rfind(";"), before.rfind(". ")) + 1:]))
        of = (after or (before[-1] if before else None))
        said_of = "" if of is None else "quarterly" if "quarter" in of.group(0).lower() else "other" if "month" in of.group(0).lower() else "annual"
        if said_of == key:
            cut = b.group(0)[:after.end()] if after else b.group(0)
            return _squeeze(cut, 80)
    return ""


def _listed_only(rep: dict, name: str, key: str) -> tuple[str, bool]:
    """Line for a row whose covenant is named without a delivery period, and whether that makes it by reference."""
    if rep["generic"]:
        return f"{name} - period {NS}; covenants: {_lower_first(rep['ref'])}", True
    blank = _blank_period(rep, key)
    if blank:
        return f"{name} - period left blank in term sheet ('{blank}')", False
    about = _ANNUAL_WORD_RE if key == "annual" else _QUARTER_WORD_RE
    own = next((sp for sp in rep["spans"] if _speaks(rep["text"], sp, about)), None)
    if own:  # the reporting item that names the accounts of this row, and what it calls them
        said = _fix(rep["text"][own[0]:own[1]])
        word = about.search(said)
        if word:
            commas = _depth0(said, ",;")
            clause = said[max((c + 1 for c in commas if c < word.start()), default=0):min((c for c in commas if c >= word.end()), default=len(said))]
            name = (_annual_name if key == "annual" else _quarterly_name)(clause)
        item = _squeeze(_first_sentence(said), 120)
    else:
        item = _squeeze(_first_sentence(_fix(_report_text(rep))), 120)
    line = f"{name} - period {NS}; '{item}' listed {rep.get('where', 'among the covenants')}"
    if rep["defers"] and rep["ref"]:
        line += f" ({_lower_first(rep['ref'])})"
    return line, rep["defers"]


def _speaks(text: str, span: tuple, about: re.Pattern | None) -> bool:
    """The item text[span] uses the row's word for accounts ("annual", "quarterly"), not for a budget ("annual budget")."""
    m = about.search(text, span[0], span[1]) if about is not None else None
    return bool(m) and not _BUDGET_WORD_RE.match(text[m.end():m.end() + 30].lstrip("ly ").lstrip())


def _report_quotes(ctx: Ctx, rep: dict, about: re.Pattern | None = None, span: tuple | None = None) -> list:
    """Evidence for a reporting row: the reporting item it was read from (``span``), or else the item that is ``about`` it, cut
    around the period when there is one; then the words the section opens with."""
    block = rep["block"]
    if rep["generic"]:
        return [_quote(ctx, block)]
    text = rep["text"]

    s, e = span or next((sp for sp in rep["spans"] if _speaks(text, sp, about)), rep["spans"][0])
    word = about.search(text, s, e) if about is not None else None
    start = word.start() if word else s
    period = _DAYS_FIGURE_RE.search(text, start, e) or _DAYS_FIGURE_RE.search(text, s, e)
    if period and period.start() < start:
        start = s
    if period and period.end() - start <= 130:
        first = _quote(ctx, block, start, period.end())
    else:
        first = _quote_item(ctx, block, s, e, prefer=_DAYS_FIGURE_RE)
    return [first, _lead_quote(ctx, rep)] if rep["defers"] or rep["closed"] else [first]


def _lead_quote(ctx: Ctx, rep: dict) -> dict | None:
    """Evidence for the words with which the reporting section points elsewhere or closes its list."""
    src = rep.get("lead_block") or rep["block"]
    opening = _quote(ctx, src)
    closing = _CLOSED_RE.search(src.text[:400]) if rep["closed"] else None
    if closing and not (opening and _sq(closing.group(0)) in _sq(opening["quote"])):
        return _quote(ctx, src, closing.start(), closing.end()) or opening  # the opening words stop short of those that close the list
    return opening


def _later_date(item: str, other: re.Pattern) -> str:
    """", or such later date as ..." after a delivery period, unless it is said of the ``other`` kind of accounts."""
    later = _LATER_DATE_RE.search(item)
    return ", " + _squeeze(later.group(0), 110) if later and not other.search(later.group(0)) else ""


# Rows of a summary table that carry one reporting item each ("Annual accounts    Within 120 days of year end"), for term sheets
# that have no reporting or covenants section to read:
# "Annual accounts", "Annual audited financial statements", "Audited accounts"
_ANNUAL_ROW_LABEL = (r"annual\s+(?:audited\s+)?(?:consolidated\s+)?(?:accounts|financial\s+statements|financials|reporting|reports?)|"
                     r"audited\s+(?:annual\s+)?(?:consolidated\s+)?(?:accounts|financial\s+statements|financials)")
# "Quarterly accounts", "Quarterly financial statements", "Management accounts", "Interim financial statements"
_QUARTERLY_ROW_LABEL = (r"quarterly\s+(?:unaudited\s+)?(?:management\s+)?(?:accounts|financial\s+statements|financials|reporting|reports?)|"
                        r"(?:monthly\s+)?management\s+accounts|interim\s+(?:accounts|financial\s+statements|financials)")
# "Budget", "Annual budget", "Business plan" (not "Forecast" or "Projections", which label rows of figures in a presentation)
_BUDGET_ROW_LABEL = r"(?:annual\s+)?(?:budgets?|business\s+plans?)"
# what the value of such a row must speak of to be a reporting requirement: a period, a delivery, or that there is none
_BUDGET_ROW_VALUE_RE = re.compile(r"\bdays\b|\bdeliver|\bprovide|\bfurnish|\bsuppl(?:y|ied)|\brequired\b|\bannual|\bnone\b|\bn\s?/\s?a\b|financial\s+year|fiscal\s+year", re.IGNORECASE)


def _row(ctx: Ctx, label: str) -> tuple[dict, list[Block], bool] | None:
    """The table rows labelled ``label``, each read as "<label> <value>": (their delivery periods, the rows to quote, unchanged from
    existing terms?); None if no such row states a period."""
    found: dict = {}
    rows: list[Block] = []
    unchanged = True
    for block in _sections(ctx, label)[:4]:
        text, src, same = _read(ctx, block, label)
        if len(text) > 300:
            continue  # a paragraph, not a table row
        periods = {k: v for k, v in _deadlines(f"{block.label} {text}").items() if k not in found}
        if periods:
            found.update(periods)
            rows.append(src)
            unchanged = unchanged and same
    return (found, rows, unchanged) if found else None


def _annual_name(clause: str) -> str:
    return "Annual " + ("audited " if _AUDITED_RE.search(clause) else "") + ("consolidated " if _CONSOLIDATED_RE.search(clause) else "") + "accounts"


def _quarterly_name(clause: str) -> str:
    return "Quarterly " + ("unaudited " if _UNAUDITED_RE.search(clause) else "") + ("management " if _MANAGEMENT_RE.search(clause) else "") + "accounts"


def _audit_opinion(item: str, limit: int = LINE_LIMIT) -> str:
    """What a reporting item says of going concern qualifications of the audit opinion, in its own words ("" if nothing)."""
    gc = _GOING_CONCERN_RE.search(item)
    if not gc:
        return ""
    tail = item[gc.start():]
    stops = [p for p in range(len(tail)) if tail[p] == ")" and _depth_at(tail, p) == 0] + [len(_first_sentence(tail))]
    return _squeeze(_upper_first(re.sub(r"^and\s+", "", tail[:min(stops)], flags=re.IGNORECASE)), limit)


@_safe(_ANNUAL_BLANK)
def info_annual_consolidated(ctx: Ctx) -> dict:
    rep = _reporting(ctx)
    found = _item_deadlines(rep).get("annual") if rep else None
    if not found:
        row = _row(ctx, _ANNUAL_ROW_LABEL)
        if row and row[0].get("annual"):  # a row of its own in a summary table
            return _entry([f"{_annual_name(row[0]['annual'][3])} - {_within(row[0]['annual'])}"], [_quote_with_label(ctx, b) for b in row[1]], False,
                          _ANNUAL_BLANK, row[2])
        if rep is None:
            return _blank(*_ANNUAL_BLANK)
        line, referred = _listed_only(rep, "Annual consolidated accounts", "annual")
        own = next((sp for sp in rep["spans"] if _speaks(rep["text"], sp, _ANNUAL_WORD_RE)), None) if not rep["generic"] else None
        opinion = _audit_opinion(_fix(rep["text"][own[0]:own[1]]), LINE_LIMIT + 80) if own else ""
        return _entry([line] + ([opinion] if opinion else []), _report_quotes(ctx, rep, _ANNUAL_WORD_RE), referred, _ANNUAL_BLANK, rep["same"])
    clause, span = found[3], found[4]
    item = _fix(rep["text"][span[0]:span[1]])
    lines = [f"{_annual_name(clause)} - {_within(found)}" + _later_date(item, _QUARTER_WORD_RE)]
    opinion = _audit_opinion(item)
    if opinion:
        lines.append(opinion)
    return _entry(lines, _report_quotes(ctx, rep, _ANNUAL_WORD_RE, span), False, _ANNUAL_BLANK, rep["same"])


@_safe(_OBLIGOR_BLANK)
def info_annual_obligor(ctx: Ctx) -> dict:
    rep = _reporting(ctx)
    if rep is None or rep["generic"]:
        return _blank(*_OBLIGOR_BLANK)
    text = rep["text"]
    m = _OBLIGOR_RE.search(text)
    if not m:
        return _blank(*_OBLIGOR_BLANK)
    s, e = next(((s, e) for s, e in rep["all"] if s <= m.start() < e), (max(0, m.start() - 80), min(len(text), m.end() + 160)))
    clause = _fix(text[s:e])
    found = _deadlines(clause).get("annual")
    if found:
        line = f"Annual obligor accounts - {_within(found)}"
    else:
        line = f"Annual obligor accounts - required ('{_squeeze(_first_sentence(clause), 150)}'); period {NS}"
    period = _DAYS_FIGURE_RE.search(text, m.end(), e)
    return _entry([line], [_quote(ctx, rep["block"], m.start(), period.end() if period and period.end() - m.start() <= 130 else m.end())],
                  False, _OBLIGOR_BLANK, rep["same"])


def _interim_lines(found: dict, quarterly_extra: str = "") -> list[str]:
    """Lines for the quarterly, half-yearly and monthly accounts whose delivery periods were found."""
    lines = []
    if found.get("quarterly"):
        lines.append(f"{_quarterly_name(found['quarterly'][3])} - {_within(found['quarterly'])}" + quarterly_extra)
    if found.get("half"):
        lines.append(f"Semi-annual accounts - {_within(found['half'])}")
    if found.get("monthly"):
        lines.append(f"Monthly accounts - {_within(found['monthly'])}")
    return lines


@_safe(_QUARTERLY_BLANK)
def info_quarterly(ctx: Ctx) -> dict:
    rep = _reporting(ctx)
    found = _item_deadlines(rep) if rep else {}
    quarterly = found.get("quarterly")
    extra = _later_date(_fix(rep["text"][quarterly[4][0]:quarterly[4][1]]), _YEAR_WORD_RE) if quarterly else ""
    lines = _interim_lines(found, extra)
    if not lines:
        row = _row(ctx, _QUARTERLY_ROW_LABEL)
        if row and _interim_lines(row[0]):  # rows of their own in a summary table
            return _entry(_interim_lines(row[0]), [_quote_with_label(ctx, b) for b in row[1]], False, _QUARTERLY_BLANK, row[2])
        if rep is None:
            return _blank(*_QUARTERLY_BLANK)
        line, referred = _listed_only(rep, "Quarterly accounts", "quarterly")
        return _entry([line], _report_quotes(ctx, rep, _QUARTER_WORD_RE), referred, _QUARTERLY_BLANK, rep["same"])
    first = quarterly or found.get("half") or found.get("monthly")
    about = _QUARTER_WORD_RE if quarterly else _HALF_WORD_RE if found.get("half") else _MONTH_WORD_RE
    return _entry(lines, _report_quotes(ctx, rep, about, first[4]), False, _QUARTERLY_BLANK, rep["same"])


def _budget_item(rep: dict, at: int) -> tuple[int, int] | None:
    """The item of the reporting section that holds a mention of a budget at offset ``at``, if it is a reporting item: one that
    speaks of delivering something, or that is little more than the name ("annual budget")."""
    text = rep["text"]
    for s, e in rep["all"]:
        if s <= at < e:
            item = text[s:e]
            reporting = (s, e) in rep["spans"] or bool(_DELIVERY_RE.search(item)) or (len(item) <= 90 and not _TEST_RE.search(item))
            return (s, e) if reporting else None
    return None


def _other_reports(rep: dict) -> list[tuple[str, int, int]]:
    """Other reporting named in the section (compliance certificates, notices ...): (wording, start, end) in section order."""
    text = rep["text"]
    hits = []
    for rx in _OTHER_REPORTS:
        for m in rx.finditer(text):
            if any(s <= m.start() < e for s, e in rep["all"]):
                hits.append((m.start(), m.end(), _squeeze(m.group(0), 70)))
                break
    return [(wording, s, e) for s, e, wording in sorted(hits)]


def _budget_line(clause: str, word: str) -> tuple[str, int | None]:
    """(line, period in days if one is stated) for a clause that names a budget, projections or a business plan."""
    m = _BUDGET_AFTER_RE.search(clause) or _BUDGET_RE.search(clause)
    n, unit = _period(m) if m else (None, "")
    if n:
        tail = m.group("tail") or ""
        when = ("after the start of the financial year" if _AFTER_START_RE.search(tail) else "before the start of the financial year" if _BEFORE_START_RE.search(tail)
                else "of financial year end" if _AFTER_END_RE.search(tail) else "")
        named = "" if not when or re.match(r"budget", word, re.IGNORECASE) else f" (term sheet: '{word.lower()}')"
        return f"Annual budget - within {n} {unit}" + (f" {when}{named}" if when else f" ('{_squeeze(m.group(0).split(',')[0], 110)}')"), n
    blank = _BLANK_DAYS_RE.search(clause)
    if blank and blank.start() >= clause.lower().find(word.lower()):
        return f"Annual budget - period left blank in term sheet ('{_squeeze(blank.group(0), 80)}')", None
    return f"Annual budget - required ('{_squeeze(_first_sentence(clause), 140)}'); period {NS}", None


@_safe(_BUDGET_BLANK)
def info_budget(ctx: Ctx) -> dict:
    rep = _reporting(ctx)
    word = None
    if rep is not None and not rep["generic"]:
        word = next((m for m in _BUDGET_WORD_RE.finditer(rep["text"]) if _budget_item(rep, m.start())), None)
    if word is None:
        row = _section(ctx, _BUDGET_ROW_LABEL, want=_BUDGET_ROW_VALUE_RE)  # a row of its own in a summary table
        text, src, same = _read(ctx, row, _BUDGET_ROW_LABEL) if row is not None else ("", None, False)
        if src is not None and len(text) <= 400 and not _CP_WORDING_RE.search(text) and not _YEAR_COLUMNS_RE.search(text):
            if _NONE_RE.match(text) and len(text) < 40:
                return _entry([f"Annual budget - none (term sheet: '{_squeeze(text, 40)}')"], [_quote_with_label(ctx, src)], False, _BUDGET_BLANK, same)
            line, _ = _budget_line(_fix(f"{row.label} {text}"), row.label)
            return _entry([line], [_quote_with_label(ctx, src)], False, _BUDGET_BLANK, same)
    if rep is None:
        return _blank(*_BUDGET_BLANK)
    block = rep["block"]
    if rep["generic"]:
        return _entry([f"Annual budget - {NS}; covenants: {_lower_first(rep['ref'])}"], [_quote(ctx, block)], True, _BUDGET_BLANK)
    text = rep["text"]
    lines, evidence = [], []
    none_listed, open_item, n = False, False, None
    if word:
        s, e = _budget_item(rep, word.start())
        line, n = _budget_line(_fix(text[s:e]), word.group(0))
        lines.append(line)
        evidence.append(_quote(ctx, block, word.start(), word.end()))
    else:
        named = _report_text(rep)
        listed = rep["closed"] and bool(_STATEMENTS_RE.search(named))
        # the covenants are a closed list, but the reporting item may itself be open ("reporting requirements (including ...)") or
        # point elsewhere: then the absence of a budget from it shows nothing
        open_item = listed and bool(_OPEN_ITEM_RE.search(named) or _defers(named))
        none_listed = listed and not open_item
        item = _squeeze(_first_sentence(_fix(named)), 130)
        if none_listed:
            lines.append(f"Annual budget - none: not among the covenants listed in the term sheet, which is a closed list (reporting item: '{item}')")
            evidence += [_quote(ctx, block, *rep["spans"][0]), _lead_quote(ctx, rep)]
        elif open_item:
            lines.append(f"Annual budget - {NS}; not among the reports named, but the reporting item is not exhaustive ('{item}')")
            evidence.append(_quote(ctx, block, *rep["spans"][0]))
        else:
            lines.append(f"Annual budget - {NS}")
    others = _other_reports(rep)
    if others:
        # "not stated" is said only if none of the items that name these reports gives a period of any kind
        items = [text[a:b] for a, b in rep["all"] if any(a <= s < b for _, s, _ in others)]
        periods = "" if any(_has_figure(x) or _BLANK_RE.search(x) or _TIMING_RE.search(x) for x in items) else "; delivery periods not stated"
        basis = f" ({_lower_first(rep['ref'])})" if rep["defers"] and rep["ref"] else ""
        lines.append(_squeeze("Other: " + ", ".join(dict.fromkeys(w for w, _, _ in others)) + periods + basis, LINE_LIMIT + 20))
        evidence.append(_quote(ctx, block, others[0][1], others[0][2]))
    if not (word or none_listed or others) and not (open_item and rep["defers"]):
        # nothing is said of a budget; where the reporting item is open-ended and points nowhere, the row is simply not stated
        note = "The covenants are a closed list, but the reporting item is not exhaustive, so a budget requirement cannot be ruled out." if open_item else ""
        return _blank(*_BUDGET_BLANK, note=note)
    # a period, or a closed list without a budget, is a statement; a bare mention in a section that defers elsewhere is by reference
    return _entry(lines, evidence, rep["defers"] and not n and not none_listed, _BUDGET_BLANK, rep["same"])


RULES: dict = {
    "events_of_default": events_of_default,
    "conditions_subsequent": conditions_subsequent,
    "mandatory_prepayment": mandatory_prepayment,
    "transferability": transferability,
    "info_annual_consolidated": info_annual_consolidated,
    "info_annual_obligor": info_annual_obligor,
    "info_quarterly": info_quarterly,
    "info_budget": info_budget,
}
