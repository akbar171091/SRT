"""Check a Key Credit Terms record against its term sheet.

    python -m kct.check record.json --pdf "..\\Hackathon (CA and TS)\\Seadrill 2026 TS.pdf"

Validates the structure of the record and looks up every evidence quote in the text of the PDF.
Exit code 0 when the record is well formed and every quote is found on the page it cites.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import pdftext, schema
from .textmodel import Doc


def check_file(record_path: Path, pdf_path: Path, verbose: bool = True) -> tuple[bool, dict]:
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    problems = schema.validate(record)
    pages, meta = pdftext.extract_pages(pdf_path)
    if record.get("sha1") and record["sha1"] != meta["sha1"]:
        problems.append(f"sha1 in the record ({record['sha1'][:12]}...) is not the sha1 of {Path(pdf_path).name} ({meta['sha1'][:12]}...)")
    tally = schema.check_evidence(record, Doc(pages)) if isinstance(record.get("fields"), dict) and not any(
        p.endswith(": missing") for p in problems) else {"total": 0, "exact": 0, "loose": 0, "other_page": 0, "missing": 0, "problems": []}
    ok = not problems and not tally["problems"]
    if verbose:
        print(f"{Path(record_path).name}: structure {'OK' if not problems else 'PROBLEMS'}; quotes {tally['exact']} exact, "
              f"{tally['loose']} loose, {tally['other_page']} on another page, {tally['missing']} missing (of {tally['total']})")
        for p in problems:
            print(f"  STRUCTURE  {p}")
        for p in tally["problems"]:
            print(f"  QUOTE      {p}")
    return ok, {"structure": problems, "quotes": tally}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("record", type=Path, help="record JSON file")
    ap.add_argument("--pdf", type=Path, required=True, help="the term sheet PDF the record was read from")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ok, _ = check_file(args.record, args.pdf)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
