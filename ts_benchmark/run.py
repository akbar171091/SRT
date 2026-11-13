"""Term sheet benchmark: pricing and financial covenants across a folder of term sheet PDFs.

    python run.py                          start the local web front end and open it in the browser
    python run.py --docs "C:\\path\\to\\pdfs"   benchmark another folder
    python run.py --export report.html     write the front end as one self-contained HTML file and exit
    python run.py --csv out_folder         write the CSV extracts and exit

Term sheets are the PDFs whose file name carries a standalone "TS" (e.g. "Accenture 2026 TS.pdf").
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tsbench import exports, server  # noqa: E402
from tsbench.config import DEFAULT_DOCS_DIR, DEFAULT_PORT  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark pricing and financial covenants across term sheet PDFs.")
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS_DIR, help=f"folder holding the term sheet PDFs (default: {DEFAULT_DOCS_DIR})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port for the local web server (default: {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--no-cache", action="store_true", help="re-read every PDF instead of using cached page text")
    parser.add_argument("--rules-only", action="store_true", help="ignore verified records and show the rules engine output for every document")
    parser.add_argument("--export", type=Path, metavar="FILE.html", help="write a self-contained HTML report and exit")
    parser.add_argument("--csv", type=Path, metavar="FOLDER", help="write the CSV extracts into FOLDER and exit")
    args = parser.parse_args(argv)

    if not args.docs.is_dir():
        print(f"Folder not found: {args.docs}", file=sys.stderr)
        return 2
    app = server.App(args.docs, use_cache=not args.no_cache, use_verified=not args.rules_only)
    print(f"Reading term sheets in {args.docs}")
    data = app.build(progress=lambda msg: print("  " + msg, flush=True))
    meta = data["meta"]
    if not meta["n_deals"]:
        print('No term sheet PDFs found (looking for a standalone "TS" in the file name).', file=sys.stderr)
        return 1
    print(f"{meta['n_deals']} term sheets: {meta['n_verified']} from AI-audited records, {meta['n_rules']} from the rules engine alone"
          + (f" ({meta['n_unreadable']} could not be read)." if meta["n_unreadable"] else "."))
    for problem in meta["problems"]:
        print("  note: " + problem)

    if args.export or args.csv:
        if args.export:
            args.export.parent.mkdir(parents=True, exist_ok=True)
            args.export.write_text(exports.static_html(data), encoding="utf-8")
            print(f"Wrote {args.export.resolve()}")
        if args.csv:
            args.csv.mkdir(parents=True, exist_ok=True)
            for name, make in exports.CSV_EXPORTS.items():
                (args.csv / name).write_text(make(data), encoding="utf-8", newline="")
                print(f"Wrote {(args.csv / name).resolve()}")
        return 0

    httpd = server.serve(app, args.port)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    if port != args.port:
        print(f"\nPort {args.port} is in use (another copy of this tool may still be running); using port {port} instead.")
    print(f"\nBenchmark front end: {url}\nPress Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
