"""Audited records: Key Credit Terms records that were extracted and then independently re-checked.

Each file in ``data/audited/`` holds one record pinned to the SHA-1 of the PDF it was read from. A
record is used only while that exact file is the input: if the term sheet is replaced by a new
version the record is reported as stale and another engine reads the new file instead.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import schema
from .config import AUDITED_DIR


def load_all(folder: Path = AUDITED_DIR) -> tuple[list[dict], list[str]]:
    """Every usable record in ``folder``, plus a message for each file that could not be used."""
    records: list[dict] = []
    problems: list[str] = []
    folder = Path(folder)
    if not folder.is_dir():
        return records, problems
    for path in sorted(folder.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or not record.get("sha1") or not isinstance(record.get("fields"), dict):
                raise ValueError("no sha1 or no fields")
            bad = schema.validate(schema.normalise(record))
            if bad:
                raise ValueError("; ".join(bad[:3]))
            record["_path"] = str(path)
            records.append(record)
        except (OSError, ValueError, TypeError) as exc:
            problems.append(f"{path.name}: not usable ({exc})")
    return records, problems


def find(records: list[dict], sha1: str, file_name: str) -> tuple[dict | None, str | None]:
    """(record, state): "current" when the record was made from this exact file, "stale" when only the name matches."""
    for r in records:
        if r.get("sha1") == sha1:
            return r, "current"
    for r in records:
        if str(r.get("source_file", "")).strip().lower() == file_name.strip().lower():
            return r, "stale"
    return None, None
