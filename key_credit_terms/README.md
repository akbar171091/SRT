# Key Credit Terms populator

Fills the **Key Credit Terms** appendix (`Key_Credit_Terms.docx`) from a term sheet PDF, one document per client:

```
Seadrill 2026 TS.pdf   ->   Key_Credit_Terms_Seadrill.docx
```

## Run it

```
python populate_key_credit_terms.py "Seadrill 2026 TS.pdf"      one term sheet
python populate_key_credit_terms.py Seadrill "Duke Energy"      pick term sheets by client name
python populate_key_credit_terms.py                             every term sheet in the documents folder
python populate_key_credit_terms.py --list                      show what would be produced, write nothing
```

Documents are written to `output\`. On Windows you can also double-click `run.bat`.

The term sheets and the template are read from `..\Hackathon (CA and TS)`; a term sheet is any PDF with a
standalone `TS` in its name. Inputs can be PDF paths, folders, file names in that folder, or client names.

Needs Python 3.10 or later with `python-docx` and `pypdf` (`python -m pip install -r requirements.txt`).

| Option | What it does |
|---|---|
| `--out DIR` | Output folder (default `output\`) |
| `--docs DIR`, `--template FILE` | Use another documents folder or another copy of the template |
| `--engine ...` | Where the content comes from: `auto` (default), `audited`, `rules`, `claude`, `claude-api`, `claude-cli` (see below) |
| `--evidence comments\|table\|none` | Show the term sheet quotes behind each row as Word comments (default), as a references table after the main table, or not at all |
| `--no-highlight` | Do not highlight the rows the term sheet is silent on |
| `--clean` | No comments and no highlighting: just the populated table |
| `--appendix N` | Put an appendix number in the title in place of `[ ]` |
| `--json` | Also save the record (values, quotes, pages) as JSON beside each document |

## What you get

A copy of the template with all 34 rows filled in, in the template's own fonts and layout. The section
headers, the pricing row ("Please see the pricing paper") and the title are left as they are.

- Each row holds what the term sheet says on that point, written in the form the template's prompt asks
  for ("Yes = $100m", "Senior Secured (first lien ...)", "Cross default: ...").
- **Yellow** marks a row the term sheet is silent on ("Not stated in term sheet") or deals with only by
  pointing to another document ("substantially the same as the Existing Credit Agreement"). Those rows
  have to be completed from the credit agreement or the deal team.
- Each populated row carries a **Word comment** with the verbatim term sheet wording and the PDF page it
  is on, plus any reviewer note (an ambiguity, an assumption). A covering comment on the title says where
  the content came from. Delete the comments and highlighting once the appendix has been reviewed, or
  produce a copy without them with `--clean`.

Only the term sheet is used. Nothing is taken from the credit agreement or from general knowledge of the
company, so a row can read "Not stated in term sheet" for something that is well known.

## Where the content comes from

| Engine | What it is | Needs |
|---|---|---|
| `audited` | A record in `data\audited\` made from this exact PDF | Nothing; offline |
| `rules` | The offline rules engine: pattern matching on the PDF text | Nothing; offline |
| `claude-api` | Claude reads the whole term sheet, through the Anthropic API | `ANTHROPIC_API_KEY` (or an `ant auth login` profile) and `pip install anthropic` |
| `claude-cli` | The same, through the Claude Code command line | Claude Code installed and logged in; no API key |

`--engine auto` (the default) uses the audited record when there is one for the exact file, otherwise Claude
through the API when credentials are present, otherwise the rules engine. `claude-cli` is never chosen
automatically; ask for it with `--engine claude-cli` (or `--engine claude`, which uses the API if it can and
the command line if not).

Whatever the engine, **every quote is looked up in the text of the PDF on each run**. A quote that is not
on the page it cites is reported on the console and marked in its comment.

### Audited records

The 14 term sheets in the folder each have a record in `data\audited\`, pinned to the SHA-1 of the PDF. If
a term sheet is replaced by a new version the record is no longer used, and the new file is read afresh.

How they were made, for each term sheet:

1. one AI reviewer read the whole document and drafted all 34 rows, with quotes;
2. a second, independent reviewer checked every line of the draft against the document;
3. a third walked the document section by section against the record, looking for anything missed or
   put in the wrong row;
4. a fourth tried to refute every printed line (figures, comparators, parties, existing against proposed
   column, statements of absence), and this was to repeat until a pass found nothing material.

Steps 2 and 3 changed 267 entries between them. No wrong figure was found at any step; the corrections of
substance were terms attached to the wrong party or facility, omissions, and wording that went further
than the document. Step 4 found nothing material in any of the 14 records on its first pass.

**These records have not been signed off by a person.** Treat them as a prepared draft for the analyst,
who can check each row against the quote and page in its comment.

### Rules engine

`kct\rules\` reads the labelled sections of a term sheet ("Financial Covenants:", "Assignments and
Participations:") and recognises the wording such documents use. It is deterministic and nothing leaves the
machine, but it does not understand a document the way a reader does. Its rules prefer to leave a row
"not stated" than to guess. Use it as a first read of a term sheet that has no audited record.

**For a term sheet outside the 14, prefer `--engine claude-cli` or `--engine claude-api`.** The rules engine
is much weaker on a document it was not written against, and its output there has to be checked row by row.

How it compares with the audited records (`python -m kct.rules.evaluate`):

| | 11 sheets the rules were written against | 3 sheets held back, first read | Same 3, after the fix pass |
|---|---|---|---|
| Rows with content that the rules also fill | 100% | 72% | 100% |
| Rows where the status agrees (stated, by reference, not stated) | 99% | 65% | 100% |
| Figures in the audited row that the rules also print | 85% (232 of 272) | 24% (32 of 136) | 77% (105 of 136) |
| Figures the rules print that are in the audited row | 232 of 233 | 32 of 36 | 105 of 110 |

How to read this:

- **The middle column is the one to expect on a new term sheet.** Delta Air Lines, Encompass Health and
  Quaker Chemical were kept away from the rule writers until the rules were finished, then measured once.
- On that first read, 79 of the 161 lines the rules printed for those three sheets were false (51) or
  garbled (28). Examples: a release said to need the Required Lenders where the term sheet says all Lenders;
  a covenant level reported as not set out when it was.
- A fix pass then removed the general cause of each of those lines. The last column is measured after it,
  on sheets the rule writers had by then read, so it is **not** an independent result.
- The fix pass was stopped before its independent check finished. The fixes pass the automated checks
  (every quote is found in the PDF, no format problems, the 11 other sheets read as before apart from four
  small wording changes), but nobody has re-read the three sheets line by line since.
- The five figures in the last column that do not count as matching are all in the term sheet: four belong
  to a basket the audited record files under another row, and one is a period the comparison does not
  recognise ("12 month" against "12-month").

Known gaps: amounts in the acquisitions and indebtedness baskets are often missed; conditions subsequent
and budget reporting are rarely picked up; tables and slides that `pypdf` runs together can defeat the
section finder.

### Claude engines

Both send the full text of the term sheet to Claude with the same drafting brief (`kct\fields.py`) and
receive the record as structured JSON. The term sheet leaves the machine when one of them is used.
`claude-api` uses `claude-opus-5-5` unless `--model` says otherwise; `claude-cli` uses Claude Code's own
default model. A run takes one to three minutes per term sheet. The output is not reviewed by anyone: the
quote check catches invented quotes, not a misreading.

## Limits

- Scanned PDFs with no text layer cannot be read (there is no OCR); the tool says so and moves on.
- Text is read with `pypdf`. Tables and slides come out as columns of text run together; the audited
  records were prepared with the page images alongside, the rules engine and Claude work from the text.
- The appendix is populated from the term sheet only. Lender commitments, and anything else the term
  sheet does not state, stay flagged for the analyst.
- The template is located by its row labels, so rows can be reordered or restyled. If a row is deleted
  or relabelled the tool stops and names the row it cannot find.

## Layout

```
populate_key_credit_terms.py   command line
kct\fields.py                  the 34 template rows and the drafting brief for each
kct\pipeline.py                PDF -> text -> engine -> quote check -> Word document
kct\template.py                writes a record into a copy of the template
kct\schema.py                  the record format, validation, quote check
kct\pdftext.py, textmodel.py   page text extraction (cached) and quote lookup
kct\records.py                 audited records, matched to a PDF by SHA-1
kct\llm.py                     the two Claude engines
kct\rules\                     the offline rules engine (one module per group of rows) and its evaluation
kct\check.py, kct\dump.py      check a record against its PDF; print the text of a PDF as the tool reads it
data\audited\                  the audited records
tests\                         unit tests
```

## Tests

```
python -m unittest discover -s tests -v
python -m kct.rules.evaluate --set all        rules engine against the audited records
python -m kct.check data\audited\seadrill_2026.json --pdf "..\Hackathon (CA and TS)\Seadrill 2026 TS.pdf"
```
