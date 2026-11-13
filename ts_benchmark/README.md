# Term sheet benchmark

Benchmarks **pricing** and **financial covenants** across every term sheet PDF in a folder, through a
local HTML front end.

## Run it

```
python run.py
```

This reads the term sheets in `..\Hackathon (CA and TS)`, starts a local server on
<http://127.0.0.1:8765/> and opens the browser. On Windows you can also double-click `run.bat`.
If port 8765 is taken (for example by a copy that is still running), the next free port is used and
printed in the console.

```
python run.py --docs "C:\path\to\folder"    benchmark another folder
python run.py --export report.html          write the front end as one self-contained HTML file
python run.py --csv out                     write the CSV extracts (pricing, grids, fees, covenants, peer statistics)
python run.py --rules-only                  ignore the audited records; show the rules engine output for everything
python run.py --no-cache                    re-read every PDF instead of using cached page text
python run.py --port 9000 --no-browser
```

Needs Python 3.10 or later. Nothing to install: the only third-party library is `pypdf`, used from
your environment if present and otherwise from the wheel in `vendor/`.

A term sheet is any PDF with a standalone `TS` in its file name (`Accenture 2026 TS.pdf`). Credit
agreements (`CA`) are ignored. The same file saved twice is counted once.

## What you get

| View | Content |
|---|---|
| Overview | The term sheets, headline terms, and headline medians for the chosen peer group |
| Pricing | Drawn margin, all-in drawn and undrawn fee ranges per deal, comparables table, peer statistics |
| Financial covenants | Leverage and interest coverage levels per deal, the full covenant package, peer statistics |
| Deal detail | Facilities, every pricing tier, fees and covenants for one deal, each with its source quote and page, and the deal's position against its peers |
| Extraction QA | Where each figure comes from and how well the rules engine agrees with the audited records |

Peer groups: all term sheets, investment-grade style (unsecured, ratings grid), leveraged style
(secured), or any set you tick. The profile is judged from the form of the facility in the term
sheet, not from a rating. A group that mixes 364-day facilities with longer-dated ones says so.

The CSV exports follow the peer group selected on screen: the same rows, with the peer columns
measured against that group and the group named in the file. `--csv` on the command line exports
all term sheets.

## Where the figures come from

1. **Rules engine** (`tsbench/rules.py`, `tables.py`, `covenants.py`): offline pattern matching on
   the PDF text. It runs on every term sheet, including ones added to the folder later.
2. **AI-audited records** (`data/verified/*.json`): for the 14 term sheets present when the tool was
   built, a record extracted from the full document by one AI reviewer and then audited value by
   value by a second, independent one. A record is pinned to the SHA-1 of its PDF and is used only
   while that exact file is in the folder. These have not been signed off by a person.

Where an audited record exists it is shown, and the rules engine output is used to report agreement
(98.9% of 367 compared fields on these documents; every pricing tier figure matches). That agreement
is measured on the documents the rules were developed against, so expect less on an unseen format.

A term sheet with no audited record (a new file, or one that has changed since it was audited) is
shown from the rules engine alone. Such rows are marked "rules engine" in every table and with a
dagger in the charts, and a banner at the top of each view names them: treat their figures as a
first read and check them against the source quotes. Where the engine cannot tell what a number
means it leaves the figure empty and says so on the Deal detail page.

Either way, every figure carries the verbatim quote and page it was read from, and every quote is
looked up in the PDF text each time the folder is read. Anything that cannot be found is listed
under Extraction QA.

## How the benchmark figures are defined

- **Headline facility.** Each deal is benchmarked on one pricing grid: the revolver's where there is
  one. A grid labelled as the existing terms is never used while another is there.
- **All-in drawn** = drawn margin + facility fee, where the undrawn fee is a facility fee (paid on
  the whole commitment), whether the fee is a grid column or stated separately. With a commitment
  fee, all-in drawn is the margin. Where a facility fee applies but its rate is not known, all-in
  drawn is left empty. Computed, and marked where it appears.
- **Drawn margin** = all-in drawn less facility fee, where a grid prints only those two columns.
  Computed, and marked where it appears.
- **Credit spread adjustment** is reported on its own and is not included in the margin or all-in
  figures. Zero means the term sheet expressly has none; blank means it is silent.
- **Facility size** is the sum of the facilities only when every one has a stated US dollar amount.
  Otherwise the deal shows a floor ("≥ $800mm") and is left out of the size statistics.
- **Tenor** is that of the headline facility; where it has tranches of different tenors the range is
  shown and the longest is used in the statistics.
- **Covenants.** The level benchmarked is the first maintenance test listed in each family that is
  not springing, at closing (or the first level tested where the test starts later). A second level
  of the same test, a dated schedule, an acquisition step-up and a springing trigger are shown beside
  it. Interest coverage and fixed charge coverage are different ratios and are not benchmarked
  together.
- **Statistics.** Quartiles use linear interpolation (Excel's PERCENTILE.INC) and are not shown for
  fewer than four term sheets. Table footers give the sample size where it is smaller than the group.

## Limits

- Scanned PDFs with no text layer cannot be read (there is no OCR). A file that cannot be read is
  named in a banner and left out of every table, chart and statistic.
- Financial covenants are read only from a financial covenant section, so incurrence tests in
  baskets are left out by design. A covenant stated only in an image is missed. Only an audited
  record can say a term sheet has no financial covenant; for a rules-only deal the tool says none
  was found.
- Leverage covenants are compared across definitions (total, net, secured, first lien); the basis
  is shown beside each figure.
- The rules engine is weakest on deal context rather than on pricing: facility amounts where an
  amendment describes both the old and the new facility, and the tenor of multi-tranche deals.
- The server listens on 127.0.0.1 only and answers only its own page: requests from other sites, or
  from other local web apps, are refused.

## Tests

```
python -m unittest discover -s tests -v
```

The document tests use the term sheet PDFs and are skipped when the folder is not there.
