"""Write the text of a term sheet PDF, page by page, as the tool reads it.

    python -m kct.dump "..\\Hackathon (CA and TS)\\Seadrill 2026 TS.pdf" --out seadrill.txt

Useful for seeing exactly what the rules engine and the quote check work from.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pdftext


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, help="write to this file instead of the screen")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)
    pages, meta = pdftext.extract_pages(args.pdf, use_cache=not args.no_cache)
    text = pdftext.with_page_markers(pages)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.pdf.name}: {meta['pages']} pages, {meta['chars']:,} characters -> {args.out}")
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
