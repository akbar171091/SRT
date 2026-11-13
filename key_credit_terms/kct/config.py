"""Paths and constants."""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DOCS_DIR = APP_DIR.parent / "Hackathon (CA and TS)"
DEFAULT_TEMPLATE = DEFAULT_DOCS_DIR / "Key_Credit_Terms.docx"
DEFAULT_OUTPUT_DIR = APP_DIR / "output"
CACHE_DIR = APP_DIR / ".cache"
AUDITED_DIR = APP_DIR / "data" / "audited"

OUTPUT_PREFIX = "Key_Credit_Terms_"

# Text written where the term sheet has nothing on a row.
NOT_STATED = "Not stated in term sheet"

# Claude engines (optional; see kct/llm.py).
CLAUDE_MODEL = "claude-opus-5-5"
