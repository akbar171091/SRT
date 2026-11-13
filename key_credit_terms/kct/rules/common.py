"""Shared tools for the rule modules: the document context, evidence quotes, and value formatting.

A rule is a function ``rule(ctx) -> entry`` that returns one field of the record:

    def purpose(ctx: Ctx) -> dict:
        block = ctx.first(r"purpose|use\\s+of\\s+proceeds")
        if block is None:
            return not_stated()
        return stated(["General corporate purposes"], ctx.quote(block, r"general\\s+corporate\\s+purposes"))

Rules never invent: every line must come from text found in the document, and every stated or
by_reference entry carries at least one quote produced by ``ctx.quote`` (which returns only text
that is verifiably on the page).
"""
from __future__ import annotations

import re
from typing import Iterable

from ..config import NOT_STATED
from ..schema import MAX_LINE_CHARS, MAX_LINES, MAX_QUOTE_CHARS
from ..textmodel import Doc, clip, tidy
from . import views
from .blocks import Block, find_blocks

LINE_LIMIT = 250  # house style: keep lines to about this length

_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty-five": 45, "sixty": 60, "ninety": 90}

# "$1,250,000,000", "$1.25 billion", "$275mm", "$10.0 bn", "U.S.$500 million", "C$100 million", "CHF 500 million".
# Layout gaps inside one amount are tolerated ("$1,325   ,000,000", "$165   million", the unit word alone on the next line).
# The whole number is always taken ("$500,000,000individually" is $500,000,000, never "$500,000"), no space after the amount
# is consumed, and a unit letter is only a unit when nothing is glued to it ("$500 M&A" is $500).
_CODES = "USD|EUR|GBP|CAD|AUD|NZD|CHF|JPY|SEK|NOK|DKK|HKD|SGD"
_GAP = r"[ \t]*"
_WRAP = r"(?:\n[ \t]*(?=billion|million|thousand))?"
MONEY_RE = re.compile(
    r"(?P<cur>(?-i:(?<![A-Za-z])(?:CA|AU|NZ|HK|SG|C|A|S)\$)|US\s?\$|U\.S\.\s?\$|\$|€|£|(?<![A-Za-z])(?:" + _CODES + r")\s?)\s?"
    r"(?P<num>\d{1,3}(?:" + _GAP + "," + _GAP + r"\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d|" + _GAP + "," + _GAP + r"\d{3})"
    r"(?:" + _GAP + _WRAP + r"(?P<unit>billion|bn|million|mm|mn|m|thousand|k)(?![A-Za-z0-9&/]))?", re.IGNORECASE)
RATIO_RE = re.compile(r"(?<![\w.])(\d{1,2}(?:\.\d{1,2})?)\s*(?:x\b|:\s?1(?:\.0{1,2})?\b|to\s+1(?:\.0{1,2})?\b)", re.IGNORECASE)
PCT_RE = re.compile(r"(?<![\w.$])(\d{1,3}(?:\.\d+)?)\s*%")
DAYS_RE = re.compile(r"(?<![\w.])(?:(\d{1,3})|(" + "|".join(_WORD_NUM) + r"))\s*(?:\(\s*\d{1,3}\s*\)\s*)?(business\s+days?|days?|months?|years?)", re.IGNORECASE)
SAME_AS_EXISTING_RE = views.SAME_AS_EXISTING_RE
# The term sheet points elsewhere instead of stating the term.
BY_REFERENCE_RE = re.compile(
    r"(substantially\s+)?(similar|consistent|the\s+same|identical)\s+(to|with|as)\s+(those\s+(set\s+forth\s+)?in\s+|under\s+)?the\s+(Existing|Prior|Current)\s+"
    r"[\w\- ]{0,40}?(Agreement|Facility|Facilities)|same\s+as\s+(under\s+)?the\s+Existing|as\s+(set\s+forth|provided)\s+in\s+the\s+Existing|"
    r"usual\s+and\s+customary|customary\s+for\s+(facilities|transactions|financings)|to\s+be\s+(agreed|determined)|documentation\s+principles",
    re.IGNORECASE)
_SENT_END_RE = re.compile(r"(?<=[a-z0-9\)\]”\"%])[.;]\s+(?=[A-Z(“\"•])")


# ---- entries ---------------------------------------------------------------------------------------

def _lines(lines: Iterable[str] | str) -> list[str]:
    if isinstance(lines, str):
        lines = [lines]
    out = []
    for line in lines:
        line = tidy(line or "")
        if line:
            out.append(line if len(line) <= MAX_LINE_CHARS else clip(line, MAX_LINE_CHARS - 2) + " …")
    return out[:MAX_LINES]


def _evidence(evidence) -> list[dict]:
    if evidence is None:
        return []
    if isinstance(evidence, dict):
        evidence = [evidence]
    seen, out = set(), []
    for e in evidence:
        if e and e.get("quote") and e["quote"] not in seen:
            seen.add(e["quote"])
            out.append({"quote": e["quote"], "page": e["page"]})
    return out[:3]


def stated(lines, evidence, note: str = "") -> dict:
    """A field the term sheet addresses. Falls back to not_stated if there is no line or no verifiable quote."""
    lines, evidence = _lines(lines), _evidence(evidence)
    if not lines or not evidence:
        return not_stated(note=note)
    return {"lines": lines, "status": "stated", "evidence": evidence, "note": note}


def by_reference(lines, evidence, note: str = "") -> dict:
    """A field the term sheet deals with only by pointing to another document."""
    entry = stated(lines, evidence, note)
    if entry["status"] == "stated":
        entry["status"] = "by_reference"
    return entry


def not_stated(text: str = NOT_STATED, note: str = "") -> dict:
    return {"lines": [text], "status": "not_stated", "evidence": [], "note": note}


# ---- formatting --------------------------------------------------------------------------------------

def money_mm(m: re.Match) -> float | None:
    """Value of a MONEY_RE match in millions."""
    try:
        num = float(re.sub(r"[\s,]", "", m.group("num")))
    except ValueError:
        return None
    unit = (m.group("unit") or "").lower()
    if unit in ("billion", "bn"):
        return num * 1000
    if unit in ("million", "mm", "mn", "m"):
        return num
    if unit in ("thousand", "k"):
        return num / 1000
    return num / 1e6


def _currency(cur: str) -> str:
    cur = cur.upper().replace(" ", "").replace(".", "")
    if cur in ("$", "US$", "USD"):
        return "$"
    if cur.endswith("$"):
        return {"CA$": "C$", "AU$": "A$", "SG$": "S$"}.get(cur, cur)
    return {"€": "EUR ", "£": "GBP "}.get(cur, cur + " ")


def _trim_number(value: float, places: int) -> str:
    """``value`` to ``places`` decimals if that is exact, otherwise as many as it takes: a figure is never rounded to another one."""
    text = ""
    for p in (places, 6, 9):
        text = f"{value:,.{p}f}"
        if abs(float(text.replace(",", "")) - value) < 1e-9 * max(1.0, abs(value)):
            break
    return text.rstrip("0").rstrip(".") if "." in text else text


def fmt_money(mm: float, cur: str = "$") -> str:
    """House style: $750m, $1.25bn, $150k; an amount that is not a whole number of thousands is written out ($3,500)."""
    if mm >= 1000:
        text = _trim_number(mm / 1000, 3)
        return f"{cur}{text if '.' in text else text + '.0'}bn"
    if mm >= 1:
        return f"{cur}{_trim_number(mm, 2)}m"
    thousands = mm * 1000
    if thousands >= 1 and abs(thousands - round(thousands)) < 1e-6:
        return f"{cur}{thousands:,.0f}k"
    return f"{cur}{_trim_number(mm * 1e6, 2)}"


def amounts(text: str) -> list[tuple[float, str, re.Match]]:
    """Money amounts in ``text``: (value in millions, formatted, match)."""
    out = []
    for m in MONEY_RE.finditer(text):
        mm = money_mm(m)
        if mm is not None and mm > 0:
            out.append((mm, fmt_money(mm, _currency(m.group("cur"))), m))
    return out


def restyle_money(text: str) -> str:
    """Rewrite every amount in ``text`` in house style ("$1,250,000,000" -> "$1.25bn")."""
    def sub(m: re.Match) -> str:
        mm = money_mm(m)
        return fmt_money(mm, _currency(m.group("cur"))) if mm else m.group(0)
    return MONEY_RE.sub(sub, text)


def fmt_ratio(value: float) -> str:
    return f"{value:.2f}x"


def number(text: str) -> int | None:
    """"five" / "5" / "five (5)" -> 5."""
    m = re.search(r"\d+", text)
    if m:
        return int(m.group(0))
    return _WORD_NUM.get(text.strip().lower())


def sentences(text: str) -> list[str]:
    """Split running text into sentences / clauses at full stops and semicolons (decimals and "U.S." are kept whole)."""
    return [s.strip() for s in _SENT_END_RE.split(text) if s.strip()]


def squeeze(text: str, limit: int = LINE_LIMIT) -> str:
    """Tidy a passage for use as a line: house-style amounts, defined-term quotes dropped, cut at a word boundary."""
    text = restyle_money(tidy(text))
    text = re.sub(r"\s+\((?:the\s+|each,?\s+an?\s+|collectively,?\s+the\s+)?[“\"][^”\"]{1,60}[”\"]\)", "", text)  # (the "Facility")
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    if len(text) <= limit:
        return text
    return clip(text, limit - 2) + " …"


def points_elsewhere(text: str) -> re.Match | None:
    """The passage defers to another document or to later agreement rather than stating the term."""
    return BY_REFERENCE_RE.search(text)


# ---- the document context ----------------------------------------------------------------------------

class Ctx:
    """One term sheet, as the rules see it.

    ``doc`` is the text the rules read. On amendment slides that print existing and proposed terms side
    by side it is the proposed column (see views.py); ``existing`` is the other column and ``raw`` the
    page text as extracted, which is what quotes are checked against.
    """

    def __init__(self, pages: list[str], client: str = "", source_file: str = ""):
        self.client, self.source_file = client, source_file
        self.raw = Doc(pages)
        self.doc, self.existing, self.split_pages = views.split_views(self.raw)
        self.text = self.raw.text
        self._cache: dict[tuple[str, int], list[Block]] = {}

    # -- sections --

    def blocks(self, label_pattern: str, max_lines: int = 260) -> list[Block]:
        """Every section whose label matches the regex fragment (case-insensitive), in document order.

        Keep patterns tight: the label is matched from the start of the line up to a colon, a dash or a
        gap, so a greedy ``.*`` swallows value text into the label.
        """
        key = (label_pattern, max_lines)
        if key not in self._cache:
            self._cache[key] = find_blocks(self.doc, label_pattern, max_lines)
        return self._cache[key]

    def first(self, *label_patterns: str, top_level: bool = False) -> Block | None:
        """The first section matching the first pattern that matches anything. ``top_level`` skips inline sub-labels."""
        for pattern in label_patterns:
            for b in self.blocks(pattern):
                if b.text and not (top_level and b.inline):
                    return b
        return None

    def all(self, *label_patterns: str) -> list[Block]:
        """Sections matching any of the patterns, without duplicates, in document order."""
        seen: dict[int, Block] = {}
        for pattern in label_patterns:
            for b in self.blocks(pattern):
                if b.text:
                    seen.setdefault(b.line.n, b)
        return [seen[k] for k in sorted(seen)]

    def value(self, block: Block) -> str:
        """Block text, with an amendment slide's "Same as existing" replaced by the existing column's text."""
        if block.page in self.split_pages and SAME_AS_EXISTING_RE.match(block.text):
            twin = [b for b in find_blocks(self.existing, re.escape(block.label)) if b.line.n == block.line.n]
            if twin and twin[0].text:
                return twin[0].text
        return block.text

    def is_same_as_existing(self, block: Block) -> bool:
        return block.page in self.split_pages and bool(SAME_AS_EXISTING_RE.match(block.text))

    # -- evidence --

    def quote(self, block: Block, needle: str | re.Match | None = None, limit: int = MAX_QUOTE_CHARS) -> dict | None:
        """An evidence item {"quote", "page"} taken from ``block``, or None if nothing verifiable can be cut.

        ``needle`` says which part of the block to quote: a regex (searched in ``block.text``), a match
        object from a search on ``block.text``, or None for the start of the block. The quote is the
        clause around the needle, kept to one page and ``limit`` characters, and is returned only if it
        is found on that page of the PDF text.
        """
        text = block.text
        if not text:
            return None
        if needle is None:
            start, end = 0, min(len(text), 80)
        else:
            m = re.search(needle, text, re.IGNORECASE) if isinstance(needle, str) else needle
            if m is None:
                return None
            start, end = m.start(), m.end()
        # widen to the clause around the needle
        left = max(text.rfind(". ", 0, start), text.rfind("; ", 0, start), text.rfind(": ", 0, start))
        left = 0 if left < 0 else left + 2
        stops = [p for p in (text.find(". ", end), text.find("; ", end)) if p >= 0]
        right = min(stops) + 1 if stops else len(text)
        if right - left > limit:  # too long: keep the needle, trim around it
            left = max(left, start - (limit - (end - start)) // 3)
            right = min(right, left + limit)
            if left > 0 and text[left - 1] != " ":
                left = text.find(" ", left) + 1
            if right < len(text) and text[right] != " ":
                right = text.rfind(" ", left, right)
        first, last = block.line_at(left), block.line_at(max(left, right - 1))
        page = block.lines[block.line_at(start)].page
        # keep to the page that holds the needle
        while block.lines[first].page != page and first < last:
            first += 1
            left = max(left, block._starts[first])
        while block.lines[last].page != page and last > first:
            right = min(right, block._starts[last] - 1)
            last -= 1
        for lo, hi in ((left, right), (max(left, start - 40), min(right, end + 120)), (start, end)):
            lo = text.rfind(" ", 0, lo) + 1 if lo > 0 and text[lo - 1] != " " else lo
            candidate = text[lo:hi].strip(" ,;:")
            if len(candidate) > limit:
                candidate = clip(candidate, limit)
            if len(candidate) >= 8 and (self.raw.has_quote(candidate, page) or self.raw.has_quote_loose(candidate, page)):
                return {"quote": candidate, "page": page}
        # last resort: the single source line that holds the needle
        part = tidy(block.parts[block.line_at(start)])
        if len(part) >= 8 and self.raw.has_quote(part, page):
            return {"quote": clip(part, limit), "page": page}
        return None

    def quote_text(self, pattern: str, pages: Iterable[int] | None = None, limit: int = MAX_QUOTE_CHARS) -> dict | None:
        """An evidence item for the first match of ``pattern`` anywhere in the document (or on ``pages``):
        the source line holding the match, extended with the following lines while it stays under ``limit``."""
        rx = re.compile(pattern, re.IGNORECASE)
        for ln in self.doc.lines:
            if ln.blank or (pages is not None and ln.page not in pages):
                continue
            if rx.search(ln.text):
                quote = tidy(ln.text[ln.qstart:] if ln.qstart else ln.text)
                if len(quote) > limit:
                    m = rx.search(quote)
                    quote = clip(quote[max(0, m.start() - 60):], limit)
                if len(quote) >= 8 and self.raw.has_quote(quote, ln.page):
                    return {"quote": quote, "page": ln.page}
        return None

    def search(self, pattern: str, flags: int = re.IGNORECASE) -> re.Match | None:
        """First match of ``pattern`` in the whole document text (lines joined by newlines; use \\s+ between words)."""
        return re.search(pattern, self.text, flags)
