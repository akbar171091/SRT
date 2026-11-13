"""Build the benchmark dataset: scan the folder, read each term sheet, derive comparable figures.

For each term sheet PDF:

1. extract the page text (cached by file hash);
2. run the rules engine on it;
3. if a verified record exists for exactly this file, use it as the record and keep the rules
   engine output only to report how well the two agree; otherwise use the rules engine output;
4. check every quote in the record against the page text;
5. derive the comparable figures.

Then compute the peer statistics. One document that cannot be read, or one reference record that
cannot be used, never stops the others: it is listed with the reason.
"""
from __future__ import annotations

import copy
import math
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import __version__, benchmark, compare, inventory, pdftext, rules, schema, verified
from .config import (COVENANT_FAMILIES, COVENANT_TYPES, FACILITY_TYPES, FEE_TYPES, PRICING_BASIS, VERIFIED_DIR)
from .textmodel import Doc

_NO_META = {"sha1": "", "pages": 0, "no_text": True, "plain_pages": [], "thin_pages": []}
_NO_EVIDENCE = {"total": 0, "found": 0, "missing": []}


def _empty_record(deal: str, file_name: str, reason: str) -> dict:
    blank = {"quote": "", "page": None}
    return {
        "deal": deal, "source_file": file_name,
        "doc": {"kind": "other", "title": "", "date": None, "is_amendment": False, "notes": reason},
        "borrower": {"name": deal, **blank},
        "credit_profile": {"value": "unclear", "basis": reason},
        "security": {"value": "unclear", "detail": "", **blank},
        "facilities": [],
        "pricing": {"benchmark": "", "basis": "not_stated", "basis_detail": "",
                    "csa": {"applies": None, "bps": None, "detail": "", **blank},
                    "floor": {"pct": None, "detail": "", **blank}, "grids": [], "fees": [], "change_vs_existing": None, "notes": ""},
        "financial_covenants": [], "no_financial_covenant_note": reason, "format_notes": "",
    }


def _reason(exc: Exception) -> str:
    """Why a file could not be read, without the local path that an operating system error message carries."""
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    return str(exc) or type(exc).__name__


def _finite(value, dropped: list[int]):
    """A copy of ``value`` with every non-finite number replaced by None (JSON cannot carry them)."""
    if isinstance(value, float) and not math.isfinite(value):
        dropped[0] += 1
        return None
    if isinstance(value, dict):
        return {k: _finite(v, dropped) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v, dropped) for v in value]
    return value


def build(docs_dir: Path, use_cache: bool = True, use_verified: bool = True,
          progress: Callable[[str], None] | None = None) -> dict:
    say = progress or (lambda _msg: None)
    docs_dir = Path(docs_dir)
    files = inventory.scan(docs_dir)
    references, problems = verified.load_all(VERIFIED_DIR) if use_verified else ([], [])
    deals: list[dict] = []
    seen: dict[str, str] = {}  # file hash -> first file name carrying it
    for i, ts in enumerate(files, 1):
        say(f"[{i}/{len(files)}] {ts.name}")
        notes: list[str] = []
        try:
            pages, meta = pdftext.extract_pages(ts.path, use_cache=use_cache)
        except Exception as exc:  # an unreadable or encrypted PDF must not stop the other documents
            reason = f"The PDF could not be read: {_reason(exc)}"
            deals.append(_deal(ts, _NO_META, _empty_record(ts.deal, ts.name, reason), "rules", None, None, None, _NO_EVIDENCE, [reason]))
            continue
        if meta["sha1"] in seen:  # the same file saved twice would give one deal two votes in every statistic
            problems.append(f"{ts.name}: an identical copy of {seen[meta['sha1']]}; left out so the deal is counted once")
            continue
        seen[meta["sha1"]] = ts.name
        doc = Doc(pages)
        if meta["no_text"]:
            notes.append("This PDF has no text layer (it is a scan). Nothing can be read from it without OCR.")
        engine_notes: list[str] = []
        try:
            rules_record = rules.extract(pages, ts.deal, ts.name)
            engine_notes = rules_record.get("_engine", {}).get("notes", [])
        except Exception:
            rules_record = _empty_record(ts.deal, ts.name, "The rules engine failed on this document.")
            notes.append("Rules engine error: " + traceback.format_exc(limit=2).strip().splitlines()[-1])
        rules_record = {k: v for k, v in rules_record.items() if not k.startswith("_")}

        reference, status = verified.find(references, ts.name, meta["sha1"])
        deal = None
        if reference is not None and status == "current":
            try:
                record = copy.deepcopy(reference.record)
                deal = _deal(ts, meta, record, "verified", status, reference, compare.compare(record, rules_record),
                             verified.check_evidence(record, doc), notes)
            except Exception as exc:  # a reference record of the wrong shape: show the rules reading and say why
                status = "unusable"
                where = reference.path.name if reference.path else ts.name
                problems.append(f"{where}: the audited record could not be used ({type(exc).__name__}: {exc}); "
                                f"the rules engine output is shown for {ts.name}")
                notes.append("The audited record for this file could not be used, so the rules engine output is shown instead.")
        if deal is None:
            notes += engine_notes  # what the rules engine could not find matters only when its output is what is shown
            if status == "stale":
                notes.append("An audited record exists for an earlier version of this file. The PDF has changed since, "
                             "so the rules engine output is shown instead.")
            try:
                deal = _deal(ts, meta, rules_record, "rules", status, reference, None, verified.check_evidence(rules_record, doc), notes)
            except Exception:
                reason = "The rules engine output for this document could not be used."
                notes.append(reason + " " + traceback.format_exc(limit=2).strip().splitlines()[-1])
                deal = _deal(ts, meta, _empty_record(ts.deal, ts.name, reason), "rules", status, reference, None, _NO_EVIDENCE, notes)
        deals.append(deal)

    scored = [d["qa"]["summary"] for d in deals if d["qa"]]
    totals = {k: sum(s[k] for s in scored) for k in ("match", "mismatch", "missed", "extra")}
    judged = totals["match"] + totals["mismatch"] + totals["missed"]
    return {
        "meta": {
            "version": __version__,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "docs_dir": str(docs_dir),
            "n_deals": len(deals),
            "n_verified": sum(1 for d in deals if d["source"] == "verified"),
            "n_rules": sum(1 for d in deals if d["source"] == "rules"),
            "n_unreadable": sum(1 for d in deals if not d["readable"]),
            "static": False,
            "problems": problems,
        },
        "vocab": {
            "facility_types": FACILITY_TYPES,
            "fee_types": FEE_TYPES,
            "covenant_types": {k: {"label": v[0], "family": v[1], "direction": v[2], "unit": v[3]} for k, v in COVENANT_TYPES.items()},
            "covenant_families": COVENANT_FAMILIES,
            "pricing_basis": PRICING_BASIS,
            "metrics": benchmark.metric_vocab(),
        },
        "deals": deals,
        "benchmarks": benchmark.presets(deals),
        "qa": {**totals, "documents": len(scored), "agreement": round(totals["match"] / judged, 4) if judged else None},
    }


def _deal(ts, meta, record, source, status, reference, qa, evidence, notes) -> dict:
    dropped = [0]
    record = _finite(record, dropped)
    notes = list(notes)
    if dropped[0]:
        notes.append(f"{dropped[0]} value(s) in this document were not usable numbers and were left out.")
    current = reference is not None and status == "current"
    return {
        "id": ts.slug,
        "deal": ts.deal,
        "file": ts.name,
        "path": str(ts.path),
        "pages": meta["pages"],
        "sha1": meta["sha1"],
        "plain_pages": meta["plain_pages"],
        # False when nothing could be read from the file: such a document is listed but never benchmarked
        "readable": meta["pages"] > 0 and not meta["no_text"],
        "source": source,
        "verified_status": status,
        "verified_on": reference.verified_on if reference is not None else None,
        "verified_method": reference.method if current else None,
        "verified_notes": reference.notes if current else [],
        "record": record,
        "derived": schema.derive(record),
        "evidence": evidence,
        "qa": qa,
        "notes": notes,
    }
