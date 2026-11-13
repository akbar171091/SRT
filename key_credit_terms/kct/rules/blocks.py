"""Labelled sections of a term sheet ("Financial Covenants:", "Assignments and Participations:" ...).

Term sheets are two-column lists: a short label on the left and wrapped text on the right.
A block is the label plus everything up to the next label. Four layouts occur in practice:

* column   label in the left column, value text in a deeper column; the block ends when a line
           returns to the label column with a new label.
* enum     a lettered sub-heading inside a longer section ("(c) Financial Covenants - ...");
           the block ends at the next letter or at the next top-level label.
* inline   a "Label:" written inside the value column or as a bullet; the block is that
           paragraph or bullet.
* plain    pages extracted without layout (rotated slides) have no columns at all; the block
           ends at the next "Label:" line.

A label may wrap over two or three lines of the left column ("Assignments and" / "Participations:").
The pattern may match any one of those lines; the whole label and all of its value text are returned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..textmodel import Doc, Line, fragments, is_footer, tidy

MAX_BLOCK_LINES = 260
_BULLET = "•·▪●"
_LEAD = r"^(?P<lead>\s*(?:[" + _BULLET + r"\-–]\s*|\(?[a-zA-Z0-9]{1,3}[.)]\s+)?)"
_TERM = r"(?P<term>\s*:|\s+[-–]\s|\s{2,}|\s*$)"
_PLAIN_LABEL_RE = re.compile(r"^[A-Z][A-Za-z /&\-()’']{2,44}:(\s|$)")
_BULLET_LINE_RE = re.compile(r"^\s*[" + _BULLET + r"]")
_LABEL_WORDS = 7


@dataclass
class Block:
    label: str
    line: Line  # the (first) label line
    lines: list[Line]  # label line(s) followed by the continuation lines
    parts: list[str]  # value text of each line, same order as ``lines``
    inline: bool  # label sat inside the value column (a sub-heading or a bullet such as "Upfront Fee: ...")
    mode: str = "column"
    _text: str | None = field(default=None, repr=False)
    _starts: list[int] | None = field(default=None, repr=False)

    def _build(self) -> None:
        pieces, starts, pos = [], [], 0
        for part in self.parts:
            part = tidy(part)
            starts.append(pos)
            if part:
                pieces.append(part)
                pos += len(part) + 1
        self._text, self._starts = " ".join(pieces), starts

    @property
    def text(self) -> str:
        """The value text of the block: each line's value part, joined by single spaces."""
        if self._text is None:
            self._build()
        return self._text

    def line_at(self, offset: int) -> int:
        """Index into ``lines`` / ``parts`` of the line that holds character ``offset`` of ``text``."""
        if self._starts is None:
            self._build()
        idx = 0
        for i, start in enumerate(self._starts):
            if start <= offset and tidy(self.parts[i]):
                idx = i
            elif start > offset:
                break
        return idx

    @property
    def page(self) -> int:
        return self.line.page

    @property
    def pages(self) -> list[int]:
        return sorted({ln.page for ln in self.lines})

    @property
    def end(self) -> int:
        return self.lines[-1].n


def _first_cell(text: str) -> str:
    cells = fragments(text, 3)
    return cells[0][2] if cells else ""


def _looks_like_label(text: str) -> bool:
    cells = fragments(text, 3)
    if not cells:
        return False
    first = cells[0][2]
    if not (first[0].isupper() or first[0].isdigit() or first[0] in "(“\""):
        return False
    return len(first.split()) <= _LABEL_WORDS and (first.rstrip().endswith(":") or len(cells) > 1 or len(text.strip()) < 50)


def _label_fragment(ln: Line, label_indent: int) -> tuple[str, str] | None:
    """(label text, value text) if this line is a wrapped piece of a left-column label at ``label_indent``."""
    if ln.blank or abs(ln.indent - label_indent) > 1:
        return None
    cells = fragments(ln.text, 3)
    if not cells:
        return None
    first = cells[0][2]
    if len(first.split()) > 5 or len(first) > 44 or first.rstrip().endswith((".", ";", ",")):
        return None
    if len(cells) == 1 and not first.rstrip().endswith(":") and len(ln.text.strip()) > 44:
        return None
    return first, ln.text[cells[0][1]:].strip()


def find_blocks(doc: Doc, label_pattern: str, max_lines: int = MAX_BLOCK_LINES) -> list[Block]:
    """All blocks whose label matches ``label_pattern`` (a regex fragment, case-insensitive)."""
    label_re = re.compile(_LEAD + r"(?P<label>" + label_pattern + r")" + _TERM, re.IGNORECASE)
    blocks: list[Block] = []
    taken: set[int] = set()
    for ln in doc.lines:
        if ln.blank or ln.n in taken:
            continue
        m = label_re.match(ln.text)
        if not m:
            continue
        marked = bool(m.group("term").strip())  # "Label:" or "Label - "
        lead = m.group("lead").strip()
        deep = ln.indent > 40 or (bool(lead) and ln.indent > 12)
        if deep and not marked:
            continue  # inside the value column and not written as a label: part of a sentence
        if not marked and ln.indent > 20 and ln.text[m.end():].strip()[:1].islower():
            continue
        block = _grow(doc, ln, m, deep, max_lines)
        taken.update(x.n for x in block.lines[:4] if abs(x.indent - ln.indent) <= 1)
        blocks.append(block)
    return blocks


def _grow(doc: Doc, ln: Line, m: re.Match, deep: bool, max_lines: int) -> Block:
    rest = ln.text[m.end():]
    first_part = rest.strip()
    value_col = m.end() + (len(rest) - len(rest.lstrip())) if first_part else None
    label_indent = ln.indent
    label = tidy(m.group("label"))
    letter = re.search(r"\(([a-y])\)", m.group("lead"))
    if letter:
        mode = "enum"
        next_letter = re.compile(r"^\s*\(" + chr(ord(letter.group(1)) + 1) + r"\)\s")
    elif deep:
        mode = "inline"
    elif label_indent <= 3 and (value_col is None or value_col - label_indent < 28) and not doc.has_columns(ln.page):
        mode = "plain"
    else:
        mode = "column"

    lines, parts = [ln], [first_part]
    label_open = mode == "column" and not m.group("term").strip().startswith(":")  # the label may wrap onto the next lines

    # A label that wraps: the pattern may have matched its second or third line. Pull in the lines above.
    if mode == "column" and not m.group("lead").strip():
        prev_n = ln.n - 1
        pulled = 0
        while prev_n >= 0 and pulled < 2:
            prev = doc.lines[prev_n]
            if prev.blank or prev.page != ln.page:
                break
            frag = _label_fragment(prev, label_indent)
            if frag is None or frag[0].rstrip().endswith(":"):
                break
            if value_col is not None and frag[1] and abs(prev.text.rindex(frag[1]) - value_col) > 6:
                break  # its value text does not sit in this block's value column
            label = tidy(frag[0] + " " + label)
            lines.insert(0, prev)
            parts.insert(0, frag[1])
            pulled += 1
            prev_n -= 1
        if pulled and value_col is None:
            first = lines[0]
            cells = fragments(first.text, 3)
            if len(cells) > 1:
                value_col = cells[1][0]

    # A table cell whose label is centred vertically: the value starts on the line(s) above the label line.
    # Recognised when the value beside the label reads as a continuation and the line above is unfinished.
    if mode == "column" and value_col is not None and len(lines) == 1 and first_part and (
            first_part[0].islower() or first_part[0] in "(\"“,;"):
        above: list[Line] = []
        k = ln.n - 1
        while k >= 0 and len(above) < 12:
            prev = doc.lines[k]
            if prev.blank or prev.page != ln.page or prev.indent < value_col - 3 or is_footer(prev.text):
                break
            above.insert(0, prev)
            k -= 1
        if above and not above[-1].text.rstrip().endswith((".", ";", ":")):
            lines = above + lines
            parts = [x.text.strip() for x in above] + parts

    base: int | None = None  # left margin of an inline paragraph
    prev_page = ln.page
    shifted = False  # on a later page whose layout offset differs from the label's page
    label_lines = 0
    n = ln.n + 1
    while n < len(doc.lines) and len(lines) < max_lines:
        cur = doc.lines[n]
        n += 1
        if cur.blank:
            if mode == "inline" and (first_part or len(lines) > 1):
                break  # an inline label owns one paragraph
            label_open = False
            continue
        if is_footer(cur.text):
            continue
        new_page = cur.page != prev_page
        prev_page = cur.page
        if mode == "plain":
            if new_page or _PLAIN_LABEL_RE.match(cur.text):
                break
        elif mode == "enum":
            first_cell = _first_cell(cur.text)
            if next_letter.match(cur.text):
                break
            if _looks_like_label(cur.text) and (
                (first_cell.rstrip().endswith(":") and cur.indent <= label_indent + 1) or (label_indent > 20 and cur.indent <= 6)
            ):
                break
        elif mode == "inline":
            if base is None:
                base = min(label_indent, cur.indent)
            if cur.indent < base - 1 or (_BULLET_LINE_RE.match(cur.text) and cur.indent <= label_indent + 1):
                break
        else:  # column
            if label_open and not new_page and label_lines < 2:
                frag = _label_fragment(cur, label_indent)
                if frag is not None and (value_col is None or cur.indent < value_col - 3):
                    label = tidy(label + " " + frag[0])
                    label_lines += 1
                    label_open = not frag[0].rstrip().endswith(":")
                    lines.append(cur)
                    parts.append(frag[1])
                    if value_col is None and frag[1]:
                        value_col = len(cur.text) - len(frag[1])
                    continue
            label_open = False
            if value_col is None:
                value_col = cur.indent
                if value_col <= label_indent + 1:
                    break  # nothing deeper follows: a heading, not a labelled value
            if new_page:
                # Layout offsets differ from page to page; a page that carries on mid-sentence at the
                # left edge has simply shifted, so indentation cannot end the block there.
                shifted = cur.indent <= label_indent + 6 and not _looks_like_label(cur.text)
            if shifted:
                cells = fragments(cur.text, 3)
                if len(cells) > 1 and cells[0][2].rstrip().endswith(":") and _looks_like_label(cur.text):
                    break
            elif cur.indent < value_col - 3 and cur.indent <= label_indent + 6:
                break
        lines.append(cur)
        parts.append(cur.text[cur.qstart:].strip() if cur.qstart and cur.indent >= cur.qstart else cur.text.strip())
    return Block(label=label.rstrip(": "), line=lines[0], lines=lines, parts=parts, inline=deep, mode=mode)
