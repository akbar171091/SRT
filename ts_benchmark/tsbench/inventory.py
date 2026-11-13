"""Find the term sheet PDFs in a folder.

A file is a term sheet when its name carries a standalone ``TS`` token (``Accenture 2026 TS.pdf``)
or spells it out (``... Term Sheet.pdf``, ``... Summary of Terms.pdf``). Credit agreements (``CA``)
and anything else are ignored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TS_RE = re.compile(r"(?<![A-Za-z0-9])(TS|term[\s_-]*sheet|summary[\s_-]*of[\s_-]*terms)(?![A-Za-z0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class TermSheetFile:
    path: Path
    deal: str  # display name, e.g. "Accenture 2026"
    slug: str  # stable id, e.g. "accenture_2026"

    @property
    def name(self) -> str:
        return self.path.name


def deal_name(stem: str) -> str:
    name = _TS_RE.sub(" ", stem)
    return re.sub(r"\s+", " ", name).strip(" _-") or stem.strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def is_term_sheet(path: Path) -> bool:
    return path.suffix.lower() == ".pdf" and bool(_TS_RE.search(path.stem))


def scan(folder: Path) -> list[TermSheetFile]:
    """Term sheet PDFs directly inside ``folder``, sorted by deal name."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    found: dict[str, TermSheetFile] = {}
    for pdf in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not pdf.is_file() or not is_term_sheet(pdf):
            continue
        deal = deal_name(pdf.stem)
        slug = slugify(deal)
        if slug in found:  # two files for one deal: keep both, told apart by file name
            deal = pdf.stem.strip()
        if slug in found or not slug:
            slug = slugify(pdf.stem) or "ts"
        base, n = slug, 2
        while slug in found:  # a file never replaces another one in the list
            slug, n = f"{base}_{n}", n + 1
        found[slug] = TermSheetFile(path=pdf, deal=deal, slug=slug)
    return sorted(found.values(), key=lambda t: t.deal.lower())
