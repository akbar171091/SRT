"""Number formats shared by the extractors: rates, ratios, percentages and dollar amounts."""
from __future__ import annotations

import re

# "0.875%", "2.25 percent", "112.5 bps", "20 basis points" -> group 1 number, group 2 unit
RATE_RE = re.compile(r"(?<![\w.,$/])(\d{1,4}(?:\.\d{1,4})?)\s*(%|per\s?cent(?:um)?\b|bps\b|bp\b|basis\s+points\b)", re.IGNORECASE)
# "3.50 to 1.00", "3.50:1.00" (group 1), "3.00x to 1.00x" (group 2), "3.5x" (group 3) or "3.5 times" (group 4); a
# sentence-ending full stop may follow. The square brackets a draft puts round a figure are read through ("[4.00]:1.00",
# "[4.00]x"). After "from", "3.00x to 1.00x" is two levels, not one ratio. "times" needs a decimal figure: a whole
# number of times counts occasions ("no more than 2 times in any year").
RATIO_RE = re.compile(
    r"(?<![\w.$])\[?(\d{1,2}(?:\.\d{1,3})?)\]?\s*(?:to|:|-to-)\s*\[?1(?:\.0{1,3})?\]?(?!\d)(?!\.\d)"
    r"|(?<![\w.$])(?<!from\s)\[?(\d{1,2}(?:\.\d{1,2})?)\]?\s*x\s*(?:to|:)\s*1(?:\.0{1,3})?\s*x(?!\w)"
    r"|(?<![\w.$])\[?(\d{1,2}(?:\.\d{1,2})?)\]?\s*x(?!\w)"
    r"|(?<![\w.$])\[?(\d{1,2}\.\d{1,2})\]?\s*times\b",
    re.IGNORECASE,
)
PCT_RE = re.compile(r"(?<![\w.$])\[?(\d{1,3}(?:\.\d+)?)\]?\s*(?:%|per\s?cent\b)", re.IGNORECASE)
AMOUNT_RE = re.compile(
    r"(?:US\s*)?\$\s?(\d{1,3}(?:,\d{3}){1,5}(?:\.\d{1,6})?|\d{1,15}(?:\.\d{1,6})?)\s*(billion|million|bn\b|mm\b|B\b|M\b)?", re.IGNORECASE
)
_MAX_AMOUNT_MM = 1e7  # ten trillion dollars: anything larger is a misprint or a damaged file, never a facility


def rate_bps(number: str, unit: str) -> float:
    """A rate in basis points; ``unit`` is the unit as matched ("%", "percent", "bps", "basis points")."""
    return round(float(number) * (100.0 if unit == "%" or unit.lower().startswith("per") else 1.0), 4)


def amount_mm(m: re.Match) -> float | None:
    """A matched dollar amount in millions, or None when it carries no scale and is too small to be one."""
    num = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    if unit in ("billion", "bn", "b"):
        value = num * 1000.0
    elif unit in ("million", "mm", "m"):
        value = num
    else:
        value = num / 1e6 if num >= 1e6 else None
    return value if value is not None and value <= _MAX_AMOUNT_MM else None


def thresholds(text: str, unit: str) -> list[tuple[float, int, int]]:
    """Covenant levels in ``text`` for a unit ("x", "pct" or "usd_mm"): (value, start, end)."""
    out: list[tuple[float, int, int]] = []
    if unit == "x":
        for m in RATIO_RE.finditer(text):
            v = float(m.group(m.lastindex))  # the one group of the form that matched
            if 0.1 <= v <= 20:
                out.append((v, m.start(), m.end()))
    elif unit == "pct":
        out = [(float(m.group(1)), m.start(), m.end()) for m in PCT_RE.finditer(text) if 10 <= float(m.group(1)) <= 100]
        if not out:  # written as a ratio: "0.65 to 1.00"
            out = [(round(float(m.group(1)) * 100.0, 4), m.start(), m.end()) for m in RATIO_RE.finditer(text)
                   if m.group(1) and float(m.group(1)) <= 1.0]
    else:
        for m in AMOUNT_RE.finditer(text):
            v = amount_mm(m)
            if v:
                out.append((round(v, 4), m.start(), m.end()))
    return out
