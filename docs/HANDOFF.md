# sans_schema — Handoff

Context primer for starting a **new session to brainstorm the first
implementation**. Read this first; `docs/kickoff.md` is the deep reference
(design, prior art, results, decisions — section numbers cited below).

---

## TL;DR — where we are

- **Concept:** a **Semantic Query Gateway**. A client sends `{want, where}` using
  its *own* field names + a plain-language filter, against a backend whose schema
  it doesn't know. The gateway semantically resolves fields, compiles the NL
  filter to a **validated predicate AST**, executes, and returns the response in
  the client's *own* keys. (kickoff §1, §4)
- **Status:** the de-risking **spike is done and green-lit.** The one novel,
  risky layer — semantic resolution — was measured across **9 models / 3 vendors**
  (real per-request API). Top-tier models scored **100% / 100%**; even cheap
  models were ~100% on field resolution. (kickoff §8)
- **Next:** brainstorm + build the **first gateway implementation** (a thin
  end-to-end vertical slice that reuses the spike's resolver).
- **Repo:** 15 commits; `docs/kickoff.md` + a working Python `spike/`.

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
DSL. (kickoff §4)

Why it's worth building: the pieces (text-to-SQL, semantic layers, federation)
are commodity; the **unoccupied niche** is *runtime, client-driven resolution
over an unknown backend behind a plain REST contract*. (kickoff §2, §3)

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

- **`docs/kickoff.md`** — full design, prior art, certified results, all decisions.
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

> Read `docs/HANDOFF.md` and `docs/kickoff.md`. I want to brainstorm the **first
> implementation** of the sans_schema gateway — the thin end-to-end vertical
> slice described in the handoff (one JSON `{want, where}` adapter → resolver
> lifted from the spike → minimal `RawQuery`/`CanonicalQueryIR` → a Postgres
> connector with a fake-connector seam test → response in the client's own keys).
> Start by pinning down the `RawQuery` and `CanonicalQueryIR` shapes, then the
> connector interface. Push back on scope creep.
