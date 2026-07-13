# Devlog

Running log of decisions and learnings, **newest first**. The top entry is the
project's current state — the root `CLAUDE.md` points here instead of restating
the version. Historical (append-only) yet always current, because "newest on top"
holds forever. Each entry links the spec/plan it came from.

### Learning tags

| Tag | Meaning |
|-----|---------|
| `[note]` | Useful context, well-documented — you'd find it in the docs |
| `[insight]` | Non-obvious; meaningfully changes how you design or debug |
| `[gotcha]` | A specific trap that bit us; high risk of biting again |

## TL;DR

| Version | Summary |
|---------|---------|
| [v0.3.0](#v030--demo-session-guardrails-playground-deploy-deck-2026-07-12-2355) | Demo session build — env-driven public-demo guardrails (CORS + per-IP limit + daily cap, all off by default, `create_app()` factory), Next.js playground (`playground/`) with the `interpreted` echo as centerpiece, Fly.io/Vercel deploy config + runbook, 9-slide deck + demo script. Live 4-state error pass verified locally. 75 tests green. Fly/Vercel deploys + dry run = operator steps in `todo.md`. |
| [v0.2.4](#v024--cache-hit-rate-observability-2026-07-07-0231) | Cache-hit-rate observability — `DictCache` counts hits/misses; `ResolutionCache.stats()` reports field/where/combined `hit_rate`, surfaced at `/debug/cache`. Building block for the "measure cache-hit on agent traffic" de-risking item. Counters port to a Redis store (per-replica); entry enumeration does not. 65 tests green. |
| [v0.2.3](#v023--debug-introspection-endpoints-2026-07-07-0223) | Dev-only `/debug/*` endpoints — `prompts` (system prompts), `schema` (the schema prompt + samples), `cache` (resolution cache contents). Off by default (`ENABLE_DEBUG_ENDPOINTS`); 404 when disabled. schema/cache disclose data → not for public exposure. 64 tests green (with Postgres). |
| [v0.2.2](#v022--static-type-check-of-the-ast-2026-07-07-0212) | Static pre-execute type check: leaf values validated against each field's declared type → a type-mismatched filter (e.g. the case-35 string-on-int) is a deterministic 422 instead of a backend 502. Conservative (unknown types skipped, coercible values pass); no eval re-measure needed. 60 tests green. |
| [v0.2.1](#v021--security-review--hardening-2026-07-07-0201) | Adversarial security review (SQLi + prompt injection): no injection found, core claim holds. Hardened anyway — `want`-path schema validation, backend-error→502 containment, empty/malformed-AST→422, configurable ingress limits (`want`/`where` size). 50 tests green. |
| [v0.2.0](#v020--first-gateway-slice-2026-07-07-0031) | Built the first end-to-end gateway slice — `core/` (resolver + predicate) lifted from the spike, `gateway/` (contracts, gate, two-part cache, 10-step pipeline, Postgres + fake connectors, FastAPI `POST /query`). Seam parity verified against real Postgres 16; 35 tests green. Docker + quickstart. |
| [v0.2.0-design](#v020-design--first-gateway-slice-design-2026-07-06) | Designed the first gateway slice — locked Python/FastAPI, `RawQuery`/`CanonicalQueryIR` contracts, denorm-view connector + fake seam, two-part cache, want+where gates. Added maintained `system-design.md`. No code. |
| [v0.1.0](#v010--resolution-accuracy-spike-2026-07-06) | Built + ran the resolution-accuracy spike; certified ~100% across 3 vendors / 9 models. Green light. |

---

## v0.3.0 — Demo session: guardrails, playground, deploy, deck (2026-07-12 23:55)

**Review:** not yet
**Design docs:**
- Demo Session: [Spec](superpowers/specs/2026-07-12-demo-session-design.md) [Plan](superpowers/plans/2026-07-12-demo-session.md)

**What was built:**
- Gateway demo-hardening: env-driven CORS + per-IP rate limit + global daily cap
  (slowapi), friendly 429s, proxy-aware IP keying, `DB_VIEW` — all off by default;
  `create_app()` factory for per-instance guardrail testing. Review hardening on top of
  the plan: fail-fast limit-string validation, per-IP-before-cap evaluation order,
  platform-set-header-only IP trust model. 75 tests green (was 62).
- Playground (`playground/`, Next.js 15 + React 19, no Tailwind): request builder +
  example chips, results in the client's own keys, the `interpreted` echo as the
  centerpiece, error states rendered as features, own-data quickstart page. Review
  fixes: 30 s fetch timeout, non-JSON error-body handling.
- Deployment **config**: `fly.toml` + `gateway/DEPLOY.md` (incl. the vendor quota
  backstop). The actual Fly/Vercel deploys + production dry run are operator steps —
  tracked in `todo.md`, not yet run.
- 9-slide self-contained HTML deck (`playground/public/slides.html` + QR) + demo script
  (`docs/demo/script.md`). Slide 5 rewritten during review to attribute 100%/98% to the
  production model with honest multi-model ranges (99–100% want / 80–100% where).
- Live local error-state pass (real Postgres container + real Gemini call): happy path
  (confidence 1.0), gate refusal on "only the good ones" (first try), per-IP 429, daily-cap
  429, CORS preflight both ways, `/debug/schema` 404.

**Key technical learnings:**
- `[gotcha]` **slowapi fails OPEN on a malformed limit string** — the decorator catches the
  parse `ValueError`, logs one line, and registers *no* limit; a config typo ships an
  unlimited public API. Fixed with `validate_limits()` (`limits.parse_many`) at the top of
  `create_app()` so a bad deploy dies at startup.
- `[insight]` **slowapi limit registration order is a security property.** Limits evaluate
  in registration order and stop at the first failure — registering the per-IP limit before
  the daily cap means throttled requests never drain the global budget. With the opposite
  order, one bot loop bricks the demo for everyone at near-zero cost (verified live both ways);
  `test_both_limits_on_per_ip_then_global_cap` pins the order.
- `[gotcha]` **A client-appendable `X-Forwarded-For` defeats per-IP limiting** — when the
  platform appends rather than overwrites, the leftmost hop is client-supplied, so visitors
  mint fresh buckets. Only key on a header the platform itself sets (`Fly-Client-IP`,
  `CF-Connecting-IP`, `True-Client-IP`).
- `[gotcha]` **slowapi passes the request by parameter *name*** — `key_func=lambda request: …`
  and the endpoint's `request: Request` both break if the parameter is renamed (slowapi
  introspects names). Inline comments mark both sites.
- `[note]` Limiter state is in-memory and per-process: restarts reset it, multiple
  workers/machines multiply the budget (fine for single-process uvicorn; noted in the README).
- `[note]` Browser client hardening that a live demo actually needs: `AbortSignal.timeout`
  on fetch (a hung gateway otherwise freezes the UI with everything disabled) and a
  try/catch around `res.json()` on error responses (a proxy 502 with an HTML body otherwise
  misreports as "could not reach the gateway").

**Process learnings:**
- `[insight]` **Plan-verbatim code still needs real review.** The plan's code was written and
  self-reviewed at planning time, yet the two-stage review found four substantive issues in it
  (fail-open limits, budget-drain order, spoofable-header advice, an overstated slide claim).
  Treat "the plan says exactly this" as a starting point, not as pre-approved.
- `[note]` Worktree + user-site editable install: running `python3 -m pytest` from inside the
  worktree makes the worktree's code win over the site-packages path (cwd precedence) — no
  need to re-point the editable install (which would break the main checkout).

## v0.2.4 — Cache-hit-rate observability (2026-07-07 02:31)

**Review:** not yet

**What was built:**
- **`DictCache` counts hits/misses** (a `get` that finds the key is a hit, else a miss) and
  **`ResolutionCache.stats()`** reports `{hits, misses, lookups, hit_rate}` for the field cache,
  the where cache, and combined. Surfaced under `stats` in `GET /debug/cache`.
- The resolution cache is the primary cost lever (skip the LLM on a repeat), so its hit rate is
  the number the cost model rests on — this is the instrumentation for the "measure cache-hit on
  realistic agent traffic" de-risking item. Counters are cumulative-since-start (no windowing yet).
- Tests: +3 (62 LLM-free / 65 with Postgres).

**Key technical learnings:**
- `[note]` **The `CacheStore` seam makes this backend-portable.** Counters live in the store's
  `get()`, so a future Redis-backed store counts hits/misses in-process the same way — `stats()`
  reads them by duck-typing (`getattr(store, "hits", …)`). Two Redis caveats: the counters are
  **per-replica** (aggregate across processes for a fleet-wide rate, or read Redis' own
  `INFO stats` keyspace_hits/misses for a coarse instance-wide number), and **entry enumeration**
  (`snapshot`) doesn't port cleanly (needs `SCAN` / a tracked index) — `snapshot` already returns
  `null` for a non-enumerable store, so the hit-rate stats keep working even where the entry dump can't.

## v0.2.3 — Debug introspection endpoints (2026-07-07 02:23)

**Review:** not yet

**What was built:**
- **`GET /debug/prompts`** — the static resolver **system** prompts (`want_system`/`where_system`)
  + the operator whitelist + the prompt-cache layout. No backend data — safe.
- **`GET /debug/schema`** — the introspected **schema prompt** (`Schema.as_prompt()`) plus the
  structured fields. Discloses column names, descriptions, and **sample values**.
- **`GET /debug/cache`** — the resolution-cache contents (cached `want`-field and `where`-phrase
  resolutions, raw field/ast + confidence). Added `ResolutionCache.snapshot()` + `DictCache.items()`
  (enumeration is best-effort — a non-enumerable store like Redis reports `null`).
- **Gated + off by default** — `ENABLE_DEBUG_ENDPOINTS` (`gateway/config.py`); when disabled the
  routes return **404** (not advertised). Tests: +4 (59 LLM-free, 64 with Postgres).

**Key technical learnings:**
- `[insight]` **The "system prompt" is safe to expose; the "schema prompt" is not.** The static
  instructions carry no data, but the schema block folds in real column names + sample values — the
  same disclosure the security review flagged. Splitting them (`/debug/prompts` vs `/debug/schema`)
  keeps the safe part safe and puts the disclosure behind the flag.
- `[note]` **This is the operator's introspection tool, not client discovery.** `/debug/schema` is
  the raw dump `docs/notes/query-api-open-questions.md` Q2 warns against for *untrusted clients*;
  gated + dev-only, it's fine for the developer running the gateway. The client-facing answer stays
  the curated, authz-filtered capability listing.

## v0.2.2 — Static type-check of the AST (2026-07-07 02:12)

**Review:** not yet

**What was built:**
- **`core.type_check_ast`** — a static pre-execute type check. After `validate_ast` (op/field/
  shape) passes, each leaf value is checked against the field's *declared* type: a non-numeric
  value on an int column, an unparseable date on a date column, or `contains` on a non-text field
  is rejected as a **422** before any SQL is compiled — rather than erroring at the backend as a
  502. The pipeline runs it right after `validate_ast`, folded into the same `invalid_ast` 422.
- **Conservative by design:** it reuses the executor's own date/number coercion (so `"20"` on a
  numeric column still passes), and **skips unknown declared types** — so it can't over-reject a
  valid model output; the v0.2.1 502 containment remains the backstop for anything it can't judge.
- Kept **separate from `validate_ast`** (the injection boundary stays focused) and **out of the
  frozen spike eval** — so no re-measure was needed. Verified against real Postgres: the case-35
  string-on-int shape and a bad-date filter now return 422, normal queries unaffected.
- Tests: +9 (`tests/core/test_typecheck.py` + a pipeline case); 55 LLM-free / 60 with Postgres.

**Key technical learnings:**
- `[insight]` **We already hold the types, so the backend's type error is knowable statically.**
  `describe()` carries each column's declared type; classifying it into a logical kind
  (number/string/bool/temporal) and checking the leaf value moves a whole class of runtime 502
  to a deterministic, DB-free 422 — and makes the fake and Postgres connectors agree on rejection.
- `[note]` **The type-check must mirror execution coercion, not be stricter.** Reusing
  `predicate._parse_dt` + the same numeric-string rule keeps it from rejecting values the executor
  would happily accept (`"2026"`, `"20"`); the goal is to catch only what the backend *would* reject.

## v0.2.1 — Security review + hardening (2026-07-07 02:01)

**Review:** complete — adversarial security subagent (fresh context) focused on SQL injection
+ prompt injection, findings then verified empirically against real Postgres.

**Verdict:** **No SQL injection, no prompt-injection path to arbitrary SQL.** The core claim
(*NL → validated AST → parameterized SQL, never NL → SQL*) holds in code — proved by a
`'; DROP TABLE books;--` value that was parameterized and left the table intact. Findings were
robustness + a known authz gap, not injection.

**What was hardened:**
- **`gate_want` schema check** — the SELECT-side mirror of `validate_ast`: a resolved `want`
  path is trusted only if it's a real schema field, else declined to a null column. Closes the
  asymmetry where only `where` was validated.
- **Backend-error containment** — `connector.describe()`/`execute()` failures now raise a clean
  **502 `backend_error`** instead of an unhandled 500 (this also fixes the DB-unreachable stack
  trace hit earlier in the quickstart).
- **`validate_ast`** now rejects empty `and`/`or` clauses (would have compiled to `WHERE ()`).
- **Configurable ingress limits** — `MAX_WANT_FIELDS` (50) / `MAX_FIELD_LEN` (200) /
  `MAX_WHERE_LEN` (2000) cap the untrusted request before it inflates the LLM prompt (cost/DoS),
  enforced at the HTTP boundary → 422.
- Tests: +8 (45 LLM-free, 50 with Postgres). Verified against real Postgres that the three former
  500 vectors now return 502/422/422.

**Key technical learnings:**
- `[insight]` **`sql.Identifier` prevents injection but not a 500.** A model-invented column name
  is safely *quoted* (no breakout), but a non-existent column still errors at the backend. So the
  SELECT path needs a schema-membership check for *robustness*, even though it was never an
  injection hole. Injection-safety and error-safety are separate properties.
- `[gotcha]` **In-memory oracle ≠ Postgres on a bad value.** A string value on an integer column
  (the case-35 "managers" output) *matched nothing* in `core.predicate` but raises
  `InvalidTextRepresentation` on real Postgres → an uncaught 500. The equivalence oracle can hide
  a class of runtime error the real backend surfaces; verify adversarial inputs against the DB.
- `[note]` **Data-borne prompt injection is real but bounded.** Column comments + sample values
  flow into the prompt unsanitized; still gated by `validate_ast`, so worst case is steering
  SELECT to another real column or a 502 — logged for the security milestone, not fixed here.

## v0.2.0 — First gateway slice (2026-07-07 00:31)

**Review:** complete — fresh-context `superpowers:code-reviewer` subagent vs the plan +
spec. Verdict: complete and faithful; injection boundary genuinely enforced. Applied its
fixes: a version leak in `architecture.md` (said v0.1.0), **hardened `validate_ast`** to
reject malformed shapes as a 422 (see learnings), and **deepened the seam parity test** to
assert `schema_version` equality (not just column-name sets). The spike re-measure it flagged
has since run — **no regression** (WANT 100%, WHERE 98%; see learnings). Remaining follow-up: a
`contains` ILIKE-vs-substring divergence (noted in `postgres.py`, harmless on the demo data).
**Live-verified:** the quickstart ran end-to-end against a real Postgres 16 + live LLM — this
surfaced the field-path convention bug (see the `{view}.{column}` gotcha) and two quickstart
friction points (missing `.env` template, container→DB host routing), all fixed on the branch.
**Design docs:**
- First Gateway Slice: [Spec](specs/2026-07-first-gateway-slice.md) [Plan](plans/2026-07-first-gateway-slice.md)

**What was built:**
- **`core/`** — lifted the four reusable spike modules (`llm`, `prompts`, `resolver`,
  `schemas` types) into a shared package imported by both the gateway and the frozen
  spike eval (one copy, no drift). Added **`core/predicate.py`** — the execution-equivalence
  matcher, moved out of `spike/score.py` so the fake connector and the scorer share one oracle.
- **`core.where_resolve`** — the one v1 resolver change: the `where` prompt now emits a
  `confidence`; `where_resolve` returns `WhereResult{ast, confidence}` while `where_ast`
  keeps its bare-AST signature for the frozen eval.
- **`gateway/`** — `contracts.py` (`RawQuery`/`CanonicalQueryIR`/`ResolvedField`),
  `gate.py` (0.7 threshold, want-decline + where-422), `cache.py` (two-part field+where cache
  behind a `CacheStore` iface), `pipeline.py` (the 10-step flow + `GatewayError` semantics +
  field→client remap), `config.py` (env-driven `Settings`), `app.py` (FastAPI `POST /query`
  + JSON `RequestAdapter`).
- **Connectors** — `base.py` (`Connector` Protocol, `Capabilities`, stable `schema_version`),
  `fake.py` (in-memory seam twin over the demo mirror), `postgres.py` (introspect
  `information_schema` over a denormalized view + compile the validated AST → parameterized SQL).
- **Demo** — `demo/seed.sql` (normalized authors/books + `books_view`) as the source of truth,
  `demo/rows.py` as the in-memory mirror for the fake connector.
- **Tests** — 37 LLM-free + 5 Postgres-backed (42 green against real Postgres 16), incl. the
  headline **seam parity** test (Postgres and fake select the same row-set from one IR) and an
  opt-in live smoke test. **`Dockerfile`** (ships `core/`+`gateway/` only) + **`gateway/README.md`**
  copy-paste quickstart.

**Key technical learnings:**
- `[gotcha]` **The introspected flat-view paths were bare column names, but the resolver's
  `<table.column>` prompt convention made the LLM qualify them with the view name**
  (`category` → `books_view.category`) — so `validate_ast` rejected the where field (422) and,
  with no `where`, `SELECT "books_view.title"` quoted the whole thing as one identifier
  (`column does not exist`). Found only on the first **live** `curl` — every unit/seam test
  hand-built the IR with bare paths and never exercised the LLM→path→validate→SQL round-trip;
  the one test that would have (the live smoke) needs a key and never ran. Fix: both connectors
  now emit `{view}.{column}` paths (so the model copies the exact shown path), mapping back to
  the bare column for SQL and re-keying results by path. Strong argument for running the live
  test before calling a slice done.
- `[gotcha]` **A Postgres view does NOT inherit its base tables' column comments.** The seed
  commented `books.category`, but `describe()` introspects `books_view`, so `col_description`
  returned empty and the introspection test failed. Fix: `COMMENT ON COLUMN books_view.<col>`
  directly (the seed now comments the view columns, mirroring `rows.py`).
- `[gotcha]` **A static `[tool.setuptools] packages` list that names a dir which isn't present
  fails the build** ("package directory 'X' does not exist"). Bit twice: first the yet-uncreated
  `gateway/` at the editable install, then `spike/` inside the Docker image (which ships only
  `core/`+`gateway/`). Fix: drop `spike/` from the distribution's `packages` — it stays
  importable in dev because `tests/` is a package, so the repo root lands on `sys.path`.
- `[insight]` **Sharing `core/predicate.py` is what makes the seam parity test meaningful:**
  the fake connector filters rows with the *same* oracle the spike scorer trusts for execution
  equivalence, so asserting Postgres == fake asserts Postgres agrees with the eval's semantics.
- `[note]` **`_accepts_limit` keeps the pipeline connector-agnostic** — `PostgresConnector.execute`
  takes a `limit`; the fake one doesn't. The pipeline introspects the signature rather than forcing
  the fake to carry a LIMIT it can't enforce.
- `[note]` **The gate is applied at read time, not write time.** Caches store raw
  `{field/ast, confidence}`; changing `GATE_THRESHOLD` never invalidates a cache entry.
- `[note]` **Old pip (21.2.4) can't do PEP 660 editable installs** from a pyproject-only
  setuptools project — upgraded pip+setuptools (user) first.
- `[insight]` **`validate_ast` is the right place to reject malformed shape, not just
  off-contract ops/fields** (post-review hardening). A `not` with no `clause`, or a
  `between`/`in` with a scalar value, previously passed validation and then blew up as a
  KeyError/TypeError in the connector → an unhandled 500. Validating shape at the injection
  boundary turns those into the 422 §12 already promises. Strengthens the boundary in
  `core/` (surfaced per the locked-decisions rule); the frozen spike eval still assembles.

**Process learnings:**
- `[gotcha]` **Version collision the plan didn't catch:** the plan's Task 13 labelled this
  milestone `v0.1.0`, but `v0.1.0` is the spike and `v0.2.0-design` was this slice's design.
  Per the `vX.Y.0-design → vX.Y.0` convention this build is **v0.2.0** (pyproject + README + this
  entry aligned).
- `[note]` **Spike re-measure done — no regression from the where-confidence change.**
  `spike.score --models gemini/gemini-3.1-flash-lite` (2026-07-07): **WANT 125/125 = 100%,
  WHERE→AST 39/40 = 98%** — identical to the v0.1.0 certified baseline (100/98). The single
  WHERE miss is the known "managers" ambiguity (case 35: the model emitted a subquery-string as
  the `value` instead of `contains(title, "Manager")`), not caused by the confidence line.
  Injection-wise the boundary holds — that text is passed as a parameterized *value*, never
  executed as SQL. But note (from the later security review): against the spike's in-memory oracle
  it merely matched nothing, whereas against **real Postgres** a string value on an integer column
  raises a type-cast error → an **uncaught 500** (no data leak; a robustness gap now tracked). The
  opt-in `RUN_LIVE_LLM=1` test remains optional (the live `curl` already exercised the real path).

## v0.2.0-design — First gateway slice design (2026-07-06)

**Review:** not yet
**Design docs:**
- First Gateway Slice: [Spec](specs/2026-07-first-gateway-slice.md)

**What was decided (design only — no code shipped):**
- **Language locked: Python (FastAPI)**, lifting the spike resolver. The novel/risky
  layer is already de-risked Python; TS would re-implement + re-validate it. Deploy
  stays container-portable (Cloud Run / Fly / Render); Vercel kept for the demo UI.
- **Contracts:** `RawQuery` (unresolved, client vocab) / `CanonicalQueryIR` (resolved,
  backend-agnostic) / `ResolvedField`. IR carries a **new `where_confidence`**.
- **Connector:** denormalized-view per backend, **no join planning in v1**; Postgres +
  a fake in-memory connector for the seam test.
- **Demo:** real Postgres seeded from `seed.sql` + **dynamic schema detection** (no
  hardcoded schema in the gateway runtime); `BOOKS`/`ECOMMERCE`/`HR`/`STREAMING` stay
  `spike/` eval fixtures. `core/schemas.py` holds the `Schema`/`Field` *types* only.
- **Two-part resolution cache:** a field cache (per `want` key) + a where cache (per NL
  phrase + `today`), not a per-whole-request key.
- **Gate:** `want` below threshold → `null` (declined, visible); `where` below threshold
  → **422** (untrusted filter, don't execute). One threshold (0.7) for both.
- **Response:** data-only by default; `isVerbose` adds the `interpreted` echo; 4xx
  always include the diagnostic.
- **Repo shape:** promote `resolver/prompts/schemas/llm` from `spike/` into a shared
  `core/`; `spike/` becomes the **eval harness** that re-measures `core`.
- Added maintained [`system-design.md`](system-design.md) (Mermaid topology + swap
  matrix) + a glossary section in `architecture.md`.

**Key learnings / decisions:**
- `[insight]` **Semantic caching doesn't force Python.** Embeddings are one API call
  (LiteLLM `Embed`), and the vector store is external/language-agnostic (pgvector — we
  already run Postgres — or Pinecone/Qdrant). The Python call rests on resolver reuse,
  not on caching.
- `[insight]` **The spike's `where` output has no confidence** — so a *confidently-wrong
  filter* (`writer→editor`) is the scariest silent failure and the want-gate can't catch
  it. Added a `where`-confidence score in v1 (the one resolver change) → the 422 refusal.
- `[gotcha]` **A compiled relative-date AST is `today`-dependent** ("this year" bakes
  2026 bounds). So `today` is in the where-cache key (daily bust, acceptable). The clean
  fix — symbolic dates + deterministic `bind_today` — also removes LLM date-math errors,
  but it modifies the risky layer, so it's deferred to the **first fast-follow** milestone.
- `[insight]` **The hourglass makes protocol ≠ language forcing function.** New protocol
  = one `RequestAdapter` → `RawQuery`; new backend = one `Connector` ← `CanonicalQueryIR`.
  The core never changes. So the TS/GraphQL-Mesh pull is for deferred, thin edge work.
- `[note]` **Maintained law folded on approval.** Spec approved 2026-07-06; the settled
  calls were folded into `architecture.md` §2 (where-confidence) + §7 (Python/FastAPI)
  and `CLAUDE.md` (status + Locked decisions) in a follow-up commit after the pre-review
  baseline — so the baseline→approval diff stays legible.

**Process learnings:**
- `[note]` Committed a **pre-review baseline** (spec + docs) before the spec review, on
  request, so subsequent discussion edits surface as clean diffs.

## v0.1.0 — Resolution-accuracy spike (2026-07-06)

**Review:** not yet
**References:** [spec](specs/2026-07-concept-and-spike.md) (concept, prior art, full results)

**What shipped:**
- The `spike/` harness measuring the one novel/risky layer — semantic resolution
  (client vocab → real columns) + NL filter → validated predicate AST.
- 52 cases across 4 domains (library, shop, hr, streaming); vendor-agnostic `LLM`
  interface (LiteLLM); execution-equivalence scorer; paste-ready failure debug.
- **Certified cross-vendor results (real per-request API):** every top-tier model
  100/100 (WANT/WHERE). Anthropic haiku 100/98, sonnet 100/100, opus 100/100;
  Gemini flash-lite 100/98, flash 100/100, pro-latest 100/100; OpenAI gpt-5.4-mini
  100/80, gpt-5.4 100/90, gpt-5.5 99/100.
- **Decision:** start on `gemini-3.1-flash-lite` (cheapest, format-compliant, ~100%).
- Doc tree adopted to manage the project; opted into the dev-cycle loop, the
  PR/"ship it" gate, a `Before committing` secrets scan, and the `docs/plans/` tier.

**Key learnings:**
- `[insight]` ~100% of the economic value is in **semantic resolution**; protocol
  adapters, filter DSL, federation, query IR are all commodity to reuse.
- `[insight]` **Exact-AST match is the wrong oracle** for query semantics — two
  correct predicates differ in shape. Switched to **execution equivalence** (do
  they select the same sample rows?); a first run's "57%" was oracle error, real
  accuracy ~100%.
- `[gotcha]` ...but **execution equivalence on ~8 sample rows can *inflate* WHERE
  scores** — two different predicates can coincidentally select the same rows.
  Flagged by a 2026-07 persona review (AI-app dev / senior eng / enthusiast): before
  the accuracy number is trustworthy it needs large/realistic row sets + adversarial
  equivalence + a **confident-wrong rate**, and testing on messy real schemas. We
  swung from a too-strict oracle to a too-loose one. See `todo.md` → Validation & de-risking.
- `[insight]` The residual failures were **not capability walls**: (1) small
  OpenAI models emit off-contract JSON (no `{"op":...}` wrapper) → durable fix is
  **structured output**; (2) genuine NL ambiguity ("managers") → needs a **clarify
  path**; (3) a **gate false positive** at 0.55 → raise the gate to ~0.7.
- `[gotcha]` **`git add -A` swept the run logs into git.** Now `*.log` is
  gitignored and the convention is explicit-path staging only.
- `[gotcha]` **Reasoning models (gemini-pro) wrap JSON in prose/trailing content**
  → `json.loads` "Extra data" errored ~half its cases (a bogus 48%). Fixed
  `_extract_json` to `raw_decode` the first object; real score 100/100. The
  production gateway will hit this too.
- `[note]` Cost at scale is dominated by **cache hit rate**, not model choice
  (30%→99% cache ≈ 35× swing); prompt-cache the per-backend schema prefix.
- `[note]` Model IDs drift fast — Gemini 2.0/1.x and OpenAI gpt-4o are already
  legacy; verified current IDs (Gemini 3.x, GPT-5.x) mid-2026.
