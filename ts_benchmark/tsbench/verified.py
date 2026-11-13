"""Verified reference records, and the check that ties every quoted value back to the PDF text.

A verified file (``data/verified/<slug>.json``) holds one term sheet record that was extracted and
then independently re-checked against the document, pinned to the SHA-1 of the PDF it was read
from. It is used only while that exact file is in the folder: if the PDF is replaced by a new
version, the record is reported as stale and the rules engine output is shown instead.

Whatever the source of a record, ``check_evidence`` looks up each of its quotes in the text of the
PDF as it is today and marks it found or not found, so the front end can show which figures are
traceable to the page.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import schema
from .textmodel import Doc


@dataclass
class Verified:
    record: dict
    sha1: str
    source_file: str
    verified_on: str = ""
    method: str = ""
    notes: list[str] = field(default_factory=list)
    path: Path | None = None


def load_all(folder: Path) -> tuple[list[Verified], list[str]]:
    """Every readable verified file in ``folder``, plus a message for each file that could not be used."""
    out: list[Verified] = []
    problems: list[str] = []
    if not folder.is_dir():
        return out, problems
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = data["record"]
            for key in ("facilities", "pricing", "financial_covenants", "borrower", "security", "credit_profile", "doc"):
                record[key]  # noqa: B018 - a missing section makes the file unusable
            schema.derive(record)  # a record the benchmark cannot work with is rejected here, by file name
            out.append(Verified(record=record, sha1=data["sha1"], source_file=data["source_file"], verified_on=data.get("verified_on", ""),
                                method=data.get("method", ""), notes=list(data.get("notes", [])), path=path))
        except Exception as exc:  # whatever is wrong with one file, the others are still used
            problems.append(f"{path.name}: not usable ({type(exc).__name__}: {exc})")
    return out, problems


def find(verified: list[Verified], file_name: str, sha1: str) -> tuple[Verified | None, str | None]:
    """(record, status): status is "current" for an exact file match, "stale" when only the file name matches."""
    for v in verified:
        if v.sha1 == sha1:
            return v, "current"
    for v in verified:
        if v.source_file.strip().lower() == file_name.strip().lower():
            return v, "stale"
    return None, None


def _items(record: dict):
    """Every (label, holder, page) in a record that carries a quote."""
    yield "Borrower", record["borrower"], record["borrower"].get("page")
    yield "Security", record["security"], record["security"].get("page")
    for f in record["facilities"]:
        yield f"Facility {f['id']}", f, f.get("page")
    pricing = record["pricing"]
    yield "Credit spread adjustment", pricing["csa"], pricing["csa"].get("page")
    yield "Benchmark floor", pricing["floor"], pricing["floor"].get("page")
    for g in pricing["grids"]:
        for t in g["tiers"]:
            yield f"{g['name']}: tier {t['level']}", t, g.get("page")
    for f in pricing["fees"]:
        yield f"Fee: {f['description'][:60] or f['type']}", f, f.get("page")
    for c in record["financial_covenants"]:
        yield f"Covenant: {c['name'][:60] or c['type']}", c, c.get("page")


def check_evidence(record: dict, doc: Doc) -> dict:
    """Mark each quote in ``record`` as found on its page (``quote_ok``) and return the tally."""
    total = found = 0
    missing: list[dict] = []
    for label, holder, page in _items(record):
        quote = holder.get("quote") or ""
        if not quote.strip():
            holder["quote_ok"] = None
            continue
        total += 1
        ok = doc.has_quote(quote, page)
        elsewhere = [] if ok else doc.find_quote(quote)
        holder["quote_ok"] = ok
        if ok:
            found += 1
        else:
            missing.append({"item": label, "page": page, "found_on": elsewhere, "quote": quote[:160]})
    return {"total": total, "found": found, "missing": missing}
