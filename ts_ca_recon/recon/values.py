"""Parse and normalise the quantitative values that appear in loan documents:
money amounts, percentages / basis points, leverage-style ratios and dates."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_UNITS = {
    "trillion": 1e12, "tn": 1e12,
    "billion": 1e9, "bn": 1e9, "b": 1e9,
    "million": 1e6, "mm": 1e6, "mn": 1e6, "mil": 1e6, "m": 1e6,
    "thousand": 1e3, "k": 1e3,
}
_CURRENCY = [
    (r"U\.\s?S\.\s?\$|US\$|USD\s?\$?|\$", "USD"),
    (r"€|EUR\s?|Euros?\s", "EUR"),
    (r"£|GBP\s?", "GBP"),
    (r"C\$|CAD\s?", "CAD"),
]
_CUR_RE = "|".join(f"(?:{p})" for p, _ in _CURRENCY)
MONEY_RE = re.compile(
    rf"(?P<cur>{_CUR_RE})\s?(?P<num>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<unit>trillion|billion|million|thousand|bn|tn|mm|mn|mil|b|m|k)\b)?",
    re.IGNORECASE,
)
PCT_RE = re.compile(r"(?<![\d.])(?P<num>\d{1,3}(?:\.\d+)?|\.\d+)\s?(?:%|percent\b|per\s?cent\b)", re.IGNORECASE)
BPS_RE = re.compile(r"(?<![\d.,])(?P<num>\d{1,3}(?:,\d{3})+|\d{1,4}(?:\.\d+)?)\s?(?:bps|bp|basis\s+points?)\b", re.IGNORECASE)
# Fractional percentages written in words/fractions: "1/2 of 1%", "1/2%", "66-2/3%".
FRAC_PCT_RE = re.compile(r"(?<![\d/])(?:(?P<whole>\d{1,3})[- ])?(?P<n>\d)/(?P<d>\d{1,2})\s?(?:of\s+(?P<of>\d{1,3})\s?)?%", re.IGNORECASE)
# Bare decimals in a pricing table whose header says the unit is basis points, e.g. "6.5   68.5   120.0".
BARE_BPS_RE = re.compile(r"(?<![\d.,$§])(?P<num>\d{1,3}\.\d{1,3})(?![\d%x.])(?!\s*(?:to|:)\s*1)", re.IGNORECASE)
BPS_HEADER_RE = re.compile(r"\(\s*bps\s*\)|in\s+basis\s+points|\(basis\s+points\)", re.IGNORECASE)
PCT_HEADER_RE = re.compile(r"\(\s*%\s*\)|\(\s*in\s*%\s*\)|\(per\s+annum\s*%\)|%\s+per\s+annum\)", re.IGNORECASE)
RATIO_RE = re.compile(
    r"(?<![\d.])(?P<num>\d{1,2}(?:\.\d{1,3})?)\s?(?:x(?![a-z])|×|\s+times\b|:\s?1(?:\.0{1,3})?(?!\d|\.\d)|to\s+1(?:\.0{1,3})?(?!\d|\.\d))",
    re.IGNORECASE,
)
_MONTHS = {
    m: i
    for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
         ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
         ("oct", "october"), ("nov", "november"), ("dec", "december")],
        1,
    )
    for m in names
}
_MON = r"(?P<mon>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
DATE_MDY_RE = re.compile(rf"\b{_MON}\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,\s*|\s+)(?P<year>(?:19|20)\d\d)\b", re.IGNORECASE)
DATE_DAYOF_RE = re.compile(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+day\s+of\s+{_MON},?\s+(?P<year>(?:19|20)\d\d)\b", re.IGNORECASE)
# Blackline: struck and inserted text run together, e.g. "March 1716, 20282030" or "July 1June 24, 20272031".
DATE_BLACKLINE_RE = re.compile(rf"\b{_MON}\s+(?P<d1>\d{{1,2}})(?:(?P<d2>\d{{1,2}})|(?P<mon2>[A-Z][a-z]+)\.?\s+(?P<d3>\d{{1,2}})),\s*(?P<y1>(?:19|20)\d\d)(?P<y2>(?:19|20)\d\d)\b")
_NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
TENOR_RE = re.compile(
    r"\b(?P<n>\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*\(\d{1,3}\))?[\s-]*(?P<unit>years?|months?|days?)\s+"
    r"(?:after|from|following|of)\s+(?:the\s+)?(?:date\s+of\s+)?(?:effectiveness|closing|effective|signing|funding|initial|amendment|execution|(?:[A-Z][\w.-]*\s+){1,4}Date)",
    re.IGNORECASE)
ANNIV_RE = re.compile(r"\b(?P<ord>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d{1,2}(?:st|nd|rd|th))\s+anniversary\b", re.IGNORECASE)
NDAY_FACILITY_RE = re.compile(r"\b(?P<n>\d{2,3})[- ]day\s+(?:revolving|credit|facility|senior|unsecured)", re.IGNORECASE)
DATE_DMY_RE = re.compile(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON},?\s+(?P<year>(?:19|20)\d\d)\b", re.IGNORECASE)
DATE_NUM_RE = re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>(?:19|20)\d\d)\b")

MIN_MONEY = 100_000  # ignore small amounts (notice minimums etc. are still >= this)


@dataclass(frozen=True)
class Value:
    kind: str  # money | pct | ratio | date
    value: float | str
    currency: str = ""
    text: str = ""
    start: int = 0

    @property
    def key(self) -> tuple:
        if self.kind == "money":
            return ("money", self.currency, round(float(self.value), -2))
        if self.kind in ("pct", "ratio"):
            return (self.kind, round(float(self.value), 4))
        return (self.kind, self.value)

    def display(self) -> str:
        if self.kind == "money":
            v = float(self.value)
            sym = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "C$"}.get(self.currency, self.currency + " ")
            if v >= 1e9:
                return f"{sym}{v / 1e9:,.3f}".rstrip("0").rstrip(".") + "bn"
            if v >= 1e6:
                return f"{sym}{v / 1e6:,.3f}".rstrip("0").rstrip(".") + "m"
            return f"{sym}{v:,.0f}"
        if self.kind == "pct":
            return f"{float(self.value):g} bps"
        if self.kind == "ratio":
            return f"{float(self.value):.2f}x"
        if self.kind == "tenor":
            d = float(self.value)
            if abs(d / 365.25 - round(d / 365.25)) < 0.02 and d >= 360:
                return f"{round(d / 365.25)} yr"
            if abs(d / 30.44 - round(d / 30.44)) < 0.05 and d >= 28 and d % 7:
                return f"{round(d / 30.44)} mo"
            return f"{d:g} days"
        return str(self.value)


def _currency(token: str) -> str:
    t = token.strip().lower()
    if t.startswith(("€", "eur")):
        return "EUR"
    if t.startswith(("£", "gbp")):
        return "GBP"
    if t.startswith(("c$", "cad")):
        return "CAD"
    return "USD"


_ABUTTING_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")


def parse_money(text: str) -> list[Value]:
    out = []
    for m in MONEY_RE.finditer(text):
        num = float(m.group("num").replace(",", ""))
        unit = (m.group("unit") or "").lower()
        # Apply a unit ("$1,000 million", "$4.2bn") unless the figure is already written out in full.
        if unit and num < 1e6:
            num *= _UNITS[unit]
        cur = _currency(m.group("cur"))
        if num >= MIN_MONEY:
            out.append(Value("money", num, cur, m.group(0), m.start()))
        # Blackline / conformed copies print struck and inserted figures back to back
        # ("$1,500,000,0001,000,000,000"); capture the abutting (inserted) figure too.
        if not unit:
            nxt = _ABUTTING_RE.match(text, m.end())
            if nxt:
                v2 = float(nxt.group(0).replace(",", ""))
                if v2 >= MIN_MONEY:
                    out.append(Value("money", v2, cur, nxt.group(0), nxt.start()))
    return out


def parse_bare_pct(text: str) -> list[Value]:
    """Bare decimals read as percentages (only call on a pricing table whose header gives '(%)')."""
    return [Value("pct", round(float(m.group("num")) * 100, 4), text=m.group(0), start=m.start()) for m in BARE_BPS_RE.finditer(text)
            if 0 < float(m.group("num")) <= 10]


def parse_bare_bps(text: str) -> list[Value]:
    """Bare decimals read as basis points (only call on a pricing table with a bps header)."""
    return [Value("pct", float(m.group("num")), text=m.group(0), start=m.start()) for m in BARE_BPS_RE.finditer(text)
            if 0 < float(m.group("num")) <= 1000]


def parse_pct(text: str) -> list[Value]:
    """Percentages and basis points, both normalised to basis points."""
    out = []
    for m in PCT_RE.finditer(text):
        out.append(Value("pct", round(float(m.group("num")) * 100, 4), text=m.group(0), start=m.start()))
    for m in BPS_RE.finditer(text):
        out.append(Value("pct", round(float(m.group("num").replace(",", "")), 4), text=m.group(0), start=m.start()))
    for m in FRAC_PCT_RE.finditer(text):
        frac = int(m.group("whole") or 0) + int(m.group("n")) / int(m.group("d"))
        if m.group("of"):  # "1/2 of 1%"
            frac *= int(m.group("of"))
        out.append(Value("pct", round(frac * 100, 4), text=m.group(0), start=m.start()))
    # Blackline runs such as "17.516.25 bps" (struck 17.5, inserted 16.25): emit every valid split.
    for m in re.finditer(r"(?<![\d.])(\d{1,3}\.\d{1,4}\d{1,3}\.\d{1,3})\s?(%|bps|bp|basis\s+points?)", text, re.IGNORECASE):
        run, unit = m.group(1), m.group(2)
        for i in range(1, len(run)):
            a, b = run[:i], run[i:]
            if a.count(".") == 1 and b.count(".") == 1 and not a.endswith(".") and not b.startswith(".") and b[0] != "0" and len(b.split(".")[1]) <= 3:
                mult = 100 if unit == "%" else 1
                out.append(Value("pct", round(float(a) * mult, 4), text=m.group(0), start=m.start()))
                out.append(Value("pct", round(float(b) * mult, 4), text=m.group(0), start=m.start()))
    # A fraction like "1/2 of 1%" also matches PCT_RE on its trailing "1%"; drop those overlaps.
    fr = [(v.start, v.start + len(v.text)) for v in out if "/" in v.text]
    return [v for v in out if "/" in v.text or not any(a <= v.start < b for a, b in fr)]


def parse_ratio(text: str) -> list[Value]:
    out = []
    for m in RATIO_RE.finditer(text):
        v = float(m.group("num"))
        if 0.1 <= v <= 20:
            out.append(Value("ratio", v, text=m.group(0), start=m.start()))
    return out


def _mk_date(y, mon, d):
    try:
        return date(int(y), _MONTHS[mon.lower().rstrip(".")], int(d)).isoformat()
    except (KeyError, ValueError):
        return None


def parse_dates(text: str) -> list[Value]:
    out = []
    # Blackline runs: emit the inserted (second) date and the struck one.
    for m in DATE_BLACKLINE_RE.finditer(text):
        mon2 = m.group("mon2") or m.group("mon")
        d2 = m.group("d2") or m.group("d3")
        new = _mk_date(m.group("y2"), mon2, d2)
        old = _mk_date(m.group("y1"), m.group("mon"), m.group("d1"))
        if new:
            out.append(Value("date", new, text=m.group(0), start=m.start()))
        if old:
            out.append(Value("date", old, text=m.group(0), start=m.start()))
    for m in DATE_DAYOF_RE.finditer(text):
        d = _mk_date(m.group("year"), m.group("mon"), m.group("day"))
        if d:
            out.append(Value("date", d, text=m.group(0), start=m.start()))
    for rx in (DATE_MDY_RE, DATE_DMY_RE):
        for m in rx.finditer(text):
            try:
                d = date(int(m.group("year")), _MONTHS[m.group("mon").lower().rstrip(".")], int(m.group("day")))
            except (KeyError, ValueError):
                continue
            out.append(Value("date", d.isoformat(), text=m.group(0), start=m.start()))
    for m in DATE_NUM_RE.finditer(text):
        try:
            d = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        except ValueError:
            continue
        out.append(Value("date", d.isoformat(), text=m.group(0), start=m.start()))
    return out


def parse_tenor(text: str) -> list[Value]:
    """Relative maturities: 'five (5) years after the Closing Date', 'fifth anniversary', '364-day facility' (value in days)."""
    out = []
    for m in TENOR_RE.finditer(text):
        n = m.group("n").lower()
        n = int(n) if n.isdigit() else _NUMWORDS[n]
        unit = m.group("unit").lower()
        days = n * 365.25 if unit.startswith("year") else (n * 30.44 if unit.startswith("month") else n)
        out.append(Value("tenor", round(days, 2), text=m.group(0), start=m.start()))
    for m in ANNIV_RE.finditer(text):
        o = m.group("ord").lower()
        n = _ORDINALS.get(o) or int(re.sub(r"\D", "", o))
        out.append(Value("tenor", round(n * 365.25, 2), text=m.group(0), start=m.start()))
    for m in NDAY_FACILITY_RE.finditer(text):
        out.append(Value("tenor", float(m.group("n")), text=m.group(0), start=m.start()))
    return out


PARSERS = {"money": parse_money, "pct": parse_pct, "ratio": parse_ratio, "date": parse_dates}


def parse(text: str, kinds: tuple[str, ...] = ("money", "pct", "ratio", "date")) -> list[Value]:
    vals: list[Value] = []
    for k in kinds:
        vals.extend(PARSERS[k](text))
    return vals


def unique(values: list[Value]) -> list[Value]:
    seen, out = set(), []
    for v in values:
        if v.key not in seen:
            seen.add(v.key)
            out.append(v)
    return out
