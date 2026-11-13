"""Peer statistics: where each term sheet sits against the others on every comparable figure.

All benchmark numbers shown in the front end and written to the CSV exports come from here.
"""
from __future__ import annotations

from statistics import mean, median

# id, label, unit, group, decimals, note
METRICS = [
    ("margin_open", "Drawn margin, opening level", "bps", "pricing", 1, "Applicable margin over SOFR at the tier that applies at closing, where the term sheet says which tier that is. Excludes any credit spread adjustment."),
    ("margin_min", "Drawn margin, best tier", "bps", "pricing", 1, "Lowest margin on the pricing grid. Excludes any credit spread adjustment."),
    ("margin_max", "Drawn margin, worst tier", "bps", "pricing", 1, "Highest margin on the pricing grid. Excludes any credit spread adjustment."),
    ("all_in_open", "All-in drawn, opening level", "bps", "pricing", 1, "Margin plus facility fee at the opening tier (margin alone where the undrawn fee is a commitment fee). Excludes any credit spread adjustment."),
    ("all_in_min", "All-in drawn, best tier", "bps", "pricing", 1, "Lowest margin plus facility fee on the grid. Excludes any credit spread adjustment."),
    ("all_in_max", "All-in drawn, worst tier", "bps", "pricing", 1, "Highest margin plus facility fee on the grid. Excludes any credit spread adjustment."),
    ("undrawn_open", "Undrawn fee, opening level", "bps", "pricing", 2, "Commitment or facility fee at the opening tier."),
    ("undrawn_min", "Undrawn fee, best tier", "bps", "pricing", 2, "Lowest commitment or facility fee."),
    ("undrawn_max", "Undrawn fee, worst tier", "bps", "pricing", 2, "Highest commitment or facility fee."),
    ("upfront_max", "Upfront fee, highest", "bps", "pricing", 1, "Highest upfront fee stated (typically new money or the largest commitment tier)."),
    ("upfront_min", "Upfront fee, lowest", "bps", "pricing", 1, "Lowest upfront fee stated (typically existing commitments)."),
    ("csa", "SOFR credit spread adjustment", "bps", "pricing", 1, "Zero where the term sheet expressly has none; blank where it is silent."),
    ("tiers", "Pricing tiers", "count", "pricing", 0, "Number of tiers on the headline pricing grid."),
    ("leverage", "Maximum leverage, initial level", "x", "covenants", 2, "Level of the primary leverage covenant at closing, or the first level tested where the test only starts later (total, net, secured or first lien as defined in the term sheet)."),
    ("leverage_loosest", "Maximum leverage, loosest scheduled", "x", "covenants", 2, "Highest level the leverage covenant reaches under any dated schedule."),
    ("leverage_step_up", "Maximum leverage, acquisition step-up", "x", "covenants", 2, "Temporary level after a qualifying acquisition."),
    ("coverage", "Minimum interest coverage", "x", "covenants", 2, "Interest coverage covenant at closing. Fixed charge coverage is a different ratio and is not included."),
    ("debt_cap", "Maximum debt / capitalization", "pct", "covenants", 1, "Debt to capitalization covenant level."),
    ("liquidity", "Minimum liquidity", "usd_mm", "covenants", 0, "Minimum liquidity covenant at closing."),
    ("facility_mm", "Total facility size", "usd_mm", "deal", 0, "Sum of the facilities the term sheet covers. Blank where the size of a facility is not final or the amounts are not all in US dollars."),
    ("tenor", "Tenor", "years", "deal", 1, "Tenor of the headline facility where the term sheet states one (the longest tranche where it has several)."),
]
METRIC_IDS = [m[0] for m in METRICS]
PRESETS = {
    # The profile is judged from the form of the facility in the term sheet, not from a rating.
    "all": ("All term sheets", lambda d: True),
    "investment_grade": ("Investment-grade style", lambda d: d["record"]["credit_profile"]["value"] == "investment_grade"),
    "leveraged": ("Leveraged style", lambda d: d["record"]["credit_profile"]["value"] == "leveraged"),
}


def metric_vocab() -> list[dict]:
    return [{"id": i, "label": label, "unit": unit, "group": group, "decimals": dec, "note": note}
            for i, label, unit, group, dec, note in METRICS]


def quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation quantile (the "inclusive" method, as in Excel's PERCENTILE.INC)."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def stats(values: list[float]) -> dict | None:
    if not values:
        return None
    s = sorted(values)
    return {
        "n": len(s), "min": s[0], "p25": round(quantile(s, 0.25), 4), "median": round(median(s), 4),
        "mean": round(mean(s), 4), "p75": round(quantile(s, 0.75), 4), "max": s[-1],
    }


def benchmark(deals: list[dict], ids: list[str] | None = None) -> dict:
    """Peer statistics over ``deals`` (optionally restricted to the given deal ids).

    For each metric: the peer statistics, and for each deal with a value its rank from the lowest
    (ties share the better rank), its mid-rank percentile and its distance from the peer median.
    """
    # a PDF that could not be read has no figures: it is listed in the front end but is never a peer
    peers = [d for d in deals if d.get("readable", True) and (ids is None or d["id"] in ids)]
    out: dict[str, dict] = {}
    for metric in METRIC_IDS:
        have = [(d["id"], d["derived"]["metrics"].get(metric)) for d in peers]
        have = [(i, float(v)) for i, v in have if v is not None]
        values = [v for _, v in have]
        st = stats(values)
        per_deal = {}
        for deal_id, v in have:
            below = sum(1 for x in values if x < v)
            ties = sum(1 for x in values if x == v)
            per_deal[deal_id] = {
                "value": v,
                "rank": below + 1,
                "of": len(values),
                "percentile": round(100.0 * (below + 0.5 * ties) / len(values), 1),
                "vs_median": round(v - st["median"], 4),
            }
        out[metric] = {"stats": st, "deals": per_deal}
    return {"peer_ids": [d["id"] for d in peers], "n": len(peers), "metrics": out}


def presets(deals: list[dict]) -> dict:
    return {key: {"label": label, **benchmark([d for d in deals if keep(d)])} for key, (label, keep) in PRESETS.items()}


def custom(deals: list[dict], ids: list[str]) -> dict:
    """Peer statistics for a hand-picked set of deals, shaped like a preset group."""
    return {"label": "Custom selection", **benchmark(deals, ids)}
