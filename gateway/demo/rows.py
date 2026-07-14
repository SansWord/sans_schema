"""In-memory mirror of the demo denormalized view.

SOURCE OF TRUTH for the demo DATA is gateway/demo/books.json (frozen snapshot,
built deliberately by build_dataset.py); seed.sql is generated from the same
snapshot, so the two cannot drift (test_demo_dataset guards it). This module
loads the snapshot and joins it into the flat rows the fake connector serves;
a parity test (test_seam_parity) asserts Postgres agrees."""
from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Dict, List, Tuple

from gateway.demo.columns import COLUMNS

# The view name both connectors qualify column paths with (`books_view.<column>`),
# matching seed.sql. Field paths are exposed as `view.column` so the resolver's
# `table.column` convention lines up with a real, copyable path.
VIEW_NAME = "books_view"

_SNAPSHOT = json.loads(files("gateway.demo").joinpath("books.json").read_text("utf-8"))
_AUTHORS: Dict[int, Dict[str, Any]] = {a["author_id"]: a for a in _SNAPSHOT["authors"]}

_BOOK_KEYS = ("book_id", "title", "category", "published_at", "price",
              "page_count", "language", "author_id")
_AUTHOR_KEYS = ("author_name", "birth_year", "country", "gender")

VIEW_ROWS: List[Dict[str, Any]] = [
    {**{k: b[k] for k in _BOOK_KEYS},
     **{k: _AUTHORS[b["author_id"]][k] for k in _AUTHOR_KEYS}}
    for b in _SNAPSHOT["books"]
]


def _samples(column: str, k: int = 3) -> List[str]:
    """First k distinct non-null values in row order — deterministic because the
    snapshot is frozen. Key columns get no samples (matches the old mirror)."""
    if column.endswith("_id"):
        return []
    seen: List[str] = []
    for row in VIEW_ROWS:
        value = row[column]
        if value is not None and str(value) not in seen:
            seen.append(str(value))
        if len(seen) == k:
            break
    return seen


# (column, type, description, samples) — the shape describe() emits for each column.
# NOTE: bare column names; the connector qualifies them to `books_view.<column>`.
VIEW_FIELDS: List[Tuple[str, str, str, List[str]]] = [
    (name, type_, description, _samples(name)) for (name, type_, description) in COLUMNS
]
