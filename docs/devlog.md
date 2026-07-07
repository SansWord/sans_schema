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
| [v0.2.0](#v020--first-gateway-slice-2026-07-07-0031) | Built the first end-to-end gateway slice — `core/` (resolver + predicate) lifted from the spike, `gateway/` (contracts, gate, two-part cache, 10-step pipeline, Postgres + fake connectors, FastAPI `POST /query`). Seam parity verified against real Postgres 16; 35 tests green. Docker + quickstart. |
| [v0.2.0-design](#v020-design--first-gateway-slice-design-2026-07-06) | Designed the first gateway slice — locked Python/FastAPI, `RawQuery`/`CanonicalQueryIR` contracts, denorm-view connector + fake seam, two-part cache, want+where gates. Added maintained `system-design.md`. No code. |
| [v0.1.0](#v010--resolution-accuracy-spike-2026-07-06) | Built + ran the resolution-accuracy spike; certified ~100% across 3 vendors / 9 models. Green light. |

---

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
  WHERE miss is the known "managers" ambiguity (case 35: the model emitted a subquery-as-value
  instead of `contains(title, "Manager")`), not caused by the confidence line. Nice side-proof of
  the injection boundary: that subquery text was treated as a parameterized *value* (matched
  nothing → 0 rows), never executed as SQL. The opt-in `RUN_LIVE_LLM=1` end-to-end test remains
  optional (the live `curl` in this session already exercised the real path).

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
