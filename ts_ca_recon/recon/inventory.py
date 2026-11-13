"""Scan a folder of PDFs, classify each file as a credit agreement (CA) or term
sheet (TS), and pair them by deal so missing components can be flagged."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_KIND_PATTERNS = [
    ("CA", r"(?:CA|credit[\s_-]*agreement|facility[\s_-]*agreement)"),
    ("TS", r"(?:TS|term[\s_-]*sheet|summary[\s_-]*of[\s_-]*terms)"),
]
_SUFFIX_RE = re.compile(
    r"^(?P<deal>.*?)(?:^|[\s_\-]+)(?P<kind>" + "|".join(p for _, p in _KIND_PATTERNS) + r")[\s_\-]*$",
    re.IGNORECASE,
)


@dataclass
class Deal:
    key: str
    ca: Path | None = None
    ts: Path | None = None
    duplicates: list[Path] = field(default_factory=list)
    replaced: list[Path] = field(default_factory=list)  # files superseded by an upload of the same name

    @property
    def status(self) -> str:
        if self.ca and self.ts:
            return "complete"
        if self.ca:
            return "missing_ts"
        return "missing_ca"

    @property
    def missing(self) -> list[str]:
        out = []
        if not self.ca:
            out.append("Credit agreement (CA)")
        if not self.ts:
            out.append("Term sheet (TS)")
        return out


def normalise_deal_key(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip(" _-")


def classify(path: Path) -> tuple[str | None, str]:
    """Return (kind, deal_key) for a PDF, or (None, stem) if it cannot be classified."""
    stem = path.stem.strip()
    m = _SUFFIX_RE.match(stem)
    if not m:
        return None, normalise_deal_key(stem)
    kind_text = m.group("kind")
    kind = next(k for k, p in _KIND_PATTERNS if re.fullmatch(p, kind_text, re.IGNORECASE))
    return kind, normalise_deal_key(m.group("deal"))


def scan(folders: list[Path]) -> tuple[dict[str, Deal], list[Path]]:
    """Pair CA/TS files across one or more folders. A file name found in a LATER folder (e.g. the uploads
    folder) replaces the same name in an earlier one; the superseded file is recorded in Deal.replaced.

    Returns (deals keyed by deal name, unclassified files)."""
    deals: dict[str, Deal] = {}
    unclassified: list[Path] = []
    chosen: dict[str, Path] = {}
    shadowed: dict[str, Path] = {}
    for folder in folders:
        if not folder or not folder.is_dir():
            continue
        for pdf in sorted(folder.glob("*.pdf")):
            if pdf.name.lower() in chosen:
                shadowed[pdf.name.lower()] = chosen[pdf.name.lower()]
            chosen[pdf.name.lower()] = pdf
    for pdf in sorted(chosen.values(), key=lambda q: q.name.lower()):
        kind, key = classify(pdf)
        if kind is None:
            unclassified.append(pdf)
            continue
        # Case-insensitive merge of keys ("AON 2026" vs "Aon 2026").
        existing = next((k for k in deals if k.lower() == key.lower()), None)
        deal = deals.setdefault(existing or key, Deal(key=existing or key))
        slot = "ca" if kind == "CA" else "ts"
        if getattr(deal, slot) is None:
            setattr(deal, slot, pdf)
        else:
            deal.duplicates.append(pdf)
        if pdf.name.lower() in shadowed:
            deal.replaced.append(shadowed[pdf.name.lower()])
    return dict(sorted(deals.items(), key=lambda kv: kv[0].lower())), unclassified
