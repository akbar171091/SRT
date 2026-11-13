"""Line-level view of an extracted document, plus the text normalisation used to check quotes."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_TRANS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", "•": "", "·": "", "": "", "▪": "", "●": "", "‣": "",
})


def normalise(text: str) -> str:
    """Unify quote and dash styles and drop bullet glyphs; keeps whitespace and case."""
    return unicodedata.normalize("NFKC", text).translate(_TRANS)


def squash(text: str) -> str:
    """Normalise for verbatim matching: unify quote/dash styles, drop bullets and all whitespace, lowercase."""
    return re.sub(r"\s+", "", normalise(text)).lower()


def words(text: str) -> list[str]:
    """Lower-cased word tokens (letters, digits, and the symbols that carry meaning in a term sheet)."""
    return re.findall(r"[a-z0-9$%£€.,]*[a-z0-9$%£€]", normalise(text).lower())


def tidy(text: str) -> str:
    """Collapse runs of whitespace; used for display strings and quotes."""
    return re.sub(r"\s+", " ", text).strip()


def clip(text: str, limit: int = 300) -> str:
    """Tidy and cut at a word boundary so the result is at most ``limit`` characters."""
    text = tidy(text)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0]


@dataclass
class Line:
    page: int  # 1-based PDF page
    n: int  # index into Doc.lines
    text: str
    qstart: int = 0  # column from which the text is contiguous in the source (see rules/views.py)

    @property
    def indent(self) -> int:
        return len(self.text) - len(self.text.lstrip())

    @property
    def blank(self) -> bool:
        return not self.text.strip()


_FOOTER_RE = re.compile(
    r"^\s*(?:[-–]?\s*\d{1,3}\s*[-–]?|\[\[.*\]\]|page\s+\d+(\s+of\s+\d+)?|confidential|restricted\s*-\s*internal"
    r"|(?:addendum|annex|exhibit|schedule)\s+[\w-]{1,6}(\s*-\s*\d+)?|#?\d{6,}(v\d+)?|[A-Z]{2,}[-_ ]?#?\d{6,}.*)\s*$",
    re.IGNORECASE,
)


def is_footer(text: str) -> bool:
    """Page numbers, document ids and running footers: never part of a term and never a label."""
    return bool(_FOOTER_RE.match(text)) or (len(text) - len(text.lstrip()) > 60 and len(text.strip()) <= 4)


def fragments(text: str, gap: int = 2) -> list[tuple[int, int, str]]:
    """Split a layout line into cells separated by at least ``gap`` spaces: (start, end, text)."""
    pattern = r"\S+(?: {1,%d}\S+)*" % (gap - 1) if gap > 1 else r"\S+"
    return [(m.start(), m.end(), m.group(0)) for m in re.finditer(pattern, text)]


class Doc:
    """Pages split into lines, with helpers to find where a quote sits."""

    def __init__(self, pages: list[str]):
        self.pages = pages
        self.lines: list[Line] = []
        for p, text in enumerate(pages, 1):
            for raw in text.expandtabs(4).split("\n"):
                self.lines.append(Line(page=p, n=len(self.lines), text=raw.rstrip()))
        self._squashed = [squash(t) for t in pages]
        self._words: list[list[str]] | None = None
        self._columns: dict[int, bool] = {}

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    def has_columns(self, page: int) -> bool:
        """True when the page was extracted with layout (an indented value column), false for plain reading order."""
        if page not in self._columns:
            body = [ln for ln in self.page_lines(page) if not ln.blank]
            self._columns[page] = bool(body) and sum(1 for ln in body if ln.indent >= 8) / len(body) > 0.25
        return self._columns[page]

    def page_lines(self, page: int) -> list[Line]:
        return [ln for ln in self.lines if ln.page == page]

    # ---- quote lookup -------------------------------------------------------------------------

    def has_quote(self, quote: str, page: int | None) -> bool:
        """The quote appears verbatim (ignoring whitespace, case and quote/dash style) on ``page``."""
        q = squash(quote)
        if not q or page is None or not 1 <= page <= len(self.pages):
            return False
        return q in self._squashed[page - 1]

    def find_quote(self, quote: str) -> list[int]:
        """Pages (1-based) on which the quote appears verbatim."""
        q = squash(quote)
        return [i + 1 for i, t in enumerate(self._squashed) if q and q in t]

    def has_quote_loose(self, quote: str, page: int | None, max_gap: int = 8, max_foreign: float = 0.35) -> bool:
        """The words of the quote appear on ``page`` in order, with only short interruptions.

        Layout extraction keeps a left-hand label column on the same text line as the value column,
        so a sentence that wraps past a two-line label ("Assignments and / Participations:") is
        interrupted by a label fragment. This accepts such a quote: each next word must be found
        within ``max_gap`` words of the previous one, and the skipped words in total may not exceed
        ``max_foreign`` of the quote length.
        """
        if page is None or not 1 <= page <= len(self.pages):
            return False
        if self._words is None:
            self._words = [words(t) for t in self.pages]
        hay, needle = self._words[page - 1], words(quote)
        if len(needle) < 4:
            return False
        budget = max(2, int(len(needle) * max_foreign))
        for start in (i for i, w in enumerate(hay) if w == needle[0]):
            pos, skipped, ok = start, 0, True
            for w in needle[1:]:
                window = hay[pos + 1: pos + 2 + max_gap]
                if w not in window:
                    ok = False
                    break
                step = window.index(w)
                skipped += step
                pos += step + 1
                if skipped > budget:
                    ok = False
                    break
            if ok:
                return True
        return False

    def locate(self, quote: str, page: int | None) -> tuple[str, list[int]]:
        """How a quote is supported by the text: (grade, pages).

        exact       verbatim on the stated page
        loose       on the stated page, interrupted only by layout fragments (see has_quote_loose)
        other_page  verbatim (or loosely) on a different page; ``pages`` lists where
        missing     not found
        """
        if self.has_quote(quote, page):
            return "exact", [page]
        if self.has_quote_loose(quote, page):
            return "loose", [page]
        elsewhere = self.find_quote(quote) or [p for p in range(1, len(self.pages) + 1) if p != page and self.has_quote_loose(quote, p)]
        return ("other_page", elsewhere) if elsewhere else ("missing", [])
