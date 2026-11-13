"""Shared paths, status vocabulary and the attribute checklist."""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DOCS_DIR = APP_DIR.parent / "Hackathon (CA and TS)"
UPLOAD_DIR = APP_DIR / "uploads"
RESULTS_DIR = APP_DIR / "results"
CACHE_DIR = APP_DIR / ".cache"

ENGINES = {
    "verified": "Agent reconciliation (multi-agent)",
    "claude": "Claude API (live)",
    "rules": "Rules engine (offline)",
}

# Status vocabulary shared by every engine.
STATUSES = {
    "match": {"label": "Match", "color": "#1a7f37", "bg": "#d1f2dc", "issue": False},
    "match_minor_drafting": {"label": "Match (minor drafting)", "color": "#2f6f4e", "bg": "#e3f4ea", "issue": False},
    "ts_open_filled_in_ca": {"label": "TS open, set in CA", "color": "#1f5fa8", "bg": "#dbe9fb", "issue": False},
    "review": {"label": "Needs review", "color": "#8a5a00", "bg": "#fdf0c8", "issue": True},
    "differs": {"label": "Differs", "color": "#b42318", "bg": "#fbd5d2", "issue": True},
    "not_in_ca": {"label": "Missing from CA", "color": "#b42318", "bg": "#fde2cf", "issue": True},
    "not_in_ts": {"label": "Not in TS (CA only)", "color": "#5b616e", "bg": "#eceef1", "issue": False},
    "not_applicable": {"label": "N/A", "color": "#8b919c", "bg": "#f6f7f8", "issue": False},
    "missing_document": {"label": "Document missing", "color": "#ffffff", "bg": "#b42318", "issue": True},
}
STATUS_ORDER = list(STATUSES)

# 36-attribute checklist used by the Claude engine and the agent-verified results.
CHECKLIST = {
    "A": (
        "Commercial and economic terms",
        [
            ("A01", "Facility type(s) and structure"),
            ("A02", "Facility amount(s) and total commitments"),
            ("A03", "Currencies available"),
            ("A04", "Maturity / tenor"),
            ("A05", "Extension options / term-out"),
            ("A06", "Accordion / incremental capacity"),
            ("A07", "Letter of credit sublimit"),
            ("A08", "Swingline sublimit"),
            ("A09", "Borrower or other sublimits"),
            ("A10", "Benchmark rates, floors and CSA"),
            ("A11", "Applicable margin / pricing grid"),
            ("A12", "Pricing basis and initial pricing level"),
            ("A13", "Commitment / facility / unused fee"),
            ("A14", "LC participation fee and fronting fee"),
            ("A15", "Upfront, ticking, term-out or other fees"),
            ("A16", "Default interest"),
            ("A17", "Amortization and mandatory prepayments"),
            ("A18", "Optional prepayments, reductions, minimum borrowings"),
            ("A19", "Interest periods, notice periods and day count"),
        ],
    ),
    "B": (
        "Parties, credit support, covenants and legal terms",
        [
            ("B01", "Borrower(s)"),
            ("B02", "Guarantor(s)"),
            ("B03", "Administrative agent and other agent roles"),
            ("B04", "Lead arrangers / bookrunners / titled agents"),
            ("B05", "Purpose / use of proceeds"),
            ("B06", "Security / collateral (incl. fall-away)"),
            ("B07", "Financial covenants"),
            ("B08", "Key negative covenants and baskets"),
            ("B09", "Representations and warranties"),
            ("B10", "Conditions precedent to closing"),
            ("B11", "Conditions to each borrowing"),
            ("B12", "Events of default and thresholds"),
            ("B13", "Change of control"),
            ("B14", "Required lenders, voting and sacred rights"),
            ("B15", "Assignments and participations"),
            ("B16", "Defaulting lender, yield protection, taxes"),
            ("B17", "Governing law and jurisdiction"),
        ],
    ),
}
CHECKLIST_NAMES = {aid: name for _, (_, attrs) in CHECKLIST.items() for aid, name in attrs}

# Indicative Claude Opus 5.5 pricing (USD per million tokens) for the cost estimate shown in the UI.
CLAUDE_MODEL = "claude-opus-5-5"
PRICE_IN_PER_M = 4.00
PRICE_OUT_PER_M = 20.00
PRICE_CACHE_READ_PER_M = 0.20
