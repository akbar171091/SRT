"""Rules engine: turn the text of one term sheet into a structured pricing and covenant record.

Deterministic and offline. It reads the page text only, so it also works on term sheets it has
never seen, within the limits of pattern matching: every value it returns carries the verbatim
quote and page it came from, so a reader can check it against the PDF.

The record layout is documented in ``schema.py``.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import tables, views
from .blocks import Block, find_blocks
from .config import FACILITY_CLASS, FACILITY_TYPES, FEE_TYPES
from .covenants import extract_covenants
from .textmodel import Doc, clip, fragments, is_footer, squash, tidy
from .values import AMOUNT_RE, RATE_RE, amount_mm, rate_bps

_OPEN_QUOTE = chr(0x201C)
_BULLETS = "".join(map(chr, (0x2022, 0x00B7, 0xF0B7)))
_NS = r"(?:[^.;]|\.(?=\d))"  # any character that does not end a sentence (a decimal point is fine)
# Where one statement ends in a page's flow text: a full stop or semicolon, or the start of the next "Label:" row.
_SENT_END_RE = re.compile(r"(?<=[a-z0-9)\]%\"" + chr(0x201D) + r"])[.;]\s+(?=[A-Z(\"" + _OPEN_QUOTE + _BULLETS + r"])"
                          r"|\s+(?=[A-Z][\w/&'\-]*(?:\s[\w/&'\-]+){0,4}:\s)")
_RATING = r"(?:AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|Aaa|Aa[123]|A[123]|Baa[123]|Ba[123]|B[123])"
_RATING_PAIR_RE = re.compile(r"(?<![A-Za-z])" + _RATING + r"\s*/\s*" + _RATING + r"(?![A-Za-z0-9])")
_IG_RE = re.compile(r"(?<![A-Za-z])(?:AAA|AA[+-]?|A[+-]?|BBB[+-]?|Aaa|Aa[123]|A[123]|Baa[123])(?![A-Za-z0-9+-])")
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7}

_FACILITY_PATTERNS = [
    ("revolver_364_day", r"364[-\s]*day"),
    ("delayed_draw_term_loan", r"delayed[-\s]draw"),
    ("term_loan_b", r"term\s+loan\s+b\b|term\s+b\s+(?:loan|facility)|\btlb\b"),
    ("term_loan_a", r"term\s+loan\s+a\b|term\s+a\s+(?:loan|facility)|\btla\b"),
    ("bridge", r"\bbridge\b"),
    ("revolver", r"revolving|revolver|\brcf\b"),
    ("term_loan_a", r"term\s+loans?\b|term\s+facilit"),
]
_NOT_A_FACILITY_RE = re.compile(
    r"sublimit|sub-limit|increase|incremental|accordion|swing|not\s+to\s+exceed|greater\s+of|basket|threshold|in\s+excess|"
    r"at\s+least|minimum|liquidity|fee|issuance\s+of|letters?\s+of\s+credit|per\s+annum",
    re.IGNORECASE,
)

# (fee type, label pattern, True when the clause must itself say "fee" or "premium")
_FEE_LABELS = [
    ("commitment_fee", r"(?:commitment|unused|undrawn)(?:\s+line)?\s+fees?(?:\s+rate)?", False),
    ("facility_fee", r"(?:364[-\s]*day\s+)?facility\s+fees?", False),
    ("ticking_fee", r"ticking\s+fees?", False),
    ("upfront_fee", r"(?:up-?\s?front|closing|participation)\s+fees?", False),
    ("extension_fee", r"extension\s+fees?", False),
    ("consent_fee", r"consent\s+fees?", False),
    ("amendment_fee", r"amendment\s+fees?", False),
    ("duration_fee", r"duration\s+fees?", False),
    ("term_out_fee", r"term[-\s]out(?:\s+option)?(?:\s+(?:fee|premium)s?)?|term\s+loan\s+conversion(?:\s+option)?", True),
    ("utilization_fee", r"utili[sz]ation\s+fees?", False),
    ("lc_fee", r"(?:letters?\s+of\s+credit|l/?c)\s+fees?", False),
    ("arrangement_fee", r"arrangement\s+fees?", False),
]
_SAME_RE = views.SAME_AS_EXISTING_RE


def _sentence(text: str, start: int, end: int, back: int = 320, ahead: int = 160) -> tuple[int, int]:
    """Where the sentence holding text[start:end] begins and ends, looking no further than ``back`` and ``ahead`` characters."""
    lo, hi = max(0, start - back), min(len(text), end + ahead)
    cuts = [m.end() for m in _SENT_END_RE.finditer(text, lo, min(len(text), start + 60)) if m.end() <= start]
    stop = _SENT_END_RE.search(text, end, hi)
    return (cuts[-1] if cuts else lo), (stop.start() + 1 if stop else hi)


class _Context:
    """One term sheet: the proposed-terms view everything reads, plus the existing-terms view to fall back on."""

    def __init__(self, pages: list[str]):
        self.raw = Doc(pages)
        self.doc, self.existing, self.split_pages = views.split_views(self.raw)
        self.notes: list[str] = []
        self.changes: list[str] = []  # "from A to B" wording: what a proposed term replaces
        self.flow = {p: tidy(" ".join(ln.text for ln in self.doc.page_lines(p) if not is_footer(ln.text)))
                     for p in range(1, len(pages) + 1)}
        self.all_text = " ".join(self.flow.values())
        self.plain_comparison = not self.split_pages and any(
            re.search(r"existing\s+terms\s+proposed\s+terms", t, re.IGNORECASE) for t in self.flow.values())

    def blocks(self, pattern: str, max_lines: int = 140) -> list[Block]:
        """Blocks from the proposed view; a cell that only says 'Same as existing' is read from the existing view."""
        out = []
        for b in find_blocks(self.doc, pattern, max_lines):
            if b.page in self.split_pages and (_SAME_RE.match(b.text) or not b.text):
                other = [e for e in find_blocks(self.existing, pattern, max_lines) if e.line.n == b.line.n]
                if other:
                    b = other[0]
            out.append(b)
        return out

    def evidence(self, text: str, page: int | None, span: tuple[int, int] | None = None) -> tuple[str, int | None]:
        """A verbatim quote for a passage, checked against the page text, and the page it is on.

        Returns an empty quote when nothing can be tied to the PDF text, rather than an unverified one.
        """
        tries: list[str] = []
        if span:  # the passage that matters first, in ever tighter windows, so the quote always shows the value
            s, e = span
            s = max(s, e - 290)  # a long passage: keep its end, where the value sits

            def window(pad: int) -> str:
                a, b = max(0, s - pad), min(len(text), e + pad)
                while 0 < a < s and not text[a - 1].isspace():
                    a += 1  # do not start mid-word
                while e < b < len(text) and not text[b].isspace():
                    b -= 1  # do not stop mid-word
                return text[a:b]

            tries = [window((300 - (e - s)) // 2), window(110), window(40), window(0)]
        if not span or len(tidy(text)) <= 300:
            tries.append(text)
        for q in (clip(t, 300) for t in tries):
            if len(q) < 4:
                continue
            if page and self.raw.has_quote(q, page):
                return q, page
            hits = self.raw.find_quote(q)
            if hits:
                return q, hits[0]
        return "", page


def extract(pages: list[str], deal: str, source_file: str) -> dict:
    """Extract one term sheet. Returns a record in the shared schema plus engine notes under ``_engine``."""
    ctx = _Context(pages)
    facilities = _facilities(ctx)
    grids = _grids(ctx, facilities)
    fees = _fees(ctx, grids, facilities)
    covenants = extract_covenants(ctx)
    pricing = {
        "benchmark": _benchmark(ctx),
        "basis": _basis(grids),
        "basis_detail": "; ".join(dict.fromkeys(g["metric"] for g in grids if g["metric"])),
        "csa": _csa(ctx),
        "floor": _floor(ctx),
        "grids": grids,
        "fees": fees,
        "change_vs_existing": " ".join(ctx.changes) or None,
        "notes": "",
    }
    security = _security(ctx, pricing)
    undrawn = [f for f in fees if f["type"] in ("commitment_fee", "facility_fee")]
    for g in grids:  # the grid has no fee column but the fee is stated on its own line
        if g["undrawn_fee_type"] == "not_stated" and undrawn:
            g["undrawn_fee_type"] = undrawn[0]["type"]
    for g in grids:
        g.pop("_lines", None)
    if not grids:
        ctx.notes.append("No pricing grid or flat margin was recognised.")
    if not covenants:
        ctx.notes.append("No financial covenant section was recognised.")
    return {
        "deal": deal,
        "source_file": source_file,
        "doc": _doc_info(ctx),
        "borrower": _borrower(ctx, deal),
        "credit_profile": _credit_profile(pricing, security),
        "security": security,
        "facilities": facilities,
        "pricing": pricing,
        "financial_covenants": covenants,
        "no_financial_covenant_note": None if covenants else "The rules engine found no financial covenant section in this document.",
        "format_notes": "",
        "_engine": {"name": "rules", "notes": ctx.notes, "split_pages": sorted(ctx.split_pages)},
    }


# ---------------------------------------------------------------------------------------------- document level


def _doc_info(ctx: _Context) -> dict:
    n_pages = len(ctx.raw.pages)
    head = " ".join(list(ctx.flow.values())[:3]).lower()
    words = sum(len(t.split()) for t in ctx.flow.values())
    if n_pages <= 2:
        kind = "summary"
    elif re.search(r"forward[- ]looking statements|lender presentation|public lender|management presentation", head) or (
        n_pages > 15 and words / n_pages < 330
    ):
        kind = "lender_presentation"
    else:
        kind = "term_sheet"
    title = next((tidy(ln.text) for ln in ctx.raw.lines if len(tidy(ln.text)) > 8 and re.search(r"[A-Za-z]{4}", ln.text)
                  and ln.text.isascii()), "")
    amend = len(re.findall(r"existing\s+(?:credit\s+agreement|terms|facility|revolv)|same\s+as\s+existing|amend(?:ment|ed)\b|"
                           r"\bextension\s+of\s+the\b|upsize", ctx.all_text, re.IGNORECASE))
    return {"kind": kind, "title": clip(title, 120), "date": _doc_date(ctx, kind), "is_amendment": amend >= 3, "notes": ""}


_DATE_RE = re.compile(r"\b(?:(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})"
                      r"|(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(20\d{2}|\d{2}))\b")
# "[CS&M Draft - 03/26/2026]", "Posting Version 6/5/2026": a stamp opens its line, and the date closes it. A sentence
# that speaks of a draft or a version of some other document does neither.
_STAMP_RE = re.compile(r"^(?:\S+\s+){0,3}?\W*(?:draft|version)\b(?:\s+(?:of|dated))?[^A-Za-z0-9]{0,8}$", re.IGNORECASE)
_STAMP_END_RE = re.compile(r"[^A-Za-z0-9]*$")
# The line above a date ends a label ("Maturity Date:") or stops mid-sentence, on a word in lower case ("dated as of"):
# the date belongs to it. A title ends on a capitalised word; a heading that names a date ("Scheduled Maturity") is no title.
_LEADS_ON_RE = re.compile(r"(?:\b[a-z][\w'\-]*|[,(:])\s*$|(?i:\b(?:matur\w*|expir\w*|terminat\w*|closing|effective|funding|signing)\b[^.]{0,20}$)")
_TITLE_LINES = 15


def _iso_date(m: re.Match) -> str | None:
    """A ``_DATE_RE`` match as an ISO date; None when it is no calendar date or lies in the future (a maturity, not today's document)."""
    try:
        if m.group(1):
            day = datetime.strptime(" ".join(m.group(1, 2, 3)), "%B %d %Y").date()
        else:
            year = int(m.group(6))
            day = datetime(year + 2000 if year < 100 else year, int(m.group(4)), int(m.group(5))).date()
    except ValueError:
        return None
    return day.isoformat() if day <= datetime.now().date() else None


def _doc_date(ctx: _Context, kind: str) -> str | None:
    """The date of the document itself: a draft or version stamp, or a date alone on a line of the title area.

    Dates in running text are left alone: on a first page they are maturities and the dates of earlier agreements.
    """
    for page in (1, 2) if kind == "lender_presentation" else (1,):
        lines = [ln.text.strip() for ln in ctx.raw.page_lines(page) if not ln.blank]
        found = [m for text in lines for m in _DATE_RE.finditer(text)
                 if _STAMP_RE.match(text[: m.start()]) and _STAMP_END_RE.fullmatch(text, m.end())]
        for above, text in zip([""] + lines, lines[:_TITLE_LINES]):
            m = _DATE_RE.fullmatch(re.sub(r"^(?:dated?:?|as\s+of)\s+", "", text, flags=re.IGNORECASE))
            if m and (not _LEADS_ON_RE.search(above) or re.fullmatch(r"dated?\s*:", above, re.IGNORECASE)):
                found.append(m)
        for day in filter(None, map(_iso_date, found)):
            return day
    return None


def _borrower(ctx: _Context, deal: str) -> dict:
    stop = (r"(?=\s*\((?:the\s+)?[" + _OPEN_QUOTE + r"\"]|,\s+an?\s+[A-Z]?\w+\s+(?:corporation|company|limited)|;|\s+Same\s+as\s+existing|$)")
    for b in ctx.blocks(r"(?:the\s+)?borrowers?(?:\s*\(s\))?", 12):
        text = b.text
        m = re.match(r"^(?:\(i\)\s*)?(.+?)" + stop, text)
        name = clip(m.group(1) if m else text, 140).rstrip(" ,;")
        if len(name) < 3 or _SAME_RE.match(name):
            continue
        quote, page = ctx.evidence(text, b.page, (0, min(len(text), 110)))
        return {"name": name, "quote": quote, "page": page}
    return {"name": deal, "quote": "", "page": None}


# The collateral section itself says there is none. "Unsecured" further on is about something else: the kind of rating
# that releases the collateral, other debt, or what the facility becomes once the collateral falls away.
_NO_COLLATERAL_RE = re.compile(r"^\W*(?:none|no\s+(?:collateral|security)|n\s?/\s?a|not\s+applicable)\b|\bnot\s+be\s+secured"
                               r"|\bunsecured\b(?!\s+(?:[\w\-]+\s+){0,3}?(?:debt|notes?|bonds?|indebtedness|ratings?|creditors?|claims?)\b)",
                               re.IGNORECASE)
_COLLATERAL_RE = re.compile(r"security\s+interest|\bliens?\b|pledge|first[-\s]priority|perfected|secured\s+by", re.IGNORECASE)
# Not the "secured" inside "unsecured"; a collateral section that only lists what is charged ("All assets of the Borrower") is secured.
_SECURED_RE = re.compile(r"\bsecured\b|\bliens?\b|pledge|security\s+interest|collateral|\ball\s+(?:of\s+the\s+)?(?:[\w\-]+\s+){0,3}?assets\b",
                         re.IGNORECASE)
_IS_UNSECURED_RE = re.compile(r"\b(?:be|is|are|remain)\s+unsecured\b|\bnot\s+be\s+secured", re.IGNORECASE)
_FALL_AWAY_RE = re.compile(r"releas|fall\w*\s+away|whereupon", re.IGNORECASE)


def _security(ctx: _Context, pricing: dict) -> dict:
    for b in ctx.blocks(r"(?:collateral|security)(?:\s+and\s+guarantees?)?", 30):
        text = b.text
        low = text.lower()[:600]
        opening = re.split(r"[.;]\s", low, maxsplit=1)[0]
        none, some = _NO_COLLATERAL_RE.search(opening), _COLLATERAL_RE.search(opening)
        if none and (not some or none.start() < some.start()):  # whichever the sentence leads with
            value = "unsecured"
        elif _SECURED_RE.search(low):
            value = "secured"
        elif _IS_UNSECURED_RE.search(low):
            value = "unsecured"  # said after the opening sentence, in a section that names no collateral at all
        else:
            continue
        m = re.search(r"none|unsecured|not be secured|first[- ]priority|perfected|lien|pledge|security interest|secured", text, re.IGNORECASE)
        quote, page = ctx.evidence(text, b.page, (m.start(), m.end()) if m else None)
        detail = clip(text, 240)
        release = next((s for s in re.split(r"(?<=[.;])\s+", text) if _FALL_AWAY_RE.search(s)
                        and re.search(r"unsecured|investment[-\s]grade", s, re.IGNORECASE)), "") if value == "secured" else ""
        if release and clip(release, 60) not in detail:
            detail += " [...] " + clip(release, 200)  # secured at closing; the reader should see when that ends
        return {"value": value, "detail": detail, "quote": quote, "page": page}
    unsec_pat = r"senior unsecured|\bunsecured (?:revolving|credit|facility|term)"
    sec_pat = r"senior secured|first[- ]priority|first lien|\bsecured (?:revolving|credit facility|term)"
    unsec = len(re.findall(unsec_pat, ctx.all_text, re.IGNORECASE))
    sec = len(re.findall(sec_pat, ctx.all_text, re.IGNORECASE))
    if unsec or sec:
        value, pat = ("unsecured", unsec_pat) if unsec > sec else ("secured", sec_pat)
        for p, text in ctx.flow.items():
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                quote, page = ctx.evidence(text, p, (m.start(), m.end()))
                return {"value": value, "detail": f"The document describes the facility as {m.group(0).lower()}.", "quote": quote, "page": page}
    for p, text in ctx.flow.items():
        m = re.search(r"rank\w*\s+(?:at\s+least\s+)?pari\s+passu\s+with" + _NS + r"{0,80}?unsecured", text, re.IGNORECASE)
        if m:
            quote, page = ctx.evidence(text, p, (m.start(), m.end()))
            return {"value": "unsecured", "detail": "Inferred: the obligations rank pari passu with other unsecured debt and no "
                    "collateral provision was found.", "quote": quote, "page": page}
    grids = pricing["grids"]
    if pricing["basis"] == "ratings_grid" and grids and _IG_RE.search(_best_tier(grids)["criteria"]) and not re.search(
            r"secured\s+by|security\s+interest|first[-\s]priority|perfected|collateral\s+(?:agent|documents?)|\bpledge", ctx.all_text, re.IGNORECASE):
        return {"value": "unsecured", "detail": "Inferred: investment-grade ratings grid and no collateral or security provision "
                "anywhere in the document.", "quote": "", "page": None}
    return {"value": "unclear", "detail": "", "quote": "", "page": None}


def _best_tier(grids: list[dict]) -> dict:
    def rate(t: dict) -> float:
        for key in ("drawn_margin_bps", "all_in_drawn_bps", "undrawn_fee_bps"):
            if t.get(key) is not None:
                return t[key]
        return 1e9
    return min((t for g in grids for t in g["tiers"]), key=rate)


def _credit_profile(pricing: dict, security: dict) -> dict:
    grids = pricing["grids"]
    if pricing["basis"] == "ratings_grid" and grids:
        top = _best_tier(grids)["criteria"]
        if _IG_RE.search(top) or re.search(r"\bat\s+least\s+(?:AA|A)", top):
            return {"value": "investment_grade", "basis": "Ratings-based pricing grid whose best tier is an investment-grade rating"
                    + (" on an unsecured facility." if security["value"] == "unsecured" else ".")}
        if _RATING_PAIR_RE.search(top):
            return {"value": "leveraged", "basis": "Ratings-based pricing grid confined to sub-investment-grade ratings."}
    margins = [t["drawn_margin_bps"] for g in grids for t in g["tiers"] if t["drawn_margin_bps"] is not None]
    reasons = [text for text, on in (
        ("leverage-based pricing grid", pricing["basis"] == "leverage_grid"),
        ("secured facility", security["value"] == "secured"),
        ("drawn margins of 200 bps or more", bool(margins) and min(margins) >= 200),
    ) if on]
    if reasons:
        return {"value": "leveraged", "basis": "Judged from: " + ", ".join(reasons) + "."}
    return {"value": "unclear", "basis": "No ratings grid, leverage grid or security description was recognised."}


# ---------------------------------------------------------------------------------------------- facilities


# "five-year", "5 years", "five (5) years", "3.5 years" (not the "5 years" in it); not the length of an extension option
_YEARS_RE = re.compile(r"(?<![\d.,])\b(\d{1,2}(?:\.\d)?|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*\(\d{1,2}\))?[-\s]+years?\b"
                       r"(?!\s+(?:extension|renewal))", re.IGNORECASE)
_ANNIVERSARY_RE = re.compile(r"\b(first|second|third|fourth|fifth|sixth|seventh)\s+anniversary", re.IGNORECASE)
# Words before a number of years that make it something other than this facility's tenor: the facility being replaced
# ("the existing three-year facility") or a length of time ("extended by one year", "extended for one year", "within two years").
_NOT_A_TENOR_RE = re.compile(r"\b(?:existing|current|prior|previous|replac\w+|refinanc\w+)\s+(?:[\w$,.'\-]+\s+){0,3}$"
                             r"|\b(?:by|additional|further|another|within|last|past|preceding|each|every|up\s+to|successive|consecutive)\s+(?:an?\s+|the\s+)?$"
                             r"|\bexten\w+\s+(?:[A-Za-z]+\s+){0,4}?for\s+(?:(?:an?|up\s+to|two|three)\s+){0,2}$", re.IGNORECASE)
_MATURES_RE = re.compile(r"(?:matur|terminat|due\s+and\s+payable)" + _NS + r"*(?:closing|effective|funding)", re.IGNORECASE)
_ASIDE_RE = re.compile(r"\s*(?:\([^)]{0,40}\)\s*)?")  # what may stand between an amount and its tenor: "$500 million (the "Facility") five-year"


def _names_other_facility(text: str, at: int, ftype: str) -> bool:
    """True when the words that follow a tenor ending at ``at`` name a facility of another class than ``ftype``."""
    tail = re.split(r"[,.;:()]", text[at: at + 45])[0]
    named = [(k.start(), t) for t, pat in _FACILITY_PATTERNS for k in [re.search(pat, tail, re.IGNORECASE)] if k]
    return bool(named) and FACILITY_CLASS.get(min(named)[1]) != FACILITY_CLASS.get(ftype)


def _tenors(text: str, ftype: str = "") -> list[float]:
    """Every tenor the text names in years, or failing that as an anniversary.

    The tenor of a facility being replaced is not one. Nor, for a facility of type ``ftype``, is a tenor that names another
    kind of facility ("a seven-year term loan B" in the sentence that gives a revolver's amount).
    """
    for pattern in (_YEARS_RE, _ANNIVERSARY_RE):
        found = [m.group(1).lower() for m in pattern.finditer(text) if not _NOT_A_TENOR_RE.search(text, max(0, m.start() - 160), m.start())
                 and not (ftype and _names_other_facility(text, m.end(), ftype))]
        years = [float(_WORD_NUM.get(v) or v) for v in found]
        if any(years):
            return [y for y in years if y]
    return []


def _tenor_years(text: str, ftype: str) -> float | None:
    """The one tenor ``text`` states; None when it states none, or several (tranches) and so no single one."""
    if ftype == "revolver_364_day":
        return 1.0
    found = set(_tenors(text))
    return found.pop() if len(found) == 1 else None


def _main_facility_type(ctx: _Context) -> str:
    low = ctx.all_text.lower()
    counts: dict[str, int] = {}
    for ftype, pat in _FACILITY_PATTERNS[:6]:
        counts[ftype] = counts.get(ftype, 0) + len(re.findall(pat, low))
    return max(counts, key=counts.get) if any(counts.values()) else "other"


def _facility(n: int, ftype: str, amount: float | None, tenor: float | None, quote: str, page: int | None, currency: str = "USD") -> dict:
    return {"id": f"F{n}", "name": FACILITY_TYPES[ftype], "type": ftype, "amount_mm": round(amount, 3) if amount else None,
            "currency": currency, "tenor_text": "", "tenor_years": tenor, "maturity_text": None, "quote": quote, "page": page}


# An amount in another currency, with the groups of values.AMOUNT_RE so that amount_mm reads it too.
_SIGNS = {chr(0x20AC): "EUR", chr(0xA3): "GBP"}  # the euro and pound signs
_FX_AMOUNT_RE = re.compile(r"(?:\b(?:USD|EUR|GBP|CHF|JPY|CAD|AUD)\s?|[" + "".join(_SIGNS) + r"]\s?)"
                           r"(\d{1,3}(?:,\d{3}){1,5}(?:\.\d{1,6})?|\d{1,15}(?:\.\d{1,6})?)\s*((?i:billion|million|bn\b|mm\b|b\b|m\b))?")
_DOLLARS = {"US": "USD", "USD": "USD", "C": "CAD", "CA": "CAD", "CDN": "CAD", "CAN": "CAD", "CAD": "CAD", "A": "AUD", "AU": "AUD", "AUD": "AUD",
            "NZ": "NZD", "NZD": "NZD", "HK": "HKD", "HKD": "HKD", "S": "SGD", "SG": "SGD", "SGD": "SGD"}
# Letters glued to the dollar sign ("C$", "Cdn$"), or a code and a space; "A $500 million" is an article, not Australian dollars.
_DOLLAR_CODE_RE = re.compile(r"(?<![A-Za-z])(?:([A-Z]{1,3}|Cdn\.?|Can\.?)|(USD|CAD|AUD|NZD|HKD|SGD)\s)\$\s?$")
_FACILITY_LABEL = r"(?:total\s+)?(?:facility|facilities)(?:\s+(?:amount|size))?|amounts?|(?:total\s+)?commitments?|size"
_BACKGROUND_LABEL = r"purpose|use\s+of\s+proceeds|background|existing\s+(?:credit\s+)?(?:facilit\w+|agreements?)"  # sections that describe other debt
# What the words leading up to an amount say about it (see _amount_rank).
_RESIZED_RE = re.compile(r"(?:\b(?:upsized?|upsizing|increased?|raised)\s+(?:(?:from|by)\s+[^.;]{0,40}?\s+)?"
                         r"|(?P<bare>\bfrom\s+\S+(?:\s+(?:million|billion|mm|bn))?\s+))"
                         r"to\s+(?:an?\s+)?(?:aggregate\s+)?(?:(?:principal\s+)?amount\s+of\s+)?(?:up\s+to\s+)?$", re.IGNORECASE)
# "from $50 million to $100 million" on its own is a span of amounts (commitments, borrowings): a change of size says what it is
_SIZE_CHANGE_RE = re.compile(r"\b(?:upsiz|increas|rais|reduc|decreas|downsiz|expan|enlarg)\w*", re.IGNORECASE)
_AT_OPTION_RE = re.compile(r"\b(?:may|can|could|request\w*|option\w*|right|ability|permit\w*|elect\w*|incremental|accordion|uncommitted)\b",
                           re.IGNORECASE)
# Only words that describe a facility may stand between "existing" (or "refinance the") and the amount: the amount is then
# that facility's, and not one that merely follows in the same sentence ("to refinance existing debt under the $600 million ...").
_OF_A_FACILITY = (r"(?:(?:senior|secured|unsecured|revolving|credit|term|loan|facilit\w+|agreement|commitments?|[\w\-]*year|[\w\-]*day|"
                  r"multi-?currency|of|in|an?|the|aggregate|principal|amount|up|to|[AB])\s+){0,10}$")
_EXISTING_RE = re.compile(r"(?<!same as )\b(?:existing|current)\s+" + _OF_A_FACILITY, re.IGNORECASE)
_SUPERSEDED_RE = re.compile(r"\b(?:refinanc\w*|replac\w*|(?:pre|re)pa(?:y|id)\w*)\s+(?:in\s+full\s+)?(?:(?:the|its|their|all)\s+|[\w.]+['" + chr(0x2019)
                            + r"]s\s+){0,3}"
                            r"(?:(?:existing|current|outstanding)\s+)?" + _OF_A_FACILITY
                            # a term sheet with a name of its own ("the Term Loan Facility Term Sheet"), not this one
                            + r"|\bas\s+defined\s+in\s+the\s+[^$.;()\s][^$.;()]{0,60}?\s+term\s+sheet\b[^$.;]{0,110}$", re.IGNORECASE)


def _amounts(text: str) -> list[re.Match]:
    return sorted([*AMOUNT_RE.finditer(text), *_FX_AMOUNT_RE.finditer(text)], key=lambda m: m.start())


def _currency(text: str, m: re.Match) -> str:
    """Currency of a matched amount: its own marker ("EUR", a pound sign) or the letters in front of the dollar sign ("C$")."""
    if "$" not in m.group(0):
        marker = text[m.start(): m.start(1)].strip()
        return _SIGNS.get(marker, marker)
    letters = _DOLLAR_CODE_RE.search(text, max(0, m.start() - 6), m.start(1))
    code = (letters.group(1) or letters.group(2)).rstrip(".").upper() if letters else "US"
    return _DOLLARS.get(code, code + "$")


def _facility_type(text: str, m: re.Match, resized: bool) -> str | None:
    """The kind of facility an amount is stated for: the nearest facility word in the same clause.

    ``resized`` says the amount is one side of a committed change of size, where "increased" is not the wording of an accordion.
    """
    lo = max(0, m.start() - 130)
    best: tuple[int, str] | None = None
    for ftype, pat in _FACILITY_PATTERNS:
        for k in re.finditer(pat, text[lo: m.end() + 130], re.IGNORECASE):
            a, b = sorted((lo + k.start(), m.start()))
            between = text[a: max(lo + k.end(), m.end())]
            if _NOT_A_FACILITY_RE.search(re.sub(r"(?i)\bincreased?\b", " ", between) if resized else between) or re.search(r"[.;]\s", between):
                continue
            if best is None or b - a < best[0]:
                best = (b - a, ftype)
    if best and best[1] == "revolver" and re.search(r"364[-\s]*day", text[max(0, m.start() - 60): m.end() + 80], re.IGNORECASE):
        return "revolver_364_day"
    return best[1] if best else None


def _amount_rank(lead: str) -> int:
    """How well an amount stands for the facility on offer, judged from the words of its sentence that lead up to it.

    0 the size after an upsize ("upsized to", "from $400 million to"), 1 nothing said, 2 the existing size, 3 a facility that
    is being refinanced or is the subject of another term sheet.
    """
    resized = _RESIZED_RE.search(lead)
    if resized and not _AT_OPTION_RE.search(lead) and (not resized.group("bare") or _SIZE_CHANGE_RE.search(lead, 0, resized.start())):
        return 0
    if _SUPERSEDED_RE.search(lead):
        return 3
    return 2 if _EXISTING_RE.search(lead) or _changed_from(lead) else 1


def _facility_tenor(ctx: _Context, text: str, m: re.Match, ftype: str) -> float | None:
    """Tenor of the facility whose amount is ``m``.

    Read from the words at the amount ("$500 million five-year revolver", "a five-year revolver of $500 million"), else the one
    tenor its sentence names, else a maturity sentence right after it. A sentence naming several tenors (tranches) gives none.
    """
    if ftype == "revolver_364_day":
        return 1.0
    a, z = _sentence(text, m.start(), m.end(), 250, 700)
    lead = text[a: m.start()]
    beside = _YEARS_RE.match(text, _ASIDE_RE.match(text, m.end()).end())
    at_amount = _tenors(beside.group(0)) if beside else _tenors(lead[max((x.end() for x in _amounts(lead)), default=0):], ftype)
    if at_amount:
        return at_amount[-1]
    near = set(_tenors(text[a: min(z, m.end() + 350)], ftype))
    if near and len(set(_tenors(text[a:z], ftype))) > 1:
        ctx.notes.append(f"{FACILITY_TYPES[ftype]}: the amount is stated with more than one tenor, so no tenor was read from it.")
        return None
    if near:
        return near.pop()
    after = next((s for s in _SENT_END_RE.split(text[z: m.end() + 350]) if _MATURES_RE.search(s)), "")  # "... terminate five years after the Closing Date"
    return _tenor_years(after, ftype)


def _section_amounts(ctx: _Context, label: str) -> set[float]:
    return {round(amount_mm(m) or 0, 3) for b in ctx.blocks(label, 8) for m in _amounts(b.text)}


def _facilities(ctx: _Context) -> list[dict]:
    aside = _section_amounts(ctx, _BACKGROUND_LABEL) - _section_amounts(ctx, _FACILITY_LABEL)
    cands: list[tuple[int, bool, int, str, int, re.Match]] = []  # (rank, stated only as background, order, type, page, amount)
    for p in dict.fromkeys(sorted(ctx.flow)[:8] + sorted(ctx.split_pages)):
        text = ctx.flow[p]
        for m in _amounts(text):
            amount = amount_mm(m)
            if amount is None or amount < 50:
                continue
            lead = text[_sentence(text, m.start(), m.end(), 200)[0]: m.start()]
            rank = _amount_rank(lead)
            ftype = _facility_type(text, m, rank == 0 or _changed_from(lead))
            if ftype:
                cands.append((rank, round(amount, 3) in aside, len(cands), ftype, p, m))
    live = [c for c in cands if c[0] < 3] or cands  # an amount being refinanced counts only when nothing else is stated
    chosen = sorted((min(c for c in live if c[3] == ftype) for ftype in dict.fromkeys(c[3] for c in live)), key=lambda c: c[2])
    found: list[dict] = []
    for _, _, _, ftype, p, m in chosen[:4]:
        text = ctx.flow[p]
        quote, page = ctx.evidence(text, p, (m.start(), m.end()))
        found.append(_facility(len(found) + 1, ftype, amount_mm(m), _facility_tenor(ctx, text, m, ftype), quote, page, _currency(text, m)))
    if not found:  # no "$X revolving credit facility" phrase: fall back to a labelled amount
        ftype = _main_facility_type(ctx)
        for b in ctx.blocks(_FACILITY_LABEL, 8):
            m = next((m for m in _amounts(b.text) if (amount_mm(m) or 0) >= 50), None)
            if m:
                quote, page = ctx.evidence(b.text, b.page, (m.start(), m.end()))
                found.append(_facility(1, ftype, amount_mm(m), _tenor_years(b.text, ftype), quote, page, _currency(b.text, m)))
                break
        if not found:
            found.append(_facility(1, ftype, None, _tenor_years(ctx.all_text[:4000], ftype), "", None))
            ctx.notes.append("Facility amount not recognised.")
    for b in ctx.blocks(r"(?:availability\s+and\s+)?(?:final\s+)?maturity(?:\s+date|\s+and\s+amorti[sz]ation)?|tenor|commitment\s+termination\s+date", 14):
        text = _SAME_RE.sub("", b.text).strip()
        if len(text) < 4:
            continue
        for f in found:
            f["tenor_text"] = f["tenor_text"] or clip(text, 160)
            f["tenor_years"] = f["tenor_years"] or _tenor_years(text, f["type"])
        break
    return found


# ---------------------------------------------------------------------------------------------- pricing


def _facility_ids_for(text: str, facilities: list[dict]) -> list[str]:
    low = text.lower()
    wanted = {ftype for ftype, pat in _FACILITY_PATTERNS if re.search(pat, low)}
    return [f["id"] for f in facilities if f["type"] in wanted] or [f["id"] for f in facilities]


def _grid_name(g: tables.Grid) -> str:
    for chunk in reversed([c for c in re.split(r"\s{2,}|(?<=[.:])\s", g.context) if c]):
        if re.search(r"pricing|grid|applicable|margin|annex|schedule|addendum", chunk, re.IGNORECASE) and len(chunk) <= 80:
            return clip(chunk, 80)
    return "Flat pricing" if len(g.tiers) == 1 else "Pricing grid"


def _to_record(g: tables.Grid, facilities: list[dict]) -> dict:
    tiers = []
    for t in g.tiers:
        v = t.values
        tiers.append({
            "level": t.level, "criteria": t.criteria,
            "drawn_margin_bps": v.get("drawn"), "base_rate_margin_bps": v.get("base"),
            "undrawn_fee_bps": v.get("commitment_fee", v.get("facility_fee")),
            "all_in_drawn_bps": v.get("all_in"), "lc_fee_bps": v.get("lc"),
            "is_opening": len(g.tiers) == 1, "quote": t.quote,
        })
    return {
        "name": _grid_name(g), "facility_ids": _facility_ids_for(g.context, facilities), "metric": g.metric,
        "undrawn_fee_type": g.undrawn_fee_type, "page": g.page, "tiers": tiers,
        "opening_level_note": "Flat pricing: the single tier applies from closing." if len(g.tiers) == 1 else "",
        "notes": " ".join(g.notes), "_lines": [g.first_line, g.last_line],
    }


def _signature(grid: dict) -> list[tuple]:
    return [(t["drawn_margin_bps"], t["undrawn_fee_bps"], t["all_in_drawn_bps"]) for t in grid["tiers"]]


def _proposed_cells(ctx: _Context, g: tables.Grid) -> list[str]:
    """What the proposed column says beside a table of the existing column, header and label line included."""
    lines = ctx.doc.lines
    labelled = any(lines[n].text[: lines[n].qstart].strip() for n in range(g.first_line, g.last_line + 1))
    top = g.first_line
    while top - 1 >= max(0, g.first_line - 4) and lines[top - 1].qstart and not ctx.raw.lines[top - 1].blank:
        label = lines[top - 1].text[: lines[top - 1].qstart].strip()
        if label and labelled:
            break  # the row above belongs to the section before this one
        top -= 1
        if label:
            break  # the table's own label line: nothing above it is part of the section
    return [cell for cell in (lines[n].text[lines[n].qstart:].strip() for n in range(top, g.last_line + 1)) if cell]


def _grids(ctx: _Context, facilities: list[dict]) -> list[dict]:
    found = tables.find_grids(ctx.doc)
    if ctx.split_pages:  # a proposed cell that is blank or only says "same as existing": read the existing column's table
        have = {g.page for g in found}
        for g in tables.find_grids(ctx.existing):
            if g.page not in ctx.split_pages or g.page in have:
                continue
            note = (f"Page {g.page}: a pricing table in the existing-terms column was left out, because the proposed-terms "
                    "column has its own text beside it and that text was not read as a table.")
            if all(_SAME_RE.match(cell) for cell in _proposed_cells(ctx, g)):
                found.append(g)
            elif note not in ctx.notes:
                ctx.notes.append(note)
    out: list[dict] = []
    for g in sorted(found, key=lambda x: x.first_line):
        rec = _to_record(g, facilities)
        if any(_signature(rec) == _signature(o) for o in out):
            continue  # the same table printed twice
        for t in rec["tiers"]:  # keep only quotes that verifiably sit on the grid's page
            t["quote"] = t["quote"] if ctx.raw.has_quote(t["quote"], rec["page"]) else ""
        out.append(rec)
    out += _flat_pricing(ctx, facilities, out)
    _mark_opening(ctx, out)
    return out


_NUM = r"\d{1,4}(?:\.\d{1,4})?"
_UNIT = r"%|per\s?cent(?:um)?\b|bps\b|bp\b|basis\s+points\b"
_CSA_WORD = r"(?:credit\s+spread\s+adjustment|sofr\s+adjustment|\bCSA\b)"
_BENCH = r"(?<!['" + chr(0x2019) + r"])\b(?:Term\s+SOFR|SOFR|LIBOR|S|L)"  # not the "s" of a possessive
_SPREAD_RE = re.compile(_BENCH + r"\s*(\+|plus)\s*", re.IGNORECASE)  # "S +", "Term SOFR plus": _spread reads what follows
# One term of the sum after the benchmark: "175 bps", "10 bps CSA", "CSA of 10 bps", or "CSA" with no figure.
_ADDEND_RE = re.compile(r"(?:(?:an?|the)\s+)?(?P<pre>" + _CSA_WORD + r"\s*(?:of\s+)?)?(?:(?P<num>" + _NUM + r")\s*(?P<unit>" + _UNIT + r"))?"
                        r"(?P<post>\s*\(?" + _CSA_WORD + r"\)?)?", re.IGNORECASE)
# The plus before the next term; an aside may stand in front of it: '0.10% (the "SOFR Adjustment") plus 1.75%'.
_PLUS_RE = re.compile(r"\s*(?:\((?P<aside>[^()]{0,60})\)\s*)?(?:\)\s*)?(?:\+|plus)\s*", re.IGNORECASE)
_DASH = "-" + chr(0x2013) + chr(0x2014)
# "150 - 200 bps", "1.50% to 2.00%", "2.50% to SOFR + 2.00%"; with "and" only after "between"
_RANGE_RE = re.compile(r"(?P<a>" + _NUM + r")\s*(?P<ua>" + _UNIT + r")?\s*(?:per\s+annum\s*)?(?P<sep>to|and|[" + _DASH + r"])\s*(?:" + _BENCH
                       + r"\s*(?:\+|plus)\s*)?(?P<b>" + _NUM + r")\s*(?P<ub>" + _UNIT + r")", re.IGNORECASE)
_RATE = _NUM + r"\s*(?:" + _UNIT + r")"
# "1.50% / 1.75% / 2.00%", "2.00%, 1.75% and 1.50%": three or more levels in a row, a grid written out in words
_LEVELS_RE = re.compile(_RATE + r"(?:\s*(?:/|,(?:\s*(?:and|or))?|and|or)\s*" + _RATE + r"){2,}", re.IGNORECASE)
# "reduced from", "increase in the margin from", "(up from": what follows is the term being replaced. A rate that moves with
# time or leverage is worded otherwise ("stepping down from", "will increase from", "decreasing from"), and a bare "from A
# to B" is a range.
_FROM_RE = re.compile(r"(?<!\bwill\s)(?<!\bshall\s)(?<!\bmay\s)(?<!\bwould\s)(?<!\bstep[-\s])(?<!\bstepping\s)(?<!\bstepped\s)(?<!\bsteps\s)"
                      r"\b(?:reduced?|reduction|decreased?|lower(?:ed)?|increased?|raised?|upsized?|changed?|amend(?:ed)?|revised?|reset|cut|up|down)\s+"
                      r"(?:[A-Za-z]+\s+){0,4}?from\s+(?:(?:the|its)\s+)?(?:(?:current|existing)\s+)?(?:(?:rate|level|margin)\s+of\s+)?$", re.IGNORECASE)
# "currently S + 250 bps", "(previously 0.375%)", "Existing: 0.375%": the term in force before the change
_OUTGOING_RE = re.compile(r"\b(?:currently|presently|previously|formerly|was|(?:existing|current|prior|previous)(?:\s+(?:rate|level|margin|fee|"
                          r"pricing|terms?))?\s*(?:of|is|at|:))\s*$", re.IGNORECASE)
_ABR_CONTEXT_RE = re.compile(r"one[-\s]month|1[-\s]month|month\s+tenor|federal\s+funds|prime|nyfrb|overnight|base\s+rate\s+(?:means|is)", re.IGNORECASE)
# "2.25% per annum for Term SOFR Loans [and 1.25% for Base Rate Loans]": a margin stated without the benchmark in front
_FOR_LOANS = r"(?:\s+per\s+annum)?,?\s+(?:for|in\s+the\s+case\s+of|with\s+respect\s+to)\s+(?:%s)(?:\s+rate)?\s+(?:loans|borrowings|advances)\b"
_SOFR_LOANS_RE = re.compile(r"(?<![\w.,$/+])(" + _NUM + r")\s*(" + _UNIT + r")"
                            + _FOR_LOANS % r"(?:adjusted\s+)?(?:term\s+)?sofr|term\s+benchmark|eurodollar|libor|rfr", re.IGNORECASE)
_BASE_LOANS_RE = re.compile(r"\s*(?:[,;]\s*)?(?:and\s+|or\s+)?(?:\(\w{1,3}\)\s*)?(" + _NUM + r")\s*(" + _UNIT + r")"
                            + _FOR_LOANS % r"base|abr|alternate\s+base|prime", re.IGNORECASE)
# The low end in front of such a rate: "2.25% - 2.75% for Term SOFR Loans", "from 2.50% to 2.00% for ..."
_RANGE_LEAD_RE = re.compile(r"(?<![\w.,$/+])(" + _NUM + r")\s*(" + _UNIT + r")?\s*(?:per\s+annum\s*)?(?:to|[" + _DASH + r"])\s*$", re.IGNORECASE)
# What the words before such a rate show it to be instead: an add-on ("increased by"), or a default rate, floor, adjustment, fee or premium.
_NOT_THE_MARGIN_RE = re.compile(r"(?:\bby|\bplus|\+|increas\w*|decreas\w*|reduc\w*|additional|above|over)\s*(?:of\s+)?$"
                                r"|(?:default|overdue|penalt\w+|floor|adjustment|\bcsa\b|\bfees?\b|premium|prepa\w+)" + _NS + r"{0,60}$", re.IGNORECASE)


def _changed_from(lead: str) -> bool:
    """True when ``lead`` ends in "reduced from" or the like: what follows is the term being replaced, not the low end of a range."""
    return bool(_FROM_RE.search(lead))


def _outgoing(lead: str) -> bool:
    """True when what follows ``lead`` is the term in force before the change: "reduced from", "currently", "Existing:"."""
    return bool(_FROM_RE.search(lead) or _OUTGOING_RE.search(lead))


def _range(text: str, m: re.Match, at: int) -> tuple[float, float, float | None, int] | None | bool:
    """A margin stated at ``at`` as two ends or as three or more levels, read as ``_spread`` returns it; False when it is neither."""
    levels = _LEVELS_RE.match(text, at)
    if levels:
        rates = [rate_bps(r.group(1), r.group(2)) for r in re.finditer(r"(" + _NUM + r")\s*(" + _UNIT + r")", levels.group(0), re.IGNORECASE)]
        # The levels of a grid run one way. A small figure in the row, or a row that ends by naming another term
        # ("225 bps / 125 bps / 75 bps floor"), is a margin followed by other terms and no list of margins.
        in_order = rates in (sorted(set(rates)), sorted(set(rates), reverse=True))
        other = re.match(r"\s*(?:floors?|fees?|undrawn|unused|upfront|abr|base|csa|adjustment|commitment|facility|oid)\b", text[levels.end():], re.IGNORECASE)
        return (min(rates), max(rates), None, levels.end()) if in_order and min(rates) > 50 and not other else False
    rng = _RANGE_RE.match(text, at)
    if not rng or (rng.group("sep").lower() == "and" and not re.search(r"\bbetween\s+$", text[: m.start()], re.IGNORECASE)):
        return False
    a, b = rate_bps(rng.group("a"), rng.group("ua") or rng.group("ub")), rate_bps(rng.group("b"), rng.group("ub"))
    if _changed_from(text[: m.start()]):
        return b, b, a, rng.end()  # "reduced from S + 250 bps to S + 200 bps"
    if a < b or rng.group("sep").lower() in ("to", "and"):
        return min(a, b), max(a, b), None, rng.end()
    return None  # "S + 300 bps - 50 bps": the second figure is something else


def _spread(text: str, m: re.Match) -> tuple[float, float, float | None, int] | None:
    """The margin after a benchmark ("S + ..."): (low, high, the margin it replaces, where it ends); None when no one reading fits.

    Low and high differ only for a stated range. A credit spread adjustment in the same sum is not the margin.
    """
    terms: list[tuple[float | None, bool]] = []
    pos = end = m.end()
    while True:
        spread = _range(text, m, pos)
        if spread is not False:  # a range: the margin, provided that every term before it is the adjustment
            return spread if all(is_csa for _, is_csa in terms) else None
        t = _ADDEND_RE.match(text, pos)
        if not (t.group("num") or t.group("pre")):
            break
        terms.append((rate_bps(t.group("num"), t.group("unit")) if t.group("num") else None, bool(t.group("pre") or t.group("post"))))
        end = t.end()
        plus = _PLUS_RE.match(text, end)
        if not plus:
            break
        if re.search(_CSA_WORD + r"|spread\s+adjustment", plus.group("aside") or "", re.IGNORECASE):
            terms[-1] = (terms[-1][0], True)  # the aside names the term just read
        pos = plus.end()
    margins = [bps for bps, is_csa in terms if bps is not None and not is_csa]
    if len(margins) == 2 and not any(is_csa for _, is_csa in terms) and min(margins) <= 50 < max(margins):
        margins = [max(margins)]  # "Term SOFR + 0.10% + 1.75%": the small term is the adjustment
    return (margins[0], margins[0], None, end) if len(margins) == 1 else None


def _stated_margin(text: str, grids: list[dict], taken: set) -> tuple[float, float, float | None, float | None, int, int] | None:
    """The first margin a pricing block states in words: (low, high, replaced margin, base rate margin, start, end)."""
    replaced: float | None = None
    for m in _SPREAD_RE.finditer(text):
        read = _spread(text, m)
        if read is None:
            continue
        low, high, old, end = read
        if _OUTGOING_RE.search(text, max(0, m.start() - 40), m.start()):
            replaced = low if low == high else None
            continue  # "Currently S + 250 bps; proposed S + 200 bps": the first is the margin being replaced
        if _ABR_CONTEXT_RE.search(text[max(0, m.start() - 70): end + 25]):
            continue  # part of a base rate definition ("one-month Term SOFR plus 1.00%")
        if m.group(1).lower() == "plus" and grids:
            continue
        if not 10 <= low <= high <= 1500 or low in taken or high in taken:
            continue
        if low < high and any(len(g["tiers"]) > 1 for g in grids):
            continue  # a range next to a grid only sums the grid up
        return low, high, replaced if old is None else old, None, m.start(), end
    m = None if grids else _SOFR_LOANS_RE.search(text)
    if m and not _NOT_THE_MARGIN_RE.search(text[max(0, m.start() - 70): m.start()]):
        low = high = rate_bps(m.group(1), m.group(2))
        old, start = None, m.start()
        first = _RANGE_LEAD_RE.search(text, 0, m.start())
        if first:  # the rate is the second of two: a change ("reduced from A to B") or the two ends of a range
            a, start = rate_bps(first.group(1), first.group(2) or m.group(2)), first.start()
            if _changed_from(text[:start]):
                old = a
            else:
                low, high = sorted((a, high))
        base = _BASE_LOANS_RE.match(text, m.end()) if low == high else None
        if 10 <= low <= high <= 1500 and low not in taken and high not in taken:
            return low, high, old, rate_bps(base.group(1), base.group(2)) if base else None, start, base.end() if base else m.end()
    return None


def _tier(level: str, criteria: str, bps: float, base: float | None, opening: bool, quote: str) -> dict:
    return {"level": level, "criteria": criteria, "drawn_margin_bps": bps, "base_rate_margin_bps": base, "undrawn_fee_bps": None,
            "all_in_drawn_bps": None, "lc_fee_bps": None, "is_opening": opening, "quote": quote}


def _flat_pricing(ctx: _Context, facilities: list[dict], grids: list[dict]) -> list[dict]:
    """A margin stated in words ("S + 300 bps", "SOFR + 150 - 200 bps") where the document prints no grid for it."""
    out: list[dict] = []
    label = r"(?:indicative\s+)?pricing|(?:applicable\s+)?(?:margin|spread)s?|interest\s+rates?(?:\s+options?)?|drawn(?:\s+(?:margin|pricing|spread))?|coupon"
    for b in ctx.blocks(label, 30):
        if any(g["page"] == b.page and g["_lines"][0] - 3 <= b.line.n <= g["_lines"][1] for g in grids):
            continue
        text = b.text
        read = _stated_margin(text, grids, {t["drawn_margin_bps"] for g in grids + out for t in g["tiers"]})
        if read is None:
            continue
        low, high, old, base, start, end = read
        quote, page = ctx.evidence(text, b.page, (start, end))
        around = " ".join(ln.text for ln in ctx.doc.lines[max(0, b.line.n - 12): b.line.n + 2])
        flat = low == high
        if old is not None and flat:
            ctx.changes.append(f"Drawn margin changed from {old:g} bps to {low:g} bps.")
        out.append({
            "name": "Flat pricing" if flat else "Margin range", "facility_ids": _facility_ids_for(b.label + " " + around, facilities),
            "metric": "Flat" if flat else "Stated range", "undrawn_fee_type": "not_stated", "page": page,
            "tiers": [_tier("Flat", "All periods", low, base, True, quote)] if flat else [
                _tier("Low", "Lower end of the stated range", low, None, False, quote),
                _tier("High", "Upper end of the stated range", high, None, False, quote)],
            "opening_level_note": "Flat pricing: the single tier applies from closing." if flat else
                                  "The document states a range, not the margin that applies at closing.",
            "notes": "" if flat else "Read from a range stated in words, not from a grid: the two tiers are the ends of that range.",
            "_lines": [b.line.n, b.end],
        })
        if len(out) >= 2:
            break
    return out


# What ties a "Level N shall apply" sentence to closing; "commencing on" and "until the first Business Day" also open the
# sentence that sets the penalty level for a late compliance certificate, so they are not cues.
_OPENING_CUE_RE = re.compile(r"closing\s+date|effective\s+date|initial|until\s+(?:the\s+)?delivery\s+of\s+the\s+first|(?:at|from|on)\s+closing",
                             re.IGNORECASE)
# A level that applies on a condition (a certificate not delivered, a default) is not the level at closing.
_PENALTY_RE = re.compile(r"fails?\s+to|failure|\bnot\s+(?:\w+\s+){0,3}?(?:deliver|furnish|provid|receiv)\w*|default|\blate\b|overdue|delinquen"
                         r"|(?<!as\s)\bif\b|\bunless\b|in\s+the\s+(?:event|absence)", re.IGNORECASE)
# The benchmark's own name counts only in a sum ("Term SOFR plus") or as the name of a kind of loan ("Term Benchmark Loans, 1.25%"):
# the rate of the benchmark itself and its floor are not margins.
_MARGIN_WORD_RE = re.compile(r"margin|applicable\s+rate|spread|pricing"
                             r"|(?:sofr|benchmark|eurodollar|libor)(?:\s+rate)?(?:\s*\+|\s+(?:plus|loans?|borrowings?|advances?)\b)", re.IGNORECASE)
_NOT_A_MARGIN_RE = re.compile(r"\bfees?\b|maturity|exten(?:d|sion)|amorti[sz]|default|overdue|premium|prepay|floor", re.IGNORECASE)


def _mark_opening(ctx: _Context, grids: list[dict]) -> None:
    """Flag the tier that applies at closing, when the document says which one it is."""
    multi = [g for g in grids if len(g["tiers"]) > 1]
    if len(multi) != 1:
        return
    g = multi[0]
    stated: list[tuple[dict, str]] = []  # (tier, the sentence that names it as the level at closing)
    for sentence in re.split(r"(?<=[.;])\s+", ctx.all_text):
        if not _OPENING_CUE_RE.search(sentence) or _PENALTY_RE.search(sentence):
            continue
        m = re.search(r"(?:pricing\s+)?(?:level|category|tier)\s+([IVX]{1,4}|\d{1,2})\b(?!\s*(?:being|is\s+the))", sentence, re.IGNORECASE)
        if m and re.search(r"shall\s+be|will\s+be|based\s+(?:up)?on|determined|set\s+at|appl(?:y|ies)|deemed", sentence, re.IGNORECASE):
            hits = [t for t in g["tiers"] if t["level"].upper() == m.group(1).upper()]
            if len(hits) == 1:
                stated.append((hits[0], sentence))
    if stated:  # a sentence about the closing date outranks one that only says "initial"
        tier, sentence = next((s for s in stated if re.search(r"closing\s+date", s[1], re.IGNORECASE)), stated[0])
        tier["is_opening"] = True
        g["opening_level_note"] = clip(sentence, 260)
        return
    for m in re.finditer(r"initial(?:ly)?\b[^.]{0,170}?(?<![\w.])(\d{1,2}(?:\.\s?\d{1,3})?)\s*%", ctx.all_text, re.IGNORECASE):
        said = ctx.all_text[_sentence(ctx.all_text, m.start(), m.end())[0]: m.end()]
        if not _MARGIN_WORD_RE.search(said) or _NOT_A_MARGIN_RE.search(said):
            continue  # an extension fee, an amortisation rate or a default rate that happens to equal a tier's margin
        bps = round(float(m.group(1).replace(" ", "")) * 100.0, 4)
        hits = [t for t in g["tiers"] if t["drawn_margin_bps"] == bps]
        if len(hits) == 1:
            hits[0]["is_opening"] = True
            g["opening_level_note"] = "Matched to the stated initial rate: " + clip(m.group(0), 200)
            return
    g["opening_level_note"] = "The rules engine found no statement of which level applies at closing."


def _basis(grids: list[dict]) -> str:
    if not grids:
        return "not_stated"
    g = max(grids, key=lambda x: len(x["tiers"]))
    if len(g["tiers"]) == 1:
        return "flat"
    crit = " ".join(t["criteria"] for t in g["tiers"]) + " " + g["metric"]
    if _RATING_PAIR_RE.search(crit) or re.search(r"\brat(?:ing|ed)", crit, re.IGNORECASE):
        return "ratings_grid"
    if re.search(r"\d\s*x\b|:\s*1\b|to\s+1\.0|leverage", crit, re.IGNORECASE):
        return "leverage_grid"
    return "other"


def _benchmark(ctx: _Context) -> str:
    for name, pat in (("Term SOFR", r"term\s+sofr"), ("Daily Simple SOFR", r"daily\s+simple\s+sofr"), ("SOFR", r"\bsofr\b"),
                      ("Term benchmark", r"term\s+benchmark"), ("LIBOR", r"\blibor\b")):
        if re.search(pat, ctx.all_text, re.IGNORECASE):
            return name
    return ""


_OTHER_CCY_RE = re.compile(r"corra|sonia|euribor|tibor|bbsy|sora|sterling|canadian|\beuro\b", re.IGNORECASE)
_CSA_NONE_RE = re.compile(
    r"(?:\bno\b|without(?:\s+any)?|removal\s+of|remov(?:e|es|ed|ing)|eliminat\w+(?:\s+of)?|(?:not|never)\s+include|exclud\w+)\s+"
    r"(?:the\s+|a\s+|any\s+)?(?:\d+(?:\.\d+)?\s*(?:bps|%|basis\s+points)\s+)?(?:sofr\s+)?" + _CSA_WORD
    + r"|" + _CSA_WORD + _NS + r"{0,90}?(?:shall|will|to)\s+be\s+(?:removed|eliminated|deleted)", re.IGNORECASE)
_ROW = r"(?:[^.;:]|\.(?=\d))"  # as _NS, and not past a colon: the next "Label: value" row is about something else
# A rate after the words (their own colon allowed), or a rate just before them unless another figure, a comma or a label's
# colon intervenes ("25 bps upfront fee, CSA to be agreed").
_CSA_RATE_RE = re.compile(
    _CSA_WORD + r"(?:\s*:)?" + _ROW + r"{0,90}?(?<![\w.])(\d{1,3}(?:\.\d{1,5})?)\s*(" + _UNIT + r")"
    r"|(?<![\w.])(\d{1,3}(?:\.\d{1,5})?)\s*(" + _UNIT + r")(?P<gap>[^.;:,\d]{0,25}?)(?P<words>" + _CSA_WORD + r")(?!\s*(?:\([^)]{0,14}\))?\s*:)",
    re.IGNORECASE)
_OTHER_TERM_RE = re.compile(r"\bfees?\b|floor|margin", re.IGNORECASE)  # what a rate in front of the words belongs to instead
_CSA_LABEL = r"(?:sofr\s+)?(?:credit\s+spread\s+adjustment|sofr\s+adjustment|csa)(?:\s*\([^)]{0,14}\))?"
# "None", "N/A", "0.00%"; not "No change ..." (the adjustment stays) and not the low end of "0 - 10 bps"
_NIL_RE = re.compile(r"\W*(?:none|nil|zero|no(?!\s+change)|n\s?/\s?a|not\s+applicable|not\s+included|removed|eliminated"
                     r"|0(?:\.0+)?\s*(?:%|bps|bp)?(?!\s*(?:[" + _DASH + r"]|to)\s*\d))(?![\w%]|\.\d)", re.IGNORECASE)
_REMOVED_RE = re.compile(r"(?<!may\sbe\s)(?<!can\sbe\s)(?:remov|eliminat|delet)|no\s+longer", re.IGNORECASE)


def _csa_rows(ctx: _Context) -> dict[int, list[tuple[int, int]]]:
    """Where the adjustment's own "Label: value" rows lie in each page's flow text."""
    spans: dict[int, list[tuple[int, int]]] = {}
    for b in ctx.blocks(_CSA_LABEL, 6):
        row = tidy(" ".join(ln.text for ln in b.lines))
        at = ctx.flow.get(b.page, "").find(row)
        if row and at >= 0:
            spans.setdefault(b.page, []).append((at, at + len(row)))
    return spans


def _csa_row(ctx: _Context) -> dict | None:
    """The adjustment read from its own "Label: value" row; in the flow text a neighbouring row's rate could be taken for it."""
    for b in ctx.blocks(_CSA_LABEL, 6):
        value = _SAME_RE.sub("", b.text).strip()
        sentence = re.split(r"(?<=[a-z)])\.\s", value)[0]
        head = sentence.split(";")[0]
        nil = _NIL_RE.match(value) or _REMOVED_RE.search(sentence)  # "Removal of the 10 bps adjustment", "Currently 10 bps; to be removed"
        rate = None if nil else RATE_RE.search(head)
        bps = rate_bps(rate.group(1), rate.group(2)) if rate else None
        if not nil and (not (bps and bps <= 50) or _OTHER_CCY_RE.search(head) and not re.search(r"sofr", head, re.IGNORECASE)):
            continue  # nothing this row states, or the adjustment of another currency's benchmark
        row = tidy(" ".join(ln.text for ln in b.lines))  # the row as it reads in the page's flow text
        start = max(row.find(b.label), 0)
        found = RATE_RE.search(row, start + len(b.label)) if rate else None
        flow = ctx.flow.get(b.page, "")
        text, at = (flow, flow.find(row)) if row in flow else (row, 0)
        span = (at + start, at + (found.end() if found else len(row)))
        quote, page = ctx.evidence(text, b.page, span)
        return {"applies": not nil, "bps": None if nil else bps, "detail": clip(text[span[0]: span[1]], 200), "quote": quote, "page": page}
    return None


def _csa(ctx: _Context) -> dict:
    """SOFR credit spread adjustment: stated (True), expressly none or removed (False), or not mentioned (None)."""
    for p, text in ctx.flow.items():
        for m in _CSA_NONE_RE.finditer(text):
            if _OTHER_CCY_RE.search(text[max(0, m.start() - 45): m.start() + 4]):
                continue  # about another currency's benchmark, not SOFR
            quote, page = ctx.evidence(text, p, (m.start(), m.end()))
            return {"applies": False, "bps": None, "detail": clip(text[max(0, m.start() - 20): m.end() + 60], 200), "quote": quote, "page": page}
    for p, text in ctx.flow.items():  # "Adjusted Term SOFR Rate" defined as the Term SOFR Rate itself: an adjustment of nil
        m = re.search(r"adjusted\s+term\s+sofr(?:\s+rate)?\W{0,4}means\s+(?:the\s+)?term\s+sofr(?:\s+rate)?\s*[;,.]", text, re.IGNORECASE)
        if m:
            quote, page = ctx.evidence(text, p, (m.start(), m.end()))
            return {"applies": False, "bps": None, "detail": "The adjusted rate is defined as Term SOFR with no adjustment.", "quote": quote, "page": page}
    row = _csa_row(ctx)
    if row:
        return row
    rows = _csa_rows(ctx)
    for p, text in ctx.flow.items():
        pos = 0
        while (m := _CSA_RATE_RE.search(text, pos)) is not None:
            pos = m.end()
            after = text[m.end(): m.end() + 40]
            if _OTHER_CCY_RE.search(text[max(0, m.start() - 45): m.start() + 4]) or (
                    _OTHER_CCY_RE.search(after) and not re.search(r"sofr", after, re.IGNORECASE)):
                continue  # about another currency's benchmark, not SOFR
            leads = m.group("words") is not None  # the rate stands in front of the words
            bps = rate_bps(m.group(3), m.group(4)) if leads else rate_bps(m.group(1), m.group(2))
            # a match that runs over the edge of the adjustment's own row has taken the rate of the row beside it
            crosses = any(m.start() < e and s < m.end() and not (s <= m.start() and m.end() <= e) for s, e in rows.get(p, []))
            if not 0 < bps <= 50 or crosses or _OTHER_TERM_RE.search(m.group("gap") if leads else text[m.start(): m.start(1)]) or (
                    leads and not any(squash(m.group(0)) in squash(ln.text) for ln in ctx.doc.page_lines(p))):
                if leads:
                    pos = m.start("words")  # not the adjustment's rate (the margin, say): its own may follow the words
                continue
            quote, page = ctx.evidence(text, p, (m.start(), m.end()))
            return {"applies": True, "bps": bps, "detail": clip(m.group(0), 200), "quote": quote, "page": page}
    return {"applies": None, "bps": None, "detail": "No SOFR credit spread adjustment wording was recognised.", "quote": "", "page": None}


_PCT = r"(?<![\w.])(\d{1,2}(?:\.\d{1,3})?)\s*%"
# Within one sentence, and without wandering into the base rate's own floor ("... ABR shall not be less than 1%").
_TO = r"(?:(?!\babr\b|base\s+rate|prime\s+rate|federal\s+funds|one[-\s]month|plus\s+\d)" + _NS + r")"
# The benchmark as the name of a kind of loan: "Term SOFR Loans may be prepaid in amounts of not less than 1%" sets no floor.
_NOT_LOANS = r"(?!\s+(?:rate\s+)?(?:loans?|borrowings?|advances?)\b)"
_FLOOR_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"(?:sofr|benchmark|term\s+rate|eurocurrency)\s+floor\s*:?\s*" + _PCT,
    r"(?:sofr|term\s+benchmark|benchmark|eurocurrency|term\s+rate)" + _TO + r"{0,220}?floor\s*(?:of|equal\s+to|shall\s+be|is|:)?\s*" + _PCT,
    r"floor" + _TO + r"{0,140}?(?:sofr|benchmark)" + _TO + r"{0,140}?(?:shall\s+be|is|of)\s*" + _PCT,
    r"(?:sofr|benchmark)" + _NOT_LOANS + _TO + r"{0,170}?less\s+than\s+(?:" + _PCT + r"|zero)",
    r"(?:\bnot\b|no\s+event|never)" + _NS + r"{0,60}?(?:sofr|benchmark\s+rate)" + _NOT_LOANS + _NS + r"{0,60}?less\s+than\s+(?:" + _PCT + r"|zero)",
    r"(?:sofr|benchmark)" + _TO + r"{0,160}?floor\s+of\s+(?:" + _PCT + r"|zero)",
)]


_MAX_FLOOR_PCT = 5.0  # a larger "not less than N%" near the benchmark is a voting or prepayment threshold, never a rate floor


def _floor(ctx: _Context) -> dict:
    for pattern in _FLOOR_PATTERNS:
        for p, text in ctx.flow.items():
            for m in pattern.finditer(text):
                pct = float(m.group(1)) if m.group(1) else 0.0
                if pct > _MAX_FLOOR_PCT:
                    continue
                start = max(m.start(), m.end() - 150)
                quote, page = ctx.evidence(text, p, (start, m.end()))
                return {"pct": pct, "detail": clip(text[start: m.end()], 200), "quote": quote, "page": page}
    return {"pct": None, "detail": "No benchmark floor wording was recognised.", "quote": "", "page": None}


# ---------------------------------------------------------------------------------------------- fees

_CLAUSE_SPLIT_RE = re.compile(r";|\||[" + _BULLETS + r"]|(?<=[a-z\)])\.\s+(?=[A-Z0-9])|,\s+(?=[A-Z][\w\- ]{1,28}:)"
                              r"|\s+(?:and\s+)?(?=\((?:[a-cx-z]|i{1,3})\)\s)|(?<=:)\s+(?=\()")
_HEADING_CLAUSE_RE = re.compile(r"^(?:\(\w{1,3}\)\s*)?([A-Z0-9][\w\- /]{1,40}):$")
_GRID_REF_RE = re.compile(r"pricing\s+grid|grid\s+(?:set\s+forth|below|attached)|table\s+below|set\s+forth\s+(?:below|in\s+the\s+table)|"
                          r"performance\s+pricing|as\s+per\s+the\s+attached|in\s+accordance\s+with\s+the\s+(?:pricing|table)", re.IGNORECASE)
_NOT_A_FEE_RE = re.compile(r"\s*(?:of\s+(?:the\s+)?(?:consolidated|total\s+assets|ebitda|commitments\s+(?:is|are))|senior\s+notes)", re.IGNORECASE)
_ONE_PCT = r"(?:1(?:\.0+)?|one)\s*(?:%|per\s?cent)"
_PARTS = {"half": 2, "third": 3, "quarter": 4, "fourth": 4, "fifth": 5, "eighth": 8, "tenth": 10, "sixteenth": 16}
# "3/8 of 1%", "3/8%", "one-half of 1%". The fraction of a mixed number ("1 3/8%") is left unread, as is the figure before it.
_FRACTION_RE = re.compile(r"(?<![\w./])(?<!\d[-\s])(?:(\d{1,2})\s*/\s*(\d{1,2})\s*(?:%|per\s?cent|of\s+" + _ONE_PCT + r")"
                          r"|(one|two|three|five|seven)[-\s](" + "|".join(_PARTS) + r")s?\s+of\s+" + _ONE_PCT + r")", re.IGNORECASE)
# The low end of a range that gives its unit once ("25 - 37.5 bps"), where it opens the clause or follows a word that leads
# up to a rate. In "Tier 1 - 25 bps" the first figure is part of a label.
_LOW_END_RE = re.compile(r"(?:^\W*|[:(]\s*|\b(?:of|is|be|at|from|between|fees?)\s+|(?:" + _UNIT + r")\s*to\s+)(" + _NUM + r")\s*(?:to|and|["
                         + _DASH + r"])\s*$", re.IGNORECASE)
_STEP_DOWN, _STEP_UP = r"(?:step[-\s]?downs?|reduction|decrease)", r"(?:step[-\s]?ups?|increase)"


def _fraction_bps(m: re.Match) -> float | None:
    """A ``_FRACTION_RE`` match in basis points; None when it is no proper fraction (a date, "50/50")."""
    num, den = (int(m.group(1)), int(m.group(2))) if m.group(1) else (_WORD_NUM[m.group(3).lower()], _PARTS[m.group(4).lower()])
    return round(100.0 * num / den, 4) if 0 < num < den else None


def _fee_rates(clause: str) -> list[tuple[float, int, int]]:
    fractions = list(_FRACTION_RE.finditer(clause))
    rates = [(bps, m.start(), m.end()) for m in fractions for bps in [_fraction_bps(m)] if bps is not None]
    for m in RATE_RE.finditer(clause):
        if any(f.start() <= m.start() < f.end() for f in fractions):
            continue  # the "1%" of "3/8 of 1%" is not a rate of its own
        rates.append((rate_bps(m.group(1), m.group(2)), m.start(), m.end()))
        low = _LOW_END_RE.search(clause, 0, m.start())
        if low:
            rates.append((rate_bps(low.group(1), m.group(2)), low.start(1), m.end()))
    # anything else is a usage trigger, a basket or a coupon: not a fee
    return [(bps, s, e) for bps, s, e in sorted(rates, key=lambda r: r[1]) if bps <= 500 and not _NOT_A_FEE_RE.match(clause[e: e + 30])]


def _same_range(clause: str, first: tuple[float, int, int], second: tuple[float, int, int]) -> bool:
    """True when ``second`` is the other end of the range that ``first`` opens: "0.375% - 0.50%", "37.5 - 50 bps"."""
    return second[2] <= first[2] or bool(re.fullmatch(r"\s*(?:per\s+annum\s*)?(?:[" + _DASH + r"/]|and)\s*", clause[first[2]: second[1]]))


def _step(clause: str, start: int, rate: tuple[float, int, int]) -> int:
    """-1 or 1 where the words round a figure make it the size of a step down or up and not a level, otherwise 0.

    "37.5 bps with a 12.5 bps stepdown", "a step-down of 12.5 bps", "increased by 0.125%". ``start`` is where the words
    that lead up to the figure begin.
    """
    before, after = clause[start: rate[1]], clause[rate[2]: rate[2] + 30]
    for sign, word, verb in ((-1, _STEP_DOWN, "reduc|decreas|lower"), (1, _STEP_UP, "increas|rais")):
        if re.search(word + r"\s+of\s*$|(?:" + verb + r")\w*\s+by\s*$", before, re.IGNORECASE) \
                or re.match(r"\s*(?:per\s+annum\s+)?" + word + r"\b", after, re.IGNORECASE):
            return sign
    return 0


def _fee_text(b: Block) -> str:
    """The block's text, with a row of column heads over a row of bare rates rewritten as "head: rate; head: rate".

    "Existing Lenders   New Lenders" over "10 bps   25 bps" states two fees, not one fee and a range.
    """
    parts = list(b.parts)
    for i in range(len(parts) - 1):
        heads, cells = fragments(parts[i], 3), fragments(parts[i + 1], 3)
        if len(heads) == len(cells) >= 2 and all(RATE_RE.fullmatch(c[2]) for c in cells) and not any(RATE_RE.search(h[2]) for h in heads):
            parts[i: i + 2] = ["; ".join(f"{h[2]}: {c[2]}" for h, c in zip(heads, cells)) + ";"]
            break
    return tidy(" ".join(parts))


def _fees(ctx: _Context, grids: list[dict], facilities: list[dict]) -> list[dict]:
    fees: list[dict] = []
    seen: set[tuple[str, float]] = set()
    grid_undrawn = {t["undrawn_fee_bps"] for g in grids for t in g["tiers"] if t["undrawn_fee_bps"] is not None}
    all_ids = [f["id"] for f in facilities]
    for ftype, pattern, needs_fee_word in _FEE_LABELS:
        for b in ctx.blocks(pattern, 40):
            undrawn = ftype in ("commitment_fee", "facility_fee")
            text = _SAME_RE.sub("", b.text if undrawn else _fee_text(b))  # an undrawn fee at two levels stays one fee with a range
            if any(g["page"] == b.page and g["_lines"][0] <= b.line.n <= g["_lines"][1] for g in grids):
                continue  # a row or header of a pricing grid
            if undrawn and grid_undrawn and _GRID_REF_RE.search(text) and not re.search(r"initial", text, re.IGNORECASE):
                continue  # the fee is a column of the grid
            heading = ""  # "5-Year Tranche:" applies to the clauses that follow it
            for clause in (c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c and c.strip()):
                head = _HEADING_CLAUSE_RE.match(clause)
                if head:
                    heading = head.group(1)
                    continue
                rates = _fee_rates(clause)
                if not rates or (needs_fee_word and not re.search(r"\bfee|premium", clause, re.IGNORECASE)):
                    continue
                kind = ftype
                if ftype == "lc_fee":
                    kind = "lc_fronting_fee" if re.search(r"fronting", clause, re.IGNORECASE) else "lc_participation_fee"
                # "reduced from 0.375% to 0.25%", "25 bps (currently 37.5 bps)": the rate after "from" or "currently" is the one
                # replaced, and with it the other end of its range ("from 37.5 - 50 bps to 25 - 37.5 bps")
                old: list[tuple[float, int, int]] = []
                for i, r in enumerate(rates):
                    if _outgoing(clause[max(0, r[1] - 120): r[1]]) or (old and old[-1] is rates[i - 1] and _same_range(clause, old[-1], r)):
                        old.append(r)
                rates = [r for r in rates if r not in old]
                if rates and _step(clause, 0, rates[0]):
                    rates = rates[1:]  # "reduced by 12.5 bps": the size of a change, with no level in front of it to apply it to
                if not rates:
                    continue  # only the outgoing rate, or only the size of the change, is stated
                bps, s, e = rates[0]
                if (kind, bps) in seen or (undrawn and bps in grid_undrawn):
                    continue  # already recorded, or the opening level of the grid's own fee column
                seen.add((kind, bps))
                if len(old) == 1:
                    ctx.changes.append(f"{FEE_TYPES[kind]} changed from {old[0][0]:g} bps to {bps:g} bps.")
                values = list(dict.fromkeys(r[0] for r in rates))
                step = _step(clause, e, rates[1]) if len(rates) == 2 and rates[1][0] < bps else 0
                if step:  # the second figure is the step, not the other level
                    values = [bps, round(bps + step * rates[1][0], 4)]
                quote, page = ctx.evidence(clause, b.page, (s, e))
                own = re.sub(r"^\W+", "", clause[:s]).rstrip(" :,-(")
                desc = clip(" - ".join(x for x in (heading, own) if x) or b.label, 120)
                fees.append({
                    "type": kind, "facility_ids": all_ids, "description": desc, "bps": bps,
                    "bps_low": min(values) if len(values) > 1 else None, "bps_high": max(values) if len(values) > 1 else None,
                    "amount_text": tidy(clause[s:e]), "quote": quote, "page": page,
                })
    for p, text in ctx.flow.items():  # a term-out fee mentioned inside another section ("... upon payment of a fee of 75 basis points")
        for m in re.finditer(r"\bfee\s+(?:equal\s+to\s+|of\s+)(\d{1,3}(?:\.\d{1,3})?)\s*(" + _UNIT + r")", text, re.IGNORECASE):
            a, z = _sentence(text, m.start(), m.end())  # the fee of the section before or after is not this one
            sentence = text[a:z]
            bps = rate_bps(m.group(1), m.group(2))
            if re.search(r"term[-\s]out|convert(?:ed)?\b[^.]{0,80}term\s+loan|term\s+loan\s+conversion", sentence, re.IGNORECASE) \
                    and ("term_out_fee", bps) not in seen and bps <= 500:
                seen.add(("term_out_fee", bps))
                quote, page = ctx.evidence(text, p, (m.start(), m.end()))
                fees.append({"type": "term_out_fee", "facility_ids": all_ids, "description": "Fee on loans converted to a term loan",
                             "bps": bps, "bps_low": None, "bps_high": None, "amount_text": tidy(m.group(0)), "quote": quote, "page": page})
    for p, text in ctx.flow.items():  # issue price / OID, quoted as a price rather than a rate
        for m in re.finditer(r"(?:\bOID\b|original\s+issue\s+discount|issue\s+price|offer\s+price)[^.;\d]{0,30}(\d{2,3}(?:\.\d{1,3})?)(?!\s*bps)",
                             text, re.IGNORECASE):
            price = float(m.group(1))
            if 90.0 <= price < 100.0 and ("oid", price) not in seen:
                seen.add(("oid", price))
                quote, page = ctx.evidence(text, p, (m.start(), m.end()))
                fees.append({"type": "oid", "facility_ids": all_ids, "description": f"Issue price {m.group(1)}",
                             "bps": round((100.0 - price) * 100.0, 4), "bps_low": None, "bps_high": None,
                             "amount_text": m.group(1), "quote": quote, "page": page})
    return fees
