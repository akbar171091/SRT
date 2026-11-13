"""Command-line runner (no UI): reconcile every TS/CA pair and print a summary.

Examples:
  python run_checks.py                         # rules engine on every complete deal
  python run_checks.py --engine claude --deal "Capri 2026"
  python run_checks.py --import-verified data/verified_reconciliation.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from recon import inventory, pdftext, quotes, results, rules
from recon.config import DEFAULT_DOCS_DIR, UPLOAD_DIR


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", type=Path, default=DEFAULT_DOCS_DIR, help="folder of CA/TS PDFs")
    ap.add_argument("--engine", choices=["rules", "claude"], default="rules")
    ap.add_argument("--deal", action="append", help="limit to these deal names (repeatable)")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh"])
    ap.add_argument("--import-verified", type=Path, help="import a multi-agent workflow output JSON instead of running")
    args = ap.parse_args()

    deals, unclassified = inventory.scan([args.docs, UPLOAD_DIR])
    print(f"Found {len(deals)} deal(s) in {args.docs}")
    for d in deals.values():
        flag = "OK " if d.status == "complete" else "!! "
        print(f"  {flag}{d.key:<32} CA: {d.ca.name if d.ca else 'MISSING':<36} TS: {d.ts.name if d.ts else 'MISSING'}")
    for p in unclassified:
        print(f"  ?? unclassified file: {p.name}")

    if args.import_verified:
        unmatched: list[str] = []
        written = results.import_workflow_output(json.loads(args.import_verified.read_text(encoding="utf-8-sig")), deals, unmatched)
        for u in unmatched:
            print(f"  !! could not match result block to a deal: {u}")
        for k in written:
            p = results.load_all("verified", {k: deals[k]})[k]
            p["quote_check"] = quotes.verify_rows(p["rows"], pdftext.extract_pages(deals[k].ts), pdftext.extract_pages(deals[k].ca))
            results.save("verified", deals[k], p)
            print(f"  imported {k}: {len(p['rows'])} rows, quotes {p['quote_check']}")
        return 0

    wanted = {w.lower() for w in (args.deal or [])}
    unknown = wanted - {k.lower() for k in deals}
    if unknown:
        print(f"Unknown deal(s): {', '.join(sorted(unknown))}. Known: {', '.join(deals)}")
        return 2
    targets = [d for d in deals.values() if d.status == "complete" and (not wanted or d.key.lower() in wanted)]
    failures = 0
    for d in targets:
        try:
            ts_p, ca_p = pdftext.extract_pages(d.ts), pdftext.extract_pages(d.ca)
            if args.engine == "rules":
                payload = {"rows": rules.check_deal(ts_p, ca_p, pdftext.extract_layout(d.ts)), "trace": rules.trace_figures(ts_p, ca_p),
                           "document_notes": ("The term sheet file looks like a lender presentation or slides rather than a formal "
                                              "term sheet; expect more 'review' flags.") if pdftext.looks_like_presentation(ts_p) else ""}
            else:
                from recon import llm
                payload = llm.reconcile_deal(ts_p, ca_p, d.key, effort=args.effort, progress=print)
            payload["quote_check"] = quotes.verify_rows(payload["rows"], ts_p, ca_p)
            results.save(args.engine, d, payload)
            counts = {k: v for k, v in results.status_counts(payload).items() if v}
            print(f"  {d.key:<32} {counts}")
        except Exception as e:  # one failing deal must not stop the batch
            failures += 1
            print(f"  !! {d.key}: {type(e).__name__}: {e}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
