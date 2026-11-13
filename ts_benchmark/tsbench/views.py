"""Existing-versus-proposed layouts.

Amendment summaries in lender presentations print three columns: a label, the existing term and
the proposed term. Read as plain lines, the two term columns run into each other. This module
finds the "Existing ... Proposed" header on such a page and builds two views of the document:

* ``proposed``: label column + proposed column (existing column blanked out)
* ``existing``: label column + existing column

Everything downstream reads the proposed view and falls back to the existing view where the
proposed cell says "Same as existing".

Only the rows under the header that keep to the two columns are split. A header that names two
groups of lenders ("Existing Lenders", "New Lenders") is a fee table, not a comparison of terms,
and the page is left as it is.
"""
from __future__ import annotations

import re
from collections import Counter

from .textmodel import Doc, Line, fragments

WOBBLE = 12  # columns by which a cell may start off its column where the page was set in a proportional font
AHEAD = 4  # lines looked at, below lines written across both columns, for the next row of the comparison
_OF_TERMS = r"(?:\s+(?:terms?|(?:credit\s+)?(?:facility|facilities|agreement)))?$"
_EXISTING_RE = re.compile(r"^(?:existing|current)" + _OF_TERMS, re.IGNORECASE)
_PROPOSED_RE = re.compile(r"^(?:proposed|amended|new)" + _OF_TERMS, re.IGNORECASE)
SAME_AS_EXISTING_RE = re.compile(r"^\W*(same(\s+as\s+(existing|current))?|no\s+change|unchanged)\W*$", re.IGNORECASE)
_LABEL_RE = re.compile(r"[A-Za-z][A-Za-z /&()'-]*:?")  # plain words, as a label is: no figure, bullet or sentence


def _header(line: Line) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """(span of the 'Existing' header cell, span of the 'Proposed' header cell) if this line is that header.

    The line holds those two cells and nothing else, except a heading for the label column in front
    ("Key terms"). A "Label:" in front makes it a row of a term sheet with a small table of its own.
    """
    cells = fragments(line.text, 3)
    if not 2 <= len(cells) <= 3 or (len(cells) == 3 and cells[0][2].rstrip().endswith(":")):
        return None
    ex, pr = cells[-2], cells[-1]
    if _EXISTING_RE.match(ex[2]) and _PROPOSED_RE.match(pr[2]):
        return (ex[0], ex[1]), (pr[0], pr[1])
    return None


def _starts(ln: Line) -> list[int]:
    return [s for s, _, _ in fragments(ln.text, 3)]


def _rows(lines: list[Line], cut: int, existing_head: tuple[int, int]) -> list[tuple[Line, int]]:
    """The lines under the header that keep to the two columns, each with the column its proposed cell starts after.

    That column is ``cut``, the gutter, unless the line's proposed cell starts a little off it. A line written
    across the gutter (a note over the whole width, or cells that run into each other) is left out. Two in a row
    end the comparison, as what follows is the ordinary text of the page, unless one of the next few lines has
    a cell starting right at the proposed column: then the rows go on below the note.
    """
    def tight(text: str, at: int) -> bool:
        # One space between two words at the gutter: cells that touch, but also running text one line in six.
        return len(text) > at + 1 and text[at - 1] != " " and text[at + 1] != " "

    rows: list[tuple[Line, int]] = []
    across = 0  # lines in a row that are written across the gutter
    doubt = False  # after one such line a single space is no longer taken for the gutter
    for i, ln in enumerate(lines):
        at: int | None = cut
        if ln.blank:
            rows.append((ln, cut))
            continue
        starts = _starts(ln)
        near = [s for s in starts if s > existing_head[1] and abs(s - cut - 1) <= WOBBLE]  # cells that may be the proposed one
        if len(ln.text) > cut and ln.text[cut] != " ":
            at = min(near, key=lambda s: abs(s - cut - 1)) - 1 if near else None
        elif near and near[0] <= cut and not any(8 <= s <= existing_head[0] for s in starts):
            # No existing cell, and a cell that starts short of the proposed column: the line is cut in front of that
            # cell and never through it. The ordinary text of the page may well start in such a column.
            at = near[0] - 1
        elif doubt and tight(ln.text, cut):
            at = None
        if at is None:
            across, doubt = across + 1, True
            if across >= 2 and not any(abs(s - cut - 1) <= 1 for x in lines[i + 1: i + 1 + AHEAD] for s in _starts(x)):
                break
        else:
            across = 0
            rows.append((ln, at))
    # The comparison ends with a line that shows both columns: after it a short line or a single space is no evidence.
    while rows and (len(rows[-1][0].text) <= rows[-1][1] + 1 or tight(rows[-1][0].text, rows[-1][1])):
        rows.pop()
    return rows


def _proposed_rows(below: list[Line], ex_span: tuple[int, int], pr_span: tuple[int, int]) -> tuple[int, list[tuple[Line, int]]] | None:
    """(column before the proposed cells, the rows of the comparison), or None where no column is found.

    The proposed column is one of the commonest cell starts between the two header cells, or one in the rows directly
    under the header. It is the one with most rows that show both an existing cell and a cell starting there, then
    the one the longest run of rows keeps to. The commonest start alone can be the text after a bullet, a few columns
    into the cell, or the column that the ordinary text further down the page starts in: either would cut through
    cells of the comparison.
    """
    def between(ln: Line) -> list[int]:
        return [s for s in _starts(ln) if ex_span[1] < s <= pr_span[0] + 2]

    common = Counter(s for ln in below for s in between(ln)).most_common(3)
    first = [s for ln in [x for x in below if not x.blank][:3] for s in between(ln)]
    runs = {s: _rows(below, s - 1, ex_span) for s in dict.fromkeys([s for s, _ in common] + first)}
    if not runs:
        return None

    def two_cells(s: int) -> int:
        # a cell may start a few columns into its column (the text after a bullet, an indented second line), not short of it
        rows = [_starts(ln) for ln, _ in runs[s]]
        return sum(1 for row in rows if any(s - 1 <= x <= s + WOBBLE // 2 for x in row) and any(8 <= x <= ex_span[0] for x in row))

    start = max(runs, key=lambda s: (two_cells(s), len(runs[s]), -s))
    return start - 1, runs[start]


def _existing_starts(rows: list[Line], ex_span: tuple[int, int]) -> Counter:
    """Columns at which the first or second cell of a row starts, between the label column and the "Existing" header."""
    return Counter(s for ln in rows for s in _starts(ln)[:2] if 8 <= s <= ex_span[0])


def split_views(doc: Doc) -> tuple[Doc, Doc, set[int]]:
    """Return (proposed view, existing view, pages that were split). Unsplit lines are identical in both."""
    proposed, existing = Doc(doc.pages), Doc(doc.pages)
    split_pages: set[int] = set()
    by_page: dict[int, list[Line]] = {}
    for ln in doc.lines:
        by_page.setdefault(ln.page, []).append(ln)
    for page, lines in by_page.items():
        head = next(((ln, h) for ln in lines if (h := _header(ln))), None)
        if not head:
            continue
        head_line, (ex_span, pr_span) = head
        found = _proposed_rows([ln for ln in lines if ln.n > head_line.n], ex_span, pr_span)
        if not found:
            continue
        cut, body = found  # cut: the column before the first column of the proposed cell
        # Where the existing cells start is read off the rows that have a proposed cell too, if any do: a line with
        # nothing in the proposed column may be anything.
        paired = [ln for ln, _ in body if any(cut <= s <= cut + 1 + WOBBLE // 2 for s in _starts(ln))]
        starts_left = _existing_starts(paired, ex_span) or _existing_starts([ln for ln, _ in body], ex_span)
        if not starts_left:
            continue
        # The label column ends before the leftmost start that existing cells share (before the leftmost at all, if none do).
        label_end = min([s for s, n in starts_left.items() if n > 1] or starts_left) - 1  # first column of the existing cell
        if not label_end < cut:
            continue
        for ln, at in body:
            text = ln.text
            left = fragments(text[:at], 3)
            # An existing cell that starts a little left of its column must not be left behind in the label column. Two
            # spaces after the label are enough to show it: a narrow font sets such a cell close to a long label.
            early = [s for s, _, _ in fragments(text[:at], 2) if max(8, label_end + 1 - WOBBLE) <= s <= label_end]
            keep = min(early, default=label_end + 1) - 1
            if len(left) == 1 and left[0][0] < keep < left[0][1] and _LABEL_RE.fullmatch(left[0][2]):
                # A label that runs on through the label column, with no existing cell beside it, is an ordinary line of
                # the page ("Financial Covenants:   ...") whose text happens to start under the proposed column: left whole.
                continue
            proposed.lines[ln.n] = Line(page=page, n=ln.n, text=(text[:keep].ljust(at) + text[at:]).rstrip(), qstart=at)
            existing.lines[ln.n] = Line(page=page, n=ln.n, text=text[:at].rstrip())
            if not ln.blank:
                split_pages.add(page)
    return proposed, existing, split_pages
