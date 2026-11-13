"""Measure the rules engine against the audited records.

    python -m kct.rules.evaluate                       summary table, one row per field
    python -m kct.rules.evaluate --field maturity      audited lines and rules lines side by side for one field
    python -m kct.rules.evaluate --doc seadrill_2026   every field of one term sheet side by side
    python -m kct.rules.evaluate --module fincov       only the fields of one rule module

For each term sheet that has an audited record (data/audited), the rules engine reads the same PDF
and the two records are compared field by field:

    covered     the audited record has content (stated or by_reference) and so do the rules
    status      both records give the field the same status
    figures     of the amounts, ratios, percentages and periods in the audited lines, the share that also
                appear in the rules lines (recall), and the share of the figures in the rules lines that
                appear in the audited lines (precision)
    quotes      every evidence quote the rules produce must be found on the page it cites

The audited records are the reference, but they were written by a reader: matching their wording is
not the aim. Figures, coverage and status are what the rules can be held to.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .. import config, naming, pdftext, records, schema
from ..fields import BY_ID, FIELD_IDS
from ..textmodel import Doc
from . import MODULE_NAMES, MODULES, extract
from .common import DAYS_RE, PCT_RE, RATIO_RE, amounts, number

_HOUSE_RATIO_RE = re.compile(r"(?<![\w.])(\d{1,2}\.\d{1,2})x\b")


def figures(lines: list[str]) -> set[tuple]:
    """The numbers a credit reader would check, normalised: ("$", millions), ("x", ratio), ("%", pct), ("t", n, unit)."""
    text = " \n ".join(lines)
    out: set[tuple] = set()
    for mm, _, _ in amounts(text):
        out.add(("$", round(mm, 3)))
    for m in list(RATIO_RE.finditer(text)) + list(_HOUSE_RATIO_RE.finditer(text)):
        out.add(("x", round(float(m.group(1)), 2)))
    for m in PCT_RE.finditer(text):
        out.add(("%", round(float(m.group(1)), 3)))
    for m in DAYS_RE.finditer(text):
        n = number(m.group(1) or m.group(2))
        unit = re.sub(r"\s+", " ", m.group(3).lower()).rstrip("s")
        if n is not None:
            out.add(("t", n, unit))
    return out


def compare(audited: dict, mine: dict) -> dict:
    """Per-field comparison of two records."""
    out = {}
    for fid in FIELD_IDS:
        a, r = audited["fields"][fid], mine["fields"][fid]
        fa, fr = figures(a["lines"]) if a["status"] != "not_stated" else set(), figures(r["lines"]) if r["status"] != "not_stated" else set()
        out[fid] = {
            "a_status": a["status"], "r_status": r["status"],
            "a_has": a["status"] != "not_stated", "r_has": r["status"] != "not_stated",
            "fig_a": len(fa), "fig_r": len(fr), "fig_hit": len(fa & fr),
            "missed": sorted(fa - fr, key=str), "extra": sorted(fr - fa, key=str),
        }
    return out


# Term sheets kept out of rule development. The rules were written and tuned on the others ("dev"); these show how
# the engine does on a document it was not built against.
HOLDOUT = ("delta_airlines_2026", "encompass_health_2026", "quaker_chemical_2026")

# Where reference records are looked for, best first. The last two exist only while records are being prepared.
REFERENCE_DIRS = (config.AUDITED_DIR, config.CACHE_DIR / "audit1", config.CACHE_DIR / "drafts")


def _reference(sha1: str, file_name: str, pools: list[tuple[str, list[dict]]]) -> tuple[dict | None, str]:
    for name, pool in pools:
        ref, state = records.find(pool, sha1, file_name)
        if state == "current" and sum(1 for f in ref["fields"].values() if f.get("status") != "not_stated") > 5:
            return ref, name
    return None, ""


def run(docs_dir: Path = config.DEFAULT_DOCS_DIR, which: str = "dev") -> list[dict]:
    """Compare on the "dev" term sheets, the "holdout" ones, or "all"."""
    pools = [(d.name, records.load_all(d)[0]) for d in REFERENCE_DIRS]
    results = []
    for ts in naming.describe(naming.scan(docs_dir)):
        if which != "all" and (ts.slug in HOLDOUT) != (which == "holdout"):
            continue
        pages, meta = pdftext.extract_pages(ts.path)
        ref, ref_source = _reference(meta["sha1"], ts.path.name, pools)
        if ref is None:
            continue
        ref = schema.normalise(ref)
        mine = schema.new_record(ts.client, ts.deal, ts.path.name, meta["sha1"], "rules")
        schema.from_extraction(extract(pages, ts.client, ts.path.name), mine)
        mine = schema.normalise(mine)
        problems = schema.validate(mine)
        tally = schema.check_evidence(mine, Doc(pages))
        results.append({"slug": ts.slug, "audited": ref, "rules": mine, "cmp": compare(ref, mine), "problems": problems, "quotes": tally,
                        "reference": ref_source})
    return results


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:5.0f}%" if b else "    - "


def summary(results: list[dict], fids: list[str]) -> str:
    out = [f"{'field':26} {'audited':>7} {'covered':>8} {'status':>7} {'fig recall':>11} {'fig precision':>14} {'rules-only':>11}"]
    tot = dict(a=0, cov=0, st=0, fa=0, fh=0, fr=0, n=0, only=0)
    for fid in fids:
        a = cov = st = fa = fh = fr = only = 0
        for res in results:
            c = res["cmp"][fid]
            a += c["a_has"]
            cov += c["a_has"] and c["r_has"]
            only += (not c["a_has"]) and c["r_has"]
            st += c["a_status"] == c["r_status"]
            fa += c["fig_a"]
            fh += c["fig_hit"]
            fr += c["fig_r"]
        n = len(results)
        out.append(f"{fid:26} {a:>4}/{n:<2} {_pct(cov, a):>8} {_pct(st, n):>7} {_pct(fh, fa):>7} ({fh}/{fa}) {_pct(fh, fr):>8} ({fh}/{fr}) {only:>8}")
        for k, v in dict(a=a, cov=cov, st=st, fa=fa, fh=fh, fr=fr, n=n, only=only).items():
            tot[k] += v
    out.append(f"{'ALL':26} {tot['a']:>4}/{tot['n']:<3} {_pct(tot['cov'], tot['a']):>7} {_pct(tot['st'], tot['n']):>7} {_pct(tot['fh'], tot['fa']):>7} "
               f"({tot['fh']}/{tot['fa']}) {_pct(tot['fh'], tot['fr']):>8} ({tot['fh']}/{tot['fr']}) {tot['only']:>8}")
    q = [r["quotes"] for r in results]
    bad_q = sum(t["other_page"] + t["missing"] for t in q)
    out.append(f"\nquotes: {sum(t['exact'] for t in q)} exact, {sum(t['loose'] for t in q)} loose, {bad_q} NOT FOUND (must be 0); "
               f"format problems: {sum(len(r['problems']) for r in results)} (must be 0); term sheets: {len(results)}")
    interim = [f"{r['slug']} ({r['reference']})" for r in results if r["reference"] != config.AUDITED_DIR.name]
    if interim:
        out.append("reference not yet audited for: " + ", ".join(interim))
    for r in results:
        for p in r["problems"][:5]:
            out.append(f"  FORMAT {r['slug']}: {p}")
        for p in r["quotes"]["problems"][:5]:
            out.append(f"  QUOTE  {r['slug']}: {p}")
        for fid in fids:
            note = r["rules"]["fields"][fid].get("note", "")
            if note.startswith("The rule for this row failed"):
                out.append(f"  ERROR  {r['slug']} {fid}: {note}")
    return "\n".join(out)


def side_by_side(res: dict, fid: str) -> str:
    a, r, c = res["audited"]["fields"][fid], res["rules"]["fields"][fid], res["cmp"][fid]
    out = [f"--- {res['slug']} / {fid}  (figures {c['fig_hit']}/{c['fig_a']} found; missed {c['missed']}; extra {c['extra']})",
           f"  AUDITED [{a['status']}]"]
    out += [f"      {line}" for line in a["lines"]]
    out.append(f"  RULES   [{r['status']}]")
    out += [f"      {line}" for line in r["lines"]]
    for e in r["evidence"]:
        out.append(f"      quote p.{e['page']} ({e.get('found', '?')}): {e['quote'][:150]}")
    if r.get("note"):
        out.append(f"      note: {r['note']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--field", action="append", help="show this field side by side for every term sheet (repeatable)")
    ap.add_argument("--doc", help="show every field side by side for this term sheet (slug, e.g. seadrill_2026)")
    ap.add_argument("--module", choices=MODULE_NAMES, help="limit the summary to one rule module")
    ap.add_argument("--set", choices=("dev", "holdout", "all"), default="dev", dest="which",
                    help="which term sheets to compare: those the rules were developed on (default), the held-out ones, or all")
    ap.add_argument("--json", type=Path, help="write the full comparison to this file")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    results = run(which=args.which)
    if not results:
        print("No term sheet in the documents folder has an audited record to compare with.")
        return 1
    fids = FIELD_IDS
    if args.module:
        module = next((m for m in MODULES if m.__name__.endswith("." + args.module)), None)
        if module is None:
            print(f"Rule module {args.module!r} failed to load; see the warning above.")
            return 2
        fids = [f for f in FIELD_IDS if f in module.RULES]
        if not fids:
            print(f"Rule module {args.module!r} defines no rules yet.")
            return 0
    if args.field:
        unknown = [f for f in args.field if f not in BY_ID]
        if unknown:
            print(f"Unknown field(s): {', '.join(unknown)}")
            return 2
        for fid in args.field:
            for res in results:
                print(side_by_side(res, fid))
    elif args.doc:
        res = next((r for r in results if r["slug"] == args.doc), None)
        if res is None:
            print(f"No audited term sheet with slug {args.doc!r}; have: {', '.join(r['slug'] for r in results)}")
            return 2
        for fid in fids:
            print(side_by_side(res, fid))
    print(f"[{args.which} set: {', '.join(r['slug'] for r in results)}]")
    print(summary(results, fids))
    if args.json:
        args.json.write_text(json.dumps([{k: r[k] for k in ("slug", "cmp", "problems", "quotes")} for r in results], indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
