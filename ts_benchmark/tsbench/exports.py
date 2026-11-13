"""CSV extracts of the benchmark and a single-file HTML copy of the front end.

Every CSV takes the peer group it is exported for (``bench``, as returned by ``benchmark``): the rows
are the term sheets of that group and the peer columns are measured against it, so an extract
matches the screen it was exported from. With no group given, all term sheets are used.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .config import COVENANT_TYPES, FACILITY_TYPES, FEE_TYPES, PRICING_BASIS, STATIC_DIR

_PROFILE = {"investment_grade": "Investment-grade style", "leveraged": "Leveraged style", "unclear": "Unclear"}
_SOURCE = {"verified": "AI-audited record", "rules": "Rules engine (not audited)"}
_BOM = chr(0xFEFF)
_BACKSLASH = chr(92)
_FOUND = {True: "yes", False: "no"}


def _cell(value):
    """Text taken from a PDF must not be run as a formula when the CSV is opened in a spreadsheet."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows([_cell(v) for v in row] for row in rows)
    return _BOM + buf.getvalue()  # byte order mark so Excel reads the file as UTF-8


def _group(dataset: dict, bench: dict | None) -> dict:
    return bench if bench is not None else dataset["benchmarks"]["all"]


def _peers(dataset: dict, bench: dict | None) -> list[dict]:
    ids = set(_group(dataset, bench)["peer_ids"])
    return [d for d in dataset["deals"] if d["id"] in ids]


def _common(d: dict) -> list:
    r = d["record"]
    return [d["deal"], r["borrower"]["name"], _PROFILE.get(r["credit_profile"]["value"], ""), r["security"]["value"], _SOURCE[d["source"]]]


def pricing_csv(dataset: dict, bench: dict | None = None) -> str:
    group = _group(dataset, bench)
    peer_label = f"{group['label']} ({group['n']})"
    header = ["Deal", "Borrower", "Credit profile", "Security", "Data source", "Facility", "Facility size ($mm)", "Facility size note",
              "Tenor (years)", "Tenor range (years)", "Pricing basis", "Benchmark", "CSA (bps; not included in margin or all-in)", "Floor (%)",
              "Tiers", "Opening level", "Margin open (bps)", "Margin min (bps)", "Margin max (bps)",
              "All-in drawn open (bps)", "All-in drawn min (bps)", "All-in drawn max (bps)",
              "Undrawn fee type", "Undrawn open (bps)", "Undrawn min (bps)", "Undrawn max (bps)",
              "Upfront min (bps)", "Upfront max (bps)", "Peer group", "Margin max vs peer group median (bps)",
              "Margin max rank in peer group (1 = lowest)", "Computed figures"]
    rows = []
    for d in _peers(dataset, bench):
        m, dv, r = d["derived"]["metrics"], d["derived"], d["record"]
        line = dv["lines"][dv["headline"]] if dv["headline"] is not None else None
        peer = group["metrics"]["margin_max"]["deals"].get(d["id"], {})
        size, span = dv["size"], dv["tenor_range"]
        size_note = (f"At least {size['partial_mm']:g}. " if size["partial_mm"] is not None else "") + size["note"]
        rows.append(_common(d) + [
            line["facility_label"] if line else "", m["facility_mm"], size_note,
            m["tenor"], f"{span[0]:g} to {span[1]:g}" if span and span[0] != span[1] else "",
            PRICING_BASIS.get(r["pricing"]["basis"], ""), r["pricing"]["benchmark"],
            m["csa"] if dv["csa_status"] != "not_stated" else "not stated", m["floor"], m["tiers"],
            line["opening_level"] if line and line["opening_level"] else "",
            m["margin_open"], m["margin_min"], m["margin_max"], m["all_in_open"], m["all_in_min"], m["all_in_max"],
            (line["undrawn_type"].replace("_", " ") if line else ""), m["undrawn_open"], m["undrawn_min"], m["undrawn_max"],
            m["upfront_min"], m["upfront_max"], peer_label, peer.get("vs_median"), peer.get("rank"),
            ", ".join(line["computed"]) if line else "",
        ])
    return _csv(header, rows)


def grid_csv(dataset: dict, bench: dict | None = None) -> str:
    header = ["Deal", "Grid", "Facilities", "Page", "Level", "Criteria", "Opening tier", "Drawn margin (bps)", "Base rate margin (bps)",
              "Undrawn fee (bps)", "Undrawn fee type", "All-in drawn (bps)", "LC fee (bps)", "Source quote", "Quote found in PDF"]
    rows = []
    for d in _peers(dataset, bench):
        fac = {f["id"]: FACILITY_TYPES.get(f["type"], f["type"]) for f in d["record"]["facilities"]}
        for g, line in zip(d["record"]["pricing"]["grids"], d["derived"]["lines"]):
            for t, fig in zip(g["tiers"], line["tier_figures"]):
                rows.append([d["deal"], g["name"], " + ".join(dict.fromkeys(fac.get(i, i) for i in line["facility_ids"])), g.get("page"),
                             t.get("level"), t.get("criteria"), "yes" if t.get("is_opening") else "", fig["margin"], t.get("base_rate_margin_bps"),
                             fig["undrawn"], line["undrawn_type"].replace("_", " "), fig["all_in"], t.get("lc_fee_bps"), t.get("quote"),
                             _FOUND.get(t.get("quote_ok"), "")])
    return _csv(header, rows)


def fees_csv(dataset: dict, bench: dict | None = None) -> str:
    header = ["Deal", "Fee type", "Description", "Fee (bps)", "Low (bps)", "High (bps)", "As stated", "Page", "Source quote", "Quote found in PDF"]
    rows = [[d["deal"], FEE_TYPES.get(f["type"], f["type"]), f.get("description"), f.get("bps"), f.get("bps_low"), f.get("bps_high"),
             f.get("amount_text"), f.get("page"), f.get("quote"), _FOUND.get(f.get("quote_ok"), "")]
            for d in _peers(dataset, bench) for f in d["record"]["pricing"]["fees"]]
    return _csv(header, rows)


def covenants_csv(dataset: dict, bench: dict | None = None) -> str:
    header = ["Deal", "Borrower", "Credit profile", "Security", "Data source", "Covenant", "Name in term sheet", "Test", "Level", "Unit",
              "Level applies from", "Loosest scheduled level", "Final scheduled level", "Schedule", "Acquisition step-up", "Springing",
              "Springing trigger", "Applies to", "Page", "Source quote", "Quote found in PDF", "Note"]
    unit = {"x": "x", "pct": "%", "usd_mm": "$mm"}
    rows = []
    for d in _peers(dataset, bench):
        r = d["record"]
        if not r["financial_covenants"]:
            # only an audited record can say a term sheet has no financial covenant; the rules engine can only fail to find one
            found_none = "None stated" if d["source"] == "verified" else "None found by the rules engine"
            rows.append(_common(d) + [found_none] + [""] * 15 + [r.get("no_financial_covenant_note") or ""])
        for c, dc in zip(r["financial_covenants"], d["derived"]["covenants"]):
            scale = 100.0 if dc["unit"] == "pct" and c.get("unit") == "x" else 1.0  # the schedule in the unit of the level shown
            sched = "; ".join(
                f"{s.get('period') or 'Period'}: {round(s['threshold'] * scale, 4):g}" if s.get("threshold") is not None
                else f"{s.get('period') or 'Period'}: not tested" for s in c.get("schedule") or [])
            spring = c.get("springing") or {}
            rows.append(_common(d) + [
                COVENANT_TYPES.get(c["type"], COVENANT_TYPES["other"])[0], c.get("name"), "Maximum" if dc["direction"] == "max" else "Minimum",
                dc["threshold"], unit.get(dc["unit"], dc["unit"]),
                (dc["starts"] or "a later date (not tested at closing)") if dc["deferred"] else "closing",
                dc["loosest"], dc["final"], sched, dc["step_up"], "yes" if dc["springing"] else "",
                spring.get("trigger"), c.get("applies_to"), c.get("page"), c.get("quote"), _FOUND.get(c.get("quote_ok"), ""), "",
            ])
    return _csv(header, rows)


def peer_stats_csv(dataset: dict, bench: dict | None = None) -> str:
    header = ["Peer group", "Term sheets in group", "Metric", "Unit", "N", "Minimum", "25th percentile", "Median", "Mean", "75th percentile", "Maximum"]
    labels = {m["id"]: (m["label"], m["unit"]) for m in dataset["vocab"]["metrics"]}
    groups = list(dataset["benchmarks"].values())
    if bench is not None and all(bench is not g for g in groups):  # a hand-picked selection, listed after the standard groups
        groups.append(bench)
    rows = []
    for group in groups:
        for metric, data in group["metrics"].items():
            s = data["stats"]
            if s:
                rows.append([group["label"], group["n"], labels[metric][0], labels[metric][1], s["n"], s["min"], s["p25"], s["median"],
                             s["mean"], s["p75"], s["max"]])
    return _csv(header, rows)


CSV_EXPORTS = {
    "pricing_benchmark.csv": pricing_csv,
    "pricing_grids.csv": grid_csv,
    "fees.csv": fees_csv,
    "financial_covenants.csv": covenants_csv,
    "peer_statistics.csv": peer_stats_csv,
}


def public(dataset: dict) -> dict:
    """A copy of the dataset for the browser: everything except where the PDFs sit on disk."""
    data = json.loads(json.dumps(dataset, allow_nan=False))
    for d in data["deals"]:
        d.pop("path", None)
    return data


def embed_json(data: dict) -> str:
    """JSON that is safe to place inside a <script> element.

    Every "<" is written as its JSON escape, so no text can close the element or open a comment, and
    the two line separators JavaScript treats as line ends are escaped as well.
    """
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for char in ("<", chr(0x2028), chr(0x2029)):
        text = text.replace(char, f"{_BACKSLASH}u{ord(char):04x}")
    return text


def static_html(dataset: dict) -> str:
    """The front end with the dataset embedded: one file that opens without the server."""
    data = public(dataset)
    data["meta"]["static"] = True
    # A saved copy may be passed on: keep the folder name but not the full local path, and no links to local files.
    folder = Path(data["meta"]["docs_dir"])
    if folder.name and len(str(folder)) > len(folder.name):
        data = _without(data, str(folder), folder.name)  # also catches a message that happens to quote the path
    data["meta"]["docs_dir"] = folder.name or str(folder)
    for d in data["deals"]:
        d["pdf_url"] = None
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    marker = "<!--DATASET-->"
    if marker not in page:
        raise RuntimeError("index.html has no dataset marker")
    return page.replace(marker, f'<script id="embedded-dataset" type="application/json">{embed_json(data)}</script>', 1)


def _without(value, old: str, new: str):
    """A copy of ``value`` with ``old`` replaced by ``new`` in every string it holds."""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, dict):
        return {k: _without(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_without(v, old, new) for v in value]
    return value
