"""The demo view's column law: (name, postgres data_type, description) for every
books_view column, in view order. Single definition — rows.py builds VIEW_FIELDS
from it and build_dataset.py mirrors it into seed.sql's COMMENT ON COLUMN
statements, so the schema-hash parity test (path|type|description) holds by
construction. Descriptions are resolver-visible: change them deliberately."""
from typing import List, Tuple

COLUMNS: List[Tuple[str, str, str]] = [
    ("book_id",      "integer", "primary key of the book record"),
    ("title",        "text",    "the title of the book"),
    ("category",     "text",    "genre / subject classification"),
    ("published_at", "date",    "date the book was published"),
    ("price",        "numeric", "retail price in USD"),
    ("page_count",   "integer", "number of pages"),
    ("language",     "text",    "language the book is written in"),
    ("author_id",    "integer", "primary key of the author record"),
    ("author_name",  "text",    "full name of the person who wrote the book"),
    ("birth_year",   "integer", "year the author was born"),
    ("country",      "text",    "author's country of origin"),
    ("gender",       "text",    "author's gender"),
]

# Split for seed.sql generation: which view columns come from which base table.
BOOK_COLUMNS = ["book_id", "title", "category", "published_at", "price",
                "page_count", "language", "author_id"]
AUTHOR_COLUMNS = ["author_id", "author_name", "birth_year", "country", "gender"]
