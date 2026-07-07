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
date-vs-datetime formatting. Rows are chosen so each scored predicate selects a
distinctive, non-empty PROPER subset, and no row sits on a relative-date
boundary (so an off-by-one day in the model's date math can't change selection).
"""
from __future__ import annotations

from typing import Dict

from core.schemas import Field, Schema


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
         "book.published_at": "1968-01-01", "book.price": 9.99, "book.page_count": 205, "book.language": "en"},
        {"author.name": "SansWord", "author.birth_year": 1985, "author.country": "USA",
         "book.title": "Future Shock 2026", "book.category": "Science Fiction",
         "book.published_at": "2026-03-01", "book.price": 15.00, "book.page_count": 350, "book.language": "en"},
        {"author.name": "R. Novak", "author.birth_year": 1970, "author.country": "UK",
         "book.title": "The Long Orbit", "book.category": "Science Fiction",
         "book.published_at": "2026-05-10", "book.price": 24.00, "book.page_count": 500, "book.language": "en"},
        {"author.name": "Old Writer", "author.birth_year": 1940, "author.country": "France",
         "book.title": "Vieux Roman", "book.category": "Non-Fiction",
         "book.published_at": "2010-01-01", "book.price": 12.00, "book.page_count": 280, "book.language": "fr"},
        {"author.name": "Y. Chen", "author.birth_year": 1995, "author.country": "USA",
         "book.title": "Cheap Reads", "book.category": "Fantasy",
         "book.published_at": "2024-06-01", "book.price": 8.00, "book.page_count": 150, "book.language": "en"},
        {"author.name": "A. Blake", "author.birth_year": 1960, "author.country": "UK",
         "book.title": "Orbit of Dreams", "book.category": "Science Fiction",
         "book.published_at": "2025-11-20", "book.price": 30.00, "book.page_count": 420, "book.language": "en"},
        {"author.name": "M. Ito", "author.birth_year": 1988, "author.country": "Japan",
         "book.title": "Silent Fields", "book.category": "Non-Fiction",
         "book.published_at": "2026-01-15", "book.price": 18.50, "book.page_count": 300, "book.language": "en"},
        {"author.name": "P. Adair", "author.birth_year": 1955, "author.country": "France",
         "book.title": "Le Grand Voyage", "book.category": "Fantasy",
         "book.published_at": "2023-02-01", "book.price": 11.00, "book.page_count": 260, "book.language": "fr"},
    ],
)


ECOMMERCE = Schema(
    name="shop",
    fields=[
        Field("customers.id", "int", "primary key of the customer"),
        Field("customers.full_name", "text", "customer's name", ["Jane Doe"]),
        Field("customers.email", "text", "customer email address (may be missing)"),
        Field("customers.signup_date", "date", "date the customer registered", ["2025-11-02"]),
        Field("products.id", "int", "primary key of the product"),
        Field("products.name", "text", "product display name", ["Wireless Mouse"]),
        Field("products.category", "text", "product category", ["Electronics", "Home", "Apparel"]),
        Field("products.unit_price", "decimal", "price per unit in USD", ["19.99"]),
        Field("products.in_stock", "boolean", "whether the product is available"),
        Field("orders.id", "int", "primary key of the order"),
        Field("orders.customer_id", "int", "foreign key to customers.id"),
        Field("orders.placed_at", "timestamp", "when the order was placed", ["2026-06-14T10:30:00Z"]),
        Field("orders.total_amount", "decimal", "order total in USD", ["58.00"]),
        Field("orders.status", "text", "fulfillment status",
              ["pending", "shipped", "delivered", "cancelled"]),
    ],
    rows=[
        {"orders.id": 1001, "orders.status": "delivered", "orders.total_amount": 150.00,
         "orders.placed_at": "2026-06-20T09:00:00Z", "customers.full_name": "Jane Doe",
         "customers.email": "jane@x.com", "customers.signup_date": "2025-11-02",
         "products.name": "Wireless Mouse", "products.category": "Electronics",
         "products.unit_price": 19.99, "products.in_stock": True},
        {"orders.id": 1002, "orders.status": "shipped", "orders.total_amount": 58.00,
         "orders.placed_at": "2026-06-14T10:30:00Z", "customers.full_name": "Bob Lee",
         "customers.email": "bob@x.com", "customers.signup_date": "2026-01-15",
         "products.name": "Desk Lamp", "products.category": "Home",
         "products.unit_price": 29.00, "products.in_stock": True},
        {"orders.id": 1003, "orders.status": "delivered", "orders.total_amount": 220.00,
         "orders.placed_at": "2026-05-01T12:00:00Z", "customers.full_name": "Carol Kim",
         "customers.email": "carol@x.com", "customers.signup_date": "2025-03-10",
         "products.name": "Laptop Stand", "products.category": "Electronics",
         "products.unit_price": 45.00, "products.in_stock": False},
        {"orders.id": 1004, "orders.status": "cancelled", "orders.total_amount": 30.00,
         "orders.placed_at": "2026-07-01T08:00:00Z", "customers.full_name": "Dan Roe",
         "customers.email": "dan@x.com", "customers.signup_date": "2024-12-01",
         "products.name": "T-Shirt", "products.category": "Apparel",
         "products.unit_price": 15.00, "products.in_stock": True},
        {"orders.id": 1005, "orders.status": "delivered", "orders.total_amount": 90.00,
         "orders.placed_at": "2026-02-10T15:00:00Z", "customers.full_name": "Eve Ng",
         "customers.email": "eve@x.com", "customers.signup_date": "2025-08-20",
         "products.name": "Keyboard", "products.category": "Electronics",
         "products.unit_price": 49.99, "products.in_stock": True},
        {"orders.id": 1006, "orders.status": "pending", "orders.total_amount": 12.00,
         "orders.placed_at": "2026-07-03T11:00:00Z", "customers.full_name": "Frank Ho",
         "customers.email": None, "customers.signup_date": "2026-03-05",
         "products.name": "Notebook", "products.category": "Home",
         "products.unit_price": 12.00, "products.in_stock": True},
        {"orders.id": 1007, "orders.status": "shipped", "orders.total_amount": 300.00,
         "orders.placed_at": "2026-06-28T14:00:00Z", "customers.full_name": "Grace Pak",
         "customers.email": "grace@x.com", "customers.signup_date": "2025-12-31",
         "products.name": "Monitor", "products.category": "Electronics",
         "products.unit_price": 199.99, "products.in_stock": False},
    ],
)


HR = Schema(
    name="hr",
    fields=[
        Field("employees.id", "int", "primary key of the employee"),
        Field("employees.full_name", "text", "employee's full name", ["Alice Ng"]),
        Field("employees.title", "text", "job title", ["Software Engineer", "Sales Manager"]),
        Field("employees.department", "text", "department name",
              ["Engineering", "Sales", "HR", "Finance", "Executive"]),
        Field("employees.salary", "decimal", "annual salary in USD", ["120000"]),
        Field("employees.hire_date", "date", "date the employee was hired", ["2022-04-01"]),
        Field("employees.manager_id", "int", "id of the employee's manager; null for the CEO"),
        Field("employees.is_remote", "boolean", "whether the employee works remotely"),
        Field("employees.country", "text", "country where the employee is based",
              ["USA", "Germany", "India", "Japan"]),
    ],
    rows=[
        {"employees.id": 1, "employees.full_name": "Alice Ng", "employees.title": "CEO",
         "employees.department": "Executive", "employees.salary": 300000, "employees.hire_date": "2015-01-05",
         "employees.manager_id": None, "employees.is_remote": False, "employees.country": "USA"},
        {"employees.id": 2, "employees.full_name": "Bob Stone", "employees.title": "Engineering Manager",
         "employees.department": "Engineering", "employees.salary": 180000, "employees.hire_date": "2018-06-01",
         "employees.manager_id": 1, "employees.is_remote": False, "employees.country": "USA"},
        {"employees.id": 3, "employees.full_name": "Carla Diaz", "employees.title": "Software Engineer",
         "employees.department": "Engineering", "employees.salary": 130000, "employees.hire_date": "2021-03-15",
         "employees.manager_id": 2, "employees.is_remote": True, "employees.country": "Germany"},
        {"employees.id": 4, "employees.full_name": "Dev Patel", "employees.title": "Software Engineer",
         "employees.department": "Engineering", "employees.salary": 120000, "employees.hire_date": "2023-09-01",
         "employees.manager_id": 2, "employees.is_remote": True, "employees.country": "India"},
        {"employees.id": 5, "employees.full_name": "Erin Fox", "employees.title": "Sales Rep",
         "employees.department": "Sales", "employees.salary": 85000, "employees.hire_date": "2020-02-10",
         "employees.manager_id": 1, "employees.is_remote": False, "employees.country": "USA"},
        {"employees.id": 6, "employees.full_name": "Farah Ali", "employees.title": "Sales Manager",
         "employees.department": "Sales", "employees.salary": 140000, "employees.hire_date": "2019-11-20",
         "employees.manager_id": 1, "employees.is_remote": False, "employees.country": "USA"},
        {"employees.id": 7, "employees.full_name": "Gena Ross", "employees.title": "Recruiter",
         "employees.department": "HR", "employees.salary": 78000, "employees.hire_date": "2024-01-08",
         "employees.manager_id": 1, "employees.is_remote": True, "employees.country": "USA"},
        {"employees.id": 8, "employees.full_name": "Hiro Tan", "employees.title": "Financial Analyst",
         "employees.department": "Finance", "employees.salary": 95000, "employees.hire_date": "2022-07-30",
         "employees.manager_id": 1, "employees.is_remote": False, "employees.country": "Japan"},
    ],
)


STREAMING = Schema(
    name="streaming",
    fields=[
        Field("titles.id", "int", "primary key of the title"),
        Field("titles.name", "text", "title of the movie or show", ["Cosmic Drift"]),
        Field("titles.kind", "text", "content type", ["Movie", "Series", "Documentary"]),
        Field("titles.genre", "text", "primary genre",
              ["Drama", "Comedy", "Thriller", "Sci-Fi", "Nature"]),
        Field("titles.release_year", "int", "year the title was released", ["2024"]),
        Field("titles.duration_min", "int", "runtime in minutes", ["118"]),
        Field("titles.rating", "decimal", "average user rating from 0 to 10", ["7.8"]),
        Field("titles.is_original", "boolean", "whether it is an original production"),
        Field("titles.maturity", "text", "maturity rating", ["G", "PG", "PG-13", "R"]),
        Field("titles.added_at", "date", "date the title was added to the catalog", ["2026-04-01"]),
    ],
    rows=[
        {"titles.id": 1, "titles.name": "The Deep", "titles.kind": "Movie", "titles.genre": "Thriller",
         "titles.release_year": 2021, "titles.duration_min": 118, "titles.rating": 7.8,
         "titles.is_original": False, "titles.maturity": "R", "titles.added_at": "2025-09-10"},
        {"titles.id": 2, "titles.name": "Laugh Track", "titles.kind": "Series", "titles.genre": "Comedy",
         "titles.release_year": 2024, "titles.duration_min": 30, "titles.rating": 6.5,
         "titles.is_original": True, "titles.maturity": "PG-13", "titles.added_at": "2026-05-01"},
        {"titles.id": 3, "titles.name": "Cosmic Drift", "titles.kind": "Movie", "titles.genre": "Sci-Fi",
         "titles.release_year": 2026, "titles.duration_min": 142, "titles.rating": 8.4,
         "titles.is_original": True, "titles.maturity": "PG-13", "titles.added_at": "2026-06-15"},
        {"titles.id": 4, "titles.name": "Ocean Planet", "titles.kind": "Documentary", "titles.genre": "Nature",
         "titles.release_year": 2023, "titles.duration_min": 95, "titles.rating": 8.9,
         "titles.is_original": True, "titles.maturity": "G", "titles.added_at": "2026-01-20"},
        {"titles.id": 5, "titles.name": "Old Town", "titles.kind": "Movie", "titles.genre": "Drama",
         "titles.release_year": 2019, "titles.duration_min": 105, "titles.rating": 7.1,
         "titles.is_original": False, "titles.maturity": "R", "titles.added_at": "2024-11-05"},
        {"titles.id": 6, "titles.name": "Star Cadets", "titles.kind": "Series", "titles.genre": "Sci-Fi",
         "titles.release_year": 2025, "titles.duration_min": 45, "titles.rating": 7.6,
         "titles.is_original": True, "titles.maturity": "PG", "titles.added_at": "2026-03-12"},
        {"titles.id": 7, "titles.name": "Family Ties", "titles.kind": "Series", "titles.genre": "Drama",
         "titles.release_year": 2022, "titles.duration_min": 50, "titles.rating": 6.9,
         "titles.is_original": False, "titles.maturity": "PG", "titles.added_at": "2025-12-01"},
        {"titles.id": 8, "titles.name": "Night Watch", "titles.kind": "Movie", "titles.genre": "Thriller",
         "titles.release_year": 2026, "titles.duration_min": 130, "titles.rating": 8.1,
         "titles.is_original": True, "titles.maturity": "R", "titles.added_at": "2026-07-02"},
    ],
)


ALL_SCHEMAS: Dict[str, Schema] = {s.name: s for s in (BOOKS, ECOMMERCE, HR, STREAMING)}
