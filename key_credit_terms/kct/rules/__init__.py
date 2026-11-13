"""The offline rules engine: pattern matching on the text of a term sheet.

    extract(pages, client, source_file) -> {"doc": {...}, "fields": {field id: entry}}

Each field has one rule (a function of the document context) in one of the modules below. A rule
that finds nothing returns "not stated"; a rule that fails is caught and reported in the field's
note, so one awkward document never stops the run.

The rules read labelled sections ("Financial Covenants:", "Assignments and Participations:") and
recognise the wording US and LMA-style term sheets use. They are deterministic and send nothing
anywhere, but they do not understand a document the way a reader does: treat their output as a
first read. Every stated line carries a quote that is verifiably on the page it cites.
"""
from __future__ import annotations

import re

import importlib
import warnings

from ..fields import FIELD_IDS
from ..textmodel import tidy
from .common import Ctx, not_stated

MODULE_NAMES = ("facility", "support", "fincov", "negcov", "terms")
MODULES = []
RULES: dict = {}
for _name in MODULE_NAMES:
    try:
        _module = importlib.import_module(f"{__name__}.{_name}")
    except Exception as _exc:  # one broken rule module must not take the others down
        warnings.warn(f"rule module {_name!r} could not be loaded ({type(_exc).__name__}: {_exc}); its rows will read 'not stated'")
        continue
    MODULES.append(_module)
    RULES.update(_module.RULES)

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE_RE = re.compile(rf"\b(?:(?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}|(?:{_MONTHS})\s+\d{{4}}|\d{{1,2}}\s?/\s?\d{{1,2}}\s?/\s?\d{{2,4}})\b")
_TITLE_RE = re.compile(r"summary\s+of\s+(?:principal\s+|indicative\s+)?terms(?:\s+and\s+conditions)?|term\s+sheet|lender\s+presentation|"
                       r"executive\s+summary|transaction\s+summary|commitment\s+letter", re.IGNORECASE)


def doc_info(ctx: Ctx) -> dict:
    """What kind of document this is, its title and date, from the first pages."""
    head = "\n".join(ctx.raw.pages[:2])
    title_m = _TITLE_RE.search(head)
    title = tidy(title_m.group(0)).title() if title_m else ""
    date_m = _DATE_RE.search(head)
    low = head.lower()
    if ctx.split_pages or "lender presentation" in low:
        kind = "lender_presentation"
    elif "commitment letter" in low:
        kind = "commitment_letter_term_sheet"
    elif len(ctx.raw.pages) <= 2 or "executive summary" in low:
        kind = "summary"
    else:
        kind = "term_sheet"
    notes = [f"Read by the rules engine from {len(ctx.raw.pages)} page(s) of text."]
    if ctx.split_pages:
        pages = ", ".join(str(p) for p in sorted(ctx.split_pages))
        notes.append(f"Page(s) {pages} print existing and proposed terms side by side; the proposed column was read.")
    if re.search(r"Existing\s+Credit\s+Agreement|Existing\s+[\w\- ]{0,20}Agreement", head):
        notes.append("The document refers to an existing credit agreement for terms it does not restate.")
    return {"kind": kind, "title": title, "date": tidy(date_m.group(0)) if date_m else "", "notes": " ".join(notes)}


def extract(pages: list[str], client: str = "", source_file: str = "") -> dict:
    ctx = Ctx(pages, client, source_file)
    fields: dict[str, dict] = {}
    for fid in FIELD_IDS:
        rule = RULES.get(fid)
        try:
            entry = rule(ctx) if rule else not_stated()
        except Exception as exc:  # a rule must never take the run down
            entry = not_stated(note=f"The rule for this row failed ({type(exc).__name__}: {exc}).")
        fields[fid] = entry
    return {"doc": doc_info(ctx), "fields": fields}
