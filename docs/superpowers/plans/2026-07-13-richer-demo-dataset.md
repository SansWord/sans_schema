# Richer Real Demo Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 6 hand-written demo books with ~350 real books from ~70 curated authors (Open Library + Wikidata), add a `gender` column, and make `books.json` the single source of truth that generates `seed.sql` and feeds `rows.py`.

**Architecture:** A committed curated author list (`authors.json`) drives a deliberate, network-using build script (`build_dataset.py`) that emits a frozen snapshot (`books.json`). `seed.sql` becomes a generated artifact; `rows.py` loads the snapshot at import. Column names/types/descriptions live once in a new `columns.py`, imported by both the generator and `rows.py`, so the schema-hash parity test keeps guarding Postgres↔fake drift.

**Tech Stack:** Python 3.9 stdlib only for the build script (`urllib.request`, `json`, `hashlib` — no new dependencies). Open Library Search API + Wikidata SPARQL (both CC0). pytest; local Postgres 16 via Docker for connector tests.

**Spec:** `docs/superpowers/specs/2026-07-13-richer-demo-dataset-design.md` — read it first.

---

## File structure

| File | Action | Responsibility |
|---|---|---|
| `gateway/demo/columns.py` | Create | The column law: (name, type, description) for all 12 view columns — single definition imported by `rows.py` and `build_dataset.py` |
| `gateway/demo/authors.json` | Create | Curated author list (the human input): name, coverage bucket, optional language hint |
| `gateway/demo/build_dataset.py` | Create | Fetch Open Library + Wikidata, map categories, synthesize prices, emit `books.json` + `seed.sql` |
| `gateway/demo/books.json` | Create (generated, committed) | Frozen snapshot — SOURCE OF TRUTH for demo data |
| `gateway/demo/seed.sql` | Regenerate (committed) | Generated SQL artifact of `books.json` |
| `gateway/demo/rows.py` | Rewrite | Loads `books.json`, joins to flat view rows, derives sample values |
| `pyproject.toml` | Modify | Ship `*.json` as package data |
| `tests/gateway/test_demo_build.py` | Create | Unit tests for the build script's pure functions |
| `tests/gateway/test_demo_dataset.py` | Create | Chip-coverage, required-authors, gender, size, and seed.sql-determinism guards over the frozen snapshot |
| `tests/gateway/test_seam_parity.py` | Modify | New exact-row assertion from the new snapshot |
| `tests/gateway/test_postgres_connector.py` | Modify | New exact-row assertion + de-flake the samples assertion |
| `tests/test_packaging.py` | Modify | Assert the snapshot is loadable as package data |
| `playground/lib/examples.ts` | Modify | Add the gender chip (spec: optional, included) |
| `gateway/README.md`, `gateway/DEPLOY.md`, `docs/devlog.md`, `todo.md` | Modify | Source-of-truth wording, re-seed runbook note, devlog v0.4.0, todo cleanup |

---

### Task 1: Feature branch

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/richer-demo-dataset
```

- [ ] **Step 2: Confirm clean state**

Run: `git status --short` — expect empty output.

---

### Task 2: The column law (`columns.py`)

**Files:**
- Create: `gateway/demo/columns.py`
- Test: `tests/gateway/test_demo_build.py`

- [ ] **Step 1: Write the failing test**

Create `tests/gateway/test_demo_build.py`:

```python
"""Unit tests for the demo dataset build pipeline's PURE parts.
The network-fetching parts are exercised by deliberately running the script."""
from gateway.demo.columns import COLUMNS


def test_columns_carry_the_full_view_including_gender():
    names = [c[0] for c in COLUMNS]
    assert names == ["book_id", "title", "category", "published_at", "price",
                     "page_count", "language", "author_id", "author_name",
                     "birth_year", "country", "gender"]
    by_name = {c[0]: c for c in COLUMNS}
    assert by_name["gender"] == ("gender", "text", "author's gender")
    assert by_name["price"] == ("price", "numeric", "retail price in USD")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/test_demo_build.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.demo.columns'`

- [ ] **Step 3: Write the implementation**

Create `gateway/demo/columns.py`:

```python
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
```

Note: existing descriptions are copied verbatim from the current `seed.sql`/`rows.py` (they are the resolver-visible law); `gender` is the one addition, appended last so all existing column order is preserved.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/gateway/test_demo_build.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gateway/demo/columns.py tests/gateway/test_demo_build.py
git commit -m "feat(demo): columns.py — single definition of the view column law (adds gender)"
```

---

### Task 3: Build script — pure functions (TDD)

**Files:**
- Create: `gateway/demo/build_dataset.py`
- Test: `tests/gateway/test_demo_build.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/gateway/test_demo_build.py`:

```python
from gateway.demo.build_dataset import (
    map_category, synth_price, marc_to_iso, normalize_country, emit_seed_sql,
)


def test_map_category_prefers_specific_over_fallback():
    assert map_category(["Science fiction", "American fiction"]) == "Science Fiction"
    assert map_category(["Fantasy", "Fiction"]) == "Fantasy"
    assert map_category(["Detective and mystery stories"]) == "Mystery"
    assert map_category(["Biography", "History"]) == "Non-Fiction"
    assert map_category(["Fiction"]) == "Literary Fiction"
    assert map_category([]) == "Literary Fiction"


def test_synth_price_is_deterministic_and_bounded():
    a = synth_price("A Wizard of Earthsea", "Fantasy", 205)
    b = synth_price("A Wizard of Earthsea", "Fantasy", 205)
    assert a == b
    for title, cat, pages in [("x", "Fantasy", 100), ("Dune", "Science Fiction", 700),
                              ("y", "History", 900), ("z", "Romance", 50)]:
        p = synth_price(title, cat, pages)
        assert 4.99 <= p <= 49.99
        cents = round(p - int(p), 2)
        assert cents in (0.50, 0.99)


def test_marc_to_iso_maps_known_codes_and_none_for_unknown():
    assert marc_to_iso("eng") == "en"
    assert marc_to_iso("fre") == "fr"
    assert marc_to_iso("chi") == "zh"
    assert marc_to_iso("xxx") is None


def test_normalize_country_shortens_long_forms():
    assert normalize_country("United States of America") == "USA"
    assert normalize_country("United Kingdom") == "UK"
    assert normalize_country("Taiwan") == "Taiwan"
    assert normalize_country("Japan") == "Japan"


TINY_SNAPSHOT = {
    "authors": [{"author_id": 1, "author_name": "Ursula K. Le Guin",
                 "birth_year": 1929, "country": "USA", "gender": "female"}],
    "books": [{"book_id": 1, "title": "A Wizard of Earthsea", "category": "Fantasy",
               "published_at": "1968-01-01", "price": 9.99, "page_count": 205,
               "language": "en", "author_id": 1}],
}


def test_emit_seed_sql_structure_and_escaping():
    sql = emit_seed_sql(TINY_SNAPSHOT)
    assert sql.startswith("-- Demo dataset — GENERATED")
    assert "CREATE TABLE authors" in sql and "gender      text" in sql
    assert "CREATE VIEW books_view AS" in sql
    assert "(1, 'A Wizard of Earthsea', 'Fantasy', '1968-01-01', 9.99, 205, 'en', 1)" in sql
    # every view column gets its comment, single quotes doubled
    # (whitespace-insensitive: the emitter pads column names for alignment)
    normalized = " ".join(sql.split())
    assert "COMMENT ON COLUMN books_view.gender IS 'author''s gender';" in normalized
    assert all(f"books_view.{name}" in sql for (name, _t, _d) in COLUMNS)
    # deterministic: same input, same output
    assert emit_seed_sql(TINY_SNAPSHOT) == sql
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/gateway/test_demo_build.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.demo.build_dataset'` (the Task 2 test still passes)

- [ ] **Step 3: Write the implementation (pure parts + skeleton)**

Create `gateway/demo/build_dataset.py`:

```python
"""Build the demo dataset snapshot (spec:
docs/superpowers/specs/2026-07-13-richer-demo-dataset-design.md).

Deliberate, network-using script — NEVER run by tests or CI. Reads
gateway/demo/authors.json (curated list), fetches works from Open Library and
author facts (birth year, country, gender) from Wikidata (both CC0), synthesizes
deterministic prices, and freezes the result into gateway/demo/books.json (the
SOURCE OF TRUTH). seed.sql is emitted from the same snapshot.

Usage:
    python -m gateway.demo.build_dataset               # full fetch + emit both files
    python -m gateway.demo.build_dataset --emit-only   # books.json -> seed.sql only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from gateway.demo.columns import AUTHOR_COLUMNS, BOOK_COLUMNS, COLUMNS

DEMO_DIR = Path(__file__).resolve().parent
USER_AGENT = "sans-schema-demo-builder/0.4 (https://github.com/SansWord/sans_schema)"
MAX_WORKS_PER_AUTHOR = 6
TARGET_MIN, TARGET_MAX = 300, 500

# --- category mapping (Open Library subjects -> small controlled vocabulary) ---
# First matching rule wins; order = specific before generic.
CATEGORY_RULES = [
    ("Science Fiction", ("science fiction", "sci-fi", "dystopia")),
    ("Fantasy",         ("fantasy", "magic", "wizards", "dragons")),
    ("Mystery",         ("mystery", "detective", "crime", "thriller", "suspense")),
    ("Romance",         ("romance", "love stories")),
    ("History",         ("history", "historical")),
    ("Non-Fiction",     ("biography", "memoir", "autobiography", "essays",
                         "science", "politics", "travel", "philosophy")),
]
FALLBACK_CATEGORY = "Literary Fiction"


def map_category(subjects: List[str]) -> str:
    joined = " | ".join(s.lower() for s in subjects)
    for category, needles in CATEGORY_RULES:
        if any(n in joined for n in needles):
            return category
    return FALLBACK_CATEGORY


# --- price synthesis (no open dataset carries prices — spec §Price synthesis) ---
CATEGORY_BASE = {
    "Science Fiction": 14.0, "Fantasy": 13.0, "Mystery": 12.0, "Romance": 11.0,
    "History": 20.0, "Non-Fiction": 18.0, "Literary Fiction": 15.0,
}


def synth_price(title: str, category: str, page_count: int) -> float:
    """Pure + deterministic: category base + page-count factor + stable hash
    jitter, rounded to .50/.99, clamped to [4.99, 49.99]."""
    h = int(hashlib.sha256(title.encode("utf-8")).hexdigest(), 16)
    jitter = (h % 1300) / 100.0 - 6.5                      # +/- 6.50 spread
    raw = CATEGORY_BASE.get(category, 15.0) + page_count / 60.0 + jitter
    raw = min(max(raw, 4.99), 49.99)
    cents = 0.50 if (h >> 16) % 2 else 0.99
    return round(min(max(int(raw) + cents, 4.99), 49.99), 2)


# --- language + country normalization ---
_MARC_TO_ISO = {"eng": "en", "fre": "fr", "chi": "zh", "jpn": "ja", "kor": "ko",
                "spa": "es", "ger": "de", "ita": "it", "swe": "sv", "por": "pt",
                "rus": "ru", "dut": "nl"}


def marc_to_iso(code: str) -> Optional[str]:
    return _MARC_TO_ISO.get(code)


_COUNTRY_SHORT = {
    "United States of America": "USA",
    "United Kingdom": "UK",
    "United Kingdom of Great Britain and Ireland": "UK",
    "Republic of China": "Taiwan",
    "People's Republic of China": "China",
}


def normalize_country(label: str) -> str:
    return _COUNTRY_SHORT.get(label, label)


# --- seed.sql emission (books.json -> SQL artifact) ---
def _sql_str(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def emit_seed_sql(snapshot: Dict[str, Any]) -> str:
    desc = {name: d for (name, _t, d) in COLUMNS}
    lines: List[str] = [
        "-- Demo dataset — GENERATED by `python -m gateway.demo.build_dataset --emit-only`",
        "-- from gateway/demo/books.json (the SOURCE OF TRUTH; rows.py loads the same file).",
        "-- Do NOT edit by hand — edit authors.json / build_dataset.py and re-run.",
        "DROP VIEW IF EXISTS books_view;",
        "DROP TABLE IF EXISTS books;",
        "DROP TABLE IF EXISTS authors;",
        "",
        "CREATE TABLE authors (",
        "    author_id   integer PRIMARY KEY,",
        "    author_name text NOT NULL,",
        "    birth_year  integer,",
        "    country     text,",
        "    gender      text",
        ");",
        "",
        "CREATE TABLE books (",
        "    book_id      integer PRIMARY KEY,",
        "    title        text NOT NULL,",
        "    category     text,",
        "    published_at date,",
        "    price        numeric(8,2),",
        "    page_count   integer,",
        "    language     text,",
        "    author_id    integer REFERENCES authors(author_id)",
        ");",
        "",
        "INSERT INTO authors (author_id, author_name, birth_year, country, gender) VALUES",
    ]
    author_rows = [
        "    ({0}, {1}, {2}, {3}, {4})".format(
            a["author_id"], _sql_str(a["author_name"]), a["birth_year"],
            _sql_str(a["country"]) if a.get("country") else "NULL",
            _sql_str(a["gender"]) if a.get("gender") else "NULL")
        for a in snapshot["authors"]
    ]
    lines.append(",\n".join(author_rows) + ";")
    lines.append("")
    lines.append("INSERT INTO books (book_id, title, category, published_at, price,"
                 " page_count, language, author_id) VALUES")
    book_rows = [
        "    ({0}, {1}, {2}, {3}, {4}, {5}, {6}, {7})".format(
            b["book_id"], _sql_str(b["title"]), _sql_str(b["category"]),
            _sql_str(b["published_at"]), format(b["price"], ".2f"),
            b["page_count"], _sql_str(b["language"]), b["author_id"])
        for b in snapshot["books"]
    ]
    lines.append(",\n".join(book_rows) + ";")
    lines += [
        "",
        "CREATE VIEW books_view AS",
        "    SELECT b.book_id, b.title, b.category, b.published_at, b.price, b.page_count,",
        "           b.language, a.author_id, a.author_name, a.birth_year, a.country, a.gender",
        "    FROM books b JOIN authors a ON a.author_id = b.author_id;",
        "",
        "-- Comment the VIEW columns directly: a view does not inherit its base tables'",
        "-- column comments, and describe() introspects the view. These descriptions are",
        "-- the resolver-visible law (single definition: gateway/demo/columns.py).",
    ]
    width = max(len(n) for (n, _t, _d) in COLUMNS)
    for (name, _t, _d) in COLUMNS:
        lines.append("COMMENT ON COLUMN books_view.{0} IS {1};".format(
            name.ljust(width), _sql_str(desc[name])))
    return "\n".join(lines) + "\n"
```

(The fetch + assembly half comes in Task 4 — this file must import cleanly without network access, which the tests prove.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/gateway/test_demo_build.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add gateway/demo/build_dataset.py tests/gateway/test_demo_build.py
git commit -m "feat(demo): build_dataset.py pure core — category map, price synthesis, seed.sql emitter"
```

---

### Task 4: Build script — fetch + assembly

**Files:**
- Modify: `gateway/demo/build_dataset.py` (append)

No unit tests for this half — it is network I/O, exercised by the deliberate run in Task 6. Keep each fetch function thin.

- [ ] **Step 1: Append the fetch + assembly code**

Append to `gateway/demo/build_dataset.py`:

```python
# --- fetch (deliberate use only; polite: 1 req/s, identified UA) ---
def _get_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_author_facts(name: str) -> Optional[Dict[str, Any]]:
    """Wikidata: birth year, country, gender for a human writer with this
    exact English label. Returns None when not found (caller logs + skips)."""
    query = """
    SELECT ?birth ?genderLabel ?countryLabel WHERE {{
      ?p wdt:P31 wd:Q5; rdfs:label {name}@en; wdt:P569 ?birth; wdt:P106 ?occ.
      VALUES ?occ {{ wd:Q36180 wd:Q482980 wd:Q49757 wd:Q6625963 wd:Q4853732 }}
      OPTIONAL {{ ?p wdt:P21 ?gender. }}
      OPTIONAL {{ ?p wdt:P27 ?country. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT 1
    """.format(name=json.dumps(name))          # json.dumps -> quoted/escaped literal
    url = ("https://query.wikidata.org/sparql?format=json&query="
           + urllib.parse.quote(query))
    rows = _get_json(url)["results"]["bindings"]
    if not rows:
        return None
    row = rows[0]
    facts = {"birth_year": int(row["birth"]["value"][:4])}
    facts["gender"] = row.get("genderLabel", {}).get("value")
    country = row.get("countryLabel", {}).get("value")
    facts["country"] = normalize_country(country) if country else None
    return facts


def fetch_works(name: str, lang_hint: Optional[str]) -> List[Dict[str, Any]]:
    """Open Library search: an author's most-published works with complete-enough
    metadata. Drop policy (spec): missing year/pages/language -> drop the work."""
    url = ("https://openlibrary.org/search.json?author=" + urllib.parse.quote(name)
           + "&fields=title,first_publish_year,number_of_pages_median,language,subject"
           + "&sort=editions&limit=30")
    docs = _get_json(url).get("docs", [])
    works, seen_titles = [], set()
    for d in docs:
        title = (d.get("title") or "").strip()
        year = d.get("first_publish_year")
        pages = d.get("number_of_pages_median")
        marcs = d.get("language") or []
        if not title or not year or not pages or title.lower() in seen_titles:
            continue
        if lang_hint:
            lang = lang_hint if any(marc_to_iso(m) == lang_hint for m in marcs) else None
        else:
            lang = next((iso for m in marcs if (iso := marc_to_iso(m)) == "en"), None) \
                or next((iso for m in marcs if (iso := marc_to_iso(m))), None)
        if not lang:
            continue
        seen_titles.add(title.lower())
        works.append({"title": title, "year": int(year), "pages": int(pages),
                      "language": lang, "subjects": d.get("subject") or []})
        if len(works) == MAX_WORKS_PER_AUTHOR:
            break
    return works


def build_snapshot(curated: List[Dict[str, Any]]) -> Dict[str, Any]:
    authors, books = [], []
    for entry in curated:
        name, lang_hint = entry["name"], entry.get("lang")
        facts = fetch_author_facts(name)
        time.sleep(1)
        if facts is None:
            print(f"  SKIP (no Wikidata match): {name}", file=sys.stderr)
            continue
        works = fetch_works(name, lang_hint)
        time.sleep(1)
        if not works:
            print(f"  SKIP (no usable works): {name}", file=sys.stderr)
            continue
        author_id = len(authors) + 1
        authors.append({"author_id": author_id, "author_name": name,
                        "birth_year": facts["birth_year"],
                        "country": facts["country"], "gender": facts["gender"]})
        for w in sorted(works, key=lambda w: (w["year"], w["title"])):
            category = map_category(w["subjects"])
            books.append({
                "book_id": len(books) + 1, "title": w["title"], "category": category,
                # Open Library carries first-publish YEAR only; month/day are set
                # to Jan 1 by convention (precedent: the old seed's 'Vieux Roman').
                "published_at": f"{w['year']}-01-01",
                "price": synth_price(w["title"], category, w["pages"]),
                "page_count": w["pages"], "language": w["language"],
                "author_id": author_id,
            })
        print(f"  ok: {name} — {len(works)} works", file=sys.stderr)
    return {"authors": authors, "books": books}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-only", action="store_true",
                        help="regenerate seed.sql from the committed books.json (no network)")
    args = parser.parse_args()
    books_path = DEMO_DIR / "books.json"
    if not args.emit_only:
        curated = json.loads((DEMO_DIR / "authors.json").read_text("utf-8"))
        snapshot = build_snapshot(curated)
        n = len(snapshot["books"])
        print(f"built {n} books from {len(snapshot['authors'])} authors", file=sys.stderr)
        if not (TARGET_MIN <= n <= TARGET_MAX):
            print(f"WARNING: outside spec range [{TARGET_MIN}, {TARGET_MAX}]", file=sys.stderr)
        books_path.write_text(
            json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n", "utf-8")
    snapshot = json.loads(books_path.read_text("utf-8"))
    (DEMO_DIR / "seed.sql").write_text(emit_seed_sql(snapshot), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Python-3.9 caveat: the `:=` inside a generator in `fetch_works` is valid 3.8+; no other version-sensitive syntax is used.

- [ ] **Step 2: Verify the module still imports cleanly (no network at import)**

Run: `pytest tests/gateway/test_demo_build.py -v && python -c "import gateway.demo.build_dataset"`
Expected: PASS, no output from the import.

- [ ] **Step 3: Commit**

```bash
git add gateway/demo/build_dataset.py
git commit -m "feat(demo): build_dataset.py fetch half — Open Library works + Wikidata author facts"
```

---

### Task 5: The curated author list

**Files:**
- Create: `gateway/demo/authors.json`

- [ ] **Step 1: Write the list**

Create `gateway/demo/authors.json` — buckets per spec: `taiwan` (10, Yang Shuang-zi + Kevin Chen required), `french` (8), `young` (8, born after 1980), `sff` (15), `general` (30). `lang` is the language-hint (omit for English):

```json
[
 {"name": "Yang Shuang-zi", "bucket": "taiwan", "lang": "zh"},
 {"name": "Kevin Chen", "bucket": "taiwan", "lang": "zh"},
 {"name": "Wu Ming-yi", "bucket": "taiwan", "lang": "zh"},
 {"name": "Qiu Miaojin", "bucket": "taiwan", "lang": "zh"},
 {"name": "Sanmao", "bucket": "taiwan", "lang": "zh"},
 {"name": "Chi Ta-wei", "bucket": "taiwan", "lang": "zh"},
 {"name": "Li Ang", "bucket": "taiwan", "lang": "zh"},
 {"name": "Pai Hsien-yung", "bucket": "taiwan", "lang": "zh"},
 {"name": "Huang Chun-ming", "bucket": "taiwan", "lang": "zh"},
 {"name": "Lin Yi-han", "bucket": "taiwan", "lang": "zh"},
 {"name": "Albert Camus", "bucket": "french", "lang": "fr"},
 {"name": "Jules Verne", "bucket": "french", "lang": "fr"},
 {"name": "Leïla Slimani", "bucket": "french", "lang": "fr"},
 {"name": "Amélie Nothomb", "bucket": "french", "lang": "fr"},
 {"name": "Victor Hugo", "bucket": "french", "lang": "fr"},
 {"name": "Annie Ernaux", "bucket": "french", "lang": "fr"},
 {"name": "Antoine de Saint-Exupéry", "bucket": "french", "lang": "fr"},
 {"name": "Marguerite Duras", "bucket": "french", "lang": "fr"},
 {"name": "Sally Rooney", "bucket": "young"},
 {"name": "R.F. Kuang", "bucket": "young"},
 {"name": "Ocean Vuong", "bucket": "young"},
 {"name": "Tomi Adeyemi", "bucket": "young"},
 {"name": "Angie Thomas", "bucket": "young"},
 {"name": "Chloe Gong", "bucket": "young"},
 {"name": "Brit Bennett", "bucket": "young"},
 {"name": "Raven Leilani", "bucket": "young"},
 {"name": "Ursula K. Le Guin", "bucket": "sff"},
 {"name": "Liu Cixin", "bucket": "sff", "lang": "zh"},
 {"name": "Ted Chiang", "bucket": "sff"},
 {"name": "N.K. Jemisin", "bucket": "sff"},
 {"name": "Isaac Asimov", "bucket": "sff"},
 {"name": "Arthur C. Clarke", "bucket": "sff"},
 {"name": "Octavia E. Butler", "bucket": "sff"},
 {"name": "Frank Herbert", "bucket": "sff"},
 {"name": "Ken Liu", "bucket": "sff"},
 {"name": "Andy Weir", "bucket": "sff"},
 {"name": "Martha Wells", "bucket": "sff"},
 {"name": "Becky Chambers", "bucket": "sff"},
 {"name": "Ann Leckie", "bucket": "sff"},
 {"name": "Philip K. Dick", "bucket": "sff"},
 {"name": "William Gibson", "bucket": "sff"},
 {"name": "Haruki Murakami", "bucket": "general", "lang": "ja"},
 {"name": "Banana Yoshimoto", "bucket": "general", "lang": "ja"},
 {"name": "Yoko Ogawa", "bucket": "general", "lang": "ja"},
 {"name": "Keigo Higashino", "bucket": "general", "lang": "ja"},
 {"name": "Han Kang", "bucket": "general", "lang": "ko"},
 {"name": "Gabriel García Márquez", "bucket": "general", "lang": "es"},
 {"name": "Isabel Allende", "bucket": "general", "lang": "es"},
 {"name": "Jorge Luis Borges", "bucket": "general", "lang": "es"},
 {"name": "Elena Ferrante", "bucket": "general", "lang": "it"},
 {"name": "Stieg Larsson", "bucket": "general", "lang": "sv"},
 {"name": "Fredrik Backman", "bucket": "general", "lang": "sv"},
 {"name": "Toni Morrison", "bucket": "general"},
 {"name": "George Orwell", "bucket": "general"},
 {"name": "Jane Austen", "bucket": "general"},
 {"name": "Virginia Woolf", "bucket": "general"},
 {"name": "Ernest Hemingway", "bucket": "general"},
 {"name": "Kazuo Ishiguro", "bucket": "general"},
 {"name": "Salman Rushdie", "bucket": "general"},
 {"name": "Chimamanda Ngozi Adichie", "bucket": "general"},
 {"name": "Zadie Smith", "bucket": "general"},
 {"name": "Margaret Atwood", "bucket": "general"},
 {"name": "Alice Munro", "bucket": "general"},
 {"name": "Yuval Noah Harari", "bucket": "general"},
 {"name": "Tara Westover", "bucket": "general"},
 {"name": "Trevor Noah", "bucket": "general"},
 {"name": "Bill Bryson", "bucket": "general"},
 {"name": "Mary Beard", "bucket": "general"},
 {"name": "Agatha Christie", "bucket": "general"},
 {"name": "Raymond Chandler", "bucket": "general"},
 {"name": "Gillian Flynn", "bucket": "general"}
]
```

(71 authors × up to 6 works ≈ 350–420 books after drops — inside the 300–500 spec range. Skips get logged; if the run lands under 300, widen `MAX_WORKS_PER_AUTHOR` to 7 or add authors — do NOT relax the drop policy.)

- [ ] **Step 2: Validate it parses**

Run: `python -c "import json,pathlib; a=json.loads(pathlib.Path('gateway/demo/authors.json').read_text()); print(len(a), 'authors')"`
Expected: `71 authors`

- [ ] **Step 3: Commit**

```bash
git add gateway/demo/authors.json
git commit -m "feat(demo): curated author list — taiwan/french/young/sff/general buckets"
```

---

### Task 6: Run the build — generate + eyeball the snapshot

Network required. This is the one deliberate fetch; everything after runs from the frozen files.

- [ ] **Step 1: Run the build**

Run: `python -m gateway.demo.build_dataset`
Expected: per-author `ok:`/`SKIP` lines on stderr, then `built N books from M authors` with 300 ≤ N ≤ 500. Both `gateway/demo/books.json` and `gateway/demo/seed.sql` regenerated.

If a **required** author (Yang Shuang-zi, Kevin Chen) is skipped: their Wikidata label or Open Library listing didn't match. Fix by adjusting the `name` to the exact English label (check `https://www.wikidata.org/w/index.php?search=<name>`) — never by relaxing the drop policy.

- [ ] **Step 2: Eyeball the snapshot**

```bash
python - <<'EOF'
import json, collections
s = json.load(open("gateway/demo/books.json"))
books, authors = s["books"], {a["author_id"]: a for a in s["authors"]}
print("books:", len(books), " authors:", len(authors))
print("languages:", collections.Counter(b["language"] for b in books))
print("categories:", collections.Counter(b["category"] for b in books))
print("genders:", collections.Counter(a["gender"] for a in authors.values()))
print("countries:", collections.Counter(a["country"] for a in authors.values()))
print("required:", {n for n in ("Yang Shuang-zi", "Kevin Chen")
                    if any(a["author_name"] == n for a in authors.values())})
print("\nsample zh rows:")
for b in books:
    if b["language"] == "zh":
        print("  ", b["title"], "—", authors[b["author_id"]]["author_name"])
EOF
```

Check: languages include `zh` and `fr`; both required authors present; `Taiwan` in countries; both `male` and `female` genders; zh titles look like real books by those authors (if they're all English translations that's acceptable — the `language` column reflects the edition language we selected).

- [ ] **Step 3: Sanity-check seed.sql loads into Postgres**

```bash
docker run --rm -d --name sans-pg-test -p 15433:5432 -e POSTGRES_PASSWORD=test postgres:16
sleep 3
docker exec -i sans-pg-test psql -U postgres -d postgres < gateway/demo/seed.sql
docker exec -i sans-pg-test psql -U postgres -d postgres -c "SELECT count(*) FROM books_view;"
```

Expected: count matches the built book count. Leave the container running — Task 10 uses it.

- [ ] **Step 4: Commit the frozen snapshot**

```bash
git add gateway/demo/books.json gateway/demo/seed.sql
git commit -m "feat(demo): frozen snapshot — ~350 real books from Open Library + Wikidata"
```

---

### Task 7: Rewrite `rows.py` to load the snapshot

**Files:**
- Modify: `gateway/demo/rows.py` (full rewrite)

The existing fake-connector tests (`tests/gateway/test_fake_connector.py`) are the harness — they assert `describe()`/`execute()` behavior through `VIEW_FIELDS`/`VIEW_ROWS` and must pass unchanged.

- [ ] **Step 1: Rewrite the module**

Replace the whole of `gateway/demo/rows.py` with:

```python
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
```

- [ ] **Step 2: Run the fake-connector + contract tests**

Run: `pytest tests/gateway/test_fake_connector.py tests/gateway/test_contracts.py tests/gateway/test_pipeline.py tests/gateway/test_app.py -v`
Expected: PASS (all — these depend on column paths and behavior, not rows)

- [ ] **Step 3: Commit**

```bash
git add gateway/demo/rows.py
git commit -m "feat(demo): rows.py loads the frozen snapshot — no more hand-mirrored literals"
```

---

### Task 8: Package data + packaging test

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_packaging.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py`:

```python
def test_demo_snapshot_ships_as_package_data():
    from importlib.resources import files
    snapshot = files("gateway.demo").joinpath("books.json")
    assert snapshot.is_file()
    from gateway.demo.rows import VIEW_ROWS, VIEW_FIELDS
    assert len(VIEW_ROWS) >= 300
    assert any(name == "gender" for (name, _t, _d, _s) in VIEW_FIELDS)
```

- [ ] **Step 2: Run it (passes from the repo checkout; the pyproject change is for installed wheels)**

Run: `pytest tests/test_packaging.py -v`
Expected: PASS (repo-root import). The pyproject edit below makes the same hold for `pip install`-ed copies — that's what the Docker image uses.

- [ ] **Step 3: Add package data to pyproject.toml**

In `pyproject.toml`, after the `[tool.setuptools]` table's `packages` line, add:

```toml
[tool.setuptools.package-data]
"gateway.demo" = ["*.json", "*.sql"]
```

- [ ] **Step 4: Verify a built wheel carries the data files**

Run: `pip wheel --no-deps -w /tmp/sans-wheel . && python -c "import zipfile,glob; print([n for n in zipfile.ZipFile(glob.glob('/tmp/sans-wheel/*.whl')[0]).namelist() if 'demo' in n])"`
Expected: the list includes `gateway/demo/books.json`, `gateway/demo/authors.json`, and `gateway/demo/seed.sql`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_packaging.py
git commit -m "build: ship gateway/demo JSON + SQL as package data"
```

---

### Task 9: Dataset invariants — chip coverage + determinism guard

**Files:**
- Create: `tests/gateway/test_demo_dataset.py`

These tests pin the spec's invariants over the frozen snapshot. They are expected to pass immediately — if any fails, the DATASET is wrong: fix `authors.json`/the build script and re-run Task 6, don't weaken the test.

- [ ] **Step 1: Write the tests**

Create `tests/gateway/test_demo_dataset.py`:

```python
"""Invariants over the frozen demo snapshot (spec 2026-07-13, §Tests).
If one of these fails, fix the dataset (authors.json / build script + re-run
the build), never the assertion."""
import json
from pathlib import Path

from gateway.demo.build_dataset import emit_seed_sql
from gateway.demo.rows import VIEW_ROWS

DEMO = Path(__file__).resolve().parents[2] / "gateway" / "demo"


def test_size_is_in_the_spec_range():
    assert 300 <= len(VIEW_ROWS) <= 500


def test_required_taiwanese_authors_survived_the_drop_policy():
    names = {r["author_name"] for r in VIEW_ROWS}
    assert "Yang Shuang-zi" in names
    assert "Kevin Chen" in names


def test_chip_scifi_under_25_returns_several_rows():
    hits = [r for r in VIEW_ROWS
            if r["category"] == "Science Fiction" and r["price"] < 25]
    assert len(hits) >= 5


def test_chip_written_in_french_returns_rows():
    assert any(r["language"] == "fr" for r in VIEW_ROWS)


def test_chip_young_authors_returns_rows():
    assert any(r["birth_year"] > 1980 for r in VIEW_ROWS)


def test_chip_mandarin_price_and_age_returns_rows():
    # 價格低於 $20, 作者 35 歲以上 — born 1985 or earlier keeps the chip true
    # for years without hardcoding "today".
    assert any(r["price"] < 20 and r["birth_year"] <= 1985 for r in VIEW_ROWS)


def test_gender_field_has_both_male_and_female_rows():
    genders = {r["gender"] for r in VIEW_ROWS}
    assert {"male", "female"} <= genders


def test_committed_seed_sql_matches_the_snapshot():
    snapshot = json.loads((DEMO / "books.json").read_text("utf-8"))
    assert emit_seed_sql(snapshot) == (DEMO / "seed.sql").read_text("utf-8")
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/gateway/test_demo_dataset.py -v`
Expected: PASS. On any failure, apply the header rule: adjust the dataset, re-run `python -m gateway.demo.build_dataset`, re-commit the snapshot — then re-run this step.

- [ ] **Step 3: Commit**

```bash
git add tests/gateway/test_demo_dataset.py
git commit -m "test(demo): pin chip coverage, required authors, gender, and seed.sql determinism"
```

---

### Task 10: Move the row-dependent connector tests to the new data

**Files:**
- Modify: `tests/gateway/test_seam_parity.py:5-11,27-28`
- Modify: `tests/gateway/test_postgres_connector.py:9,11-21`

The exact-row assertions anchor on **Yang Shuang-zi** — a required author guarded by Task 9, so the expected set is stable and small (≤ `MAX_WORKS_PER_AUTHOR` rows).

- [ ] **Step 1: Compute the expected titles from the frozen snapshot**

```bash
python - <<'EOF'
from gateway.demo.rows import VIEW_ROWS
rows = [r for r in VIEW_ROWS if r["author_name"] == "Yang Shuang-zi"]
for r in rows:
    print((r["title"], r["category"]))
print("cheap:", sorted(r["title"] for r in rows if r["price"] < 30))
EOF
```

Copy the printed tuples/titles — they are pasted into the two tests below.

- [ ] **Step 2: Update `test_seam_parity.py`**

Replace the module-level `IR` and the final assertion (keep `test_introspected_schema_matches_the_fake_mirror` untouched):

```python
IR = CanonicalQueryIR(
    select=[ResolvedField("t", "books_view.title", 0.9),
            ResolvedField("g", "books_view.category", 0.9)],
    predicate={"op": "and", "clauses": [
        {"op": "eq", "field": "books_view.author_name", "value": "Yang Shuang-zi"},
        {"op": "lte", "field": "books_view.price", "value": 100}]},
    where_confidence=0.9, where_raw="books by Yang Shuang-zi under $100")
```

and in `test_same_ir_selects_the_same_rows`, replace the hardcoded set:

```python
    assert key(pg_rows) == {
        # paste the exact (title, category) tuples printed in Step 1
    }
```

- [ ] **Step 3: Update `test_postgres_connector.py`**

In `test_execute_compiles_ast_and_keys_by_path`, replace the predicate and expected set:

```python
    predicate={"op": "and", "clauses": [
        {"op": "eq", "field": "books_view.author_name", "value": "Yang Shuang-zi"},
        {"op": "lt", "field": "books_view.price", "value": 30}]},
```

```python
    assert {r["books_view.title"] for r in rows} == {
        # paste the "cheap:" titles printed in Step 1
    }
```

Also de-flake `test_describe_introspects_view_columns` line 9 — `_samples()` is `DISTINCT … LIMIT 5` with no ORDER BY, and the category vocabulary now has ~7 values, so membership of one specific value is not guaranteed. Replace:

```python
    assert "Science Fiction" in by_path["books_view.category"].samples
```

with:

```python
    vocab = {"Science Fiction", "Fantasy", "Mystery", "Romance", "History",
             "Non-Fiction", "Literary Fiction"}
    samples = by_path["books_view.category"].samples
    assert samples and set(samples) <= vocab
```

- [ ] **Step 4: Run the full suite against the Task 6 container**

Run:
```bash
TEST_DATABASE_URL=postgresql://postgres:test@localhost:15433/postgres pytest tests/ -v
```
Expected: ALL PASS (Postgres-backed tests included; `tests/live/` skips without a key — that's fine).

- [ ] **Step 5: Commit + stop the container**

```bash
git add tests/gateway/test_seam_parity.py tests/gateway/test_postgres_connector.py
git commit -m "test: move row-dependent connector tests to the new snapshot; de-flake samples assertion"
docker stop sans-pg-test
```

---

### Task 11: Playground gender chip

**Files:**
- Modify: `playground/lib/examples.ts`

Spec marks this optional and it was included at plan time. One chip, no other playground changes.

- [ ] **Step 1: Add the chip**

In `playground/lib/examples.ts`, append to `EXAMPLES` (before the closing `];`):

```typescript
  { label: "Books by female authors",
    want: ["book name", "writer", "writer's gender"],
    where: "written by a female author" },
```

- [ ] **Step 2: Type-check the playground**

Run: `cd playground && npx tsc --noEmit && cd ..`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add playground/lib/examples.ts
git commit -m "feat(playground): gender chip — books by female authors"
```

---

### Task 12: Docs — close the loop

**Files:**
- Modify: `gateway/README.md:29-30`
- Modify: `gateway/DEPLOY.md` (after the one-time-setup block)
- Modify: `docs/devlog.md` (new v0.4.0 entry + TL;DR row)
- Modify: `todo.md`
- Check only: `docs/architecture.md`, `docs/system-design.md`, `docs/demo/script.md`

- [ ] **Step 1: Sweep for stale references to the old 6-book data**

Run: `grep -rn "Long Orbit\|Vieux Roman\|Orbit of Dreams\|Silent Fields\|Future Shock\|hand-written" docs/ gateway/ playground/ --include="*.md" --include="*.ts" --include="*.tsx"`
Fix every hit (e.g. `docs/demo/script.md` walkthroughs that name old titles — swap in titles from the new snapshot that satisfy the same filter).

- [ ] **Step 2: Update `gateway/README.md`**

Replace lines 29–30:

```markdown
`gateway/demo/books.json` is the source of truth for the demo data (~350 real
books from Open Library + Wikidata; `seed.sql` is generated from it by
`python -m gateway.demo.build_dataset --emit-only`); the gateway introspects
`books_view` at startup — no schema is hardcoded.
```

- [ ] **Step 3: Add the re-seed note to `gateway/DEPLOY.md`**

After the "One-time setup" section, add:

```markdown
## Re-seed after a dataset change

When `gateway/demo/seed.sql` changes (e.g. a dataset rebuild), re-run the seed
step above (proxy + `psql < gateway/demo/seed.sql` — the script drops and
recreates the tables), then restart the app so the memoized schema refreshes:

```bash
fly apps restart sans-schema-demo
```

Re-click the playground chips afterward — the in-process resolution cache
empties on restart.
```

- [ ] **Step 4: Devlog v0.4.0 entry + TL;DR row**

Prepend a `## v0.4.0 — Richer real demo dataset (YYYY-MM-DD HH:MM)` entry to `docs/devlog.md` (timestamp from `git log` at commit time), following the house format (`**Review:** not yet`, **Design docs:** linking this spec + plan, **What was built:** bullets, **Key technical learnings:** tagged bullets). Add the matching TL;DR table row with an anchor link. Content to cover: books.json as source of truth, generated seed.sql, JSON-loading rows.py, gender column, chip-coverage + determinism tests, the year-only→Jan-1 publish-date convention, and the Fly re-seed.

- [ ] **Step 5: Update `todo.md`**

Mark done (move into the done style used by the file): the "Extend the demo data" bullet under **Demo improvements** and the "Richer demo dataset from open data" bullet under **MVP shape & setup** — note the landed shape (source-of-truth inversion + gender column) in one line each.

- [ ] **Step 6: Commit**

```bash
git add gateway/README.md gateway/DEPLOY.md docs/devlog.md todo.md docs/demo/script.md
git commit -m "docs: fold richer demo dataset into README/DEPLOY/devlog/todo"
```

(Adjust the `git add` list to the files actually touched in Step 1's sweep — explicit paths only, never `git add -A`.)

---

### Task 13: Secret scan + PR

- [ ] **Step 1: Secret scan (load-bearing, per CLAUDE.md)**

Run: `git diff main --name-only` then `git diff main | grep -inE "api[_-]?key|secret|token|password|\.env" | grep -v "GEMINI_API_KEY=<key>"`
Expected: no real secrets (doc placeholders like `<key>` are fine).

- [ ] **Step 2: Push + open the PR**

```bash
git push -u origin feat/richer-demo-dataset
gh pr create --title "Richer real demo dataset (~350 books, gender column)" --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-07-13-richer-demo-dataset-design.md
(plan: docs/superpowers/plans/2026-07-13-richer-demo-dataset.md).

- books.json (frozen snapshot from Open Library + Wikidata, both CC0) is the new
  source of truth; seed.sql is generated; rows.py loads the JSON.
- New nullable `gender` column on authors/books_view.
- Chip-coverage + seed.sql-determinism tests; row-dependent tests moved.
- After merge: re-seed the Fly Postgres + restart (gateway/DEPLOY.md § Re-seed).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Then **stop** — merging is the user's call.

---

### Task 14: Rollout (operator step, after merge — run WITH the user)

- [ ] **Step 1: Re-seed the deployed Fly Postgres**

Per `gateway/DEPLOY.md`: `fly proxy 15432:5432 -a sans-schema-demo-db`, then in a second terminal `psql "<attach-connection-string, host swapped to localhost:15432>" < gateway/demo/seed.sql`.

- [ ] **Step 2: Restart the app (memoized schema must refresh)**

Run: `fly apps restart sans-schema-demo`

- [ ] **Step 3: Verify live**

Click every playground chip at `https://sans-schema-playground.vercel.app` — each returns rows (the new gender chip included), and run one live gender query ("books by female authors") to sanity-check resolution of the new field per the spec's out-of-scope note.

---

## Self-review notes (done at plan time)

- **Spec coverage:** size range (T6/T9), fixed schema + gender (T2/T6), 100% real + Taiwan (T5/T9), script+snapshot committed (T3–T6), price synthesis (T3), source-of-truth inversion (T6/T7), packaging (T8), moved tests (T10), chip coverage + determinism guards (T9), optional gender chip (T11), re-seed + restart + live sanity check (T12/T14), docs (T12). Deviation to record in the devlog: published_at is year-accurate with month/day set to Jan 1 (Open Library carries first-publish year only).
- **Known risk:** Wikidata label lookups may miss some authors (logged as SKIP; headroom absorbs it; required authors are test-guarded). Open Library subject quality varies — `map_category` is rule-ordered to keep misfiles rare, and no test pins a specific book's category.
- **Flake fix folded in:** the `DISTINCT … LIMIT 5` samples assertion (T10 Step 3).
