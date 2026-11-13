# TS ↔ CA Reconciliation

A Python toolkit with a Streamlit front end that checks syndicated-loan **term sheets (TS)** against the executed **credit agreements (CA)**. It flags:

- **Missing components:** a client with a CA but no TS (or the reverse), duplicate files, and PDFs whose names can't be classified.
- **Terms that differ:** every attribute is compared and colour-coded. Green means match, red means differs, orange means the TS term is missing from the CA, amber means it needs review, and grey means the CA has it but the TS is silent.

## Quick start

```bash
# from the Hackathon folder
python -m venv --system-site-packages .venv
.venv\Scripts\python -m pip install -r ts_ca_recon\requirements.txt
cd ts_ca_recon
..\.venv\Scripts\python -m streamlit run app.py      # or double-click run_app.bat
```

The app reads `../Hackathon (CA and TS)/` by default; you can change the folder in the sidebar or upload PDFs there. Files are paired by name: `<Client> <Year> CA.pdf` and `<Client> <Year> TS.pdf`. "Credit Agreement" and "Term Sheet" spelled out also work.

Command line, without the UI:

```bash
python run_checks.py                                   # rules engine, all deals
python run_checks.py --engine claude --deal "Capri 2026"
python run_checks.py --import-verified data/verified_reconciliation.json
python -m pytest tests                                 # unit tests
```

## Three result sources

| Source | What it does | Needs |
|---|---|---|
| **Rules engine** (offline) | Finds 15 headline terms in both documents by term-sheet label, CA defined term, section heading, pricing table and cover page. Normalises amounts, rates (bps), ratios and dates and compares them. Also **traces every figure in the term sheet through the whole CA**. | Nothing. Instant and deterministic. |
| **Claude API** (live) | Full semantic reconciliation of a 36-attribute checklist plus every other term the TS states, with verbatim quotes, page references, materiality, and which side each difference favours. Uses `claude-opus-5-5` with structured outputs and prompt caching (the CA is cached between the two requests per deal). | `ANTHROPIC_API_KEY`, an `ant auth login` profile, or a key typed into the app. Roughly $1 per deal. |
| **Agent-verified** (import) | Output of a multi-agent run: for each deal and attribute group, one agent reconciles and an independent adversarial agent re-checks every row and quote. | The workflow's JSON output. |

Whichever source you use, **every quote is checked mechanically against the PDF text** ("TS quote ✓ / CA quote ✓" columns). Where a quote can't be found, the row's evidence should not be relied on.

## App tabs

- **📁 Documents:** document inventory, with missing TS/CA highlighted in red.
- **📊 Overview:** KPIs, a per-deal count of each status, and an attribute heatmap (deals × attributes).
- **🔍 Deal detail:** a colour-coded row for each attribute, side-by-side evidence quotes with pass/fail on the quote check, and (for the rules engine) the figure-traceability table.
- **⚠️ Exceptions:** every difference, missing term and missing document across deals, with filters and CSV/Excel export.
- **▶️ Run checks:** run the rules engine or Claude, import agent-verified results, and re-check quotes.

## Importing a multi-agent run

```bash
# merge the main run's journal with any follow-up re-check runs, then import
python tools/export_workflow_journal.py <main journal.jsonl> data/verified_reconciliation.json [<extra journal.jsonl> ...]
python run_checks.py --import-verified data/verified_reconciliation.json
```

Each attribute group is labelled in the app as either "re-checked by verifier" or "first pass, not yet re-checked".

## Limitations

- The rules engine is a **screening** tool. An independent audit of its output against the PDFs (14 deals × 15 attributes) found the status correct for 75% of attributes. Most of the misses are cautious `review` flags where both documents agree; about 5% are false `differs` flags, mostly on pricing grids and lender-presentation "term sheets" (APi Group, Seadrill). It confirms figures and named parties; it does not interpret legal drafting.
- Term-sheet labels are paired with their values by **position on the page** (pypdf text coordinates), so two-column term sheets where a label sits beside the end of the previous paragraph are handled. Single-column "Label: value" paragraphs are recognised too. Slide decks remain approximate.
- Maturities written as tenors ("five (5) years after the Closing Date", "fifth anniversary", "364-day") are checked by measuring the CA maturity date from the agreement or effective date.
- Some CAs are amendments whose conformed copy is a blackline, so deleted and inserted text appear side by side. A deleted figure may therefore "match". The Claude and agent-verified sources are told to read the agreement as amended.
- Text comes from `pdftotext` when it is on PATH, otherwise pypdf. Scanned (image-only) PDFs would need OCR first.
- Results under `results/` and cached text under `.cache/` contain document content; treat them as confidential.

## Layout

```
app.py              Streamlit UI
run_checks.py       CLI runner
recon/inventory.py  pair files, flag missing components
recon/pdftext.py    page-aware text extraction + cache
recon/values.py     money / % / bps / ratio / date parsing and normalisation
recon/rules.py      offline rules engine + figure traceability
recon/llm.py        Claude reconciliation (structured outputs, prompt caching)
recon/quotes.py     mechanical quote verification
recon/results.py    result storage, workflow import
tests/              unit tests
```
