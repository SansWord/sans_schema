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
| [v0.2.0-design](#v020-design--first-gateway-slice-design-2026-07-06) | Designed the first gateway slice — locked Python/FastAPI, `RawQuery`/`CanonicalQueryIR` contracts, denorm-view connector + fake seam, two-part cache, want+where gates. Added maintained `system-design.md`. No code. |
| [v0.1.0](#v010--resolution-accuracy-spike-2026-07-06) | Built + ran the resolution-accuracy spike; certified ~100% across 3 vendors / 9 models. Green light. |

---

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
