"""Page-aware PDF text extraction with an on-disk cache.

Uses the poppler ``pdftotext`` binary when it is on PATH (best layout fidelity),
otherwise falls back to pypdf's layout extraction mode."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from .config import CACHE_DIR

PAGE_MARKER = "=============== [PDF PAGE {n}] ==============="


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_pdftotext(path: Path, exe: str) -> list[str]:
    out = subprocess.run(
        [exe, "-layout", "-enc", "UTF-8", str(path), "-"],
        capture_output=True,
        check=True,
        timeout=300,
    ).stdout.decode("utf-8", errors="replace")
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def _extract_pypdf(path: Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text(extraction_mode="layout") or "")
        except Exception:  # some pages fail in layout mode; fall back to plain
            pages.append(page.extract_text() or "")
    return pages


def extract_pages(path: Path, use_cache: bool = True) -> list[str]:
    """Return the text of each page (index 0 = PDF page 1)."""
    path = Path(path)
    cache_file = CACHE_DIR / "text" / f"{_sha1(path)}.json"
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))["pages"]
    exe = shutil.which("pdftotext")
    pages = None
    engine = "pypdf"
    if exe:
        try:
            pages = _extract_pdftotext(path, exe)
            engine = "pdftotext"
        except Exception:
            pages = None
    if pages is None:
        pages = _extract_pypdf(path)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"file": path.name, "engine": engine, "pages": pages}, ensure_ascii=False),
        encoding="utf-8",
    )
    return pages


def _page_lines(page, tol: float = 2.5) -> tuple[list[tuple[float, list[tuple[float, str]]]], float]:
    """Group a page's text runs into lines using their (x, y) position. Returns (lines top-to-bottom, page height).
    Each line is (y, [(x, text, font_size), ...]) with runs kept in content-stream order."""
    runs: list[tuple[float, float, int, str, float]] = []

    def visit(text, cm, tm, font, size):
        if not text or not text.strip():
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        eff = (size or 10) * (abs(tm[0] * cm[0]) or abs(cm[3]) or 1)  # rendered font size in points
        step = eff * 1.15
        for i, part in enumerate(text.split("\n")):
            if part.strip():
                runs.append((y - i * step, x, len(runs), part, round(eff, 2)))

    page.extract_text(visitor_text=visit)
    lines: list[list] = []
    for y, x, order, text, size in sorted(runs, key=lambda r: (-r[0], r[2])):
        if lines and abs(lines[-1][0] - y) <= tol:
            lines[-1][1].append((order, x, text, size))
        else:
            lines.append([y, [(order, x, text, size)]])
    out = [(y, [(x, t, sz) for _, x, t, sz in sorted(parts)]) for y, parts in lines]
    try:
        height = float(page.mediabox.height)
    except Exception:
        height = 792.0
    return out, height


def extract_layout(path: Path, use_cache: bool = True) -> list[dict]:
    """Positioned lines for each page (used to pair term-sheet labels with their values).
    Rotated pages are normalised first so coordinates read upright."""
    path = Path(path)
    cache_file = CACHE_DIR / "layout2" / f"{_sha1(path)}.json"
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))["pages"]
    from pypdf import PdfWriter

    writer = PdfWriter(clone_from=str(path))
    pages = []
    for page in writer.pages:
        try:
            if page.get("/Rotate", 0):
                page.transfer_rotation_to_content()
            lines, height = _page_lines(page)
        except Exception:
            lines, height = [], 792.0
        pages.append({"height": height, "lines": [[y, [[x, t, sz] for x, t, sz in parts]] for y, parts in lines]})
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"file": path.name, "pages": pages}, ensure_ascii=False), encoding="utf-8")
    return pages


def with_page_markers(pages: list[str]) -> str:
    return "".join(f"\n{PAGE_MARKER.format(n=i)}\n{p}" for i, p in enumerate(pages, 1))


def looks_like_presentation(pages: list[str]) -> bool:
    """Heuristic: lender decks and slide extracts rather than a formal term sheet."""
    head = " ".join(pages[:3]).lower()
    return any(k in head for k in ("lender presentation", "forward-looking statements", "confidential presentation")) or (
        len(pages) > 15 and sum(len(p.split()) for p in pages) / max(len(pages), 1) < 250
    )
