# sans_schema — Handoff

Context primer for starting a **new session to brainstorm the first
implementation**. Read this first; `docs/specs/2026-07-concept-and-spike.md` is the deep reference
(design, prior art, results, decisions — section numbers cited below).

---

## TL;DR — where we are

- **Concept:** a **Semantic Query Gateway**. A client sends `{want, where}` using
  its *own* field names + a plain-language filter, against a backend whose schema
  it doesn't know. The gateway semantically resolves fields, compiles the NL
  filter to a **validated predicate AST**, executes, and returns the response in
  the client's *own* keys. (spec §1, §4)
- **Status:** the de-risking **spike is done and green-lit.** The one novel,
  risky layer — semantic resolution — was measured across **9 models / 3 vendors**
  (real per-request API). Top-tier models scored **100% / 100%**; even cheap
  models were ~100% on field resolution. (spec §8)
- **Next:** brainstorm + build the **first gateway implementation** (a thin
  end-to-end vertical slice that reuses the spike's resolver).
- **Repo:** doc tree (root `CLAUDE.md`, `docs/`, `todo.md`) + a working Python
  `spike/`. Current state = top row of [`docs/devlog.md`](devlog.md).

---

## The 30-second concept

```
POST /query
{ "want":  { "title": null, "writer": null, "releaseDate": null },
  "where": "published this year, sci-fi only" }
```
→ resolve `writer→author`, `releaseDate→published_at`; compile `where` to a
validated AST; run it; return `{ "title": ..., "writer": ..., "releaseDate": ... }`
plus an `interpreted` echo. Client learns **neither** the schema **nor** a filter
DSL. (spec §4)

Why it's worth building: the pieces (text-to-SQL, semantic layers, federation)
are commodity; the **unoccupied niche** is *runtime, client-driven resolution
over an unknown backend behind a plain REST contract*. (spec §2, §3)

---

## Decisions already locked (don't re-litigate — refine if needed)

| Decision | What | Ref |
|---|---|---|
| Request contract | `{want}` = fields in your words (structured, no DSL); `{where}` = natural language | §4 |
| Core discipline | **NL → validated AST → execute. Never NL → SQL.** `validate_ast()` is the injection boundary | §4 |
| Semantics/scoring | **Execution equivalence** (do two predicates select the same rows?) | §8 |
| Architecture | Two-sided hourglass: `RequestAdapter → RawQuery → resolver → CanonicalQueryIR → Connector` | §6 |
| Response shape | Deterministic — client's own keys (structured `want` fixes them) + `interpreted` echo | §4 |
| Starting model | `gemini/gemini-3.1-flash-lite` (cheapest, format-compliant, ~100%), behind the `LLM` interface, **default-with-escalation** | §8 |
| Prompt-cache layout | `system[instructions] + system[schema+cache_control] + user[request]` | §6 |
| Stack | Gateway leaning **TypeScript** (GraphQL-Mesh/JSON-native) or **Python+Ibis**; spike is Python | §7 |

---

## Open decisions — the brainstorm inputs

1. **The two contracts** (load-bearing, decide first): the shapes of `RawQuery`
   (unresolved, client vocab) and `CanonicalQueryIR` (resolved). Everything hangs
   off these.
2. **Connector interface** — `describe()` / `capabilities()` / `execute()`.
   Build a Postgres connector such that a **fake in-memory connector swaps in
   without touching resolver/planner** (the MVP seam test — §8 end).
3. **Resolution cache** — the *primary* cost lever. Key ≈ `tenant +
   schema-version + normalized(want-key | where-phrase)`; invalidate on schema
   drift. (Cost math: §3 / the 1000-QPS note — cost scales with `1 − cache_rate`.)
4. **Confidence gate + clarify path** — raise the gate to ~0.7; add a
   "did you mean X?" / escalate-to-stronger-model path for low-confidence or
   ambiguous requests (the spike's only real misses were ambiguity + a 0.55 gate
   slip).
5. **Structured output** — enforce the AST shape via schema-constrained
   `response_format` (also rescues small models that emit off-contract JSON).
6. **Value resolution** (enum fuzzing: `sci-fi → "Science Fiction"`) as its own
   step. (§5)
7. **Security** — field allowlist / field-level authz.
8. **FTO check** on patent **US 12045656** if commercializing. (§2)

---

## Proposed scope for the FIRST implementation (to refine while brainstorming)

Smallest **end-to-end vertical slice** that proves the gateway, **reusing the
spike's resolver** rather than rebuilding it:

- **One** `RequestAdapter`: a JSON `{want, where}` body (no GraphQL/OData yet).
- **Resolver**: lift the spike's logic (`prompts.py` + `resolver.py`:
  `resolve_want`, `where_ast`, `validate_ast`) → produce a resolved plan.
- Define **minimal** `RawQuery` + `CanonicalQueryIR`.
- **One** `Connector`: real Postgres + a fake in-memory one for the seam test.
- Execute → return response in the client's own keys + the `interpreted` echo.
- **Resolution cache**: in-memory to start.
- **Gate**: confirm-before-execute on low confidence.

**Deliberately defer:** multi-protocol adapters, cross-source joins, aggregation,
broad federation pushdown, the prompt-cache markers (cost, not correctness).

---

## Key files

- **`docs/specs/2026-07-concept-and-spike.md`** — full design, prior art, certified results, all decisions.
  The deep reference.
- **`spike/`** — a *working* resolver to lift from:
  - `prompts.py` — the layered LLM prompts (contract / schema / domain hints / request)
  - `resolver.py` — `resolve_want`, `where_ast`, `parse_where`, `validate_ast`
  - `schemas.py` — the `Schema`/`Field`/rows model (what `describe()` should emit)
  - `score.py` — execution-equivalence scorer + debug output
  - `llm.py` — the vendor-agnostic `LLM`/`Embed` interfaces (LiteLLM impl)
  - `README.md` — how to run/measure/debug
- **`spike/requirements.txt`** — `litellm` (multi-vendor).

---

## Suggested prompt to open the next session

Paste this as-is (`CLAUDE.md` auto-loads; this points at the lazy-loaded docs):

```
I'm starting the first implementation of the sans_schema gateway. Before
planning anything, consult the tree: read docs/architecture.md (the current
rules), docs/HANDOFF.md (the primer), and skim docs/specs/2026-07-concept-and-spike.md
(the why) and todo.md — including its "Validation & de-risking" section (the
spike's accuracy number is soft; account for the confident-wrong risk in the
gate/confirm-before-execute design). Name the docs you consulted.

Then let's brainstorm the first implementation — the thin end-to-end vertical
slice: one JSON {want, where} adapter → the resolver lifted from spike/ → a
Postgres connector with a fake-in-memory-connector seam test → response in the
client's own keys.

Start with the load-bearing decision: the shapes of RawQuery (unresolved,
client vocab) and CanonicalQueryIR (resolved), then the Connector interface.
Give me options with a recommendation, and push back on scope creep — defer
multi-protocol adapters, cross-source joins, aggregation, and caching.

Follow the dev cycle: brainstorm → land a spec in docs/specs/. Don't start
coding until the spec is agreed.

When the spec is agreed, close the loop (explicit-path git staging, never
git add -A): add a newest-on-top docs/devlog.md entry linking the new spec,
update todo.md, and git rm docs/HANDOFF.md — it's a one-time bridge primer,
superseded by CLAUDE.md + the tree + the new spec.
```
