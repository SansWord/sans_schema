"""Test cases.

Each case is a client request in the client's OWN vocabulary, plus the expected
resolution. `today` is passed to the resolver so relative values ("this year")
normalize deterministically; expected values below assume 2026-07-06.

The point is to be adversarial: synonyms (writer->author), paraphrases,
relative dates, enum-value mismatches (sci-fi -> "Science Fiction"), and
ambiguous joins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Case:
    schema: str                       # which sample schema
    want: List[str]                   # client field names (client vocabulary)
    where: Optional[str]              # natural-language filter, or None
    expect_want: Dict[str, Optional[str]]   # client key -> expected field path (None = unresolvable)
    expect_where: Optional[Dict[str, Any]]  # expected canonical predicate AST
    note: str = ""


TODAY = "2026-07-06"


# --- library / books --------------------------------------------------------

CASES: List[Case] = [
    Case(
        schema="library",
        want=["title", "writer", "genre", "releaseDate"],
        where="published this year, sci-fi only",
        expect_want={
            "title": "book.title",
            "writer": "author.name",
            "genre": "book.category",
            "releaseDate": "book.published_at",
        },
        expect_where={"op": "and", "clauses": [
            {"op": "gte", "field": "book.published_at", "value": "2026-01-01"},
            {"op": "eq", "field": "book.category", "value": "Science Fiction"},
        ]},
        note="synonyms + relative date + enum fuzz (sci-fi->Science Fiction)",
    ),
    Case(
        schema="library",
        want=["title", "cost", "pages"],
        where="cheaper than 20 dollars and more than 300 pages",
        expect_want={
            "title": "book.title",
            "cost": "book.price",
            "pages": "book.page_count",
        },
        expect_where={"op": "and", "clauses": [
            {"op": "lt", "field": "book.price", "value": 20},
            {"op": "gt", "field": "book.page_count", "value": 300},
        ]},
        note="paraphrased comparisons",
    ),
    Case(
        schema="library",
        want=["bookName", "authorName", "authorCountry"],
        where="written by someone born before 1950",
        expect_want={
            "bookName": "book.title",
            "authorName": "author.name",
            "authorCountry": "author.country",
        },
        expect_where={"op": "lt", "field": "author.birth_year", "value": 1950},
        note="filter references a field not in `want` (cross-entity)",
    ),
    Case(
        schema="library",
        want=["title", "language"],
        where=None,
        expect_want={"title": "book.title", "language": "book.language"},
        expect_where=None,
        note="no filter",
    ),
    Case(
        schema="library",
        want=["title", "vibes"],
        where=None,
        expect_want={"title": "book.title", "vibes": None},
        expect_where=None,
        note="unresolvable field ('vibes') — confidence gate should flag it",
    ),

    # --- ecommerce ----------------------------------------------------------
    Case(
        schema="shop",
        want=["product", "price", "category"],
        where="electronics that are in stock, under $50",
        expect_want={
            "product": "products.name",
            "price": "products.unit_price",
            "category": "products.category",
        },
        expect_where={"op": "and", "clauses": [
            {"op": "eq", "field": "products.category", "value": "Electronics"},
            {"op": "eq", "field": "products.in_stock", "value": True},
            {"op": "lt", "field": "products.unit_price", "value": 50},
        ]},
        note="enum fuzz + boolean + comparison",
    ),
    Case(
        schema="shop",
        want=["orderId", "amount", "state"],
        where="delivered orders over 100 placed in the last 30 days",
        expect_want={
            "orderId": "orders.id",
            "amount": "orders.total_amount",
            "state": "orders.status",
        },
        expect_where={"op": "and", "clauses": [
            {"op": "eq", "field": "orders.status", "value": "delivered"},
            {"op": "gt", "field": "orders.total_amount", "value": 100},
            {"op": "gte", "field": "orders.placed_at", "value": "2026-06-06"},
        ]},
        note="'state'->status (not a US state), relative window last 30 days",
    ),
    Case(
        schema="shop",
        want=["buyer", "email"],
        where="signed up in 2025",
        expect_want={
            "buyer": "customers.full_name",
            "email": "customers.email",
        },
        expect_where={"op": "and", "clauses": [
            {"op": "gte", "field": "customers.signup_date", "value": "2025-01-01"},
            {"op": "lte", "field": "customers.signup_date", "value": "2025-12-31"},
        ]},
        note="year -> date range (between semantics)",
    ),
]
