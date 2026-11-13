"""Labelled sections of a term sheet ("Commitment Fee:", "Financial Covenants:" ...).

Term sheets are two-column lists: a short label on the left and wrapped text on the right.
A block is the label plus everything up to the next label. Four layouts occur in practice:

* column   label in the left column, value text in a deeper column; the block ends when a line
           returns to the label column.
* enum     a lettered sub-heading inside a longer section ("(c) Financial Covenants - ...");
           the block ends at the next letter or at the next top-level label.
* inline   a "Label:" written inside the value column or as a bullet; the block is that
           paragraph or bullet.
* plain    pages extracted without layout (rotated slides) have no columns at all; the block
           ends at the next "Label:" line.

A "Label:" that stands alone on its line with its text underneath at the same margin is read the
plain way even on a page that has columns elsewhere. A label that wraps over two lines of the
label column ("Financial" / "Covenants:") is joined before it is matched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .textmodel import Doc, Line, fragments, is_footer, tidy

MAX_BLOCK_LINES = 140
_BULLET = "\u2022\u00b7\uf0b7"
_LEAD = r"^(?P<lead>\s*(?:[" + _BULLET + r"\-\u2013]\s*|\(?[a-zA-Z0-9]{1,3}[.)]\s+)?)"
_TERM = r"(?P<term>\s*:|\s+[-\u2013]\s|\s{2,}|\s*$)"
_PLAIN_LABEL = r"[A-Z][A-Za-z /&\-()\u2019']{2,44}:(\s|$)"
_PLAIN_LABEL_RE = re.compile("^" + _PLAIN_LABEL)
_MARKED_LABEL_RE = re.compile(_LEAD + _PLAIN_LABEL)
_BULLET_LINE_RE = re.compile(r"^\s*[" + _BULLET + r"]")


@dataclass
class Block:
    label: str
    line: Line  # the label line
    lines: list[Line]  # label line followed by its continuation lines
    parts: list[str]  # value text of each line, same order as ``lines``
    inline: bool  # label sat inside the value column (a sub-heading or a bullet such as "Upfront Fee: ...")
    continues: bool = False  # the label line reads as the second line of a longer label ("Negative" / "Covenants:")

    @property
    def text(self) -> str:
        return tidy(" ".join(self.parts))

    @property
    def page(self) -> int:
        return self.line.page

    @property
    def end(self) -> int:
        return self.lines[-1].n


def _looks_like_label(text: str) -> bool:
    cells = fragments(text, 3)
    if not cells:
        return False
    first = cells[0][2]
    if not (first[0].isupper() or first[0].isdigit() or first[0] in "(\u201c\""):
        return False
    return len(first.split()) <= 7 and (first.rstrip().endswith(":") or len(cells) > 1 or len(text.strip()) < 50)


def _mark(lead: str) -> str:
    """The style of the number or bullet in front of a label: "7." and "12." are alike, "7." and "(a)" are not."""
    return re.sub(r"\d+", "9", re.sub(r"[a-z]+", "a", re.sub(r"[A-Z]+", "A", lead.strip())))


def _starts_section(text: str, lead: str) -> bool:
    """True when a line without columns opens the next section: a "Label:", bare or marked the way this block's label is.

    A "Label:" that is numbered or bulleted in another style is a sub-item of the section, not the next one.
    """
    if _PLAIN_LABEL_RE.match(text):
        return True
    m = _MARKED_LABEL_RE.match(text) if lead and not text[:1].isspace() else None
    return bool(m) and _mark(m.group("lead")) == _mark(lead)


def _is_title(text: str) -> bool:
    """A few capitalised words and no figure, such as "NEGATIVE COVENANTS": the next section where headings carry no colon."""
    core = text.strip()
    return len(core.split()) <= 6 and core[0].isupper() and core[-1] not in ".,;" and not any(ch.isdigit() for ch in core)


def _is_deep(ln: Line, lead: str) -> bool:
    return ln.indent > 40 or (bool(lead) and ln.indent > 12)


def find_blocks(doc: Doc, label_pattern: str, max_lines: int = MAX_BLOCK_LINES) -> list[Block]:
    """All blocks whose label matches ``label_pattern`` (a regex fragment, case-insensitive)."""
    label_re = re.compile(_LEAD + r"(?P<label>" + label_pattern + r")" + _TERM, re.IGNORECASE)
    blocks: list[Block] = []
    joined: set[int] = set()  # second lines of labels that wrap over two lines
    for ln in doc.lines:
        if ln.blank or ln.n in joined:
            continue
        m = label_re.match(ln.text)
        if not m:
            wrapped = _wrapped(doc, ln, label_re, max_lines)
            if wrapped:
                blocks.append(wrapped)
                joined.add(ln.n + 1)
            continue
        marked = bool(m.group("term").strip())  # "Label:" or "Label - "
        lead = m.group("lead").strip()
        deep = _is_deep(ln, lead)
        if deep and not marked:
            continue  # inside the value column and not written as a label: part of a sentence
        if not marked and ln.indent > 20 and ln.text[m.end():].strip()[:1].islower():
            continue
        blocks.append(_grow(doc, ln, tidy(m.group("label")), m.group("lead"), m.end(), deep, max_lines))
        blocks[-1].continues = marked and _continues(doc, ln)
    return blocks


def _continues(doc: Doc, ln: Line) -> bool:
    """True when the line above ``ln`` reads as the first line of the same label: short, at the same margin, no colon."""
    above = doc.lines[ln.n - 1] if ln.n else None
    if above is None or above.blank or above.page != ln.page or above.indent != ln.indent:
        return False
    top = fragments(above.text, 3)[0][2]
    return top[0].isupper() and top[-1] not in ":.;," and len(top.split()) <= 4


def _wrapped(doc: Doc, ln: Line, label_re: re.Pattern, max_lines: int) -> Block | None:
    """The block of a label that wraps over two lines of the label column ("Financial" / "Covenants:"), where ``ln`` is its first line."""
    nxt = doc.lines[ln.n + 1] if ln.n + 1 < len(doc.lines) else None
    if nxt is None or ":" not in nxt.text or nxt.page != ln.page or nxt.indent != ln.indent:
        return None
    top, tail = fragments(ln.text, 3)[0], fragments(nxt.text, 3)[0]
    if not tail[2].endswith(":") or top[2].endswith(":") or max(len(top[2].split()), len(tail[2].split())) > 4:
        return None
    label = ln.text[:top[1]] + " " + tail[2]
    m = label_re.match(label)
    if not m or m.end() != len(label) or m.end("label") <= top[1]:
        return None  # the two lines do not make one label that ends at the colon
    value = ln.text[top[1]:]
    value_col = top[1] + len(value) - len(value.lstrip()) if value.strip() else None
    deep = _is_deep(ln, m.group("lead").strip())
    rest = _grow(doc, nxt, tidy(m.group("label")), m.group("lead"), tail[1], deep, max_lines - 1, value_col)
    return Block(label=rest.label, line=ln, lines=[ln] + rest.lines, parts=[value.strip()] + rest.parts, inline=deep)


def _grow(doc: Doc, ln: Line, label: str, lead: str, end: int, deep: bool, max_lines: int, value_col: int | None = None) -> Block:
    """The block of the label that ends at column ``end`` of ``ln``; ``value_col`` is given where the value began on a line above."""
    rest = ln.text[end:]
    first_part = rest.strip()
    if first_part:
        value_col = end + (len(rest) - len(rest.lstrip()))
    label_indent = ln.indent
    alone = not first_part and value_col is None and ln.text[:end].rstrip().endswith(":")  # "Label:" and nothing else
    lead = lead.strip()
    letter = re.search(r"\(([a-y])\)", lead)
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
    base: int | None = None  # left margin of an inline paragraph
    prev_page = ln.page
    shifted = False  # on a later page whose layout offset differs from the label's page
    gap = False  # a blank line stands between the last line taken and this one
    n = ln.n + 1
    while n < len(doc.lines) and len(lines) < max_lines:
        cur = doc.lines[n]
        n += 1
        if cur.blank:
            if mode == "inline" and (first_part or len(lines) > 1):
                break  # an inline label owns one paragraph
            gap = True
            continue
        if is_footer(cur.text):
            continue
        new_page = cur.page != prev_page
        prev_page = cur.page
        if mode == "column" and value_col is None:
            value_col = cur.indent
            if value_col <= label_indent + 1:
                if not alone or new_page:
                    break  # nothing deeper follows: a heading, not a labelled value
                mode = "heading"  # "Label:" alone on its line, its text underneath at the same margin
        if mode == "plain":
            if new_page or _starts_section(cur.text, lead):
                break
        elif mode == "heading":
            at_margin = cur.indent <= label_indent + 1
            if new_page or (at_margin and (_starts_section(cur.text.lstrip(), lead) or (gap and _is_title(cur.text)))):
                break
        elif mode == "enum":
            first_cell = fragments(cur.text, 3)[0][2]
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
        gap = False
        lines.append(cur)
        parts.append(cur.text[cur.qstart:].strip() if cur.qstart and cur.indent >= cur.qstart else cur.text.strip())
    return Block(label=label, line=ln, lines=lines, parts=parts, inline=deep)
