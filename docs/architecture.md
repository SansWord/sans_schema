# Architecture & current rules — sans_schema

Maintained (source of truth). Holds the **current** design rules the gateway must
follow; the root `CLAUDE.md` Locked decisions point here for detail. The *history*
behind these (prior art, spike results, root-cause analyses) lives in
[`specs/2026-07-concept-and-spike.md`](specs/2026-07-concept-and-spike.md).

**Update when:** a contract, interface, or locked decision below changes — in the
**same** change, and log the change in [`devlog.md`](devlog.md).

**Status legend:** ✅ implemented (in `core/` + `gateway/`, or the frozen `spike/`
eval) · 📐 design only (not built yet). The first gateway slice (v0.2.0) is built.

---

## 1. Request contract ✅ (shape + HTTP surface)

Client sends a desired-shape body with **its own field names** + an NL filter:

```json
POST /query
{ "want":  { "title": null, "writer": null, "releaseDate": null },
  "where": "published this year, sci-fi only" }
```

- `want` = the fields you want back, **in your vocabulary** (structured — no DSL).
- `where` = a **natural-language** filter (no filter syntax to learn).
- Response is returned in the **client's own keys** (structured `want` fixes them
  → deterministic response shape) plus an `interpreted` echo (what each key/filter
  resolved to + a confidence), so the magic is inspectable.
- You don't need GraphQL — any protocol carrying the field names works; the JSON
  shape body is the default. Others become `RequestAdapter`s later.
- **Built:** `POST /query` in `gateway/app.py`; the JSON `RequestAdapter`
  (`to_raw_query`) collapses `{want:{k:null}}` to `[k]`, accepts a `want` list too,
  and server-stamps `today`.

## 2. Resolution discipline ✅

Two LLM tasks, both against an **unknown** backend schema:
1. `resolve_want(schema, keys) → {key: field | null, confidence}`
2. `where → validated predicate AST` **+ a filter confidence** — `core.where_resolve`
   returns `WhereResult{ast, confidence}`; `where_ast` keeps its bare-AST signature
   for the frozen spike eval.

Rules:
- **NL → validated AST → execute. Never NL → SQL.** The model emits a constrained
  AST; `validate_ast` (in `core/resolver.py`) rejects anything outside the
  operator whitelist or referencing a non-existent field. **This is the injection
  boundary — it lives in code, never in the prompt.**
- **Confidence gate:** applies to **both** tasks, threshold **~0.7** (spike used 0.5
  and let one junk field through at 0.55).
  - *`want` field* below threshold → decline (`field: null`), still returned as a
    `null` column (caution surfaced, not silently dropped).
  - *`where` filter* below threshold → **refuse to execute** (HTTP 422): a filter the
    resolver doesn't trust must not run — silently returning all/other rows is worse
    than refusing. (Later, confirm-before-execute converts this into "ask to confirm.")
- **Value resolution** (enum fuzzing, e.g. `sci-fi → "Science Fiction"`) is a
  distinct step from field resolution. 📐
- **Ambiguity** (e.g. "managers") is handled by the gate + a clarify/escalation
  path, not by guessing. 📐

## 3. Architecture — two-sided hourglass ✅ (v1 slice) / 📐 (federation)

Many request protocols compile **up** to one IR; many backends compile **down**
from it. The novel value sits in the shared middle (the resolver); the rest is
commodity to reuse (Trino / Steampipe / GraphQL-Mesh / Calcite / Ibis).

```
protocols ─► RequestAdapter ─► RawQuery ─► [resolver] ─► CanonicalQueryIR ─► Connector ─► backends
             (parse/format)    (client      (semantic     (resolved)
                                vocab)        layer)
```

- **`RequestAdapter`** (ingress, one per protocol): `matches` / `parse` (→
  `RawQuery`) / `format`.
- **`Connector`** (egress, one per backend): `describe()` (auto-introspect +
  LLM-enriched schema — see `spike/schemas.py` for the shape) / `capabilities()`
  (what it can push down) / `execute(CanonicalQueryIR)`.
  - **Field-path convention — `table.column` (qualified).** `describe()` must expose
    each field's path in the same `table.column` form the resolver prompt tells the
    model to emit, so the model **copies the path it is shown** rather than inventing a
    qualifier. The demo's flat view is one "table": paths are `books_view.<column>`
    (not bare `<column>`). A connector over a flat surface maps the qualified path back
    to the real column internally (`gateway/connectors/postgres.py::_col`) and keys
    result rows by the qualified path so the remap finds them. Bare-column paths were a
    live bug: the model qualified them anyway and `validate_ast` rejected the result.
- **`RawQuery`** (unresolved, client vocab) and **`CanonicalQueryIR`** (resolved)
  are the two load-bearing contracts. **Defined** in `gateway/contracts.py`
  (with `ResolvedField`). The 10-step flow lives in `gateway/pipeline.py::run_query`.
- **MVP seam test:** ✅ a fake in-memory connector (`gateway/connectors/fake.py`)
  swaps in for Postgres — `tests/gateway/test_seam_parity.py` asserts both select the
  same row-set from the same IR (verified against a real Postgres 16).

## 4. Prompt-cache layout 📐 (gateway) / intentionally uncached in the spike

Structure the resolver call stable-first, volatile-last (prompt caching is a
prefix match):

```
system[0]:  static resolver instructions        ← cached globally
system[1]:  the backend schema  + cache_control  ← cached PER BACKEND (the win)
user:       just the {want}/{where} request      ← tiny, volatile, full price
```

- Keep `system` byte-identical; never interpolate schema/dates/IDs into it
  (per-tenant domain hints are fine — stable per tenant).
- Relative-date context ("today is …") goes in the `user` turn, or it busts the
  cache daily.
- Anthropic needs the explicit `cache_control` marker; OpenAI/Gemini auto-cache.
- Bigger cost lever is the **resolution cache** (skip the LLM on a repeat
  key→column); prompt caching cuts input ~90% on the miss path. ✅ (in-memory:
  `gateway/cache.py` — a field cache + a where cache behind a `CacheStore` iface;
  prompt-cache markers themselves are 📐).

## 5. Model & LLM abstraction ✅ (interface) / 📐 (escalation)

- Depend only on two interfaces: `LLM.json` and `Embed.embed`
  (`core/llm.py`); inject the impl (LiteLLM). Any provider LiteLLM supports.
- **Start on `gemini/gemini-3.1-flash-lite`** — cheapest tier tested, and the
  standout among cheap models (100% field resolution, held the AST format where
  the cheap OpenAI models didn't). **Default-with-escalation:** escalate to a
  stronger model only on low confidence / ambiguity.
- **Structured output** (schema-constrained `response_format`) is the durable fix
  for small models emitting off-contract JSON — prefer it over prompt-wrestling. 📐
- **JSON extraction** must tolerate reasoning models that wrap JSON in prose:
  decode the first JSON object, ignore trailing data (`core/llm.py::_extract_json`). ✅

## 6. Security ✅ (injection boundary + hardening) / 📐 (authz + auth)

**Reviewed (v0.2.1, adversarial subagent pass).** Verdict: **no SQL injection, no
prompt-injection path to arbitrary SQL.** The core claim holds in code — every value
reaching SQL is a psycopg parameter; every identifier is `sql.Identifier`; `validate_ast`
whitelists ops + real fields before compile. A hijacked model can at worst mis-resolve
within the allowed schema, never emit SQL.

Boundaries and hardening in place:
- **`validate_ast`** — the `where`-side injection boundary (operator whitelist + real
  fields + node shape; rejects empty `and/or`, bad `between`/`in` shapes).
- **`type_check_ast`** — a static pre-execute type check (v0.2.2): leaf values are checked
  against each field's *declared* type (a non-numeric value on an int column, an unparseable
  date, `contains` on a non-text field) and rejected as a **422** before any SQL runs, rather
  than erroring at the backend (502). Conservative — unknown types are skipped, coercible
  values (`"20"` on numeric) pass — so it never over-rejects valid model output; the 502
  containment stays as the backstop.
- **`gate_want` schema check** — the **SELECT-side mirror**: a resolved `want` path is
  trusted only if it exists in the schema, else declined to a null column (stops a
  hijacked/mis-resolved `want` from injecting a bogus column identifier).
- **Error containment** — `connector.describe()`/`execute()` failures (unreachable DB,
  a compiled query the backend rejects — e.g. a type-mismatched value) return a clean
  **502 `backend_error`**, never an unhandled 500 / stack trace.
- **Ingress limits** — configurable caps on `want` field count, field-name length, and
  `where` length (`MAX_WANT_FIELDS` / `MAX_FIELD_LEN` / `MAX_WHERE_LEN`) bound the
  untrusted request before it reaches the LLM (cost/DoS).

Still 📐 (deferred to the security milestone, tracked in `todo.md`):
- **Field-level authz / field allowlist** — today any *real* schema field resolves for any
  client (fine for a single curated view; required before multi-tenant / column-restricted use).
- **Endpoint authentication** — `POST /query` is unauthenticated; add before any exposure.
  The `/debug/*` introspection endpoints (`prompts`/`schema`/`cache`, v0.2.3) are **off by
  default** (`ENABLE_DEBUG_ENDPOINTS`); `schema`/`cache` disclose schema + samples + query
  history, so they're a local/dev aid — never expose a debug-enabled gateway publicly.
- **Data-borne prompt injection** — `describe()` folds backend column comments + sample
  values into the prompt unsanitized; low blast radius today (still bounded by `validate_ast`),
  higher if a view ever exposes untrusted user-generated content. Treat schema text as data.
- The `interpreted` echo is a per-request schema-probing oracle — see
  [`notes/query-api-open-questions.md`](notes/query-api-open-questions.md) Q2.

## 7. Stack (gateway) ✅ — built

**Locked: Python (FastAPI).** The de-risked spike resolver is now lifted into a shared
`core/` package (types + resolver + `predicate`), imported by both the gateway and the
frozen spike eval — one copy, no drift. Deploy is container-portable via one `Dockerfile`
(the image ships `core/` + `gateway/` only; `spike/` is eval-only, excluded); the demo UI
can still use Vercel. TS/GraphQL-Mesh's edge is
multi-protocol/federation plumbing — deferred, and the hourglass keeps protocol a thin
swappable adapter, so it is not a forcing function. Rationale in full:
[`specs/2026-07-first-gateway-slice.md`](specs/2026-07-first-gateway-slice.md) §1.

## 8. Glossary

The project's load-bearing vocabulary, in one place. (Component topology →
[`system-design.md`](system-design.md).)

- **`want`** — the fields a client asks for, in **its own vocabulary** (structured,
  no DSL). **`where`** — the client's filter, in **natural language**.
- **`interpreted` echo** — the inspectable response annex (what each key/filter
  resolved to + confidence); returned only when `isVerbose` is set.
- **`RawQuery`** — unresolved request in client vocab (ingress → core).
  **`CanonicalQueryIR`** — resolved, backend-agnostic query (core → egress). The two
  contracts form the hourglass's **narrow waist**.
- **Resolver / Semantic Core** — the novel middle: `resolve_want` (client key →
  real field + confidence) and `where → predicate AST`. The part that is *not*
  commodity.
- **`validate_ast`** — the code that rejects any AST outside the operator whitelist
  or referencing a non-existent field. **The injection boundary** — lives in code,
  never in a prompt.
- **Confidence gate** — declines low-confidence `want` fields (→ `null`) and refuses
  low-confidence `where` filters. Threshold ~0.7.
- **`RequestAdapter`** (ingress, per protocol) / **`Connector`** (egress, per
  backend: `describe`/`execute`/`capabilities`).
- **Seam test** — proof that a **fake in-memory connector** swaps in for Postgres
  without touching resolver/planner.
- **Execution equivalence** — the scoring semantics: two predicates are equal if
  they select the **same rows**, regardless of AST shape. The engine is
  **`core/predicate.py`** (`matches`/`select_indices`) — one shared oracle used by
  the fake connector (to filter rows) and the spike scorer (to compare row sets),
  so a Postgres connector can be asserted equal to the exact semantics the eval trusts.
- **Resolution cache** — the primary cost lever: a **field cache** (per `want` key)
  + a **where cache** (per NL phrase + date), skipping the LLM on a repeat.
- **Domain hints** — optional per-tenant synonyms/glossary/rules/examples that
  improve resolution accuracy without touching the contract.
- **`core/`** — the shared, evolving implementation lifted from the spike;
  **`spike/`** — the frozen eval harness that re-measures `core`.
