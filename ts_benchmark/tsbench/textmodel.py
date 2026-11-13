"""Line-level view of an extracted document, plus the text normalisation used to check quotes."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_TRANS = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u00a0": " ", "\u2022": "", "\u00b7": "", "\uf0b7": "",
})


def squash(text: str) -> str:
    """Normalise for verbatim matching: unify quote/dash styles, drop bullets and all whitespace, lowercase."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).translate(_TRANS)).lower()


def tidy(text: str) -> str:
    """Collapse runs of whitespace; used for display strings and quotes."""
    return re.sub(r"\s+", " ", text).strip()


def clip(text: str, limit: int = 300) -> str:
    text = tidy(text)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0]


@dataclass
class Line:
    page: int  # 1-based PDF page
    n: int  # index into Doc.lines
    text: str
    qstart: int = 0  # column from which the text is contiguous in the source (see views.py)

    @property
    def indent(self) -> int:
        return len(self.text) - len(self.text.lstrip())

    @property
    def blank(self) -> bool:
        return not self.text.strip()


_FOOTER_RE = re.compile(
    r"^(?:[-\u2013]?\s*\d{1,3}\s*[-\u2013]?|\[\[.*\]\]|page\s+\d+(\s+of\s+\d+)?|confidential|restricted\s*-\s*internal"
    r"|(?:addendum|annex|exhibit|schedule)\s+[\w-]{1,6}(\s*-\s*\d+)?)$",
    re.IGNORECASE,
)


def is_page_furniture(text: str) -> bool:
    """A page number, document id or running footer, judged on the words alone."""
    core = text.strip()  # matched without its indentation: the pattern must not backtrack over a long run of spaces
    return len(core) <= 60 and bool(_FOOTER_RE.match(core))


def is_footer(text: str) -> bool:
    """Page furniture, or a stray few characters far to the right: never part of a term and never a label."""
    return is_page_furniture(text) or (len(text) - len(text.lstrip()) > 60 and len(text.strip()) <= 4)


class Doc:
    """Pages split into lines, with helpers to find where a quote sits."""

    def __init__(self, pages: list[str]):
        self.pages = pages
        self.lines: list[Line] = []
        for p, text in enumerate(pages, 1):
            for raw in text.expandtabs(4).split("\n"):
                self.lines.append(Line(page=p, n=len(self.lines), text=raw.rstrip()))
        self._squashed = [squash(t) for t in pages]
        self._columns: dict[int, bool] = {}

    def has_columns(self, page: int) -> bool:
        """True when the page was extracted with layout (an indented value column), false for plain reading order."""
        if page not in self._columns:
            body = [ln for ln in self.page_lines(page) if not ln.blank]
            self._columns[page] = bool(body) and sum(1 for ln in body if ln.indent >= 8) / len(body) > 0.25
        return self._columns[page]

    def has_quote(self, quote: str, page: int | None) -> bool:
        q = squash(quote)
        if not q or page is None or not 1 <= page <= len(self.pages):
            return False
        return q in self._squashed[page - 1]

    def find_quote(self, quote: str) -> list[int]:
        """Pages (1-based) on which the quote appears verbatim."""
        q = squash(quote)
        return [i + 1 for i, t in enumerate(self._squashed) if q and q in t]

    def page_lines(self, page: int) -> list[Line]:
        return [ln for ln in self.lines if ln.page == page]


def fragments(text: str, gap: int = 2) -> list[tuple[int, int, str]]:
    """Split a layout line into cells separated by at least ``gap`` spaces: (start, end, text)."""
    return [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\S+(?: {1,%d}\S+)*" % (gap - 1), text)] if gap > 1 else \
        [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\S+", text)]
