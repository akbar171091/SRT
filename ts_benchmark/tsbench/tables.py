"""Pricing grid detection in layout-preserved text.

pypdf's layout mode keeps table cells at roughly their horizontal position, so a grid can be
recovered from character columns:

1. candidate rows are lines whose rate tokens ("0.875%", "112.5 bps", "S+175 bps") stand alone
   in cells rather than inside a sentence;
2. neighbouring candidates form a table, and token centres cluster into value columns. A table
   ends at a heading or header row, where the level numbering starts again, and at a labelled
   rate of its own ("Upfront Fee:   0.10%"), which is a term of the deal rather than a row;
3. lines are grouped into tier bands, so wrapped rows and cells that spill onto the next line
   are stitched back together;
4. header text above each column says what the column is (SOFR margin, base rate margin,
   commitment / facility fee, LC fee, all-in drawn).

Grids laid out sideways (levels across the top, "Commitment Fee" and "Applicable Margin" as rows)
are detected from their row labels and transposed. Rows at the top of the next page are added to
the grid that ran to the foot of the page before, when they demonstrably carry it on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median

from .textmodel import Doc, Line, clip, fragments, is_footer, is_page_furniture, tidy

COL_TOL = 7.0  # token centres closer than this share a column
MAX_ROW_GAP = 6  # lines allowed between two rows of one table
MAX_TABLE_ROWS = 60  # no pricing grid is this long: a longer run of rate rows is some other schedule
MAX_COLUMNS = 12  # nor this wide
MIN_MARGIN_BPS = 10.0  # a margin column that never reaches this was read in the wrong unit, or is not a margin
MAX_LONE_FEE_BPS = 100.0  # an undrawn fee above this, in a table without a margin, is something else under the wrong header
_KEYED = ("drawn", "all_in", "commitment_fee", "facility_fee")  # a grid needs at least one of these columns
_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI")


@dataclass
class Tok:
    start: int
    end: int
    bps: float
    splus: bool = False  # written as a spread over the term rate ("S + 175 bps")
    base: bool = False  # written as a spread over the base rate ("ABR + 75 bps")
    whole: bool = False  # a bare whole number: a rate only where its column header says basis points

    @property
    def centre(self) -> float:
        return (self.start + self.end) / 2


@dataclass
class Tier:
    level: str
    criteria: str
    values: dict[str, float]
    quote: str
    line: int


@dataclass
class Grid:
    page: int
    first_line: int
    last_line: int
    tiers: list[Tier]
    metric: str  # header of the criteria column, e.g. "Leverage Ratio"
    columns: list[str]  # class of each value column, left to right
    undrawn_fee_type: str
    context: str  # heading text above the table
    transposed: bool = False
    notes: list[str] = field(default_factory=list)
    heading: str = ""  # the line directly above the header, e.g. "Proposed Pricing Grid"
    col_x: list[float] = field(default_factory=list)  # centre of each value column, left to right


_VALUE_RE = re.compile(
    r"(?P<pre>\b(?:(?P<sofr>(?:(?:Adjusted\s+)?(?:Daily\s+Simple\s+)?(?:Term\s+)?SOFR|LIBOR|S|L)\s*\+\s*(?:CSA\s*\+\s*)?)"
    # "B + 1.00%" needs its single spaces: "B+  3.00%" and "B +     3.00%" are a rating followed by a rate in the next cell
    r"|(?:(?:Alternate\s+)?Base\s+Rate|ABR|Prime(?:\s+Rate)?)\s*\+\s*|B \+ (?=\d)))?"
    r"(?<![\w.,$/])(?P<num>\d{1,4}(?:\.\d{1,4})?)\s*(?P<unit>%|bps\b|bp\b|basis\s+points\b)",
    re.IGNORECASE,
)
_BARE_RE = re.compile(r"(?<![\w.,$:/<>\u2264\u2265+\-])(\d{1,3}\.\d{1,3})(?![\w.:%/])(?!\s*(?:x\b|to\s+1|:\s*1))")
_NUM_RE = re.compile(r"(?<![\w.,$:/<>\u2264\u2265+\-])(?<!to )(\d{1,4}(?:\.\d{1,3})?)(?![\w.,:%/])(?!\s*(?:x\b|to\s+1|:\s*1))")
_INT_RE = re.compile(r"(?<![\w.,$:/<>\u2264\u2265+\-])(\d{1,3}(?:\.\d{1,3})?)(?![\w.:%/])")
_UNIT_ONLY_RE = re.compile(r"\b(bps|bp)\b|%", re.IGNORECASE)
_UNIT_WORD_RE = re.compile(r"\b(?:bps|bp|basis\s+points?)\b|%", re.IGNORECASE)
_LABEL_PREFIX_RE = re.compile(r"^(?:indicative\s+)?pricing(?!\s+(?:level|category|tier))(?:\s+grid)?\s*:?\s+", re.IGNORECASE)
_LEVEL_RE = re.compile(
    r"^(?:(?:pricing\s+)?(?:level|category|tier)\s*)?(?P<lvl>[IVX]{1,4}|\d{1,2})(?=\s|:|\)|$)[:)]?\s*", re.IGNORECASE
)
_METRIC_ROW_RE = re.compile(
    r"^\W*(?:drawn|undrawn|unused|commitment\s+fee|facility\s+fee|applicable\s+margin|applicable\s+rate|margin|spread|"
    r"l/?c\b|letter\s+of\s+credit|sofr|term\s+sofr|base\s+rate|abr\b|all[- ]in|ticking)",
    re.IGNORECASE,
)
_PRICING_WORD_RE = re.compile(r"margin|spread|pricing|\bfee|sofr|\brate\b|drawn", re.IGNORECASE)
_LEVEL_NAMES_RE = re.compile(r"\b(?:level|category|tier)\s+([IVX]{1,4}|\d{1,2})\b", re.IGNORECASE)
# The last word of a sideways row's name, left on the rate line when the name wrapped ("Facility" / "Fee   0.07% ...").
_LABEL_TAIL_RE = re.compile(r"^\W*(?:fees?(?:\s+rates?)?|rates?|margins?|spreads?|loans?|advances)\W*(?:\(\w{1,3}\)\W*)?$", re.IGNORECASE)
_TERM_LABEL_RE = re.compile(r"[A-Za-z][A-Za-z /&()'\u2019-]*:?")
# What a label without a colon must end in to name a term of the deal ("Upfront fee", "Default rate", "MFN protection").
_TERM_WORD_RE = re.compile(r"\b(?:fees?|rates?|margins?|spreads?|adjustment|csa|floor|premium|discount|oid|amorti[sz]ation|sweep|"
                           r"protection|coupon|yield)\W*$", re.IGNORECASE)
# Words that make a label a tier's criteria ("Lower or unrated:", "Thereafter:") rather than the name of a term.
_NOT_A_TERM_RE = re.compile(r"\b(?:thereafter|otherwise|else|lower|higher|below|above|worse|better|less|greater|(?:un)?rated|grade)\b"
                            r"|\bno\s+ratings?\b|^\W*(?:all\s+)?others?\W*$|\b(?:A{1,3}|B{1,3}|Aaa|Aa|Baa|Ba)\s*/", re.IGNORECASE)
_TIER_LABEL_RE = re.compile("[<>=/" + chr(0x2264) + chr(0x2265) + r"]|\d")  # a ratio, a rating pair, a period: criteria of a tier
_OLD_TERMS_RE = re.compile(r"^\W*(?:existing|current|old|prior|previous|original)\b", re.IGNORECASE)
_NEW_TERMS_RE = re.compile(r"^\W*(?:proposed|amended|new|revised)\b", re.IGNORECASE)
# What the header of a column of bare whole numbers must say for the column to be a rate, and what shows it is an amount.
_RATE_NAME_RE = re.compile(r"margin|spread|\bfees?\b|\brates?\b|sofr|libor|loans|advances|pricing|all[- ]in|drawn|unused|ticking|\babr\b"
                           r"|\bl/?c\b|letters?\s+of\s+credit", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\$|\b(?:mm|mn|millions?|billions?|usd|amounts?)\b", re.IGNORECASE)


def value_tokens(text: str) -> list[Tok]:
    out = []
    for m in _VALUE_RE.finditer(text):
        v = float(m.group("num"))
        if m.group("unit") == "%":
            v *= 100.0
        start = m.start("pre") if m.group("pre") else m.start("num")
        out.append(Tok(start=start, end=m.end(), bps=round(v, 4), splus=bool(m.group("sofr")),
                       base=bool(m.group("pre")) and not m.group("sofr")))
    return out


def _isolated(text: str, tok: Tok) -> bool:
    """True when the token sits in its own cell (wide gaps around it) rather than inside a sentence."""
    before, after = text[: tok.start], text[tok.end:]
    right_ok = not after.strip() or after.startswith("  ")
    left_ok = not before.strip() or before.endswith("  ") or before.rstrip().endswith(":")
    return right_ok and left_ok


def _other_text(text: str, toks: list[Tok]) -> str:
    """Text between and after the tokens (cells that are not rates)."""
    parts, pos = [], toks[0].end
    for t in toks[1:]:
        parts.append(text[pos:t.start])
        pos = t.end
    parts.append(text[pos:])
    return tidy(" ".join(parts))


def _number_cells(text: str) -> list[Tok]:
    """Numbers standing alone in cells, without the level number that opens a row ("3    < 2.00x    150    25")."""
    cells = [Tok(m.start(1), m.end(1), float(m.group(1)), whole="." not in m.group(1)) for m in _NUM_RE.finditer(text)]
    cells = [t for t in cells if _isolated(text, t)]
    if cells and cells[0].whole and not text[: cells[0].start].strip():
        del cells[0]
    return cells


def _candidate(ln: Line) -> tuple[str, list[Tok]] | None:
    text = ln.text
    if not text.strip() or is_footer(text):
        return None
    toks = value_tokens(text)
    if toks:
        if not all(_isolated(text, t) for t in toks):
            return None
        if len(tidy(text[: toks[0].start])) > 70 or len(_other_text(text, toks)) > 45:
            return None
        return "unit", toks
    bare = [Tok(m.start(1), m.end(1), float(m.group(1))) for m in _BARE_RE.finditer(text)]
    cells = _number_cells(text)
    # A whole number counts only beside another number, and only under a header that says basis points (see _normal).
    for row, least in ((cells if any(t.whole for t in cells) else [], 2), (bare, 3)):
        if len(row) >= least and all(_isolated(text, t) for t in row) \
                and len(tidy(text[: row[0].start])) <= 45 and len(_other_text(text, row)) <= 12:
            return "bare", row
    return None


def _classify(header: str) -> str:
    h = header.lower()
    if re.search(r"floor|adjustment|\bcsa\b", h):
        # a benchmark floor or credit spread adjustment is not a margin; a column that is nothing else is not a fee either
        return "unknown" if re.search(r"margin|all[- ]in|drawn|loans|advances|\+", h) else "other"
    if re.search(r"\bnon[- ]?(?:utili[sz]ation|usage|use)\b|\bun-?utili[sz]ed\b", h):
        return "commitment_fee"  # the fee for not using the facility: the opposite of a utilisation fee
    if re.search(r"(?:utili[sz]ation|usage)\s+(?:fee|premium)", h):
        return "other"  # charged on top of the margin when the facility is heavily used: neither margin nor undrawn fee
    if re.search(r"\b(?:fronting|issuance|duration|extension|amendment|consent|agency|structuring|underwriting|prepayment|exit)\s+(?:fees?|premium)", h):
        return "other"  # a fee with a name of its own is not the undrawn fee, however small it is
    if re.search(r"performance\s+(?:letters?\s+of\s+credit|l/?c)", h):
        return "other"  # a separate, lower fee for performance letters of credit
    if re.search(r"all[- ]in", h):
        return "all_in"
    if re.search(r"sofr|term benchmark|benchmark loans|term rate|eurodollar|euro-?currency|libor|\brfr\b|sonia|bsby", h):
        return "drawn"
    if re.search(r"base rate|\babr\b|alternate base|prime|index rate|floating rate", h):
        return "base"
    if re.search(r"facility fee", h):
        return "facility_fee"
    if re.search(r"commitment fee|unused|undrawn|ticking|commitment\s*fee|\bfee rate\b", h) and "letter of credit" not in h:
        return "commitment_fee"
    if re.search(r"letter of credit|letters of credit|l/c|\blc\b", h):
        return "lc"
    if re.search(r"commitment", h):
        return "commitment_fee"
    if re.search(r"upfront|up-front|closing fee|arrangement", h):
        return "upfront"
    if re.search(r"margin|spread|pricing|applicable rate|drawn|\brate\b", h):
        return "drawn"
    return "unknown"


def _unit_scale(header: str) -> float | None:
    """Multiplier to basis points for the unit a header names ("(bps)" 1, "%" 100); None when it names neither or both."""
    low = header.lower()
    bps = "bps" in low or "basis point" in low
    pct = "%" in low or "percent" in low
    return (1.0 if bps else 100.0) if bps != pct else None


def _cluster_columns(centres: list[float]) -> list[float]:
    groups: list[list[float]] = []  # [sum, count] of each cluster: a running mean keeps this linear in the number of rows
    for c in sorted(centres):
        if groups and c - groups[-1][0] / groups[-1][1] <= COL_TOL:
            groups[-1][0] += c
            groups[-1][1] += 1
        else:
            groups.append([c, 1])
    return [total / count for total, count in groups]


def _nearest(cols: list[float], x: float) -> int:
    return min(range(len(cols)), key=lambda i: abs(cols[i] - x))


def _merge_columns(cols: list[float], rows: list[list[Tok]], expected: int) -> list[float]:
    """Fold stray columns together when a row was typeset out of line with the others.

    No row has more than ``expected`` rates, so more columns than that means some cell drifted
    sideways. Adjacent columns are merged, nearest first, as long as no single row uses both.
    """
    cols = sorted(cols)
    while len(cols) > expected:
        used = [{_nearest(cols, t.centre) for t in toks} for toks in rows]  # once per pass, not once per pair of columns
        best: tuple[float, int] | None = None
        for i in range(len(cols) - 1):
            gap = cols[i + 1] - cols[i]
            if gap > 30 or (best and gap >= best[0]):
                continue
            if not any({i, i + 1} <= u for u in used):
                best = (gap, i)
        if best is None:
            break
        i = best[1]
        cols[i: i + 2] = [(cols[i] + cols[i + 1]) / 2]
    return cols


@dataclass
class _Band:
    lines: list[Line] = field(default_factory=list)  # candidate lines
    extra: list[Line] = field(default_factory=list)  # continuation lines without rates
    head: list[Line] = field(default_factory=list)  # start of a sideways row's name that wrapped above its rate line
    cells: dict[int, Tok] = field(default_factory=dict)

    @property
    def first(self) -> Line:
        return self.lines[0]


def _candidates(doc: Doc) -> dict[int, tuple[str, list[Tok]]]:
    """Candidate rows by line number: ("unit" | "bare", rate tokens)."""
    cands: dict[int, tuple[str, list[Tok]]] = {}
    for ln in doc.lines:
        c = _candidate(ln)
        if c:
            cands[ln.n] = c
    # A row of whole numbers counts only beside another row of bare numbers: on its own it is a line of years or of
    # level numbers, and as a candidate it would cut the header off the table underneath.
    bare = [n for n in cands if cands[n][0] == "bare"]
    for i, n in enumerate(bare):
        beside = [m for m in bare[max(0, i - 1): i + 2] if m != n and abs(m - n) <= MAX_ROW_GAP and doc.lines[m].page == doc.lines[n].page]
        if not beside and any(t.whole for t in cands[n][1]):
            del cands[n]
    return cands


def find_grids(doc: Doc, notes: list[str] | None = None) -> list[Grid]:
    """Pricing grids in reading order. ``notes``, when given, collects tables headed as pricing grids that were not read."""
    cands = _candidates(doc)
    grids: list[Grid] = []
    page = 0
    for group in _tables(doc, cands):
        # Only the first table of a page can be the rest of a grid that closed the page before.
        prev = grids[-1] if grids and doc.lines[group[0]].page != page else None
        page = doc.lines[group[0]].page
        carry = prev if prev is not None and not prev.transposed and _page_turn(doc, prev.last_line, group[0], 2) else None
        if not (1 if carry else 2) <= len(group) <= MAX_TABLE_ROWS:
            continue
        g = _build(doc, group, cands, carry, notes)
        if g is None:
            _left_unread(doc, cands, group, grids[-1] if grids else None, carry is not None)
        elif g is not carry and not (prev is not None and _repeats_header(doc, cands, prev, g) and _continue(prev, g)):
            grids.append(g)
    return _without_existing(grids)


def _left_unread(doc: Doc, cands: dict, group: list[int], near: Grid | None, page_turn: bool) -> None:
    """Say on the grid next to them that rate rows were left unread. Labelled fee lines are not rows and need no mention."""
    if near is None or 2 * sum(1 for n in group if _own_term(doc.lines[n].text, cands[n][1])) > len(group):
        return
    page = doc.lines[group[0]].page
    if page_turn and len(cands[group[0]][1]) <= len(near.columns):
        near.notes.append(f"Rate rows at the top of page {page} may carry this table on; they could not be tied to it and were not read.")
    elif len(group) >= 2 and page == doc.lines[near.last_line].page and group[0] - near.last_line <= MAX_ROW_GAP + 2:
        near.notes.append(f"{_count(len(group), 'rate row')} below this table were not read: they do not make a pricing grid on their own.")


def _row_label(text: str, toks: list[Tok]) -> str:
    return _LABEL_PREFIX_RE.sub("", tidy(text[: toks[0].start])).strip()


def _is_prose(line: str) -> bool:
    """Running text rather than a row of header cells."""
    text = line.rstrip()
    return text.endswith((".", ";")) or (text.endswith(":") and len(text.split()) > 4) \
        or any(len(f[2].split()) >= 9 for f in fragments(line, 3))


def _layout_pages(doc: Doc) -> set[int]:
    """Pages whose lines keep their horizontal position.

    pypdf's layout mode indents lines; its plain mode, used for rotated pages, starts every line at the left edge.
    """
    lines: dict[int, int] = {}
    indented: dict[int, int] = {}
    for ln in doc.lines:
        if not ln.blank:
            lines[ln.page] = lines.get(ln.page, 0) + 1
            indented[ln.page] = indented.get(ln.page, 0) + (ln.indent > 0)
    return {page for page, n in lines.items() if 10 * indented[page] > n}


def _opens_table(doc: Doc, cands: dict, prev: int, n: int) -> bool:
    """True when a heading or a header row stands between two rate rows: the second one starts another table.

    A header row is told from a wrapped cell by where it is: it has words above at least half of the next row's rates,
    in cells of their own. Wrapped criteria can be long ("Lower than Level 1 but at least A+ or A1 by each of the two
    rating agencies") and run on under the rates, but they start in the label column, left of where the row's own
    label ends. Where a proportional font has pulled header and rows out of line, a header row still shows by having
    a cell of words for every rate of the row, clear of the label, and one more for the label; the wrapped ends of
    three rating cells ("or better   or better   or better") are all in the label columns.
    """
    toks = cands[n][1]
    label_end = len(doc.lines[n].text[: toks[0].start].rstrip())
    for i in range(prev + 1, n):
        text = doc.lines[i].text
        if not text.strip() or is_page_furniture(text):
            continue
        named = [(s, e) for s, e, cell in fragments(text, 2) if re.search(r"[A-Za-z]{3}", _UNIT_WORD_RE.sub("", cell))]
        apart = [(s, e) for s, e in named if s >= label_end]
        over = sum(1 for t in toks if any(min(e, t.end) - max(s, t.start) >= 3 for s, e in apart))
        if 2 * over >= len(toks) or (len(named) >= max(3, len(toks) + 1) and len(apart) >= len(toks)):
            return True
    return False


def _runs(doc: Doc, cands: dict, lines: list[int], layout: set[int]) -> list[list[int]]:
    """Split candidate lines, in ascending order, into runs that can each be one table.

    ``layout`` holds the pages read with layout. On the others every line starts at the left edge, so what stands
    above a rate says nothing, and only the level numbering can end a table.
    """
    runs: list[list[int]] = []
    levels: set[str] = set()
    last = ""  # level of the row before, if it opened with one
    for n in lines:
        found = _explicit_level(_row_label(doc.lines[n].text, cands[n][1]))
        prev = runs[-1][-1] if runs else None
        # "III" under "II" is the next row of the same table: words between them are a wrapped cell or a remark, not a header
        carries_on = bool(found) and found[0] == _next_level(last)
        if prev is None or doc.lines[n].page != doc.lines[prev].page or cands[n][0] != cands[prev][0] or n - prev > MAX_ROW_GAP \
                or (found and found[0] in levels) \
                or (not carries_on and doc.lines[n].page in layout and _opens_table(doc, cands, prev, n)):
            runs.append([])
            levels = set()
        runs[-1].append(n)
        if found:
            levels.add(found[0])  # a level seen twice means the numbering started again: two tables
        last = found[0] if found else ""
    return runs


def _term_label(text: str, toks: list[Tok]) -> str:
    """The label of a line with a single rate, when it is plain words that name something rather than a level or criteria."""
    label = tidy(text[: toks[0].start])
    plain = len(toks) == 1 and _TERM_LABEL_RE.fullmatch(label) and not _explicit_level(label) and not _NOT_A_TERM_RE.search(label)
    return label if plain else ""


def _own_term(text: str, toks: list[Tok]) -> bool:
    """"Upfront Fee:   0.10%": one rate under a label of its own, which names a term of the deal and not a tier."""
    label = _term_label(text, toks)
    return label.endswith(":") or bool(_TERM_WORD_RE.search(label))


def _tables(doc: Doc, cands: dict) -> list[list[int]]:
    """Candidate lines grouped into tables, in reading order."""
    out: list[list[int]] = []
    layout = _layout_pages(doc)
    for run in _runs(doc, cands, sorted(cands), layout):
        label = {n: _row_label(doc.lines[n].text, cands[n][1]) for n in run}
        own = {n for n in run if _own_term(doc.lines[n].text, cands[n][1])}
        tiers = [n for n in run if n not in own and (_explicit_level(label[n]) or _TIER_LABEL_RE.search(label[n]))]
        if sum(1 for n in tiers if len(cands[n][1]) > 1) >= 2:
            # Where the tiers hold several rates each, one rate under plain words is no tier, whatever the words end in
            # ("Hedging   50 bps", or "Drawn   S + 300 bps" for another facility).
            own |= {n for n in run if n not in tiers and _term_label(doc.lines[n].text, cands[n][1])}
        rows = [n for n in run if n not in own]
        named = sum(1 for n in rows if _METRIC_ROW_RE.match(label[n]))
        # Next to two or more tier rows (a level, a ratio, a rating) a labelled rate is a separate term. Among rows that
        # are themselves named ("Drawn", "Undrawn", "LC Fee:") it is one more row of a sideways table, and among other
        # lines of percentages nothing is known about it.
        if own and len(tiers) >= 2 and 2 * named < len(rows):
            out += _runs(doc, cands, rows, layout) + _runs(doc, cands, sorted(own), layout)
        else:
            out.append(run)
    return sorted(out, key=lambda g: g[0])


def _page_turn(doc: Doc, last: int, first: int, running_header: int = 0) -> bool:
    """True when line ``first`` opens the page after the one that line ``last`` closes, page furniture aside.

    Up to ``running_header`` lines of other text may stand above ``first`` on its page.
    """
    page = doc.lines[last].page
    if doc.lines[first].page != page + 1:
        return False
    for ln in doc.lines[last + 1: first]:
        if ln.blank or is_footer(ln.text):
            continue
        running_header -= 1
        if ln.page == page or running_header < 0:
            return False
    return True


def _repeats_header(doc: Doc, cands: dict, prev: Grid, g: Grid) -> bool:
    """True when grid ``g``, header included, opens the page after the one ``prev`` closed."""
    header = _header(doc, g.first_line, cands)[0]
    return _page_turn(doc, prev.last_line, min([ln.n for ln in header] + [g.first_line]), 2)


def _next_level(level: str) -> str:
    if level.isdigit():
        return str(int(level) + 1)
    return _ROMAN[_ROMAN.index(level) + 1] if level in _ROMAN[:-1] else ""


def _same_spacing(a: list[float], b: list[float]) -> bool:
    """Two sets of columns laid out alike. Pages may differ in scale: pypdf sizes its character grid page by page."""
    if len(a) != len(b):
        return False
    ratios = [(y - b[0]) / (x - a[0]) for x, y in zip(a[1:], b[1:])]
    return not ratios or (min(ratios) > 0.6 and max(ratios) < 1.6 and max(ratios) <= 1.25 * min(ratios))


def _continue(a: Grid, b: Grid) -> bool:
    """Append the tiers of ``b`` to ``a`` if ``b`` is the same table carried over a page break; say whether it was."""
    if a.transposed or b.transposed or a.columns != b.columns or not _same_spacing(a.col_x, b.col_x):
        return False
    numbered = [t.level for t in b.tiers] == [str(i + 1) for i in range(len(b.tiers))]  # rows without levels of their own
    if b.tiers[0].level != _next_level(a.tiers[-1].level) and not (numbered and a.tiers[-1].level == str(len(a.tiers))):
        return False  # the level numbering does not carry on: another table
    key = next(c for c in a.columns if c in _KEYED)
    rates = [t.values.get(key) for t in a.tiers + b.tiers]
    if None in rates or (len(rates) >= 3 and not _monotonic(rates)):
        return False
    if {t.criteria for t in a.tiers} & {t.criteria for t in b.tiers} - {""}:
        return False  # the same criteria twice: a second table for another facility
    for i, t in enumerate(b.tiers, len(a.tiers) + 1):
        t.level = str(i) if numbered else t.level
    a.notes += [f"The table runs on to page {b.page}: {_count(len(b.tiers), 'tier')} read from there."] + b.notes
    a.tiers += b.tiers
    a.last_line = b.last_line
    return True


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _without_existing(grids: list[Grid]) -> list[Grid]:
    """Where one table is headed "Existing Pricing Grid" and its neighbour "Proposed Pricing Grid", only the proposed one prices the deal."""
    def subject(g: Grid, word: re.Pattern) -> str:
        return tidy(word.sub("", g.heading)).lower()

    proposed: dict[int, list[Grid]] = {}
    for g in grids:
        if _NEW_TERMS_RE.match(g.heading):
            proposed.setdefault(g.page, []).append(g)
    out = []
    for g in grids:
        old = subject(g, _OLD_TERMS_RE) if _OLD_TERMS_RE.match(g.heading) else None
        # the same thing under both headings ("Pricing Grid"), on the same page or the one beside it
        new = next((n for page in (g.page, g.page + 1, g.page - 1) for n in proposed.get(page, [])
                    if old is not None and (old in subject(n, _NEW_TERMS_RE) or subject(n, _NEW_TERMS_RE) in old)), None)
        if new is not None:
            new.notes.append(f'The table headed "{clip(g.heading, 60)}" on page {g.page} was left out as the existing terms.')
        else:
            out.append(g)
    return out


def _unread(notes: list[str] | None, page: int, rows: int, why: str) -> None:
    """Record a table headed as a pricing grid that was not read (three rows or more: shorter ones are rarely grids)."""
    note = f"Page {page}: a pricing table of {rows} rows was not read ({why})."
    if notes is not None and rows >= 3 and note not in notes:
        notes.append(note)


def _build(doc: Doc, group: list[int], cands: dict[int, tuple[str, list[Tok]]], after: Grid | None = None,
           notes: list[str] | None = None) -> Grid | None:
    kind = cands[group[0]][0]
    least = 1 if after else 2  # rows that carry a grid on to the next page may be a single tier
    widest = max(len(cands[n][1]) for n in group)
    raw = _cluster_columns([t.centre for n in group for t in cands[n][1]])
    if widest > MAX_COLUMNS or len(raw) > 4 * widest + 8:
        return None  # rows this wide, or this far out of line with each other, are no grid: stop before the costly steps

    def columns_of(lines: list[int]) -> list[float]:
        rows = [cands[n][1] for n in lines]
        return _merge_columns(_cluster_columns([t.centre for toks in rows for t in toks]), rows, max(len(toks) for toks in rows))

    # A named rate in a column that no fuller row uses ("MFN protection   50 bps" beside a three-column grid) is not a row.
    # Checked before stray columns are folded together below, which would make it one.
    if widest > 1:
        shared = {_nearest(raw, t.centre) for n in group if len(cands[n][1]) > 1 for t in cands[n][1]}
        rows = [n for n in group if _nearest(raw, cands[n][1][0].centre) in shared or not _term_label(doc.lines[n].text, cands[n][1])]
        group = rows if len(rows) >= least else group
    cols = columns_of(group)
    # A lone labelled rate next to the table ("Commitment fee   0.50%") sits in a column of its own: not a row.
    used = [{_nearest(cols, t.centre) for t in cands[n][1]} for n in group]
    use = [sum(1 for u in used if ci in u) for ci in range(len(cols))]
    if max(use) >= 2:
        stray = {ci for ci, u in enumerate(use) if u == 1}
        group = [n for n, u in zip(group, used) if not u <= stray]
        if len(group) < least:
            return None
        cols = columns_of(group)
    if not cols or len(cols) > MAX_COLUMNS:
        return None
    left_edge = min(t.start for n in group for t in cands[n][1] if _nearest(cols, t.centre) == 0) - 3
    first, last = group[0], group[-1]
    rows_of_table = set(group)  # rate lines left out above (a fee line, a stray rate) are no part of any row

    # Trailing criteria that wrapped below the last row ("or lower").
    end = last
    for n in range(last + 1, min(last + 3, len(doc.lines))):
        ln = doc.lines[n]
        if ln.page != doc.lines[last].page or ln.blank or is_page_furniture(ln.text) or n in cands:
            break
        if len(ln.text.rstrip()) > left_edge + 4 or len(ln.text.strip()) > 40:
            break
        end = n

    bands: list[_Band] = []
    cur: _Band | None = None
    for n in range(first, end + 1):
        ln = doc.lines[n]
        if n in rows_of_table:
            toks = cands[n][1]
            here = {_nearest(cols, t.centre): t for t in toks}
            if cur is None or (set(here) & set(cur.cells)):
                cur = _Band()
                bands.append(cur)
            cur.lines.append(ln)
            cur.cells.update(here)
        elif cur is not None and not ln.blank and not is_page_furniture(ln.text) and n not in cands:
            cur.extra.append(ln)
    if not bands:
        return None

    # A cell split over two lines: "bps" on the row line and the number underneath (or the reverse).
    for b in bands:
        for ci, cx in enumerate(cols):
            if ci in b.cells:
                continue
            units = [m for ln in b.lines + b.extra for m in _UNIT_ONLY_RE.finditer(ln.text)
                     if abs((m.start() + m.end()) / 2 - cx) <= 9 and not ln.text[: m.start()].rstrip()[-1:].isdigit()]
            nums = [m for ln in b.extra + b.lines for m in _INT_RE.finditer(ln.text) if abs((m.start(1) + m.end(1)) / 2 - cx) <= 9]
            if units and nums:
                v = float(nums[0].group(1))
                b.cells[ci] = Tok(nums[0].start(1), nums[0].end(1), v * 100.0 if units[0].group(0) == "%" else v)

    def label_of(ln: Line, own_cell: bool = False) -> str:
        """Level / criteria cells of one line: everything left of the first value column.

        Read from column 0 even on a split page (see views.py): the row label of an existing-versus-proposed
        table sits in the label column, left of ``qstart``. ``own_cell`` leaves that column out.
        """
        stop = left_edge
        if ln.n in rows_of_table:
            tok = cands[ln.n][1][0]
            stop = tok.start if _nearest(cols, tok.centre) == 0 else left_edge
        return ln.text[(ln.qstart if own_cell else 0): max(0, stop)]

    def band_label(b: _Band, wrapped: bool, own_cell: bool = False) -> str:
        """Row label: with the wrapped lines under the row (a tier's criteria), or as a sideways row's name."""
        lines = sorted(b.lines + (b.extra if wrapped else b.head), key=lambda x: x.n)
        return tidy(" ".join(p for p in (label_of(ln, own_cell) for ln in lines) if p.strip()))

    # A sideways row's name may start on the line above its rates: "Facility" over "Fee   0.07%   0.09%".
    for b in bands:
        n = b.first.n - 1
        while _LABEL_TAIL_RE.match(label_of(b.first)) and n >= 0 and len(b.head) < 2:
            ln = doc.lines[n]
            if ln.page != b.first.page or ln.blank or n in cands or is_page_furniture(ln.text) or _is_prose(ln.text) \
                    or len(ln.text.rstrip()) > left_edge + 2:
                break
            b.head.insert(0, ln)
            n -= 1

    header_lines, context, heading = _header(doc, bands[0].head[0].n if bands[0].head else first, cands)
    head_text = " ".join(ln.text for ln in header_lines)

    def named(label: str) -> bool:
        return bool(_METRIC_ROW_RE.match(_LABEL_PREFIX_RE.sub("", label)))

    def row_name(b: _Band) -> str:
        """Name of a sideways row. The line under its rates is taken in only where it completes the name ("Facility" over "Fee")."""
        name = band_label(b, wrapped=False)
        under = next((ln for ln in b.extra if ln.n == b.lines[-1].n + 1), None)
        if name and under is not None and not named(name) and len(under.text.rstrip()) <= left_edge + 2:
            longer = tidy(name + " " + label_of(under))
            return longer if named(longer) else name
        return name

    # Sideways grids are recognised by what their rows are called ("Commitment Fee", "Applicable Margin"),
    # read from the rate lines: a wrapped line underneath usually belongs to something else.
    row_labels = [row_name(b) for b in bands]
    metric_rows = sum(1 for lab in row_labels if named(lab))
    transposed = metric_rows >= max(1, (len(bands) + 1) // 2) and not any(
        re.search(r"[<>\u2264\u2265]|\d\.\d+\s*x|/\s*(?:Aa|A|Baa|Ba|B)\d", lab) for lab in row_labels
    )
    if transposed:
        scale = _unit_scale(head_text) if kind == "bare" else 1.0
        if scale is None or len(group) < 2:
            return None  # a table of plain numbers with no rate unit is not a pricing grid
        return _transposed(doc, bands, row_labels, cols, header_lines, context, heading, scale)
    # On a split page a grid names its tiers in its own cells, and the label column only holds the section label
    # ("Pricing"); where the cells hold nothing but rates, the label column names the tiers ("Level I").
    labels = [band_label(b, wrapped=True, own_cell=True) for b in bands]
    if not any(labels):
        labels = [band_label(b, wrapped=True) for b in bands]
    return _normal(doc, bands, labels, cols, left_edge, header_lines, context, heading,
                   head_text if kind == "bare" else None, after, notes)


def _header(doc: Doc, first: int, cands: dict) -> tuple[list[Line], str, str]:
    """Header lines directly above the first row, the heading text above those, and the line next above the header."""
    page = doc.lines[first].page

    def on_page(i: int) -> bool:
        return i >= 0 and doc.lines[i].page == page

    def skip_blanks(i: int, limit: int) -> int:
        while on_page(i) and doc.lines[i].blank and limit > 0:
            i, limit = i - 1, limit - 1
        return i

    header: list[Line] = []
    n = skip_blanks(first - 1, 3)
    while on_page(n) and len(header) < 10:
        ln = doc.lines[n]
        if ln.blank or n in cands:
            break  # the header is the unbroken run of lines directly above the first row
        if is_page_furniture(ln.text):  # judged on its words: a short header cell far to the right ("Fee") is no page number
            n -= 1
            continue
        if _is_prose(ln.text):
            break  # running prose, not a column header
        header.append(ln)
        n -= 1
    # A row of level names ("LEVEL I   LEVEL II ...") may sit above a blank line.
    m = skip_blanks(n, 2)
    if on_page(m) and len(_LEVEL_NAMES_RE.findall(doc.lines[m].text)) >= 2:
        header.append(doc.lines[m])
        n = m - 1
    header.reverse()
    m = skip_blanks(n, 3)
    heading = doc.lines[m].text if on_page(m) and m not in cands and not is_page_furniture(doc.lines[m].text) else ""
    heading = "" if _is_prose(heading) else tidy(heading)
    ctx: list[str] = []
    while n >= 0 and doc.lines[n].page == page and len(ctx) < 8 and n not in cands:  # a rate row above is another table
        if not doc.lines[n].blank and not is_page_furniture(doc.lines[n].text):
            ctx.append(tidy(doc.lines[n].text))
        n -= 1
    ctx.reverse()
    return header, " ".join(ctx), heading


def _column_headers(header_lines: list[Line], cols: list[float], left_edge: int, label_cells: int | None) -> tuple[list[str], str, list[str]]:
    """Header text of each value column, of the criteria column, and of cells that span several value columns.

    ``label_cells`` is the number of cells every row has in front of its rates, when they all have the same.
    """
    per_col: list[list[str]] = [[] for _ in cols]
    spanning: list[list[str]] = [[] for _ in cols]
    criteria: list[str] = []
    lines = [fragments(ln.text, 2) for ln in header_lines]
    full = next((cells for cells in reversed(lines) if label_cells is not None and len(cells) == label_cells + len(cols)), None)
    if full is not None:
        # The header line next to the rows that has a cell for every cell of a row: its cells are matched in order, and
        # the pieces of wrapped header cells on the other lines go to the nearest of them. Position against the rates
        # misleads where a proportional font has pushed the rates to the right of their headers.
        anchors = [(start + end) / 2 for start, end, _ in full]
        for cells in lines:
            for k, (start, end, text) in enumerate(cells):
                under = [i for i, c in enumerate(anchors) if start <= c <= end]
                if cells is not full and len(under) > 1:  # a title over several cells names none of them
                    for i in under[max(0, label_cells - under[0]):]:
                        spanning[i - label_cells].append(text)
                    continue
                k = k if cells is full else _nearest(anchors, (start + end) / 2)
                (criteria if k < label_cells else per_col[k - label_cells]).append(text)
        return [tidy(" ".join(p)) for p in per_col], tidy(" ".join(criteria)), [tidy(" ".join(p)) for p in spanning]
    spacing = min((b - a for a, b in zip(cols, cols[1:])), default=40.0)
    reach = max(12.0, spacing * 0.75)
    for ln in header_lines:
        for start, end, text in fragments(ln.text, 2):
            centre = (start + end) / 2
            ci = _nearest(cols, centre)
            under = [i for i, c in enumerate(cols) if start <= c <= end]
            if end <= left_edge + 2 or (centre < left_edge and start < left_edge - 6):
                criteria.append(text)
            elif len(under) > 1:  # header cells run together, or a title: it names none of the columns under it
                for i in under:
                    spanning[i].append(text)
            elif abs(cols[ci] - centre) <= reach:
                per_col[ci].append(text)
    return [tidy(" ".join(p)) for p in per_col], tidy(" ".join(criteria)), [tidy(" ".join(p)) for p in spanning]


def _resolve_classes(classes: list[str], column_values: list[list[float]], splus: list[bool], fee_guess: list[bool]) -> list[str]:
    classes = list(classes)
    seen: set[str] = set()
    for i, c in enumerate(classes):  # the first column of a kind wins; repeats are alternate-currency variants
        if c in seen and c not in ("unknown", "other"):
            classes[i] = "other"
        seen.add(c)
    if "drawn" not in classes and "all_in" not in classes:
        unknown = [i for i, c in enumerate(classes) if c == "unknown"]
        sp = [i for i in unknown if splus[i]]
        if sp:
            classes[sp[0]] = "drawn"
        elif unknown:
            best = max(unknown, key=lambda i: median(column_values[i]) if column_values[i] else -1)
            if column_values[best] and (median(column_values[best]) >= 40 or len(unknown) > 1):
                classes[best] = "drawn"
    if "drawn" in classes:
        d = classes.index("drawn")
        for i, c in enumerate(classes):
            if c != "unknown" or not column_values[i] or len(column_values[i]) != len(column_values[d]):
                continue
            diffs = {round(a - b, 3) for a, b in zip(column_values[d], column_values[i])}
            if diffs == {100.0} or (max(column_values[i]) <= max(column_values[d]) and "base" not in classes
                                    and all(x >= 0 for x in diffs) and median(column_values[i]) > 60):
                classes[i] = "base"
            elif fee_guess[i] and "commitment_fee" not in classes and "facility_fee" not in classes and median(column_values[i]) <= 60:
                classes[i] = "commitment_fee"
    return classes


def _monotonic(vals: list[float]) -> bool:
    return all(a <= b for a, b in zip(vals, vals[1:])) or all(a >= b for a, b in zip(vals, vals[1:]))


def _explicit_level(label: str) -> tuple[str, str] | None:
    """(level, rest of the label) when the label opens with a level: "Level II  > 3.50x", "3)", "Tier IV:"."""
    m = _LEVEL_RE.match(label)
    # "1.50x" style criteria must not lose their leading digit to the level
    if m and not re.match(r"^[.,]\d", label[m.end("lvl"):]):
        return m.group("lvl").upper(), label[m.end():].strip()
    return None


def _split_level(label: str, index: int) -> tuple[str, str]:
    label = _LABEL_PREFIX_RE.sub("", label).strip()
    return _explicit_level(label) or (str(index + 1), label)


def _row_quote(ln: Line) -> str:
    return clip(ln.text[ln.qstart:], 300)


def _normal(doc, bands, labels, cols, left_edge, header_lines, context, heading, bare_head, after, notes) -> Grid | None:
    in_front = {len(fragments(b.first.text[: min(t.start for t in b.cells.values())], 2)) for b in bands}
    col_headers, metric, spanning = _column_headers(header_lines, cols, left_edge, in_front.pop() if len(in_front) == 1 else None)
    classes = [_classify(h) if h else "unknown" for h in col_headers]
    if "drawn" not in classes and "all_in" not in classes:
        notes = None  # no margin column named in the header: any table of percentages, nothing to report if it is not read
    # Rows that open a page under no header of their own are read with the columns of the grid they carry on.
    carried = after is not None and not any(c in _KEYED for c in classes)
    least = 1 if carried else 2
    if len(bands) < least or (carried and len(cols) != len(after.columns)):
        return None
    span = range(len(cols))
    scales = [1.0] * len(cols)
    if bare_head is not None:  # bare numbers take their unit from the column's own header, else from the header as a whole
        whole = [any(b.cells[i].whole for b in bands if i in b.cells) for i in span]
        scales = [_unit_scale(h) or _unit_scale(bare_head) for h in col_headers]
        if any(s is None or (w and s != 1.0) for s, w in zip(scales, whole)):
            return None  # no unit, two units, or whole numbers that are not basis points: not read as rates
    column_values = [[b.cells[i].bps * scales[i] for b in bands if i in b.cells] for i in span]
    splus = [any(b.cells[i].splus for b in bands if i in b.cells) for i in span]
    if carried:
        classes, metric, context, heading = list(after.columns), after.metric, after.context, after.heading
    else:
        based = [any(b.cells[i].base for b in bands if i in b.cells) for i in span]
        classes = ["base" if c == "unknown" and based[i] else c for i, c in enumerate(classes)]
        # a column headed "Facility ..." is not put down as a commitment fee on the strength of its values
        fee_guess = [not re.search(r"facility", h + " " + s, re.IGNORECASE) for h, s in zip(col_headers, spanning)]
        # nor is a column of bare whole numbers guessed at, or read as a rate where its header names none ("Commitment ($mm)")
        held = [i for i in span if bare_head is not None and whole[i]
                and (classes[i] == "unknown" or not _RATE_NAME_RE.search(col_headers[i]) or _AMOUNT_RE.search(col_headers[i]))]
        for i in held:
            classes[i] = "other"
        classes = _resolve_classes(classes, column_values, splus, fee_guess)
        for i in held:
            classes[i] = "unknown"
        for i, c in enumerate(classes):  # "S + CSA + 62.5 bps" under an all-in header stays all-in; elsewhere it is the margin
            if c == "unknown" and splus[i] and "drawn" not in classes:
                classes[i] = "drawn"
    if not any(c in _KEYED for c in classes):
        return None
    blob = " ".join(col_headers + spanning + labels) + " " + metric + " " + context
    if not carried and not any(splus) and not _PRICING_WORD_RE.search(blob):
        return None
    main = next(i for i, c in enumerate(classes) if c in _KEYED)
    # A labelled one-off line caught next to the table ("Commitment fee   0.50%") is a fee row, not a tier.
    kept = [(b, lab) for b, lab in zip(bands, labels) if main in b.cells]
    if len(kept) < max(least, len(bands) - 1):
        return None
    page = kept[0][0].first.page
    main_vals = [b.cells[main].bps * scales[main] for b, _ in kept]
    if any(t.bps * scales[i] < 0 or t.bps * scales[i] > 2000 for b, _ in kept for i, t in b.cells.items()):
        return None
    if len(main_vals) >= 3 and not _monotonic(main_vals):
        return _unread(notes, page, len(kept), "its rates do not run in order from row to row; two tables may be printed as one")
    # "Applicable Margin for Term SOFR Loans / Letter of Credit Fee": one column sets both rates.
    drawn_col = classes.index("drawn") if "drawn" in classes else None
    margin_is_lc_fee = drawn_col is not None and "lc" not in classes and bool(
        re.search(r"letters?\s+of\s+credit|\bl/?c\b", col_headers[drawn_col], re.IGNORECASE))
    tiers = []
    for bi, (b, lab) in enumerate(kept, len(after.tiers) if carried else 0):
        level, criteria = _split_level(lab, bi)
        values = {classes[i]: round(t.bps * scales[i], 4) for i, t in sorted(b.cells.items())
                  if classes[i] not in ("other", "unknown", "upfront")}
        if margin_is_lc_fee and "drawn" in values:
            values["lc"] = values["drawn"]
        tiers.append(Tier(level=level, criteria=criteria, values=values, quote=_row_quote(b.first), line=b.first.n))
    if _misread(tiers):
        return _unread(notes, page, len(kept), _misread(tiers))
    used = [any(i in b.cells for b, _ in kept) for i in span]
    grid_notes = []
    if any(c == "unknown" and u for c, u in zip(classes, used)):
        grid_notes.append("One or more value columns could not be identified from the table header.")
    if not carried and any(u and s and not h for u, s, h in zip(used, spanning, col_headers)):
        grid_notes.append("A header cell spans several value columns, so those columns were told apart by their values.")
    classes = [c for c, u in zip(classes, used) if u]
    fee_type = "facility_fee" if "facility_fee" in classes else "commitment_fee" if "commitment_fee" in classes else "not_stated"
    metric = tidy(re.sub(r"\b(pricing|level|category|tier)\b", " ", metric, flags=re.IGNORECASE)) or metric
    row_lines = [ln.n for b, _ in kept for ln in b.lines + b.extra]
    grid = Grid(page=page, first_line=min(row_lines), last_line=max(row_lines), tiers=tiers, metric=metric,
                columns=classes, undrawn_fee_type=fee_type, context=context, notes=grid_notes, heading=heading,
                col_x=[x for x, u in zip(cols, used) if u])
    if carried:
        return after if _continue(after, grid) else None
    return grid


def _misread(tiers: list[Tier]) -> str:
    """Why the rates cannot be what their columns were taken for, or "" when they can."""
    margins = [[t.values[key] for t in tiers if key in t.values] for key in ("drawn", "all_in")]
    if any(vals and max(vals) < MIN_MARGIN_BPS for vals in margins):
        return "its margin column stays under 10 bps, so the unit or the column was misread"
    fees = [v for t in tiers for key, v in t.values.items() if key in ("commitment_fee", "facility_fee")]
    if not any(margins) and fees and max(fees) > MAX_LONE_FEE_BPS:
        return "its only rate column was read as an undrawn fee but runs above 100 bps"
    return ""


def _transposed(doc, bands, labels, cols, header_lines, context, heading, unit_scale) -> Grid | None:
    row_classes = []
    for lab in labels:
        c = _classify(_LABEL_PREFIX_RE.sub("", lab))
        if re.match(r"^\W*drawn", lab, re.IGNORECASE):
            c = "drawn"
        if re.match(r"^\W*(undrawn|unused)", lab, re.IGNORECASE):
            c = "commitment_fee"
        if c == "unknown" and re.search(r"\w\s+fees?\W*$", lab, re.IGNORECASE):
            c = "other"  # a fee with a name of its own ("Consent Fee") is no part of the grid; a bare "Fee" is a name cut short
        row_classes.append(c)
    seen: set[str] = set()
    for i, c in enumerate(row_classes):
        if c in seen:
            row_classes[i] = "other"
        seen.add(c)
    if not any(c in _KEYED for c in row_classes):
        return None
    if len(cols) == 1 and "drawn" not in row_classes and "all_in" not in row_classes:
        return None  # labelled fees with no margin among them ("Commitment Fee: 0.25%", "Upfront Fee: 0.10%") are fee lines, not a grid
    level_names: list[str] = []
    level_line = None
    for ln in header_lines:
        found = _LEVEL_NAMES_RE.findall(ln.text)
        if len(found) == len(cols) >= 2:
            level_names, level_line = [f.upper() for f in found], ln
            break
    criteria_parts: list[list[str]] = [[] for _ in cols]
    spacing = min((b - a for a, b in zip(cols, cols[1:])), default=40.0)
    first_col_left = cols[0] - spacing / 2
    for ln in header_lines:
        if ln is level_line:
            continue
        for start, end, text in fragments(ln.text, 2):
            centre = (start + end) / 2
            if centre < first_col_left - 4:
                continue  # row-label column ("BASIS FOR PRICING")
            criteria_parts[_nearest(cols, centre)].append(text)
    tiers = []
    for ci in range(len(cols)):
        values = {}
        for bi, b in enumerate(bands):
            if ci in b.cells and row_classes[bi] not in ("other", "unknown", "upfront"):
                values[row_classes[bi]] = round(b.cells[ci].bps * unit_scale, 4)
        if not values:
            continue
        level = level_names[ci] if len(level_names) == len(cols) else ("Flat" if len(cols) == 1 else str(ci + 1))
        src = next((b for bi, b in enumerate(bands) if row_classes[bi] == "drawn" and ci in b.cells), bands[0])
        tiers.append(Tier(level=level, criteria=tidy(" ".join(criteria_parts[ci])) if len(cols) > 1 else "All periods",
                          values=values, quote=_row_quote(src.first), line=src.first.n))
    if not tiers:
        return None
    for key in ("drawn", "commitment_fee", "facility_fee"):
        vals = [t.values[key] for t in tiers if key in t.values]
        if len(vals) >= 3 and not _monotonic(vals):
            return None
    if any(v < 0 or v > 2000 for t in tiers for v in t.values.values()) or _misread(tiers):
        return None
    fee_type = "facility_fee" if "facility_fee" in row_classes else "commitment_fee" if "commitment_fee" in row_classes else "not_stated"
    # Only the rows that were read as rates belong to the grid; a neighbouring "Consent Fee: 10 bps" line does not.
    row_lines = [ln.n for b, c in zip(bands, row_classes) if c not in ("other", "unknown", "upfront") for ln in b.head + b.lines]
    notes = ["One or more rows of the table could not be identified from their labels."] if "unknown" in row_classes else []
    return Grid(page=bands[0].first.page, first_line=min(row_lines), last_line=max(row_lines), tiers=tiers,
                metric="Flat" if len(cols) == 1 else "Level", columns=row_classes, undrawn_fee_type=fee_type,
                context=context, transposed=True, notes=notes, heading=heading)
