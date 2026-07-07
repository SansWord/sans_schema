# Spec — First Gateway Slice (thin end-to-end vertical slice)

**Status:** design agreed (brainstorm 2026-07-06). Historical tier — may go stale;
the source of truth after build is [`../architecture.md`](../architecture.md) + the
root `CLAUDE.md` Locked decisions.

**Consulted before writing:** `docs/HANDOFF.md`, `docs/architecture.md`, `todo.md`,
and the spike (`spike/resolver.py`, `spike/schemas.py`, `spike/prompts.py`).

**Supersedes for build purposes:** `docs/HANDOFF.md` (the one-time bridge primer —
`git rm` it when this spec's loop closes).

---

## 1. Goal

The smallest end-to-end gateway that proves the concept, **reusing the spike's
de-risked resolver rather than rebuilding it**: one JSON `{want, where}` request →
resolve fields + compile the filter to a validated AST → execute against Postgres →
return rows in the client's own keys.

**Language locked: Python (FastAPI).** Rationale (from the brainstorm): the one
novel, risky, *measured* layer (the resolver) is already Python; going TS would
re-implement and re-validate it. Deploy stays container-portable (Cloud Run / Fly /
Render), so nothing is foreclosed. Portfolio target — backend / AI engineer — is
on-brand for the Python/LLM stack.

## 2. Scope

**In:**
- One `RequestAdapter`: JSON `{want, where, isVerbose?}` body over `POST /query`.
- Resolver lifted from the spike into a shared `core/` package.
- Minimal `RawQuery` and `CanonicalQueryIR` contracts.
- One real Postgres `Connector` + one fake in-memory `Connector` (the seam test).
- Two-part resolution cache (field cache + where cache), in-memory.
- Confidence gate on **both** `want` fields and the `where` filter.
- Response in the client's own keys; `interpreted` echo behind `isVerbose`.

**Deferred (explicit non-goals for v1)** — see §12:
multi-protocol adapters · joins / cross-source federation · aggregation · pushdown
planning · LLM schema-description enrichment · symbolic/relative dates (`bind_today`) ·
value/enum resolution as a separate step · semantic (embedding) caching · authz /
field allowlist · confirm-before-execute interactive loop · the public demo playground.

## 3. Contracts

### `RawQuery` — unresolved, client vocabulary (a `RequestAdapter` emits this)

```python
@dataclass
class RawQuery:
    want:      list[str]     # client field names, in request order: ["title","writer","releaseDate"]
    where:     str | None    # NL filter, or None
    today:     str           # ISO date for relative-date resolution — volatile, per-call
    verbose:   bool = False  # include the `interpreted` echo in the response
```

`want` collapses the request body's `{"title": null, ...}` to its keys — the `null`s
are placeholders with no v1 meaning.

### `CanonicalQueryIR` — resolved, **backend-agnostic** (the resolver emits this)

```python
@dataclass
class ResolvedField:
    client_key:  str          # "writer"       — maps results back to client vocab
    field_path:  str | None   # "author.name"  — None if the gate declined it
    confidence:  float

@dataclass
class CanonicalQueryIR:
    select:            list[ResolvedField]   # resolved `want`, in request order
    predicate:         dict | None           # the spike's validated AST, or None
    where_confidence:  float | None          # None when no `where`; else 0..1 (NEW in v1)
    where_raw:         str | None            # original NL filter, for the echo
```

The IR carries **zero backend/SQL specifics** — just resolved field paths + the
validated AST. The `Connector` owns compiling it down. This is what makes the
fake-connector seam test possible.

### Request / Response shape

```jsonc
// POST /query
{ "want": { "title": null, "writer": null, "releaseDate": null },
  "where": "published this year, sci-fi only",
  "isVerbose": false }              // default false

// 200 — default (data only)
{ "rows": [ { "title": "...", "writer": "...", "releaseDate": "..." } ] }

// 200 — isVerbose: true (adds the inspectable echo)
{ "rows": [ ... ],
  "interpreted": {
    "want":  { "writer": { "field": "author.name", "confidence": 0.95 }, "...": {} },
    "where": { "raw": "published this year, sci-fi only",
               "ast": { /* validated AST */ }, "confidence": 0.88 } } }
```

## 4. Connector interface

One per backend (egress). **No join planning in v1** — each backend exposes a
**denormalized view**, so the connector sees a flat shape (the form the spike's
`rows` already take).

```python
class Connector(Protocol):
    def describe(self) -> Schema: ...
        # Postgres: introspect information_schema over the denormalized view
        #           (name, type, column comments → description, SELECT DISTINCT … LIMIT → samples).
        # Fake:     return an in-memory Schema mirroring the demo dataset (seed.sql),
        #           used only for the seam test — NOT the spike's BOOKS.
        # NO LLM enrichment of descriptions in v1.

    def execute(self, ir: CanonicalQueryIR) -> list[dict]: ...
        # Compile IR → query, run, return rows keyed by FIELD PATH ("author.name": …).
        # Postgres: SELECT resolved paths FROM the view WHERE <AST> LIMIT <cfg>.
        # Fake:     filter denormalized in-memory rows in Python, coercing values to
        #           schema types so string/number/date compares match Postgres.

    def capabilities(self) -> Capabilities: ...
        # Static declaration only. No pushdown-negotiation planner consumes it yet.
```

## 5. End-to-end flow (the whole slice)

```
POST /query {want, where, isVerbose}
      │
 1. RequestAdapter.parse ───────────────► RawQuery
 2. Connector.describe() ───────────────► Schema        (cached per backend + schema_version)
 3. core.resolve_want(llm, schema, want) ─► {key:{field,confidence}}   (field cache: reuse hits)
 4. GATE want: confidence < threshold → field_path = None (declined, not dropped)
 5. core.where_ast(llm, schema, where, today) ─► {ast, confidence}     (where cache: reuse hits)
 6. GATE where: confidence < threshold → 422 (untrusted filter, do not execute)
 7. validate_ast(ast, schema)  ─────────► reject off-contract → 422    (injection boundary)
 8. assemble ───────────────────────────► CanonicalQueryIR
 9. Connector.execute(ir) ──────────────► rows keyed by field_path
10. remap field_path → client_key; if verbose, build `interpreted` ─► Response
```

Steps 3 and 5 are **lifted from `core/` (ex-spike)**; steps 1, 4, 6–10 are new thin
gateway glue.

## 6. Resolution cache — two independent caches

Per-key and per-phrase, **never per-whole-request** (whole-request keys almost never
hit; agents recombine keys/phrases endlessly).

```
field cache:  (backend, schema_version, normalized_key)            → {field_path, confidence}
where cache:  (backend, schema_version, normalized_phrase, today)  → {ast, confidence}
```

- **Miss-path batching:** resolve all *missing* `want` keys in one `resolve_want`
  call, then store each returned `key→field` individually. (Leans on field
  resolution being per-key independent — true in practice; named as a conscious call.)
- **`today` is in the where key** because a compiled AST for "this year" is only
  correct for a given day. Same-day reuse hits (great for an agent burst); next day
  re-resolves. Removing `today` from the key is the **symbolic-dates fast-follow** (§12).
- Both caches are **in-memory dicts behind a cache interface**, so Redis / semantic
  (embedding) lookup swap in later. The where cache is exactly where embedding-based
  fuzzy match will slot in.
- **Gate applied at read time** — caches store raw `{field/ast, confidence}`, so
  changing the threshold never invalidates a cache.
- `schema_version` = a stable hash of `describe()` output, computed once per process;
  refresh on restart. (Automatic drift invalidation is deferred.)

## 7. Confidence gate

- One configurable **threshold, default 0.7**, applied to both `want` fields and the
  `where` filter.
- **Want below threshold:** `field_path = None`. The key still appears in `select`,
  returns `null` per row, and (verbose) its `interpreted.want` entry shows the low
  confidence. Caution surfaced, never hidden.
- **Where below threshold:** **422**, no execution. A filter we don't trust must not
  run — silently returning all rows or wrong rows is worse than refusing. The 422 body
  always includes `interpreted.where` (AST + confidence). Later, `confirm-before-execute`
  converts this into "ask to confirm."
- **The `where`-confidence score is NEW in v1** (the one resolver change): the `where`
  prompt/output in `core/` gains a `confidence`. Re-measure against the spike eval
  harness (§8) before trusting it.

## 8. Code organization

Lift the reusable spike modules into a shared, evolving `core/` package that **both**
the gateway and the spike import — one copy, no drift. The spike keeps its scorer and
becomes the **eval harness for `core`** (so newer `core` versions, e.g. the
where-confidence change, are re-measured against the frozen cases).

```
pyproject.toml         # makes core / gateway / spike importable
core/                  # lifted from spike — the shared, evolving implementation
  resolver.py          #   resolve_want, where_ast (+ confidence), parse_where, validate_ast
  prompts.py           #   layered prompts (want / where / domain hints)
  schemas.py           #   Schema / Field TYPES only — the shape describe() emits and the
                       #   resolver consumes. NO hardcoded schema instances.
  llm.py               #   LLM / Embed interfaces (LiteLLM impl)
gateway/               # NEW thin glue
  app.py               #   FastAPI, POST /query
  contracts.py         #   RawQuery, CanonicalQueryIR, ResolvedField
  pipeline.py          #   the 10-step flow (§5)
  gate.py              #   GateConfig + apply
  cache.py             #   two caches behind a CacheStore interface
  connectors/
    base.py            #   Connector Protocol, Capabilities
    postgres.py
    fake.py
  demo/
    seed.sql           #   SOURCE OF TRUTH for demo data — normalized tables + denormalized
                       #   VIEW; loaded into a real Postgres (demo site + integration tests).
    rows.py            #   small in-memory mirror of seed.sql for the fake connector (seam
                       #   test); a parity test guards against drift from seed.sql.
spike/                 # eval harness — imports the core types; scorer + fixtures stay here
  schemas.py           #   BOOKS / ECOMMERCE / HR / STREAMING instances (import types from
                       #   core; eval-only — NOT used by the gateway runtime)
  score.py …
```

## 9. Demo dataset & dynamic detection

**`gateway/demo/seed.sql` is the single source of truth for demo data** — a small
books/authors dataset as normalized tables + a denormalized view (v1's flat-execution
surface). It is loaded into a **real Postgres** for the demo site.

The demo deliberately proves the headline capability **end-to-end**: the gateway is
pointed at that Postgres and **detects the schema dynamically** via `describe()`
introspection — there is **no hardcoded schema anywhere in the gateway runtime**. (The
spike's `BOOKS` / `ECOMMERCE` / `HR` / `STREAMING` constants live only in `spike/` as
eval fixtures and never enter the gateway.)

The **fake connector** (seam test) holds a small in-memory mirror of the same rows
(`gateway/demo/rows.py`). A **parity test** asserts the Postgres-*introspected* schema
and query results equal the fake connector's for a fixed `CanonicalQueryIR` — proving
both the connector-swap seam **and** that dynamic introspection lands on the expected
schema. Only this one demo dataset is seeded in v1.

## 10. Packaging & config

- **Serve:** FastAPI + `uvicorn`; one `Dockerfile`; container-portable.
- **Config via env:** `DATABASE_URL` (Postgres DSN), LLM key + model
  (default `gemini/gemini-3.1-flash-lite`), gate threshold, result `LIMIT`.
- **Result bounds:** default `LIMIT 100`, configurable via env (an empty/loose `where`
  must not return an entire table).
- Deploy target (Cloud Run / Fly / Render) is a packaging detail, not fixed here;
  keep the process container-portable and external-cache-ready.

## 11. Testing strategy — three tiers

1. **Unit (LLM-free):** gateway glue, `validate_ast`, gate, cache key/normalization,
   the field-path→client-key remap.
2. **Seam test (LLM-free) — the headline:** feed a *fixed* `CanonicalQueryIR` to both
   the Postgres (seeded from `seed.sql`) and fake connectors; assert **equal row-sets**
   (order not guaranteed without `ORDER BY`), and assert the Postgres-**introspected**
   schema equals the fake connector's mirror. Requires the fake connector to coerce
   values to schema types so compares match Postgres. Proves the connector swaps without
   touching resolver/planner **and** that dynamic detection lands on the expected schema.
3. **Live smoke (opt-in):** a few tests hitting the real LLM, gated behind an env/API
   key, out of default CI.

Plus: re-run the **spike eval** after the `where`-confidence change to confirm no
regression (§7).

## 12. Error semantics

| Condition | Response |
|---|---|
| Some `want` resolved, some declined | **200**, declined keys are `null` columns |
| **All** `want` declined (nothing to select) | **422** + diagnostic |
| `validate_ast` rejects the AST | **422** + reason (no execution) |
| `where` confidence < threshold | **422** + `interpreted.where` (no execution) |
| LLM call fails / times out | retry once → **502** |
| `where` filters on a field not in `want` | **allowed** (filtering ≠ selecting) — flagged as a schema-probing surface, deferred to authz |

All 4xx include the `interpreted` diagnostic **regardless of `isVerbose`**.

## 13. Deferred / fast-follow (with intent)

- **Symbolic / relative dates (`bind_today`)** — compile `where` to a date-independent
  AST that references `today` symbolically; bind concrete dates deterministically at
  execute time. Two wins: date-independent where cache **and** removes LLM date-math
  errors. Modifies the risky layer → its own measured milestone. *(First fast-follow.)*
- **Joins / federation** — real FK join planning (v1 uses a denormalized view).
- **Semantic (embedding) caching** of the where phrase — slots into the where cache.
- **Value / enum resolution** as its own step (`sci-fi → "Science Fiction"`).
- **LLM schema-description enrichment** in `describe()` for bare columns.
- **Confirm-before-execute** interactive loop (v1 has the hard-refuse precursor).
- **Authz / field allowlist**; resolve schema-probing via filter-on-unselected.
- **Multi-protocol adapters** (GraphQL via Strawberry, protobuf) — demonstrates the
  hourglass edge is swappable.
- **Public demo playground** — with the cost guardrails noted in `todo.md`.

## 14. De-risking ties

This slice is dev/prototype grade by design. It does **not** by itself close the
open de-risking items in `todo.md` (fix the spike oracle, confident-wrong rate,
messy-schema benchmark, cache-hit on real agent traffic, drift/canary, deterministic
baseline, authz). The where-confidence gate (§7) is a partial mitigation of the
confident-wrong risk on the *filter* side; the want gate covers the *field* side.
Production scale stays gated behind those items.
