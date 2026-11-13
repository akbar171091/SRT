#!/usr/bin/env python3
"""Populate the Key Credit Terms appendix (Key_Credit_Terms.docx) from term sheet PDFs.

    python populate_key_credit_terms.py "Seadrill 2026 TS.pdf"     ->  output\\Key_Credit_Terms_Seadrill.docx
    python populate_key_credit_terms.py Seadrill "Duke Energy"     pick term sheets by client name
    python populate_key_credit_terms.py                            every term sheet in the documents folder
    python populate_key_credit_terms.py --list                     show what would be produced, write nothing

A term sheet is a PDF with a standalone "TS" in its name ("Seadrill 2026 TS.pdf"). Inputs can be PDF
paths, folders, file names inside the documents folder, or client names.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kct import config, naming, pipeline, records, template  # noqa: E402

ENGINE_HELP = """\
where the content comes from:
  auto        (default) the audited record for this exact PDF if there is one; otherwise Claude through the
              Anthropic API if credentials are present; otherwise the rules engine
  audited     only the audited records in data/audited (fails for a PDF that has none)
  rules       the offline rules engine: pattern matching on the PDF text, nothing leaves the machine
  claude      Claude: through the API if credentials are present, otherwise through Claude Code
  claude-api  Claude through the Anthropic API (ANTHROPIC_API_KEY or an `ant auth login` profile)
  claude-cli  Claude through the Claude Code command line (uses its login; no API key needed)
"""


def resolve_inputs(inputs: list[str], docs_dir: Path) -> tuple[list[Path], list[str]]:
    """Turn what was typed into PDF paths. Returns (paths, messages for inputs that matched nothing)."""
    paths: list[Path] = []
    problems: list[str] = []
    available: list[Path] | None = None

    def in_docs() -> list[Path]:
        nonlocal available
        if available is None:
            available = naming.scan(docs_dir) if docs_dir.is_dir() else []
        return available

    def add(p: Path) -> None:
        p = p.resolve()
        if p not in paths:
            paths.append(p)

    if not inputs:
        if not docs_dir.is_dir():
            return [], [f"Documents folder not found: {docs_dir}"]
        for p in in_docs():
            add(p)
        if not paths:
            problems.append(f"No term sheet PDFs (a standalone 'TS' in the file name) in {docs_dir}")
        return paths, problems

    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            found = naming.scan(p)
            if not found:
                problems.append(f"No term sheet PDFs in {p}")
            for f in found:
                add(f)
            continue
        candidates = [p, docs_dir / raw, docs_dir / f"{raw}.pdf", Path(f"{raw}.pdf")]
        hit = next((c for c in candidates if c.is_file()), None)
        if hit is not None:
            if hit.suffix.lower() != ".pdf":
                problems.append(f"{hit.name} is not a PDF")
            else:
                add(hit)
            continue
        key = naming.slugify(raw)
        exact = [f for f in in_docs() if key in {naming.slugify(naming.client_name(f.stem)), naming.slugify(naming.deal_name(f.stem)), naming.slugify(f.stem)}]
        partial = exact or [f for f in in_docs() if key and key in naming.slugify(f.stem)]
        if len(partial) == 1:
            add(partial[0])
        elif len(partial) > 1:
            problems.append(f"'{raw}' matches several term sheets: {', '.join(f.name for f in partial)}")
        else:
            names = ", ".join(naming.client_name(f.stem) for f in in_docs()) or "none"
            problems.append(f"'{raw}' is not a file, a folder or a client with a term sheet in {docs_dir} (clients found: {names})")
    return paths, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, epilog=ENGINE_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="term sheet PDFs, folders, or client names (default: every term sheet in --docs)")
    ap.add_argument("--docs", type=Path, default=config.DEFAULT_DOCS_DIR, help="folder holding the term sheets (default: %(default)s)")
    ap.add_argument("--template", type=Path, default=None, help="the Key_Credit_Terms.docx template (default: the one in --docs)")
    ap.add_argument("--out", type=Path, default=config.DEFAULT_OUTPUT_DIR, help="output folder (default: %(default)s)")
    ap.add_argument("--engine", choices=pipeline.ENGINES, default="auto", help="where the content comes from (see below)")
    ap.add_argument("--evidence", choices=("comments", "table", "none"), default="comments",
                    help="how the term sheet quotes behind each row are shown: Word comments (default), a references table "
                         "after the main table, or not at all")
    ap.add_argument("--no-highlight", action="store_true", help="do not highlight rows the term sheet is silent on")
    ap.add_argument("--clean", action="store_true", help="shorthand for --evidence none --no-highlight")
    ap.add_argument("--appendix", metavar="N", help="appendix number to put in the title in place of '[ ]'")
    ap.add_argument("--json", action="store_true", help="also save the record (values, quotes, pages) as JSON beside each document")
    ap.add_argument("--model", help=f"Claude model for the claude engines (default: {config.CLAUDE_MODEL} for the API; Claude Code's own default for the CLI)")
    ap.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default="high", help="reasoning effort for the claude engines")
    ap.add_argument("--no-cache", action="store_true", help="re-read every PDF instead of using cached page text")
    ap.add_argument("--list", action="store_true", help="list the term sheets and the engine each would use; write nothing")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if args.clean:
        args.evidence, args.no_highlight = "none", True

    paths, problems = resolve_inputs(args.inputs, args.docs)
    for p in problems:
        print(f"! {p}", file=sys.stderr)
    if not paths:
        return 2
    files = naming.describe(paths)
    audited, record_problems = records.load_all()
    for p in record_problems:
        print(f"! audited record {p}", file=sys.stderr)

    if args.list:
        from kct import pdftext
        width = max(len(f.path.name) for f in files)
        for f in files:
            _, state = records.find(audited, pdftext.sha1_of(f.path), f.path.name)
            engine = pipeline.choose_engine(args.engine, state == "current")
            note = "  (audited record is for an earlier version of this file)" if state == "stale" else ""
            print(f"{f.path.name:<{width}}  ->  {f.output_name}   [{template.SOURCE_LABELS.get(engine, engine)}]{note}")
        return 1 if problems else 0

    template_path = args.template or (args.docs / config.DEFAULT_TEMPLATE.name)
    if not template_path.is_file():
        template_path = config.DEFAULT_TEMPLATE if args.template is None else template_path
    if not template_path.is_file():
        print(f"! Template not found: {template_path}. Pass it with --template.", file=sys.stderr)
        return 2

    failures = 0
    for f in files:
        if not naming.is_term_sheet(f.path):
            print(f"! {f.path.name} is not named as a term sheet (no 'TS' in the name); reading it anyway", file=sys.stderr)
        outcome = pipeline.process(f, template_path, args.out, engine=args.engine, audited=audited, evidence=args.evidence,
                                   highlight=not args.no_highlight, appendix=args.appendix, save_json=args.json,
                                   use_cache=not args.no_cache, model=args.model, effort=args.effort)
        if not outcome.ok:
            failures += 1
            print(f"x {f.path.name}: {outcome.error}", file=sys.stderr)
            continue
        q = outcome.quotes
        flagged = len(outcome.report.get("flagged", []))
        print(f"{f.path.name}  ->  {outcome.out_path}")
        print(f"    source: {template.SOURCE_LABELS.get(outcome.source, outcome.source)}; {outcome.report['rows']} rows written, "
              f"{flagged} flagged for completion; {q.get('exact', 0) + q.get('loose', 0)} of {q.get('total', 0)} quotes verified in the PDF")
        for w in outcome.warnings:
            print(f"    note: {w}")
    done = len(files) - failures
    print(f"\n{done} document{'s' if done != 1 else ''} written to {args.out}" + (f"; {failures} failed" if failures else ""))
    return 1 if failures or problems else 0


if __name__ == "__main__":
    sys.exit(main())
