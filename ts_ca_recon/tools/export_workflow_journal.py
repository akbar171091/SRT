"""Build an importable reconciliation JSON from a (possibly still running) multi-agent workflow journal.

For every deal/attribute group, the adversarially verified rows are used when the verifier has finished,
otherwise the reconciler's first-pass rows. Each block records which stage it came from.

Usage: python tools/export_workflow_journal.py <journal.jsonl> <out.json> [extra_journal.jsonl ...]

Extra journals (e.g. follow-up runs that re-checked the remaining groups) override first-pass rows.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Workflow deal labels -> document file names (as used by the reconciliation workflow script).
DEALS = {
    "Accenture 2026": ("Accenture  2026 TS.pdf", "Accenture  2026 CA.pdf"),
    "Aon 2026": ("AON 2026 TS.pdf", "AON 2026 CA.pdf"),
    "APi Group 2026": ("APi Group 2026 TS.pdf", "APi Group 2026 CA.pdf"),
    "Capri 2026": ("Capri 2026 TS.pdf", "Capri 2026 CA.pdf"),
    "Carnival Corp 2025": ("Carnival Corp 2025 TS.pdf", "Carnival Corp 2025 CA.pdf"),
    "Delta Air Lines 2026": ("Delta Airlines 2026 TS .pdf", "Delta Airlines 2026 CA .pdf"),
    "Duke Energy 2025": ("Duke Energy 2025 TS.pdf", "Duke Energy 2025 CA.pdf"),
    "Encompass Health 2026": ("Encompass Health 2026 TS.pdf", "Encompass Health 2026 CA.pdf"),
    "Fluence 2026": ("Fluence 2026 TS.pdf", "Fluence 2026 CA.pdf"),
    "Granite Construction 2025": ("Granite Construction 2025 TS.pdf", "Granite Construction 2025 CA.pdf"),
    "Honeywell 364-day 2026": ("Honeywell 364day 2026 TS.pdf", "Honeywell 364day 2026 CA.pdf"),
    "Honeywell 5-year 2026": ("Honeywell 5yr TS.pdf", "Honeywell 5yr CA.pdf"),
    "Quaker Chemical 2026": ("Quaker Chemical 2026 TS.pdf", "Quaker Chemical 2026 CA.pdf"),
    "Seadrill 2026": ("Seadrill 2026 TS.pdf", "Seadrill 2026 CA.pdf"),
}


def _read(journal: Path) -> list[tuple[str, dict]]:
    labels, res = {}, {}
    for line in journal.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "started":
            labels[ev["key"]] = ev.get("label", "")
        elif ev.get("type") == "result":
            res[ev["key"]] = ev.get("result")
    return [(labels.get(k, ""), v) for k, v in res.items()]


def main(journal: Path, out: Path, extra: list[Path] | None = None) -> int:
    stages: dict[tuple[str, str], dict] = {}
    for j in [journal, *(extra or [])]:
        for label, value in _read(j):
            if not value or ":" not in label:
                continue
            stage, deal, group = label.split(":", 2)
            stages.setdefault((deal, group), {})[stage] = value
    blocks, summary = [], {"verified": 0, "first_pass": 0}
    for (deal, group), st in sorted(stages.items()):
        if deal not in DEALS:
            continue
        ts, ca = DEALS[deal]
        if "verify" in st:
            result, stage = st["verify"], "verified"
        else:
            result = dict(st["recon"], corrections=[], confidence="not yet re-checked")
            stage = "first_pass"
        summary[stage] += 1
        blocks.append({"deal": deal, "group": group, "ts_file": ts, "ca_file": ca, "stage": stage, "result": result})
    out.write_text(json.dumps({"result": blocks, "summary": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(blocks)} group results to {out}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]), [Path(a) for a in sys.argv[3:]]))
