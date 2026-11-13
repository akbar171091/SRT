"""The Key Credit Terms record: one entry per template row, each with its evidence.

    {
      "schema": "kct/1",
      "client": "Seadrill", "deal": "Seadrill 2026",
      "source_file": "Seadrill 2026 TS.pdf", "sha1": "...",
      "source": "audited" | "rules" | "claude-api" | "claude-cli",
      "doc": {"kind": "...", "title": "...", "date": "...", "notes": "..."},
      "fields": {
        "<field id>": {
          "lines": ["text of each paragraph written into the cell"],
          "status": "stated" | "by_reference" | "not_stated",
          "evidence": [{"quote": "verbatim text", "page": 3}],
          "note": "reviewer note, not printed in the table"
        }, ...
      }
    }
"""
from __future__ import annotations

import copy
import re

from .config import NOT_STATED
from .fields import BY_ID, FIELD_IDS, STATUSES
from .textmodel import Doc, tidy

SCHEMA_ID = "kct/1"
DOC_KINDS = ("term_sheet", "commitment_letter_term_sheet", "lender_presentation", "summary", "other")
MAX_LINES = 8
MAX_LINE_CHARS = 420
MAX_QUOTE_CHARS = 300
MAX_EVIDENCE = 3


def empty_field(text: str = NOT_STATED) -> dict:
    return {"lines": [text], "status": "not_stated", "evidence": [], "note": ""}


def new_record(client: str, deal: str, source_file: str, sha1: str, source: str) -> dict:
    return {
        "schema": SCHEMA_ID,
        "client": client,
        "deal": deal,
        "source_file": source_file,
        "sha1": sha1,
        "source": source,
        "doc": {"kind": "term_sheet", "title": "", "date": "", "notes": ""},
        "fields": {fid: empty_field() for fid in FIELD_IDS},
    }


# ---- JSON Schema (structured outputs) -------------------------------------------------------------

_FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": list(STATUSES)},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"quote": {"type": "string"}, "page": {"type": "integer"}},
                "required": ["quote", "page"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["lines", "status", "evidence", "note"],
    "additionalProperties": False,
}


def extraction_json_schema() -> dict:
    """Schema for what a Claude engine returns: the document description and a list with one entry per field.

    The fields travel as a list of {id, lines, status, evidence, note} rather than as an object with
    34 keys, which keeps the schema small enough for structured outputs on every model.
    """
    item = copy.deepcopy(_FIELD_SCHEMA)
    item["properties"] = {"id": {"type": "string", "enum": list(FIELD_IDS)}, **item["properties"]}
    item["required"] = ["id", *item["required"]]
    return {
        "type": "object",
        "properties": {
            "doc": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(DOC_KINDS)},
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["kind", "title", "date", "notes"],
                "additionalProperties": False,
            },
            "fields": {"type": "array", "items": item},
        },
        "required": ["doc", "fields"],
        "additionalProperties": False,
    }


def from_extraction(data: dict, record: dict) -> list[str]:
    """Copy an engine's answer (see extraction_json_schema) into ``record``. Returns the field ids it left out."""
    if isinstance(data.get("doc"), dict):
        record["doc"] = data["doc"]
    seen: set[str] = set()
    fields = data.get("fields")
    items = fields.items() if isinstance(fields, dict) else [(f.get("id"), f) for f in fields or [] if isinstance(f, dict)]
    for fid, entry in items:
        if fid in BY_ID and fid not in seen and isinstance(entry, dict):
            record["fields"][fid] = {k: entry.get(k) for k in ("lines", "status", "evidence", "note")}
            seen.add(fid)
    return [fid for fid in FIELD_IDS if fid not in seen]


# ---- validation and clean-up ---------------------------------------------------------------------

def normalise(record: dict) -> dict:
    """A cleaned copy: every field present, whitespace tidied, limits applied. Never raises on a sloppy record."""
    rec = copy.deepcopy(record)
    rec.setdefault("schema", SCHEMA_ID)
    doc = rec.get("doc") if isinstance(rec.get("doc"), dict) else {}
    rec["doc"] = {k: tidy(str(doc.get(k) or "")) for k in ("kind", "title", "date", "notes")}
    if rec["doc"]["kind"] not in DOC_KINDS:
        rec["doc"]["kind"] = "other" if rec["doc"]["kind"] else "term_sheet"
    fields = rec.get("fields") if isinstance(rec.get("fields"), dict) else {}
    clean: dict[str, dict] = {}
    for fid in FIELD_IDS:
        f = fields.get(fid) if isinstance(fields.get(fid), dict) else {}
        raw_lines = f.get("lines")
        if isinstance(raw_lines, str):
            raw_lines = raw_lines.split("\n")
        lines = [tidy(str(x)) for x in (raw_lines or []) if tidy(str(x))][:MAX_LINES]
        status = f.get("status") if f.get("status") in STATUSES else ("stated" if lines else "not_stated")
        if not lines:
            lines, status = [NOT_STATED], "not_stated"
        evidence = []
        for e in f.get("evidence") or []:
            if not isinstance(e, dict):
                continue
            quote = tidy(str(e.get("quote") or ""))
            page = e.get("page")
            if isinstance(page, str) and page.strip().isdigit():
                page = int(page)
            if quote:
                item = {"quote": quote, "page": page if isinstance(page, int) and not isinstance(page, bool) else None}
                for extra in ("found", "found_on"):
                    if extra in e:
                        item[extra] = e[extra]
                evidence.append(item)
        clean[fid] = {"lines": lines, "status": status, "evidence": evidence, "note": tidy(str(f.get("note") or ""))}
    rec["fields"] = clean
    return rec


def validate(record: dict) -> list[str]:
    """Problems that make a record unfit to print, as readable messages (empty list = fine)."""
    problems: list[str] = []
    if not isinstance(record, dict):
        return ["record is not an object"]
    fields = record.get("fields")
    if not isinstance(fields, dict):
        return ["record has no 'fields' object"]
    for fid in FIELD_IDS:
        f = fields.get(fid)
        if not isinstance(f, dict):
            problems.append(f"{fid}: missing")
            continue
        lines = f.get("lines")
        if not isinstance(lines, list) or not lines or not all(isinstance(x, str) and x.strip() for x in lines):
            problems.append(f"{fid}: 'lines' must be a non-empty list of non-empty strings")
            continue
        if len(lines) > MAX_LINES:
            problems.append(f"{fid}: {len(lines)} lines (maximum {MAX_LINES})")
        for i, line in enumerate(lines, 1):
            if len(line) > MAX_LINE_CHARS:
                problems.append(f"{fid}: line {i} is {len(line)} characters (maximum {MAX_LINE_CHARS})")
        status = f.get("status")
        if status not in STATUSES:
            problems.append(f"{fid}: status {status!r} is not one of {', '.join(STATUSES)}")
        evidence = f.get("evidence")
        if not isinstance(evidence, list):
            problems.append(f"{fid}: 'evidence' must be a list")
            continue
        if len(evidence) > MAX_EVIDENCE:
            problems.append(f"{fid}: {len(evidence)} evidence quotes (maximum {MAX_EVIDENCE})")
        for i, e in enumerate(evidence, 1):
            if not isinstance(e, dict) or not isinstance(e.get("quote"), str) or not e["quote"].strip():
                problems.append(f"{fid}: evidence {i} has no quote")
                continue
            if not isinstance(e.get("page"), int) or isinstance(e.get("page"), bool) or e["page"] < 1:
                problems.append(f"{fid}: evidence {i} has no valid page number")
            if len(e["quote"]) > MAX_QUOTE_CHARS:
                problems.append(f"{fid}: evidence {i} quote is {len(e['quote'])} characters (maximum {MAX_QUOTE_CHARS})")
            if re.search(r"\.\.\.|…", e["quote"]) :
                problems.append(f"{fid}: evidence {i} quote contains an ellipsis; quotes must be contiguous")
        if status in ("stated", "by_reference") and not evidence:
            problems.append(f"{fid}: status {status} needs at least one evidence quote")
        if status == "not_stated" and evidence and fid not in ("lender_commitments", "jurisdiction_topco", "guarantor_coverage"):
            problems.append(f"{fid}: status not_stated should carry no evidence")
    for fid in fields:
        if fid not in BY_ID:
            problems.append(f"{fid}: unknown field id")
    return problems


def check_evidence(record: dict, doc: Doc) -> dict:
    """Look up every quote in the PDF text and mark it (``found``: exact / loose / other_page / missing).

    Returns the tally: {"total", "exact", "loose", "other_page", "missing", "problems": [...]}.
    """
    tally = {"total": 0, "exact": 0, "loose": 0, "other_page": 0, "missing": 0, "problems": []}
    for fid in FIELD_IDS:
        f = record["fields"].get(fid) or {}
        for e in f.get("evidence") or []:
            grade, pages = doc.locate(e.get("quote") or "", e.get("page"))
            e["found"] = grade
            if grade == "other_page":
                e["found_on"] = pages
            else:
                e.pop("found_on", None)
            tally["total"] += 1
            tally[grade] += 1
            if grade in ("other_page", "missing"):
                where = f" (it is on page {', '.join(map(str, pages))})" if pages else ""
                tally["problems"].append(f"{fid}: quote not found on page {e.get('page')}{where}: {e.get('quote', '')[:110]!r}")
    return tally
