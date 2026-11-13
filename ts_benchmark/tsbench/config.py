"""Paths and shared vocabulary."""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DOCS_DIR = APP_DIR.parent / "Hackathon (CA and TS)"
CACHE_DIR = APP_DIR / ".cache"
VERIFIED_DIR = APP_DIR / "data" / "verified"
VENDOR_DIR = APP_DIR / "vendor"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 8765

FACILITY_TYPES = {
    "revolver": "Revolver",
    "revolver_364_day": "364-day revolver",
    "term_loan_a": "Term loan A",
    "term_loan_b": "Term loan B",
    "delayed_draw_term_loan": "Delayed draw term loan",
    "bridge": "Bridge",
    "lc_facility": "LC facility",
    "other": "Other",
}
# Which facility a deal is benchmarked on when it has several (lower = preferred).
FACILITY_PRIORITY = ["revolver", "revolver_364_day", "term_loan_a", "delayed_draw_term_loan", "term_loan_b", "bridge", "lc_facility", "other"]
FACILITY_CLASS = {
    "revolver": "revolver", "revolver_364_day": "revolver", "lc_facility": "revolver",
    "term_loan_a": "term_loan", "term_loan_b": "term_loan", "delayed_draw_term_loan": "term_loan", "bridge": "term_loan",
    "other": "other",
}

FEE_TYPES = {
    "commitment_fee": "Commitment fee",
    "facility_fee": "Facility fee",
    "ticking_fee": "Ticking fee",
    "upfront_fee": "Upfront fee",
    "extension_fee": "Extension fee",
    "consent_fee": "Consent fee",
    "amendment_fee": "Amendment fee",
    "arrangement_fee": "Arrangement fee",
    "duration_fee": "Duration fee",
    "term_out_fee": "Term-out fee",
    "utilization_fee": "Utilization fee",
    "lc_participation_fee": "LC participation fee",
    "lc_fronting_fee": "LC fronting fee",
    "oid": "OID",
    "prepayment_premium": "Prepayment premium",
    "agency_fee": "Agency fee",
    "other": "Other fee",
}

# type -> (label, family, direction, unit)
COVENANT_TYPES = {
    "max_total_leverage": ("Total leverage", "leverage", "max", "x"),
    "max_net_leverage": ("Net leverage", "leverage", "max", "x"),
    "max_first_lien_leverage": ("First lien leverage", "leverage", "max", "x"),
    "max_secured_leverage": ("Secured leverage", "leverage", "max", "x"),
    "min_interest_coverage": ("Interest coverage", "coverage", "min", "x"),
    # its own family: fixed charge coverage (EBITDAR over interest plus rent) is not comparable with interest coverage
    "min_fixed_charge_coverage": ("Fixed charge coverage", "fixed_charge", "min", "x"),
    "max_debt_to_capitalization": ("Debt / capitalization", "capitalization", "max", "pct"),
    "min_liquidity": ("Minimum liquidity", "liquidity", "min", "usd_mm"),
    "min_net_worth": ("Minimum net worth", "net_worth", "min", "usd_mm"),
    "min_collateral_coverage": ("Collateral coverage", "collateral", "min", "x"),
    "other": ("Other", "other", "max", "x"),
}
COVENANT_FAMILIES = {
    "leverage": "Maximum leverage",
    "coverage": "Minimum interest coverage",
    "fixed_charge": "Minimum fixed charge coverage",
    "capitalization": "Maximum debt / capitalization",
    "liquidity": "Minimum liquidity",
    "net_worth": "Minimum net worth",
    "collateral": "Minimum collateral coverage",
    "other": "Other",
}

PRICING_BASIS = {
    "ratings_grid": "Ratings grid",
    "leverage_grid": "Leverage grid",
    "flat": "Flat",
    "other": "Other",
    "not_stated": "Not stated",
}
