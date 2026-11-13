"""Persist and load reconciliation results (one JSON file per deal per engine)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import CHECKLIST_NAMES, RESULTS_DIR, STATUSES
from .inventory import Deal


def slug(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").lower()


def _engine_dir(engine: str) -> Path:
    d = RESULTS_DIR / engine
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(engine: str, deal: Deal, payload: dict) -> Path:
    payload = dict(payload)
    payload.setdefault("generated_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    payload.update(engine=engine, deal=deal.key, ts_file=deal.ts.name if deal.ts else None, ca_file=deal.ca.name if deal.ca else None)
    path = _engine_dir(engine) / f"{slug(deal.key)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_all(engine: str, deals: dict[str, Deal]) -> dict[str, dict]:
    """Results for an engine keyed by inventory deal key (matched by file names, then by deal name)."""
    out: dict[str, dict] = {}
    by_file = {}
    for k, d in deals.items():
        for p in (d.ts, d.ca):
            if p:
                by_file[p.name.lower()] = k
    for f in sorted(_engine_dir(engine).glob("*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8-sig"))  # tolerate a BOM written by Windows tools
        except (OSError, json.JSONDecodeError):
            continue
        key = by_file.get((payload.get("ts_file") or "").lower()) or by_file.get((payload.get("ca_file") or "").lower())
        if not key:
            key = next((k for k in deals if slug(k) == slug(payload.get("deal", ""))), None)
        if not key:
            continue
        # Only show a result for the document pair it was produced from.
        d = deals[key]
        if (payload.get("ts_file") and d.ts and payload["ts_file"].lower() != d.ts.name.lower()) or (
                payload.get("ca_file") and d.ca and payload["ca_file"].lower() != d.ca.name.lower()):
            continue
        out[key] = payload
    return out


def import_workflow_output(raw: dict | list, deals: dict[str, Deal], unmatched: list[str] | None = None) -> list[str]:
    """Import the agent-verified reconciliation (workflow output) into results/verified/.

    Accepts the workflow's {"result": [...]} envelope or the bare list of
    {deal, group, ts_file, ca_file, result: {rows, ...}} blocks."""
    blocks = raw.get("result", raw) if isinstance(raw, dict) else raw
    merged: dict[str, dict] = {}
    by_file = {}
    for k, d in deals.items():
        for p in (d.ts, d.ca):
            if p:
                by_file[p.name.lower()] = k
    for b in blocks:
        if not b or not b.get("result"):
            continue
        key = by_file.get((b.get("ts_file") or "").lower()) or by_file.get((b.get("ca_file") or "").lower())
        if not key:  # fall back to the block's deal name
            name = slug(b.get("deal") or "").replace("_", "")
            key = next((k for k in deals if slug(k).replace("_", "") == name), None)
        if not key:
            if unmatched is not None:
                unmatched.append(f"{b.get('deal')} (group {b.get('group')})")
            continue
        r = b["result"]
        stage = b.get("stage", "verified")
        m = merged.setdefault(key, {"rows": [], "document_notes": [], "corrections": [], "confidence": []})
        m["rows"].extend(dict(row, stage=stage) for row in r.get("rows", []))
        if r.get("document_notes"):
            m["document_notes"].append(r["document_notes"])
        m["corrections"].extend(r.get("corrections", []))
        m["confidence"].append(f"group {b.get('group')}: " + ("re-checked by verifier, confidence " + str(r.get('confidence', 'n/a'))
                                                              if stage == "verified" else "first pass, not yet re-checked"))
    written = []
    for key, m in merged.items():
        m["rows"].sort(key=lambda r: (r["id"][0] not in "AB", r["id"]))
        payload = {
            "rows": m["rows"],
            "document_notes": "\n\n".join(dict.fromkeys(m["document_notes"])),
            "corrections": m["corrections"],
            "confidence": "; ".join(m["confidence"]),
            "source": "Claude Code multi-agent workflow: independent reconciler + adversarial verifier per attribute group",
        }
        save("verified", deals[key], payload)
        written.append(key)
    return written


def status_counts(payload: dict | None) -> dict[str, int]:
    counts = {s: 0 for s in STATUSES}
    for r in (payload or {}).get("rows", []):
        counts[r.get("status", "review")] = counts.get(r.get("status", "review"), 0) + 1
    return counts


def attribute_label(row: dict) -> str:
    rid = row.get("id", "")
    name = CHECKLIST_NAMES.get(rid) or row.get("attribute", "")
    return f"{rid} · {name}" if rid else name
