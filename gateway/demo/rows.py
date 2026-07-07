"""In-memory mirror of the demo denormalized view (spec §9).

SOURCE OF TRUTH for the demo DATA is gateway/demo/seed.sql; this mirror exists for
the fake connector (seam test). A parity test (test_seam_parity) asserts the two agree.
Keep the column set and rows identical to seed.sql's `books_view`."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# The view name both connectors qualify column paths with (`books_view.<column>`),
# matching seed.sql. Field paths are exposed as `view.column` so the resolver's
# `table.column` convention lines up with a real, copyable path.
VIEW_NAME = "books_view"

# (column, type, description, samples) — the shape describe() emits for each column.
# NOTE: these are BARE column names (a faithful mirror of seed.sql); the connector
# qualifies them to `books_view.<column>` in describe()/execute().
VIEW_FIELDS: List[Tuple[str, str, str, List[str]]] = [
    ("book_id",     "integer", "primary key of the book record", []),
    ("title",       "text",    "the title of the book", ["A Wizard of Earthsea"]),
    ("category",    "text",    "genre / subject classification",
        ["Science Fiction", "Fantasy", "Non-Fiction"]),
    ("published_at","date",    "date the book was published", ["1968-01-01", "2026-03-01"]),
    ("price",       "numeric", "retail price in USD", ["9.99", "24.00"]),
    ("page_count",  "integer", "number of pages", ["205", "500"]),
    ("language",    "text",    "language the book is written in", ["en", "fr"]),
    ("author_id",   "integer", "primary key of the author record", []),
    ("author_name", "text",    "full name of the person who wrote the book",
        ["Ursula K. Le Guin"]),
    ("birth_year",  "integer", "year the author was born", ["1929"]),
    ("country",     "text",    "author's country of origin", ["USA", "UK"]),
]

VIEW_ROWS: List[Dict[str, Any]] = [
    {"book_id": 1, "title": "A Wizard of Earthsea", "category": "Fantasy",
     "published_at": "1968-01-01", "price": 9.99, "page_count": 205, "language": "en",
     "author_id": 1, "author_name": "Ursula K. Le Guin", "birth_year": 1929, "country": "USA"},
    {"book_id": 2, "title": "Future Shock 2026", "category": "Science Fiction",
     "published_at": "2026-03-01", "price": 15.00, "page_count": 350, "language": "en",
     "author_id": 2, "author_name": "SansWord", "birth_year": 1985, "country": "USA"},
    {"book_id": 3, "title": "The Long Orbit", "category": "Science Fiction",
     "published_at": "2026-05-10", "price": 24.00, "page_count": 500, "language": "en",
     "author_id": 3, "author_name": "R. Novak", "birth_year": 1970, "country": "UK"},
    {"book_id": 4, "title": "Vieux Roman", "category": "Non-Fiction",
     "published_at": "2010-01-01", "price": 12.00, "page_count": 280, "language": "fr",
     "author_id": 4, "author_name": "Old Writer", "birth_year": 1940, "country": "France"},
    {"book_id": 5, "title": "Orbit of Dreams", "category": "Science Fiction",
     "published_at": "2025-11-20", "price": 30.00, "page_count": 420, "language": "en",
     "author_id": 5, "author_name": "A. Blake", "birth_year": 1960, "country": "UK"},
    {"book_id": 6, "title": "Silent Fields", "category": "Non-Fiction",
     "published_at": "2026-01-15", "price": 18.50, "page_count": 300, "language": "en",
     "author_id": 6, "author_name": "M. Ito", "birth_year": 1988, "country": "Japan"},
]
