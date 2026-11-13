"""Page-aware PDF text extraction with an on-disk cache.

Upright pages use pypdf's layout mode, which keeps table columns aligned by character
position (the pricing grid parser relies on that). Rotated pages, and pages where layout
mode yields nothing, fall back to plain reading-order extraction.

pypdf is imported from the environment when installed; otherwise the pure-Python wheel
bundled in ``vendor/`` is used, so the tool runs with a bare Python install.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

from .config import CACHE_DIR, VENDOR_DIR

CACHE_VERSION = 2
_reader_cls = None


def _pdf_reader():
    global _reader_cls
    if _reader_cls is None:
        try:
            from pypdf import PdfReader
        except ImportError:
            wheels = sorted(VENDOR_DIR.glob("pypdf-*.whl"))
            if not wheels:
                raise RuntimeError(
                    "pypdf is not installed and no bundled wheel was found in vendor/. Run: python -m pip install pypdf"
                ) from None
            sys.path.insert(0, str(wheels[-1]))
            from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.ERROR)  # silence "rotated text" chatter
        _reader_cls = PdfReader
    return _reader_cls


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract(path: Path) -> list[dict]:
    reader = _pdf_reader()(str(path))
    pages = []
    for page in reader.pages:
        try:  # .rotation resolves an inherited or indirect /Rotate entry, which a plain dictionary look-up does not
            rotated = (page.rotation or 0) % 360 != 0
        except Exception:
            rotated = False
        text, mode = "", "layout"
        if not rotated:
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except Exception:
                text = ""
        if len(text.strip()) < 20:
            mode = "plain"
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
        pages.append({"text": text, "mode": mode})
    return pages


def extract_pages(path: Path, use_cache: bool = True) -> tuple[list[str], dict]:
    """Return (text of each page, metadata). Index 0 is PDF page 1."""
    path = Path(path)
    sha1 = sha1_of(path)
    cache_file = CACHE_DIR / "text" / f"{sha1}.json"
    if use_cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("version") == CACHE_VERSION:
                return [p["text"] for p in cached["pages"]], _meta(sha1, cached["pages"])
        except (ValueError, KeyError):
            pass  # unreadable cache entry: re-extract
    pages = _extract(path)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"version": CACHE_VERSION, "file": path.name, "pages": pages}, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass  # read-only location: run without a cache
    return [p["text"] for p in pages], _meta(sha1, pages)


def _meta(sha1: str, pages: list[dict]) -> dict:
    chars = [len(p["text"].strip()) for p in pages]
    return {
        "sha1": sha1,
        "pages": len(pages),
        "chars": sum(chars),
        "plain_pages": [i + 1 for i, p in enumerate(pages) if p["mode"] == "plain"],
        "thin_pages": [i + 1 for i, c in enumerate(chars) if c < 200],
        "no_text": sum(chars) < 200,
    }
