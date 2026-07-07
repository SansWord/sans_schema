# Architecture & current rules — sans_schema

Maintained (source of truth). Holds the **current** design rules the gateway must
follow; the root `CLAUDE.md` Locked decisions point here for detail. The *history*
behind these (prior art, spike results, root-cause analyses) lives in
[`specs/2026-07-concept-and-spike.md`](specs/2026-07-concept-and-spike.md).

**Update when:** a contract, interface, or locked decision below changes — in the
**same** change, and log the change in [`devlog.md`](devlog.md).

**Status legend:** ✅ implemented in `spike/` · 📐 design only (gateway not built).

---

## 1. Request contract ✅ (shape) / 📐 (HTTP surface)

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

## 2. Resolution discipline ✅

Two LLM tasks, both against an **unknown** backend schema:
1. `resolve_want(schema, keys) → {key: field | null, confidence}`
2. `where → validated predicate AST`

Rules:
- **NL → validated AST → execute. Never NL → SQL.** The model emits a constrained
  AST; `validate_ast` (in `spike/resolver.py`) rejects anything outside the
  operator whitelist or referencing a non-existent field. **This is the injection
  boundary — it lives in code, never in the prompt.**
- **Confidence gate:** decline (`field: null`) below threshold. Target **~0.7**
  (spike used 0.5 and let one junk field through at 0.55). Below-threshold →
  treat as "no match" / clarify.
- **Value resolution** (enum fuzzing, e.g. `sci-fi → "Science Fiction"`) is a
  distinct step from field resolution. 📐
- **Ambiguity** (e.g. "managers") is handled by the gate + a clarify/escalation
  path, not by guessing. 📐

## 3. Architecture — two-sided hourglass 📐

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
- **`RawQuery`** (unresolved, client vocab) and **`CanonicalQueryIR`** (resolved)
  are the two load-bearing contracts. **Not yet defined — first task of the
  gateway build.**
- **MVP seam test:** a fake in-memory connector must swap in for Postgres without
  touching resolver/planner.

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
  key→column); prompt caching cuts input ~90% on the miss path. 📐

## 5. Model & LLM abstraction ✅ (interface) / 📐 (escalation)

- Depend only on two interfaces: `LLM.json` and `Embed.embed`
  (`spike/llm.py`); inject the impl (LiteLLM). Any provider LiteLLM supports.
- **Start on `gemini/gemini-3.1-flash-lite`** — cheapest tier tested, and the
  standout among cheap models (100% field resolution, held the AST format where
  the cheap OpenAI models didn't). **Default-with-escalation:** escalate to a
  stronger model only on low confidence / ambiguity.
- **Structured output** (schema-constrained `response_format`) is the durable fix
  for small models emitting off-contract JSON — prefer it over prompt-wrestling. 📐
- **JSON extraction** must tolerate reasoning models that wrap JSON in prose:
  decode the first JSON object, ignore trailing data (`spike/llm.py::_extract_json`). ✅

## 6. Security 📐

Dynamic field access needs a **field allowlist / field-level authz** and value
sanitization at the boundary. The `validate_ast` whitelist is the first layer;
authz is TBD in the gateway.

## 7. Stack (gateway) 📐

Leaning **TypeScript** (GraphQL-Mesh gives the adapter/federation plumbing;
JSON-native; frontend/agent audience) or **Python + Ibis** (if cross-source
federation/planning dominates). The spike is Python. Decide at first-build time.

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
  they select the **same rows**, regardless of AST shape.
- **Resolution cache** — the primary cost lever: a **field cache** (per `want` key)
  + a **where cache** (per NL phrase + date), skipping the LLM on a repeat.
- **Domain hints** — optional per-tenant synonyms/glossary/rules/examples that
  improve resolution accuracy without touching the contract.
- **`core/`** — the shared, evolving implementation lifted from the spike;
  **`spike/`** — the frozen eval harness that re-measures `core`.
