"""Test cases.

Each case is a client request in the client's OWN vocabulary, plus the expected
resolution. `today` (TODAY) is passed to the resolver so relative values ("this
year", "last 30 days") normalize deterministically; expected boundary values
below assume 2026-07-06.

Coverage is deliberately adversarial and broad:
  - field resolution: synonyms, abbreviations, creative paraphrases, misleading
    names (state->status), domain terms, and UNRESOLVABLE fields (confidence gate)
  - filter operators: eq/ne, gt/gte, lt/lte, in/nin, contains, between, is_null,
    and/or/not, nested boolean
  - values: enum fuzz (sci-fi->Science Fiction), booleans, numbers, bare-year ->
    range, relative windows (last N days / years), text substring, null checks

WHERE cases are scored by EXECUTION EQUIVALENCE (does the AST select the same
sample rows as the expected AST?), so open-vs-bounded ranges, gt-vs-gte at a
non-boundary, and date-vs-datetime formatting all compare equal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

TODAY = "2026-07-06"


@dataclass
class Case:
    schema: str
    want: List[str]
    where: Optional[str]
    expect_want: Dict[str, Optional[str]]
    expect_where: Optional[Dict[str, Any]]
    note: str = ""


def _and(*cl):
    return {"op": "and", "clauses": list(cl)}


CASES: List[Case] = [

    # ================= library =================
    Case("library", ["title", "writer", "genre", "releaseDate"],
         "published this year, sci-fi only",
         {"title": "book.title", "writer": "author.name",
          "genre": "book.category", "releaseDate": "book.published_at"},
         _and({"op": "gte", "field": "book.published_at", "value": "2026-01-01"},
              {"op": "eq", "field": "book.category", "value": "Science Fiction"}),
         "synonyms + relative date + enum fuzz (sci-fi->Science Fiction)"),

    Case("library", ["title", "cost", "pages"],
         "cheaper than 20 dollars and more than 300 pages",
         {"title": "book.title", "cost": "book.price", "pages": "book.page_count"},
         _and({"op": "lt", "field": "book.price", "value": 20},
              {"op": "gt", "field": "book.page_count", "value": 300}),
         "paraphrased comparisons"),

    Case("library", ["bookName", "authorName", "authorCountry"],
         "written by someone born before 1950",
         {"bookName": "book.title", "authorName": "author.name", "authorCountry": "author.country"},
         {"op": "lt", "field": "author.birth_year", "value": 1950},
         "filter references a field not in `want` (cross-entity)"),

    Case("library", ["title", "language"], None,
         {"title": "book.title", "language": "book.language"}, None,
         "no filter"),

    Case("library", ["title", "vibes"], None,
         {"title": "book.title", "vibes": None}, None,
         "unresolvable field ('vibes') — confidence gate should flag it"),

    Case("library", ["title", "genre"],
         "fantasy or non-fiction",
         {"title": "book.title", "genre": "book.category"},
         {"op": "in", "field": "book.category", "value": ["Fantasy", "Non-Fiction"]},
         "OR over enum values"),

    Case("library", ["title", "price"],
         "priced between 10 and 20 dollars",
         {"title": "book.title", "price": "book.price"},
         {"op": "between", "field": "book.price", "value": [10, 20]},
         "between (numeric range)"),

    Case("library", ["title"],
         "titles containing the word orbit",
         {"title": "book.title"},
         {"op": "contains", "field": "book.title", "value": "orbit"},
         "text substring (contains)"),

    Case("library", ["title", "language"],
         "not written in english",
         {"title": "book.title", "language": "book.language"},
         {"op": "ne", "field": "book.language", "value": "en"},
         "negation on a value"),

    Case("library", ["title", "releaseDate"],
         "published between 2024 and 2026",
         {"title": "book.title", "releaseDate": "book.published_at"},
         {"op": "between", "field": "book.published_at",
          "value": ["2024-01-01", "2026-12-31"]},
         "year range on a date field"),

    Case("library", ["writer", "country"],
         "authors not based in the USA",
         {"writer": "author.name", "country": "author.country"},
         {"op": "ne", "field": "author.country", "value": "USA"},
         "negation (not equal / not in)"),

    Case("library", ["headline", "penName", "releasedOn", "tongue"], None,
         {"headline": "book.title", "penName": "author.name",
          "releasedOn": "book.published_at", "tongue": "book.language"}, None,
         "creative synonyms (want-only)"),

    Case("library", ["title", "rating", "isbn"], None,
         {"title": "book.title", "rating": None, "isbn": None}, None,
         "two unresolvable fields (gate)"),

    # ================= shop =================
    Case("shop", ["product", "price", "category"],
         "electronics that are in stock, under $50",
         {"product": "products.name", "price": "products.unit_price", "category": "products.category"},
         _and({"op": "eq", "field": "products.category", "value": "Electronics"},
              {"op": "eq", "field": "products.in_stock", "value": True},
              {"op": "lt", "field": "products.unit_price", "value": 50}),
         "enum + boolean + comparison"),

    Case("shop", ["orderId", "amount", "state"],
         "delivered orders over 100 placed in the last 30 days",
         {"orderId": "orders.id", "amount": "orders.total_amount", "state": "orders.status"},
         _and({"op": "eq", "field": "orders.status", "value": "delivered"},
              {"op": "gt", "field": "orders.total_amount", "value": 100},
              {"op": "gte", "field": "orders.placed_at", "value": "2026-06-06"}),
         "'state'->status (not a US state), relative window last 30 days"),

    Case("shop", ["buyer", "email"],
         "signed up in 2025",
         {"buyer": "customers.full_name", "email": "customers.email"},
         {"op": "between", "field": "customers.signup_date",
          "value": ["2025-01-01", "2025-12-31"]},
         "bare year -> date range"),

    Case("shop", ["product", "stock"],
         "out of stock products",
         {"product": "products.name", "stock": "products.in_stock"},
         {"op": "eq", "field": "products.in_stock", "value": False},
         "boolean false"),

    Case("shop", ["buyer", "email"],
         "customers with no email on file",
         {"buyer": "customers.full_name", "email": "customers.email"},
         {"op": "is_null", "field": "customers.email"},
         "null check"),

    Case("shop", ["order", "status"],
         "shipped or pending orders",
         {"order": "orders.id", "status": "orders.status"},
         {"op": "in", "field": "orders.status", "value": ["shipped", "pending"]},
         "OR over enum"),

    Case("shop", ["order", "amount"],
         "orders over 50 that were not cancelled",
         {"order": "orders.id", "amount": "orders.total_amount"},
         _and({"op": "gt", "field": "orders.total_amount", "value": 50},
              {"op": "ne", "field": "orders.status", "value": "cancelled"}),
         "comparison + negation"),

    Case("shop", ["product", "price"],
         "products priced between 20 and 100",
         {"product": "products.name", "price": "products.unit_price"},
         {"op": "between", "field": "products.unit_price", "value": [20, 100]},
         "between (decimal)"),

    Case("shop", ["product"],
         "product name contains 'lamp'",
         {"product": "products.name"},
         {"op": "contains", "field": "products.name", "value": "lamp"},
         "contains"),

    Case("shop", ["order", "placedOn"],
         "orders placed after June 15 2026",
         {"order": "orders.id", "placedOn": "orders.placed_at"},
         {"op": "gt", "field": "orders.placed_at", "value": "2026-06-15"},
         "absolute date comparison (timestamp field)"),

    Case("shop", ["buyer", "joined"],
         "signed up before 2025",
         {"buyer": "customers.full_name", "joined": "customers.signup_date"},
         {"op": "lt", "field": "customers.signup_date", "value": "2025-01-01"},
         "before a year"),

    Case("shop", ["client", "spend", "fulfilment", "boughtOn"], None,
         {"client": "customers.full_name", "spend": "orders.total_amount",
          "fulfilment": "orders.status", "boughtOn": "orders.placed_at"}, None,
         "synonyms across entities (want-only)"),

    Case("shop", ["order", "discountCode", "shippingAddress"], None,
         {"order": "orders.id", "discountCode": None, "shippingAddress": None}, None,
         "unresolvable fields (gate)"),

    # ================= hr =================
    Case("hr", ["employee", "role", "team", "pay"], None,
         {"employee": "employees.full_name", "role": "employees.title",
          "team": "employees.department", "pay": "employees.salary"}, None,
         "synonyms: team->department, pay->salary (want-only)"),

    Case("hr", ["name", "salary"],
         "employees in engineering earning over 125000",
         {"name": "employees.full_name", "salary": "employees.salary"},
         _and({"op": "eq", "field": "employees.department", "value": "Engineering"},
              {"op": "gt", "field": "employees.salary", "value": 125000}),
         "department filter + numeric comparison"),

    Case("hr", ["name", "title"],
         "remote workers",
         {"name": "employees.full_name", "title": "employees.title"},
         {"op": "eq", "field": "employees.is_remote", "value": True},
         "boolean true via paraphrase"),

    Case("hr", ["name", "manager"],
         "employees with no manager",
         {"name": "employees.full_name", "manager": "employees.manager_id"},
         {"op": "is_null", "field": "employees.manager_id"},
         "null check (manager_id)"),

    Case("hr", ["name", "dept"],
         "in sales or finance",
         {"name": "employees.full_name", "dept": "employees.department"},
         {"op": "in", "field": "employees.department", "value": ["Sales", "Finance"]},
         "OR over enum"),

    Case("hr", ["name", "hired"],
         "hired before 2021",
         {"name": "employees.full_name", "hired": "employees.hire_date"},
         {"op": "lt", "field": "employees.hire_date", "value": "2021-01-01"},
         "before a year (date field)"),

    Case("hr", ["name", "salary"],
         "salary between 90000 and 140000",
         {"name": "employees.full_name", "salary": "employees.salary"},
         {"op": "between", "field": "employees.salary", "value": [90000, 140000]},
         "between (salary)"),

    Case("hr", ["name", "country"],
         "not based in the USA",
         {"name": "employees.full_name", "country": "employees.country"},
         {"op": "ne", "field": "employees.country", "value": "USA"},
         "negation"),

    Case("hr", ["name", "hired"],
         "hired in the last 3 years",
         {"name": "employees.full_name", "hired": "employees.hire_date"},
         {"op": "gte", "field": "employees.hire_date", "value": "2023-07-06"},
         "relative multi-year window"),

    Case("hr", ["name", "title"],
         "managers",
         {"name": "employees.full_name", "title": "employees.title"},
         {"op": "contains", "field": "employees.title", "value": "Manager"},
         "role via title substring"),

    Case("hr", ["name", "remote", "country"],
         "office-based employees in the USA",
         {"name": "employees.full_name", "remote": "employees.is_remote", "country": "employees.country"},
         _and({"op": "eq", "field": "employees.is_remote", "value": False},
              {"op": "eq", "field": "employees.country", "value": "USA"}),
         "boolean false + enum eq"),

    Case("hr", ["worker", "annualPay", "startedOn", "basedIn"], None,
         {"worker": "employees.full_name", "annualPay": "employees.salary",
          "startedOn": "employees.hire_date", "basedIn": "employees.country"}, None,
         "synonyms (want-only)"),

    Case("hr", ["name", "bonus", "ssn"], None,
         {"name": "employees.full_name", "bonus": None, "ssn": None}, None,
         "unresolvable fields (gate)"),

    # ================= streaming =================
    Case("streaming", ["show", "type", "genre", "score"], None,
         {"show": "titles.name", "type": "titles.kind",
          "genre": "titles.genre", "score": "titles.rating"}, None,
         "synonyms: show->name, type->kind, score->rating (want-only)"),

    Case("streaming", ["name", "rating"],
         "sci-fi released this year",
         {"name": "titles.name", "rating": "titles.rating"},
         _and({"op": "eq", "field": "titles.genre", "value": "Sci-Fi"},
              {"op": "eq", "field": "titles.release_year", "value": 2026}),
         "enum + this-year on an integer year field"),

    Case("streaming", ["name", "rating"],
         "highly rated movies over 8",
         {"name": "titles.name", "rating": "titles.rating"},
         _and({"op": "eq", "field": "titles.kind", "value": "Movie"},
              {"op": "gt", "field": "titles.rating", "value": 8}),
         "enum + decimal comparison"),

    Case("streaming", ["name", "original"],
         "original productions",
         {"name": "titles.name", "original": "titles.is_original"},
         {"op": "eq", "field": "titles.is_original", "value": True},
         "boolean true"),

    Case("streaming", ["name", "maturity"],
         "rated PG or G",
         {"name": "titles.name", "maturity": "titles.maturity"},
         {"op": "in", "field": "titles.maturity", "value": ["PG", "G"]},
         "exact enum (PG-13 must NOT match)"),

    Case("streaming", ["name", "duration"],
         "shorter than an hour",
         {"name": "titles.name", "duration": "titles.duration_min"},
         {"op": "lt", "field": "titles.duration_min", "value": 60},
         "unit reasoning (an hour -> 60 minutes)"),

    Case("streaming", ["name", "year"],
         "released between 2020 and 2024",
         {"name": "titles.name", "year": "titles.release_year"},
         {"op": "between", "field": "titles.release_year", "value": [2020, 2024]},
         "between on integer year"),

    Case("streaming", ["name", "added"],
         "added to the catalog in the last 60 days",
         {"name": "titles.name", "added": "titles.added_at"},
         {"op": "gte", "field": "titles.added_at", "value": "2026-05-07"},
         "relative window (last 60 days)"),

    Case("streaming", ["name", "type"],
         "not documentaries",
         {"name": "titles.name", "type": "titles.kind"},
         {"op": "ne", "field": "titles.kind", "value": "Documentary"},
         "negation on enum"),

    Case("streaming", ["name"],
         "thrillers or dramas rated above 7",
         {"name": "titles.name"},
         _and({"op": "in", "field": "titles.genre", "value": ["Thriller", "Drama"]},
              {"op": "gt", "field": "titles.rating", "value": 7}),
         "nested: (in) AND (comparison)"),

    Case("streaming", ["name", "original", "year"],
         "originals from 2025 or later",
         {"name": "titles.name", "original": "titles.is_original", "year": "titles.release_year"},
         _and({"op": "eq", "field": "titles.is_original", "value": True},
              {"op": "gte", "field": "titles.release_year", "value": 2025}),
         "boolean + gte on year"),

    Case("streaming", ["film", "runtime", "launchedIn", "isOriginal"], None,
         {"film": "titles.name", "runtime": "titles.duration_min",
          "launchedIn": "titles.release_year", "isOriginal": "titles.is_original"}, None,
         "synonyms (want-only)"),

    Case("streaming", ["title", "director", "subtitles"], None,
         {"title": "titles.name", "director": None, "subtitles": None}, None,
         "unresolvable fields (gate)"),
]
