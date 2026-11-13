"""Field-by-field comparison of the rules engine against a verified reference record.

Used for the Extraction QA view and the regression tests: it shows how far the offline rules
engine can be trusted on documents that have no verified record.
"""
from __future__ import annotations

from .config import COVENANT_TYPES

TIER_FIELDS = [
    ("drawn_margin_bps", "drawn margin"),
    ("base_rate_margin_bps", "base rate margin"),
    ("undrawn_fee_bps", "undrawn fee"),
    ("all_in_drawn_bps", "all-in drawn"),
    ("lc_fee_bps", "LC fee"),
]


def _cov(ctype: str) -> tuple:
    return COVENANT_TYPES.get(ctype, COVENANT_TYPES["other"])


def _kin(ctype: str) -> str:
    """Family used to pair a reference covenant with the engine's reading when the exact type differs.

    Interest and fixed charge coverage count as kin here: reading one as the other is a wrong test
    type on a covenant that was found, not a covenant that was missed.
    """
    family = _cov(ctype)[1]
    return "coverage" if family == "fixed_charge" else family


def _eq(a, b, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= tol


def _check(group: str, field: str, verified, rules) -> dict:
    if verified is None and rules is None:
        status = "match"
    elif verified is None:
        status = "extra"  # rules engine reports something the reference leaves blank
    elif rules is None:
        status = "missed"
    else:
        status = "match" if (_eq(verified, rules) if isinstance(verified, (int, float)) and not isinstance(verified, bool)
                             and isinstance(rules, (int, float)) else verified == rules) else "mismatch"
    return {"group": group, "field": field, "verified": verified, "rules": rules, "status": status}


def _grid_signature(grid: dict) -> list[tuple]:
    return [tuple(t.get(k) for k, _ in TIER_FIELDS) for t in grid["tiers"]]


def _pair_grids(verified: list[dict], rules: list[dict]) -> list[tuple[dict, dict | None]]:
    """Pair each verified grid with the rules grid sharing the most tier values."""
    free = list(rules)
    pairs = []
    for vg in verified:
        best, best_score = None, 0
        v_vals = {x for row in _grid_signature(vg) for x in row if x is not None}
        for rg in free:
            score = len(v_vals & {x for row in _grid_signature(rg) for x in row if x is not None}) + (
                1 if len(rg["tiers"]) == len(vg["tiers"]) else 0)
            if score > best_score:
                best, best_score = rg, score
        if best is not None:
            free.remove(best)
        pairs.append((vg, best))
    return pairs


def compare(verified: dict, rules: dict) -> dict:
    """Return {"checks": [...], "summary": {...}} for one deal."""
    checks: list[dict] = []
    vp, rp = verified["pricing"], rules["pricing"]

    checks.append(_check("Pricing", "pricing basis", vp["basis"], rp["basis"]))
    checks.append(_check("Pricing", "CSA applies", vp["csa"]["applies"], rp["csa"]["applies"]))
    if vp["csa"]["bps"] is not None or rp["csa"]["bps"] is not None:
        checks.append(_check("Pricing", "CSA (bps)", vp["csa"]["bps"], rp["csa"]["bps"]))
    checks.append(_check("Pricing", "benchmark floor (%)", vp["floor"]["pct"], rp["floor"]["pct"]))

    for gi, (vg, rg) in enumerate(_pair_grids(vp["grids"], rp["grids"])):
        name = f"Grid {gi + 1}: {vg['name']}"[:70]
        if rg is None:
            checks.append({"group": name, "field": "grid", "verified": f"{len(vg['tiers'])} tier(s)", "rules": None, "status": "missed"})
            continue
        checks.append(_check(name, "number of tiers", len(vg["tiers"]), len(rg["tiers"])))
        if vg["undrawn_fee_type"] not in ("none", "not_stated"):
            checks.append(_check(name, "undrawn fee type", vg["undrawn_fee_type"], rg["undrawn_fee_type"]))
        for ti, vt in enumerate(vg["tiers"]):
            rt = rg["tiers"][ti] if ti < len(rg["tiers"]) else None
            for key, label in TIER_FIELDS:
                rv = rt.get(key) if rt else None
                if vt.get(key) is None and rv is None:
                    continue
                checks.append(_check(name, f"tier {vt['level']} {label}", vt.get(key), rv))
        v_open = [t["level"] for t in vg["tiers"] if t["is_opening"]]
        r_open = [t["level"] for t in rg["tiers"] if t["is_opening"]]
        if v_open or r_open:
            checks.append(_check(name, "opening level", ", ".join(v_open) or None, ", ".join(r_open) or None))
    if not vp["grids"] and rp["grids"]:
        checks.append({"group": "Pricing", "field": "grid", "verified": None, "rules": f"{len(rp['grids'])} grid(s)", "status": "extra"})

    r_fees = [f for f in rp["fees"] if f["bps"] is not None]
    used: set[int] = set()
    for vf in vp["fees"]:
        if vf["bps"] is None:
            continue
        hit = next((i for i, rf in enumerate(r_fees) if i not in used and rf["type"] == vf["type"] and _eq(rf["bps"], vf["bps"])), None)
        if hit is None:  # same number filed under another fee type still shows the engine read the figure
            hit = next((i for i, rf in enumerate(r_fees) if i not in used and _eq(rf["bps"], vf["bps"])), None)
        label = f"{vf['type'].replace('_', ' ')}: {vf['description'][:48]}"
        if hit is None:
            checks.append({"group": "Fees", "field": label, "verified": vf["bps"], "rules": None, "status": "missed"})
        else:
            used.add(hit)
            status = "match" if r_fees[hit]["type"] == vf["type"] else "mismatch"
            checks.append({"group": "Fees", "field": label, "verified": f"{vf['bps']:g} bps",
                           "rules": f"{r_fees[hit]['bps']:g} bps" + ("" if status == "match" else f" as {r_fees[hit]['type'].replace('_', ' ')}"),
                           "status": status})
    for i, rf in enumerate(r_fees):
        if i not in used:
            checks.append({"group": "Fees", "field": f"{rf['type'].replace('_', ' ')}: {rf['description'][:48]}", "verified": None,
                           "rules": f"{rf['bps']:g} bps", "status": "extra"})

    r_covs = list(rules["financial_covenants"])
    for vc in verified["financial_covenants"]:
        label = _cov(vc["type"])[0]
        rc = next((c for c in r_covs if c["type"] == vc["type"]), None) or next(
            (c for c in r_covs if _kin(c["type"]) == _kin(vc["type"])), None)
        if rc is None:
            checks.append({"group": "Financial covenants", "field": label, "verified": vc["threshold"], "rules": None, "status": "missed"})
            continue
        r_covs.remove(rc)
        checks.append(_check("Financial covenants", f"{label}: level", vc["threshold"], rc["threshold"]))
        checks.append(_check("Financial covenants", f"{label}: test type", vc["type"], rc["type"]))
        if vc["step_up"]["present"] or rc["step_up"]["present"]:
            checks.append(_check("Financial covenants", f"{label}: acquisition step-up", vc["step_up"]["threshold"], rc["step_up"]["threshold"]))
        if vc["springing"]["is_springing"] or rc["springing"]["is_springing"]:
            checks.append(_check("Financial covenants", f"{label}: springing", vc["springing"]["is_springing"], rc["springing"]["is_springing"]))
    for rc in r_covs:
        checks.append({"group": "Financial covenants", "field": _cov(rc["type"])[0], "verified": None,
                       "rules": rc["threshold"], "status": "extra"})

    checks.append(_check("Deal", "security", verified["security"]["value"], rules["security"]["value"]))
    checks.append(_check("Deal", "credit profile", verified["credit_profile"]["value"], rules["credit_profile"]["value"]))

    def listed(record: dict) -> list[tuple]:  # facilities without a stated size sort after the sized ones of their type
        return sorted(((f["type"], f["amount_mm"]) for f in record["facilities"]), key=lambda t: (t[0], t[1] is None, t[1] or 0))

    v_fac, r_fac = listed(verified), listed(rules)
    checks.append(_check("Deal", "facilities (type, $mm)", "; ".join(f"{t} {a:g}" if a is not None else t for t, a in v_fac),
                         "; ".join(f"{t} {a:g}" if a is not None else t for t, a in r_fac)))

    counts = {s: sum(1 for c in checks if c["status"] == s) for s in ("match", "mismatch", "missed", "extra")}
    scored = counts["match"] + counts["mismatch"] + counts["missed"]
    return {"checks": checks, "summary": {**counts, "total": len(checks), "agreement": round(counts["match"] / scored, 4) if scored else None}}
