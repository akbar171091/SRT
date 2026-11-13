"""From a term sheet PDF to a populated Key_Credit_Terms_<Client>.docx.

    PDF --(pdftext)--> page text --(engine)--> record --(quote check)--> record --(template)--> .docx

Engines, in the order ``auto`` tries them:

    audited     a record in data/audited/ made from this exact PDF (matched by SHA-1)
    claude-api  Claude through the Anthropic API, when credentials are present
    rules       the offline rules engine (always available)

``claude-cli`` (Claude Code in headless mode) is never picked automatically; ask for it by name.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import llm, pdftext, records, schema, template
from .naming import TermSheetFile
from .textmodel import Doc

ENGINES = ("auto", "audited", "rules", "claude", "claude-api", "claude-cli")


class PipelineError(RuntimeError):
    """This term sheet could not be processed; the message says why."""


@dataclass
class Outcome:
    file: TermSheetFile
    out_path: Path | None = None
    source: str = ""
    record: dict | None = None
    quotes: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def choose_engine(engine: str, has_current_record: bool) -> str:
    if engine == "auto":
        if has_current_record:
            return "audited"
        return "claude-api" if llm.api_available() else "rules"
    if engine == "claude":
        return "claude-api" if llm.api_available() else "claude-cli"
    return engine


def build_record(ts: TermSheetFile, engine: str = "auto", *, audited: list[dict] | None = None, use_cache: bool = True,
                 model: str | None = None, effort: str = "high") -> tuple[dict, list[str], dict]:
    """Read the term sheet and return (record, warnings, quote tally)."""
    if engine not in ENGINES:
        raise PipelineError(f"Unknown engine {engine!r}; choose from {', '.join(ENGINES)}")
    warnings: list[str] = []
    try:
        pages, meta = pdftext.extract_pages(ts.path, use_cache=use_cache)
    except Exception as exc:  # unreadable or damaged PDF
        raise PipelineError(f"Could not read the PDF: {exc}") from exc
    if audited is None:
        audited, problems = records.load_all()
        warnings += problems
    found, state = records.find(audited, meta["sha1"], ts.path.name)
    chosen = choose_engine(engine, state == "current")

    if chosen == "audited":
        if state != "current":
            why = ("the audited record for this file name was made from a different version of the PDF"
                   if state == "stale" else "there is no audited record for this PDF")
            raise PipelineError(f"{why}; use --engine rules or --engine claude")
        record = {k: v for k, v in found.items() if not k.startswith("_")}
        record["source"] = "audited"
        record["client"], record["deal"], record["source_file"] = ts.client, ts.deal, ts.path.name
    else:
        if state == "stale" and engine == "auto":
            warnings.append("an audited record exists for an earlier version of this file; the new file was read afresh")
        if meta["no_text"]:
            raise PipelineError("the PDF has no text layer (a scan?); run OCR on it first")
        record = schema.new_record(ts.client, ts.deal, ts.path.name, meta["sha1"], chosen)
        if chosen == "rules":
            from . import rules  # imported here so the Claude engines work without it and vice versa
            answer = rules.extract(pages, ts.client, ts.path.name)
        else:
            try:
                call = llm.extract_api if chosen == "claude-api" else llm.extract_cli
                answer, usage = call(pages, ts.client, ts.path.name, model=model, effort=effort)
            except llm.ExtractionError as exc:
                raise PipelineError(str(exc)) from exc
            record["usage"] = usage
        left_out = schema.from_extraction(answer, record)
        if left_out:
            warnings.append(f"the engine returned nothing for: {', '.join(left_out)}")
        if meta["thin_pages"] and len(meta["thin_pages"]) > meta["pages"] / 2:
            warnings.append("most pages have very little text; the PDF may be partly scanned")

    record = schema.normalise(record)
    for fid, entry in record["fields"].items():  # a not_stated row has nothing to cite
        if entry["status"] == "not_stated" and entry["evidence"] and chosen != "audited":
            entry["evidence"] = []
    structure = schema.validate(record)
    if structure:
        warnings.append(f"{len(structure)} format issue(s) in the record, e.g. {structure[0]}")
    tally = schema.check_evidence(record, Doc(pages))
    bad = tally["other_page"] + tally["missing"]
    if bad:
        warnings.append(f"{bad} of {tally['total']} quotes could not be found on the page cited (marked in the comments)")
    return record, warnings, tally


def process(ts: TermSheetFile, template_path: Path, out_dir: Path, *, engine: str = "auto", audited: list[dict] | None = None,
            evidence: str = "comments", highlight: bool = True, appendix: str | None = None, save_json: bool = False,
            use_cache: bool = True, model: str | None = None, effort: str = "high") -> Outcome:
    """Populate the template for one term sheet. Never raises for a problem with the document: see Outcome.error."""
    outcome = Outcome(file=ts)
    try:
        record, warnings, tally = build_record(ts, engine, audited=audited, use_cache=use_cache, model=model, effort=effort)
        outcome.record, outcome.warnings, outcome.quotes, outcome.source = record, warnings, tally, record["source"]
        out_path = Path(out_dir) / ts.output_name
        outcome.report = template.render(record, template_path, out_path, evidence=evidence, highlight=highlight, appendix=appendix)
        outcome.out_path = out_path
        if save_json:
            out_path.with_suffix(".json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    except (PipelineError, template.TemplateError, PermissionError, FileNotFoundError) as exc:
        outcome.error = str(exc)
    return outcome
