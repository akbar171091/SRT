"""Find term sheet PDFs and derive the client name and output file name from a PDF file name.

``Seadrill 2026 TS.pdf``            -> client "Seadrill"          -> Key_Credit_Terms_Seadrill.docx
``Honeywell 364day 2026 TS.pdf``    -> client "Honeywell 364day"  -> Key_Credit_Terms_Honeywell_364day.docx
``Delta Airlines 2026 TS .pdf``     -> client "Delta Airlines"    -> Key_Credit_Terms_Delta_Airlines.docx
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import OUTPUT_PREFIX

_TS_RE = re.compile(r"(?<![A-Za-z0-9])(TS|term[\s_-]*sheet|summary[\s_-]*of[\s_-]*terms)(?![A-Za-z0-9])", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<![A-Za-z0-9])(?:19|20)\d{2}(?![A-Za-z0-9])")


@dataclass(frozen=True)
class TermSheetFile:
    path: Path
    deal: str  # "Seadrill 2026"
    client: str  # "Seadrill"
    output_name: str  # "Key_Credit_Terms_Seadrill.docx"

    @property
    def slug(self) -> str:
        return slugify(self.deal)


def _clean(text: str) -> str:
    return re.sub(r"[\s_]+", " ", text).strip(" _-.,")


def deal_name(stem: str) -> str:
    """File stem without the term sheet marker: "Seadrill 2026 TS" -> "Seadrill 2026"."""
    return _clean(_TS_RE.sub(" ", stem)) or stem.strip()


def client_name(stem: str) -> str:
    """Deal name without the year: "Seadrill 2026 TS" -> "Seadrill"."""
    deal = deal_name(stem)
    return _clean(_YEAR_RE.sub(" ", deal)) or deal


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _file_token(text: str) -> str:
    """Safe for a file name on Windows: words joined by underscores."""
    return re.sub(r"[^\w\-&()+]+", "_", text, flags=re.UNICODE).strip("_") or "Client"


def output_name(label: str) -> str:
    return f"{OUTPUT_PREFIX}{_file_token(label)}.docx"


def is_term_sheet(path: Path) -> bool:
    return path.suffix.lower() == ".pdf" and bool(_TS_RE.search(path.stem))


def describe(paths: list[Path]) -> list[TermSheetFile]:
    """Client and output name for each PDF. Two PDFs for one client keep their year so the outputs do not collide."""
    paths = [Path(p) for p in paths]
    clients = [client_name(p.stem) for p in paths]
    deals = [deal_name(p.stem) for p in paths]
    out: list[TermSheetFile] = []
    used: set[str] = set()
    for path, client, deal in zip(paths, clients, deals):
        label = client if [c.lower() for c in clients].count(client.lower()) == 1 else deal
        name = output_name(label)
        if name.lower() in used:  # still colliding (same file name in two folders, say)
            name = output_name(path.stem)
        n = 2
        while name.lower() in used:
            name = output_name(f"{path.stem} {n}")
            n += 1
        used.add(name.lower())
        out.append(TermSheetFile(path=path, deal=deal, client=client, output_name=name))
    return out


def scan(folder: Path) -> list[Path]:
    """Term sheet PDFs directly inside ``folder``, sorted by name."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    return sorted((p for p in folder.iterdir() if p.is_file() and is_term_sheet(p)), key=lambda p: p.name.lower())
