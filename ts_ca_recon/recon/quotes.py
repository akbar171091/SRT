"""Mechanical evidence check: does each quoted excerpt really appear in the source PDF text?"""
from __future__ import annotations

import re
import unicodedata

_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "‑": "-", " ": " ", "­": ""})


def normalise(s: str) -> str:
    """Lower-case, unify typography, drop whitespace. Punctuation is KEPT so '$1,000' cannot match inside
    '$1,000,000' once separators are compared."""
    s = unicodedata.normalize("NFKC", s or "").translate(_TRANS).replace("&amp;", "&").lower()
    return re.sub(r"\s+", "", s)


class QuoteIndex:
    def __init__(self, pages: list[str]):
        self.pages = [normalise(p) for p in pages]
        self.full = "".join(self.pages)

    def locate(self, quote: str) -> tuple[bool | None, list[int]]:
        """Return (found, pages). found is None for an empty quote. Ellipses split a quote into segments."""
        if not quote or not quote.strip():
            return None, []
        segs = [normalise(s) for s in re.split(r"\.\.\.|…|\[\.\.\.\]", quote)]
        # Keep short segments that carry a figure (often the very thing being quoted).
        segs = [s for s in segs if len(s) >= 8 or (len(s) >= 2 and re.search(r"\d", s))]
        if not segs:
            return None, []
        pages: list[int] = []
        for s in segs:
            hit = [i for i, p in enumerate(self.pages, 1) if self._contains(p, s)]
            if hit:
                pages.append(hit[0])
            elif not self._contains(self.full, s):  # allow quotes that straddle a page break
                return False, []
        return True, sorted(set(pages))

    @staticmethod
    def _contains(hay: str, needle: str) -> bool:
        """Substring match that will not let a quote ending in a digit match the prefix of a longer number."""
        start = 0
        while True:
            i = hay.find(needle, start)
            if i < 0:
                return False
            nxt = hay[i + len(needle): i + len(needle) + 2]
            if not (needle[-1].isdigit() and (nxt[:1].isdigit() or (nxt[:1] in ",." and nxt[1:2].isdigit()))):
                return True
            start = i + 1


def verify_rows(rows: list[dict], ts_pages: list[str] | None, ca_pages: list[str] | None) -> dict:
    """Annotate rows in place with *_quote_found / *_quote_pages; return summary counts."""
    idx = {"ts": QuoteIndex(ts_pages) if ts_pages else None, "ca": QuoteIndex(ca_pages) if ca_pages else None}
    stats = {"ts": [0, 0], "ca": [0, 0]}
    for row in rows:
        for side in ("ts", "ca"):
            if idx[side] is None:
                continue
            found, pages = idx[side].locate(row.get(f"{side}_quote", ""))
            row[f"{side}_quote_found"] = found
            row[f"{side}_quote_pages"] = pages
            if found is not None:
                stats[side][0] += 1
                stats[side][1] += int(found)
    return {f"{s}_checked": n for s, (n, _) in stats.items()} | {f"{s}_found": f for s, (_, f) in stats.items()}
