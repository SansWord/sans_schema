# Richer Real Demo Dataset — Design

**Date:** 2026-07-13
**Status:** Approved (brainstorm session)
**Elevates:** todo.md → "Richer demo dataset from open data" (MVP shape & setup) +
"Extend the demo data" (Demo improvements)
**Docs consulted:** `todo.md`, `gateway/demo/seed.sql`, `gateway/demo/rows.py`,
`tests/gateway/test_seam_parity.py`, `tests/gateway/test_postgres_connector.py`,
`tests/gateway/test_fake_connector.py`, `tests/gateway/test_pipeline.py`,
`tests/gateway/test_app.py`, `playground/lib/examples.ts`, `gateway/DEPLOY.md`

## Goal

Replace the 6 hand-written demo books with **~350 real books from ~70 real
authors**, sourced from open data, so the deployed playground feels like a real
catalog. The playground chips must keep returning sensible results, and all
row-dependent tests move with the data.

## Settled decisions (from the brainstorm)

| Question | Decision |
|---|---|
| Size | ~300–500 books (target ~350) |
| Schema | **Fixed + one addition** — the existing 11 `books_view` columns keep their names and comments; a nullable `gender` column is added to `authors` and the view (user-requested during spec review, reversing the earlier rows-only scoping) |
| Data purity | **100% real** — no synthetic rows, no easter eggs, no future publish dates; must include Taiwanese authors/books |
| Pipeline | **Commit build script + frozen snapshot**; tests never touch the network |
| Sourcing | **Approach A: curated author list** → Open Library (works/editions) + Wikidata (author birth year, country); both CC0 |

Consequences accepted: the "SansWord" easter-egg row and the 2026 publish dates
go away; date filters run against real 2024–2025 releases instead.

## Dataset shape & curation

The curation instrument is a committed author list, `gateway/demo/authors.json`,
each entry tagged with the coverage bucket it serves:

- **Taiwanese authors (~10):** **Yang Shuang-zi and Kevin Chen are required
  inclusions** (user-specified); plus e.g. Wu Ming-yi, Qiu Miaojin, Sanmao,
  Chi Ta-wei, Li Ang, Pai Hsien-yung — gives the Mandarin chip real `zh` rows.
- **French-language (~8):** e.g. Camus, Verne, Slimani — keeps "Written in
  French" working.
- **Born after 1980 (~8):** e.g. Sally Rooney (b. 1991), R.F. Kuang (b. 1996) —
  keeps "Young authors" working.
- **Sci-fi/fantasy (~15):** Le Guin stays (continuity), plus Liu Cixin, Ted
  Chiang, N.K. Jemisin, etc. — feeds "Sci-fi under $25".
- **General literary / non-fiction / classics (~30):** ballast so the catalog
  reads as a real bookstore.

Per-author work count is capped at ~6 so nobody dominates.

**Column sources:** title, publish date, page count, language from Open
Library; author birth year, country, and gender from Wikidata (citizenship
normalized to the short forms already in use — "Taiwan", "USA", "UK",
"France", … ; gender from the `sex or gender` property, values as Wikidata
gives them, e.g. "male" / "female" / "non-binary").
`category` maps Open Library subjects onto a small controlled vocabulary
(~8 values; the current 3 — Science Fiction, Fantasy, Non-Fiction — are a
subset, so existing sample values stay valid).

**Drop policy:** rows missing a critical field (publish date, language, page
count, author birth year) are **dropped**, never patched — 100% real means no
invented metadata. The author list carries headroom so drops don't sink bucket
coverage. `gender` is nullable like `country`: a missing value stays NULL, it
never drops a row.

**Schema addition:** a nullable `gender text` column on `authors`, carried
through `books_view`, with comment `author's gender` (mirrored in
`VIEW_FIELDS`). All other columns, names, and comments are unchanged. The
schema-hash parity test recomputes on both sides (seed.sql and rows.py change
together), so it keeps guarding drift without edits.

## Build pipeline & artifacts

```
gateway/demo/authors.json          (curated list — the human input)
        │
        ▼
gateway/demo/build_dataset.py      (fetch Open Library + Wikidata, select best
        │                           edition, map categories, synthesize prices)
        ▼
gateway/demo/books.json            (frozen snapshot — SOURCE OF TRUTH, committed)
        │
        ├─► emits gateway/demo/seed.sql   (generated, committed, header says so)
        └─► gateway/demo/rows.py          (loads books.json at import)
```

Ownership inverts: `books.json` becomes the source of truth; `seed.sql` becomes
a generated artifact (its header states this); `rows.py` loads the JSON at
import instead of hand-mirroring row literals.

`rows.py` keeps its public names (`VIEW_NAME`, `VIEW_FIELDS`, `VIEW_ROWS`) so
the fake connector and tests keep their shape:

- `VIEW_ROWS` — loaded from `books.json`.
- `VIEW_FIELDS` — **descriptions stay static** in `rows.py` (they are the
  resolver-visible law; the generator mirrors them into `seed.sql`'s
  `COMMENT ON COLUMN` statements so the schema-hash parity test still holds).
  Sample values are derived deterministically from the loaded rows.

The build script runs only when deliberately invoked (documented in its
docstring); tests and CI never fetch from the network.

**Packaging:** `books.json` must ship as package data (the installed package
includes `gateway/demo/`; `rows.py` reads the JSON relative to its own module
path, e.g. via `importlib.resources`). Verify `tests/test_packaging.py` covers
it or extend it.

## Price synthesis

No open bibliographic dataset carries prices (commercial data), so the build
script computes them with a pure deterministic function:

```
price = round_to_.99_or_.50( category_base + page_count_factor + stable_hash_jitter(title) )
clamped to [4.99, 49.99]
```

Tuned so the distribution straddles the $20 and $25 chip thresholds. Prices are
computed once at build time and frozen into `books.json`; re-running the script
on the same inputs reproduces the same prices.

## Tests

**Rewritten (move with the data):**

- `tests/gateway/test_seam_parity.py` — schema-hash assertion unchanged. The
  exact-row assertion is rewritten around a predicate chosen to select a small,
  stable subset of the new snapshot, with expected titles hardcoded from the
  frozen data. Still exact, still deterministic.
- `tests/gateway/test_postgres_connector.py` — the hardcoded two-title
  assertion gets the same treatment.

**New:**

- **Chip-coverage test** — for each playground chip, assert the frozen dataset
  contains satisfying rows (≥1 `zh` book under $20 with author aged 35+, ≥1
  French-language book, several sci-fi under $25, ≥1 author born after 1980).
  Also asserts the required authors (Yang Shuang-zi, Kevin Chen) are present in
  the snapshot — the drop policy must not silently remove them — and that both
  male and female authors appear (so gender-based demo queries return results).
  Turns "chips must still return sensible results" into a pinned invariant.
- **Determinism guard** — regenerate `seed.sql` in memory from the committed
  `books.json` and assert it equals the committed file; catches hand-edits to
  either artifact.

**Untouched:** `test_pipeline`, `test_app`, `test_fake_connector`,
`test_contracts`, and all `core/` tests — they depend on column paths only.

## Playground chips

Schema is fixed, so all seven chips in `playground/lib/examples.ts` remain
valid as written; the chip-coverage test proves they return results against the
new data. No copy changes are required. The Mandarin chip returning actual
Chinese-language titles is a free demo upgrade. Optional (decide at
implementation): one new chip exercising the added `gender` field, e.g.
"Books by female authors".

## Deploy & docs

- **Re-seed the deployed Fly Postgres** (`sans-schema-demo-db`) using the
  existing `gateway/DEPLOY.md` runbook one-liner (proxy + `psql < seed.sql`)
  after this lands. Re-click the playground chips afterward (in-process cache
  empties on restart).
- **Docs to update in the same change:** `gateway/README.md` (quickstart demo
  dataset description), `docs/architecture.md` if it references the 6-book
  set (verify during implementation), `docs/devlog.md` entry + `todo.md`
  cleanup per the end-of-session loop.

## Out of scope

- Schema enrichment (publisher, rating, subjects columns) — possible follow-up.
- The playground request-transparency panel (separate todo item, own brainstorm).
- Re-running the spike eval — the spike's eval fixtures (`spike/` BOOKS etc.)
  are separate from the demo data and untouched. The demo's resolver-visible
  schema does gain one field (`gender`), so after landing, sanity-check
  resolution live (click the chips + one gender query, e.g. "books by female
  authors"); a full eval re-run is not warranted for one added column.
