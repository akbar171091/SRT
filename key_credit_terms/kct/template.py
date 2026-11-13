"""Write a Key Credit Terms record into a copy of the Word template.

The template is one two-column table: section header rows spanning both columns, and under each
header a label cell and a value cell holding bracketed prompts. For every field of the record the
prompts in its value cell are replaced by the record's lines, one paragraph per line, in the
paragraph and character formatting the template already uses in that cell. Nothing else in the
document is touched: styles, column widths, headers, footers and the pricing row stay as they are.

Review aids (both optional):

* rows where the term sheet is silent, or only points to another document, are highlighted so the
  reader sees at a glance what still has to come from elsewhere;
* each populated cell carries a Word comment with the term sheet quotes and page numbers behind it.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.enum.text import WD_BREAK, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from .fields import BY_ID, FIELDS, Field

STOCK_ROW_COUNT = 41
COMMENT_AUTHOR = "Key Credit Terms populator"
COMMENT_INITIALS = "KCT"
FLAG_COLOURS = {"not_stated": WD_COLOR_INDEX.YELLOW, "by_reference": WD_COLOR_INDEX.YELLOW}
SOURCE_LABELS = {
    "audited": "audited record",
    "rules": "rules engine",
    "claude-api": "Claude (API)",
    "claude-cli": "Claude (Claude Code CLI)",
}
SOURCE_NOTES = {
    "audited": "The entries were read from the term sheet by an AI reviewer and then re-checked against it twice by independent "
               "AI reviewers. They have not been signed off by a person.",
    "rules": "The entries were read by the offline rules engine (pattern matching on the PDF text). Treat them as a first read "
             "and check each row against the term sheet.",
    "claude-api": "The entries were extracted by Claude and have not been reviewed. Check each row against the term sheet.",
    "claude-cli": "The entries were extracted by Claude and have not been reviewed. Check each row against the term sheet.",
}
STATUS_TEXT = {
    "stated": "Stated in term sheet",
    "by_reference": "Term sheet refers to another document for this",
    "not_stated": "Not stated in term sheet",
}
_W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
# Characters that are not allowed in XML 1.0 text.
_ILLEGAL_XML_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


class TemplateError(RuntimeError):
    """The template does not have the rows this tool fills."""


@dataclass
class _Row:
    index: int
    section: str  # normalised header of the section the row sits in ("" above the first header)
    ordinal: int  # position among the two-cell rows of its section
    label: str  # normalised text of the label cell
    label_tc: object
    value_tc: object


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _tc_text(tc) -> str:
    return "".join(t.text or "" for t in tc.iter(qn("w:t")))


def _find_table(doc) -> Table:
    """The Key Credit Terms table: the table that carries the template's row labels."""
    wanted = {_norm(f.label) for f in FIELDS if f.label}
    best, best_hits = None, 0
    for table in doc.tables:
        labels = {_norm(_tc_text(tr.tc_lst[0])) for tr in table._tbl.tr_lst if len(tr.tc_lst) >= 2}
        hits = len(wanted & labels)
        if hits > best_hits:
            best, best_hits = table, hits
    if best is None or best_hits < 5:
        raise TemplateError("This does not look like the Key Credit Terms template: no table with its row labels "
                            "(Borrower(s), Lender Commitments, Purpose, ...) was found.")
    return best


def _rows(table: Table) -> tuple[list[_Row], int]:
    rows: list[_Row] = []
    section, ordinal = "", 0
    trs = table._tbl.tr_lst
    for i, tr in enumerate(trs):
        cells = tr.tc_lst
        if len(cells) == 1:  # a header spanning both columns starts a new section
            section, ordinal = _norm(_tc_text(cells[0])), 0
            continue
        if len(cells) < 2:
            continue
        rows.append(_Row(index=i, section=section, ordinal=ordinal, label=_norm(_tc_text(cells[0])),
                         label_tc=cells[0], value_tc=cells[1]))
        ordinal += 1
    return rows, len(trs)


def _locate(field: Field, rows: list[_Row], n_rows: int) -> _Row | None:
    section, label = _norm(field.section), _norm(field.label)
    in_section = [r for r in rows if r.section == section or (section and r.section.startswith(section))]
    if label:
        hit = [r for r in in_section if r.label == label] or [r for r in rows if r.label == label]
        if len(hit) == 1:
            return hit[0]
    else:
        hit = [r for r in in_section if r.ordinal == field.ordinal and not r.label]
        if len(hit) == 1:
            return hit[0]
    if n_rows == STOCK_ROW_COUNT:  # the stock layout: fall back to the row number
        hit = [r for r in rows if r.index == field.row]
        if hit:
            return hit[0]
    return None


def _clean(text: str) -> str:
    return _ILLEGAL_XML_RE.sub("", text)


def _prototype(tc):
    """(paragraph, run properties) to model new content on: the cell's first paragraph and first run with text."""
    paras = tc.findall(qn("w:p"))
    proto_p = paras[0] if paras else None
    rpr = None
    for r in tc.iter(qn("w:r")):
        if any((t.text or "").strip() for t in r.iter(qn("w:t"))):
            rpr = r.find(qn("w:rPr"))
            break
    else:
        first = next(tc.iter(qn("w:r")), None)
        if first is not None:
            rpr = first.find(qn("w:rPr"))
    return proto_p, rpr


def _write_lines(tc, lines: list[str], parent, highlight=None) -> list[Run]:
    """Replace the paragraphs of a cell with one paragraph per line; returns the new runs."""
    proto_p, rpr = _prototype(tc)
    old = tc.findall(qn("w:p"))
    anchor = old[0] if old else None
    runs: list[Run] = []
    new_ps = []
    for line in lines:
        if proto_p is not None:
            p = copy.deepcopy(proto_p)
            for child in list(p):
                if child.tag != qn("w:pPr"):
                    p.remove(child)
            for attr in (f"{{{_W14}}}paraId", f"{{{_W14}}}textId"):  # ids must stay unique in the document
                p.attrib.pop(attr, None)
        else:
            p = OxmlElement("w:p")
        r = OxmlElement("w:r")
        if rpr is not None:
            r.append(copy.deepcopy(rpr))
        t = OxmlElement("w:t")
        t.text = _clean(line)
        t.set(_XML_SPACE, "preserve")
        r.append(t)
        p.append(r)
        new_ps.append(p)
        run = Run(r, Paragraph(p, parent))
        if highlight is not None:
            run.font.highlight_color = highlight
        runs.append(run)
    if anchor is not None:
        for p in new_ps:
            anchor.addprevious(p)
        for p in old:
            tc.remove(p)
    else:
        for p in new_ps:
            tc.append(p)
    return runs


def _set_label(tc, text: str) -> None:
    """Replace the text of a label cell, keeping the formatting of its first run."""
    runs = list(tc.iter(qn("w:r")))
    if not runs:
        return
    first = True
    for r in runs:
        for t in r.findall(qn("w:t")):
            t.text = _clean(text) if first else ""
            first = False


def _comment_text(field: Field, entry: dict, source_file: str) -> str:
    lines = [f"{STATUS_TEXT.get(entry['status'], entry['status'])} ({source_file})."]
    for e in entry.get("evidence") or []:
        page = f"p.{e['page']}" if e.get("page") else "page ?"
        flag = ""
        if e.get("found") == "missing":
            flag = "  [quote not found in the PDF text: check]"
        elif e.get("found") == "other_page":
            on = ", ".join(str(p) for p in e.get("found_on") or [])
            flag = f"  [found on page {on}, not on the page cited]" if on else ""
        lines.append(f"{page}: “{e['quote']}”{flag}")
    if entry.get("note"):
        lines.append(f"Note: {entry['note']}")
    return _clean("\n".join(lines))


def _fill_appendix_number(doc, appendix: str) -> bool:
    for p in doc.paragraphs:
        if "appendix" not in p.text.lower():
            continue
        for run in p.runs:
            if re.fullmatch(r"\s*\[\s*\]\s*", run.text or ""):
                run.text = str(appendix)
                return True
    return False


def _add_sources_table(doc, main: Table, record: dict) -> None:
    """Append a "Term sheet references" table after the main table (the alternative to comments)."""
    brk = doc.add_paragraph()
    brk.add_run().add_break(WD_BREAK.PAGE)
    head = doc.add_paragraph()
    head.add_run(f"Term sheet references - {record.get('source_file', '')}").bold = True
    rows = [(BY_ID[fid], entry) for fid, entry in record["fields"].items() if fid in BY_ID and (entry.get("evidence") or entry.get("note"))]
    table = doc.add_table(rows=1, cols=3)
    if main.style is not None:
        table.style = main.style
    borders = main._tbl.tblPr.find(qn("w:tblBorders"))
    if borders is not None and table._tbl.tblPr.find(qn("w:tblBorders")) is None:
        table._tbl.tblPr.append(copy.deepcopy(borders))
    for cell, text in zip(table.rows[0].cells, ("Row", "Term sheet text", "Page")):
        cell.text = ""
        cell.paragraphs[0].add_run(text).bold = True
    for field, entry in rows:
        name = field.label.strip("[]: ") or field.prompt.split(" ")[0] + " (" + field.section + ")"
        items = entry.get("evidence") or [{"quote": "", "page": None}]
        for i, e in enumerate(items):
            cells = table.add_row().cells
            cells[0].text = _clean(name if i == 0 else "")
            quote = f"“{e['quote']}”" if e.get("quote") else ""
            if i == 0 and entry.get("note"):
                quote = (quote + "\n" if quote else "") + f"Note: {entry['note']}"
            cells[1].text = _clean(quote)
            cells[2].text = str(e["page"]) if e.get("page") else ""


def render(record: dict, template_path: Path, out_path: Path, *, evidence: str = "comments", highlight: bool = True,
           appendix: str | None = None) -> dict:
    """Populate a copy of the template from ``record`` and save it to ``out_path``.

    evidence: "comments" (a Word comment on each populated cell), "table" (a references table after
    the main table) or "none". Returns a small report: rows written, rows flagged, comments added.
    """
    if evidence not in ("comments", "table", "none"):
        raise ValueError("evidence must be 'comments', 'table' or 'none'")
    doc = Document(str(template_path))
    table = _find_table(doc)
    rows, n_rows = _rows(table)
    targets: dict[str, _Row] = {}
    missing = []
    for field in FIELDS:
        row = _locate(field, rows, n_rows)
        if row is None:
            missing.append(field.label or f"row {field.ordinal + 1} of '{field.section}'")
        else:
            targets[field.id] = row
    if missing:
        raise TemplateError("The template is missing these rows: " + "; ".join(missing))
    if len({id(r.value_tc) for r in targets.values()}) != len(targets):
        raise TemplateError("Two fields resolved to the same template row; the template layout has changed too much.")

    report = {"rows": 0, "flagged": [], "comments": 0}
    source_file = record.get("source_file") or "term sheet"
    first_runs: list[Run] = []
    for field in FIELDS:
        entry = record["fields"][field.id]
        row = targets[field.id]
        colour = FLAG_COLOURS.get(entry["status"]) if highlight else None
        cell = table.cell(0, 0)  # any cell of the table serves as the python-docx parent for new paragraphs
        runs = _write_lines(row.value_tc, entry["lines"], cell, highlight=colour)
        report["rows"] += 1
        if entry["status"] in FLAG_COLOURS:
            report["flagged"].append(field.id)
        if field.id == "other_covenants" and entry["status"] != "not_stated" and row.label == "other":
            _set_label(row.label_tc, "Other")
        if not first_runs:
            first_runs = runs
        if evidence == "comments" and runs and (entry.get("evidence") or entry.get("note")):
            doc.add_comment(runs, text=_comment_text(field, entry, source_file), author=COMMENT_AUTHOR, initials=COMMENT_INITIALS)
            report["comments"] += 1

    if appendix:
        _fill_appendix_number(doc, appendix)
    title_runs = next((p.runs for p in doc.paragraphs if "key credit terms" in p.text.lower() and p.runs), None)
    first_runs = title_runs or first_runs  # the covering comment sits on the title
    if evidence == "comments" and first_runs:
        how = SOURCE_LABELS.get(record.get("source", ""), record.get("source", ""))
        intro = [f"Populated from {source_file}" + (f" ({how})" if how else "") + "."]
        if record.get("source") in SOURCE_NOTES:
            intro.append(SOURCE_NOTES[record["source"]])
        if highlight:
            intro.append("Yellow = the term sheet is silent on the row or only refers to another document: complete from "
                         "the credit agreement or the deal team.")
        intro.append("Comments on the rows give the term sheet wording and page behind each entry. Delete the comments "
                     "and highlighting once reviewed.")
        if record.get("doc", {}).get("notes"):
            intro.append(f"About the term sheet: {record['doc']['notes']}")
        doc.add_comment(first_runs, text=_clean("\n".join(intro)), author=COMMENT_AUTHOR, initials=COMMENT_INITIALS)
        report["comments"] += 1
    if evidence == "table":
        _add_sources_table(doc, table, record)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc.save(str(out_path))
    except PermissionError as exc:
        raise PermissionError(f"Cannot write {out_path}: close it in Word and run again.") from exc
    return report
