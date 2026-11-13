"""The term sheet record and the headline metrics derived from it.

Record layout (one per term sheet; produced by the rules engine or loaded from a verified file)::

    deal, source_file
    doc             kind, title, date, is_amendment, notes
    borrower        name, quote, page
    credit_profile  value (investment_grade | leveraged | unclear), basis
    security        value (secured | unsecured | unclear), detail, quote, page
    facilities[]    id, name, type, amount_mm, currency, tenor_text, tenor_years, maturity_text, quote, page
    pricing
        benchmark, basis (ratings_grid | leverage_grid | flat | other | not_stated), basis_detail
        csa         applies (true | false | null = not mentioned), bps, detail, quote, page
        floor       pct, detail, quote, page
        grids[]     name, facility_ids, metric, undrawn_fee_type, page, opening_level_note, notes
            tiers[] level, criteria, drawn_margin_bps, base_rate_margin_bps, undrawn_fee_bps,
                    all_in_drawn_bps, lc_fee_bps, is_opening, quote
        fees[]      type, facility_ids, description, bps, bps_low, bps_high, amount_text, quote, page
        change_vs_existing, notes
    financial_covenants[]
        type, name, direction (max | min), threshold, unit (x | pct | usd_mm), threshold_text,
        schedule[] (period, threshold), step_up (present, threshold, detail),
        springing (is_springing, trigger), applies_to, test_frequency, definition_notes,
        change_vs_existing, quote, page
    no_financial_covenant_note, format_notes

Rates are in basis points, ratios in turns (x), amounts in millions. A null means the document does
not state the value; nothing is filled in from outside the document.

``derive`` turns a record into the comparable figures the benchmark works on. Two figures are
computed rather than read, and are flagged as such:

* all-in drawn = drawn margin + facility fee, where the undrawn fee is a facility fee (paid on the
  whole commitment, so it is part of the cost of a drawn dollar). With a commitment fee, all-in
  drawn is the margin itself. Where there is a facility fee but its rate for a tier is not known,
  all-in drawn is left empty rather than understated.
* drawn margin = all-in drawn - facility fee, where a grid prints only those two columns.

Neither figure includes a SOFR credit spread adjustment; that is reported on its own.

The total facility size is given only when every facility has a stated US dollar amount. Otherwise
the sum of the stated amounts is kept apart (``size.partial_mm``) so that it is never read as the total.
"""
from __future__ import annotations

import re

from .config import COVENANT_TYPES, FACILITY_CLASS, FACILITY_PRIORITY, FACILITY_TYPES

UNDRAWN_FEE_TYPES = ("commitment_fee", "facility_fee", "ticking_fee")
_EXISTING_GRID_RE = re.compile(r"\b(existing|current|prior)\b", re.IGNORECASE)


def _rng(values: list[float | None], opening: int | None) -> dict:
    present = [v for v in values if v is not None]
    return {
        "min": min(present) if present else None,
        "max": max(present) if present else None,
        "open": values[opening] if opening is not None and values[opening] is not None else None,
    }


def tier_figures(tier: dict, fee_type: str) -> dict:
    """Comparable figures for one tier, with the names of any that were computed rather than read."""
    drawn, undrawn, all_in = tier.get("drawn_margin_bps"), tier.get("undrawn_fee_bps"), tier.get("all_in_drawn_bps")
    computed: list[str] = []
    if drawn is None and all_in is not None and undrawn is not None and fee_type == "facility_fee":
        drawn = round(all_in - undrawn, 4)
        computed.append("margin")
    if all_in is None and drawn is not None:
        if fee_type != "facility_fee":
            all_in = drawn
        elif undrawn is not None:
            all_in = round(drawn + undrawn, 4)
            computed.append("all_in")
        # else: a facility fee applies but this tier does not give it, so the all-in cost is not known
    return {"margin": drawn, "undrawn": undrawn, "all_in": all_in, "computed": computed}


def _facility_rank(ftype: str) -> int:
    return FACILITY_PRIORITY.index(ftype) if ftype in FACILITY_PRIORITY else len(FACILITY_PRIORITY)


def _pricing_line(record: dict, index: int, grid: dict) -> dict:
    facilities = record["facilities"]
    ids = grid.get("facility_ids") or [f["id"] for f in facilities]
    covered = [f for f in facilities if f["id"] in ids] or facilities
    best = min(covered, key=lambda f: _facility_rank(f["type"])) if covered else None
    fee_type = grid.get("undrawn_fee_type") or "not_stated"
    figures = [tier_figures(t, fee_type) for t in grid["tiers"]]
    flagged = [i for i, t in enumerate(grid["tiers"]) if t.get("is_opening")]
    opening = flagged[0] if len(flagged) == 1 else None

    undrawn = _rng([f["undrawn"] for f in figures], opening)
    undrawn_source = "grid"
    if undrawn["min"] is None:  # no fee column in the grid: use a separately stated commitment / facility fee
        stated = [f for f in record["pricing"]["fees"] if f["type"] in UNDRAWN_FEE_TYPES[:2] and f.get("bps") is not None
                  and (not f.get("facility_ids") or set(f["facility_ids"]) & set(ids))]
        if stated:
            fee = stated[0]
            values = [v for v in (fee["bps"], fee.get("bps_low"), fee.get("bps_high")) if v is not None]
            # a single stated rate applies from closing; a stepped fee has no known opening level
            undrawn = {"min": min(values), "max": max(values), "open": fee["bps"] if min(values) == max(values) else None}
            undrawn_source = "fee"
            if fee_type in ("not_stated", "none"):
                fee_type = fee["type"]
            if fee_type == "facility_fee" and fee["type"] == "facility_fee" and min(values) == max(values):
                # paid on drawn amounts too, so it belongs in the all-in cost of every tier that does not print one
                for fig, tier in zip(figures, grid["tiers"]):
                    if tier.get("all_in_drawn_bps") is None and fig["margin"] is not None:
                        fig["all_in"] = round(fig["margin"] + fee["bps"], 4)
                        fig["computed"] = sorted({*fig["computed"], "all_in"})
            elif fee_type != (grid.get("undrawn_fee_type") or "not_stated"):
                # the fee type was only settled here: with a commitment fee the all-in cost is the margin
                figures = [tier_figures(t, fee_type) for t in grid["tiers"]]
    computed = sorted({c for f in figures for c in f["computed"]})
    return {
        "grid": index,
        "name": grid["name"],
        "facility_ids": [f["id"] for f in covered],
        "facility_type": best["type"] if best else "other",
        "facility_class": FACILITY_CLASS.get(best["type"], "other") if best else "other",
        "facility_label": " + ".join(dict.fromkeys(FACILITY_TYPES.get(f["type"], f["type"]) for f in covered)),
        "tiers": len(grid["tiers"]),
        "metric": grid.get("metric", ""),
        "opening_level": grid["tiers"][opening]["level"] if opening is not None else None,
        "opening_criteria": grid["tiers"][opening]["criteria"] if opening is not None else None,
        "margin": _rng([f["margin"] for f in figures], opening),
        "all_in": _rng([f["all_in"] for f in figures], opening),
        "undrawn": undrawn,
        "undrawn_type": fee_type,
        "undrawn_source": undrawn_source,
        "computed": computed,
        "tier_figures": figures,
    }


def _covenant(index: int, cov: dict) -> dict:
    label, family, direction, _ = COVENANT_TYPES.get(cov["type"], COVENANT_TYPES["other"])
    direction = cov.get("direction") or direction
    threshold, unit = cov.get("threshold"), cov.get("unit")
    scale = 100.0 if cov["type"] == "max_debt_to_capitalization" and unit == "x" and threshold is not None and threshold <= 1.5 else 1.0
    if scale != 1.0:
        unit = "pct"
    schedule = cov.get("schedule") or []
    levels = [threshold] + [row.get("threshold") for row in schedule]
    levels = [round(v * scale, 4) for v in levels if v is not None]
    step = cov.get("step_up") or {}
    spring = cov.get("springing") or {}
    # A schedule that opens with "not tested" means the level shown only starts to apply later.
    deferred = bool(schedule) and schedule[0].get("threshold") is None
    starts = next((row.get("period", "") for row in schedule if row.get("threshold") is not None), "") if deferred else ""
    return {
        "index": index,
        "type": cov["type"],
        "label": label,
        "family": family,
        "direction": direction,
        "threshold": round(threshold * scale, 4) if threshold is not None else None,
        "unit": unit,
        # the most permissive level the test ever allows, and the level it ends on
        "loosest": (max(levels) if direction == "max" else min(levels)) if levels else None,
        "final": levels[-1] if levels else None,
        "has_schedule": len(schedule) > 1 and not (deferred and len(schedule) == 2),
        "deferred": deferred,
        "starts": starts,
        "step_up": round(step["threshold"] * scale, 4) if step.get("present") and step.get("threshold") is not None else None,
        "has_step_up": bool(step.get("present")),
        "springing": bool(spring.get("is_springing")),
    }


def derive(record: dict) -> dict:
    """Comparable figures for one term sheet."""
    pricing = record["pricing"]
    lines = [_pricing_line(record, i, g) for i, g in enumerate(pricing["grids"])]

    def headline_key(i: int) -> tuple:
        # a grid labelled as the existing terms never stands for the deal while another grid is there
        return (bool(_EXISTING_GRID_RE.search(lines[i]["name"])), _facility_rank(lines[i]["facility_type"]), -lines[i]["tiers"], i)

    headline = min(range(len(lines)), key=headline_key) if lines else None
    # other grids that could equally have been taken as the headline (same facility type, not marked as existing terms)
    rivals = [i for i in range(len(lines)) if i != headline and headline_key(i)[:2] == headline_key(headline)[:2]] if lines else []

    csa = pricing["csa"]
    csa_status = "stated" if csa.get("applies") else "none" if csa.get("applies") is False else "not_stated"
    csa_bps = csa.get("bps") if csa.get("applies") else 0.0 if csa.get("applies") is False else None

    upfront = [f["bps"] for f in pricing["fees"] if f["type"] == "upfront_fee" and f.get("bps") is not None]
    covenants = [_covenant(i, c) for i, c in enumerate(record["financial_covenants"])]
    primary: dict[str, int] = {}
    for c in sorted(covenants, key=lambda c: (c["springing"], c["index"])):
        if c["threshold"] is not None:
            primary.setdefault(c["family"], c["index"])

    # Other maintenance tests of the same kind as the primary one but at a different level (one level per
    # borrower group, say): the benchmark uses the first listed, and the front end says there are others.
    alternates = {
        family: [c["index"] for c in covenants
                 if c["index"] != i and c["type"] == covenants[i]["type"] and not c["springing"]
                 and c["threshold"] is not None and c["threshold"] != covenants[i]["threshold"]]
        for family, i in primary.items()
    }

    facilities = record["facilities"]
    size = _size(facilities)

    def lead_of(group: list[dict]) -> dict:
        # the facility that stands for the deal: best-ranked type, and the longest tranche of that type
        return min(group, key=lambda f: (_facility_rank(f["type"]), -(f.get("tenor_years") or 0)))

    lead = lead_of(facilities) if facilities else None
    covered = facilities
    if headline is not None:
        covered = [f for f in facilities if f["id"] in lines[headline]["facility_ids"]] or facilities
        lead = lead_of(covered) if covered else None
    tenors = sorted({f["tenor_years"] for f in covered if lead and f["type"] == lead["type"] and f.get("tenor_years") is not None})

    def cov_metric(family: str, key: str = "threshold"):
        return covenants[primary[family]][key] if family in primary else None

    line = lines[headline] if headline is not None else None
    metrics = {
        "margin_open": line["margin"]["open"] if line else None,
        "margin_min": line["margin"]["min"] if line else None,
        "margin_max": line["margin"]["max"] if line else None,
        "all_in_open": line["all_in"]["open"] if line else None,
        "all_in_min": line["all_in"]["min"] if line else None,
        "all_in_max": line["all_in"]["max"] if line else None,
        "undrawn_open": line["undrawn"]["open"] if line else None,
        "undrawn_min": line["undrawn"]["min"] if line else None,
        "undrawn_max": line["undrawn"]["max"] if line else None,
        "tiers": line["tiers"] if line else None,
        "csa": csa_bps,
        "floor": pricing["floor"].get("pct"),
        "upfront_min": min(upfront) if upfront else None,
        "upfront_max": max(upfront) if upfront else None,
        "leverage": cov_metric("leverage"),
        "leverage_loosest": cov_metric("leverage", "loosest"),
        "leverage_step_up": cov_metric("leverage", "step_up"),
        "coverage": cov_metric("coverage"),
        "debt_cap": cov_metric("capitalization"),
        "liquidity": cov_metric("liquidity"),
        "facility_mm": size["total_mm"],
        "tenor": lead.get("tenor_years") if lead else None,
    }
    return {
        "lines": lines,
        "headline": headline,
        "headline_rivals": rivals,
        "csa_status": csa_status,
        "covenants": covenants,
        "primary_covenant": primary,
        "primary_alternates": alternates,
        "n_covenants": len(covenants),
        "lead_facility": lead["id"] if lead else None,
        "tenor_range": [tenors[0], tenors[-1]] if tenors else None,
        "size": size,
        "metrics": metrics,
    }


def _size(facilities: list[dict]) -> dict:
    """Total facility size, or the reason there is none.

    ``total_mm`` is set only when every facility has a stated US dollar amount. When some do not,
    ``partial_mm`` is the sum of those that do: a floor, never to be shown as the total.
    """
    stated = [f for f in facilities if f.get("amount_mm") is not None]
    open_ended = [f for f in facilities if f.get("amount_mm") is None]
    currencies = sorted({(f.get("currency") or "USD").upper() for f in stated})
    if not stated:
        return {"total_mm": None, "partial_mm": None, "note": "The term sheet does not state a facility amount." if facilities else ""}
    if currencies != ["USD"]:
        return {"total_mm": None, "partial_mm": None,
                "note": f"Facility amounts are in {' and '.join(currencies)}, so no US dollar total is shown."}
    amount = round(sum(f["amount_mm"] for f in stated), 4)
    if open_ended:
        # the name without any bracketed description that follows it
        names = ", ".join((f.get("name") or "").split(" (")[0].strip() or FACILITY_TYPES.get(f["type"], f["type"]) for f in open_ended)
        return {"total_mm": None, "partial_mm": amount,
                "note": f"Excludes {names}: the term sheet does not fix {'its' if len(open_ended) == 1 else 'their'} size."}
    return {"total_mm": amount, "partial_mm": None, "note": ""}
