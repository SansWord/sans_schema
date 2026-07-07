"""Sample backend schemas — the "unknown" storage layers the resolver must map
client vocabulary onto.

A schema is a flat list of fields. Each field has a canonical path
("table.column"), a type, a human description, and a few sample values. The
resolver sees exactly this — no more privileged than what an auto-introspection
step (information_schema + LLM-generated descriptions) would produce.

Each schema also carries `rows`: a small denormalized (fully joined) sample
dataset, keyed by field path. The scorer uses it for EXECUTION EQUIVALENCE —
two predicate ASTs that select the same rows are semantically equal, regardless
of clause order, gt-vs-gte at a non-boundary, open-range-vs-bounded, or
date-vs-datetime formatting. Rows are chosen so each real predicate selects a
distinctive, non-empty subset.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Field:
    path: str          # canonical "table.column"
    type: str          # sql-ish type
    description: str    # what auto-enrichment would generate
    samples: List[str] = field(default_factory=list)


@dataclass
class Schema:
    name: str
    fields: List[Field]
    rows: List[Dict[str, Any]] = field(default_factory=list)

    def as_prompt(self) -> str:
        lines = [f"Backend schema: {self.name}", "Fields:"]
        for f in self.fields:
            s = f", e.g. {', '.join(f.samples)}" if f.samples else ""
            lines.append(f"  - {f.path} ({f.type}): {f.description}{s}")
        return "\n".join(lines)


BOOKS = Schema(
    name="library",
    fields=[
        Field("author.id", "int", "primary key of the author record"),
        Field("author.name", "text", "full name of the person who wrote the book",
              ["Ursula K. Le Guin", "SansWord"]),
        Field("author.birth_year", "int", "year the author was born", ["1929"]),
        Field("author.country", "text", "author's country of origin", ["USA", "UK"]),
        Field("book.id", "int", "primary key of the book record"),
        Field("book.title", "text", "the title of the book", ["A Wizard of Earthsea"]),
        Field("book.author_id", "int", "foreign key to author.id"),
        Field("book.category", "text", "genre / subject classification",
              ["Science Fiction", "Fantasy", "Non-Fiction"]),
        Field("book.published_at", "date", "date the book was published",
              ["2026-03-01", "1968-01-01"]),
        Field("book.price", "decimal", "retail price in USD", ["12.99", "24.00"]),
        Field("book.page_count", "int", "number of pages", ["256"]),
        Field("book.language", "text", "language the book is written in", ["en", "fr"]),
    ],
    rows=[
        {"author.name": "Ursula K. Le Guin", "author.birth_year": 1929, "author.country": "USA",
         "book.title": "A Wizard of Earthsea", "book.category": "Fantasy",
         "book.published_at": "1968-01-01", "book.price": 9.99, "book.page_count": 205,
         "book.language": "en"},
        {"author.name": "SansWord", "author.birth_year": 1985, "author.country": "USA",
         "book.title": "Future Shock 2026", "book.category": "Science Fiction",
         "book.published_at": "2026-03-01", "book.price": 15.00, "book.page_count": 350,
         "book.language": "en"},
        {"author.name": "R. Novak", "author.birth_year": 1970, "author.country": "UK",
         "book.title": "The Long Orbit", "book.category": "Science Fiction",
         "book.published_at": "2026-05-10", "book.price": 24.00, "book.page_count": 500,
         "book.language": "en"},
        {"author.name": "Old Writer", "author.birth_year": 1940, "author.country": "France",
         "book.title": "Vieux Roman", "book.category": "Non-Fiction",
         "book.published_at": "2010-01-01", "book.price": 12.00, "book.page_count": 280,
         "book.language": "fr"},
        {"author.name": "Y. Chen", "author.birth_year": 1995, "author.country": "USA",
         "book.title": "Cheap Reads", "book.category": "Fantasy",
         "book.published_at": "2024-06-01", "book.price": 8.00, "book.page_count": 150,
         "book.language": "en"},
    ],
)


ECOMMERCE = Schema(
    name="shop",
    fields=[
        Field("customers.id", "int", "primary key of the customer"),
        Field("customers.full_name", "text", "customer's name", ["Jane Doe"]),
        Field("customers.email", "text", "customer email address"),
        Field("customers.signup_date", "date", "date the customer registered",
              ["2025-11-02"]),
        Field("products.id", "int", "primary key of the product"),
        Field("products.name", "text", "product display name", ["Wireless Mouse"]),
        Field("products.category", "text", "product category",
              ["Electronics", "Home", "Apparel"]),
        Field("products.unit_price", "decimal", "price per unit in USD", ["19.99"]),
        Field("products.in_stock", "boolean", "whether the product is available"),
        Field("orders.id", "int", "primary key of the order"),
        Field("orders.customer_id", "int", "foreign key to customers.id"),
        Field("orders.placed_at", "timestamp", "when the order was placed",
              ["2026-06-14T10:30:00Z"]),
        Field("orders.total_amount", "decimal", "order total in USD", ["58.00"]),
        Field("orders.status", "text", "fulfillment status",
              ["pending", "shipped", "delivered", "cancelled"]),
    ],
    # Denormalized: each row is one order joined to its customer and a product.
    rows=[
        {"orders.id": 1001, "orders.status": "delivered", "orders.total_amount": 150.00,
         "orders.placed_at": "2026-06-20T09:00:00Z",
         "customers.full_name": "Jane Doe", "customers.email": "jane@x.com",
         "customers.signup_date": "2025-11-02",
         "products.name": "Wireless Mouse", "products.category": "Electronics",
         "products.unit_price": 19.99, "products.in_stock": True},
        {"orders.id": 1002, "orders.status": "shipped", "orders.total_amount": 58.00,
         "orders.placed_at": "2026-06-14T10:30:00Z",
         "customers.full_name": "Bob Lee", "customers.email": "bob@x.com",
         "customers.signup_date": "2026-01-15",
         "products.name": "Desk Lamp", "products.category": "Home",
         "products.unit_price": 29.00, "products.in_stock": True},
        {"orders.id": 1003, "orders.status": "delivered", "orders.total_amount": 220.00,
         "orders.placed_at": "2026-05-01T12:00:00Z",
         "customers.full_name": "Carol Kim", "customers.email": "carol@x.com",
         "customers.signup_date": "2025-03-10",
         "products.name": "Laptop Stand", "products.category": "Electronics",
         "products.unit_price": 45.00, "products.in_stock": False},
        {"orders.id": 1004, "orders.status": "cancelled", "orders.total_amount": 30.00,
         "orders.placed_at": "2026-07-01T08:00:00Z",
         "customers.full_name": "Dan Roe", "customers.email": "dan@x.com",
         "customers.signup_date": "2024-12-01",
         "products.name": "T-Shirt", "products.category": "Apparel",
         "products.unit_price": 15.00, "products.in_stock": True},
        {"orders.id": 1005, "orders.status": "delivered", "orders.total_amount": 90.00,
         "orders.placed_at": "2026-02-10T15:00:00Z",
         "customers.full_name": "Eve Ng", "customers.email": "eve@x.com",
         "customers.signup_date": "2025-08-20",
         "products.name": "Keyboard", "products.category": "Electronics",
         "products.unit_price": 49.99, "products.in_stock": True},
    ],
)


ALL_SCHEMAS: Dict[str, Schema] = {s.name: s for s in (BOOKS, ECOMMERCE)}
