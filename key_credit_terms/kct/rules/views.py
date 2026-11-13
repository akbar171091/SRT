"""Existing-versus-proposed layouts.

Amendment summaries in lender presentations print three columns: a label, the existing term and
the proposed term. Read as plain lines, the two term columns run into each other. This module
finds the "Existing ... Proposed" header on such a page and builds two views of the document:

* ``proposed``: label column + proposed column (existing column blanked out)
* ``existing``: label column + existing column

Everything downstream reads the proposed view and falls back to the existing view where the
proposed cell says "Same as existing".
"""
from __future__ import annotations

import re
from collections import Counter

from ..textmodel import Doc, Line, fragments

_EXISTING_RE = re.compile(r"^(existing|current)\b", re.IGNORECASE)
_PROPOSED_RE = re.compile(r"^(proposed|amended|new)\b", re.IGNORECASE)
SAME_AS_EXISTING_RE = re.compile(r"^\W*(same(\s+as\s+(existing|current))?|no\s+change|unchanged)\W*$", re.IGNORECASE)


def _header(line: Line) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """(span of the 'Existing' header cell, span of the 'Proposed' header cell) if this line is that header."""
    cells = fragments(line.text, 3)
    if not 2 <= len(cells) <= 3:
        return None
    ex = [c for c in cells if _EXISTING_RE.match(c[2]) and len(c[2].split()) <= 3]
    pr = [c for c in cells if _PROPOSED_RE.match(c[2]) and len(c[2].split()) <= 3]
    if len(ex) == 1 and len(pr) == 1 and ex[0][0] < pr[0][0]:
        return (ex[0][0], ex[0][1]), (pr[0][0], pr[0][1])
    return None


def split_views(doc: Doc) -> tuple[Doc, Doc, set[int]]:
    """Return (proposed view, existing view, pages that were split). Unsplit pages are identical in both."""
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
        body = [ln for ln in lines if ln.n > head_line.n and not ln.blank]
        starts_right = Counter(s for ln in body for s, _, _ in fragments(ln.text, 3) if ex_span[1] < s <= pr_span[0] + 2)
        starts_left = Counter(s for ln in body for i, (s, _, _) in enumerate(fragments(ln.text, 3)) if 8 <= s <= ex_span[0] and i <= 1)
        if not starts_right or not starts_left:
            continue
        cut = starts_right.most_common(1)[0][0] - 1  # first column of the proposed cell
        label_end = starts_left.most_common(1)[0][0] - 1  # first column of the existing cell
        if not label_end < cut:
            continue
        split_pages.add(page)
        for ln in lines:
            if ln.n <= head_line.n:
                continue
            text = ln.text
            proposed.lines[ln.n] = Line(page=page, n=ln.n, text=(text[:label_end].ljust(cut) + text[cut:]).rstrip(), qstart=cut)
            existing.lines[ln.n] = Line(page=page, n=ln.n, text=text[:cut].rstrip())
    return proposed, existing, split_pages
