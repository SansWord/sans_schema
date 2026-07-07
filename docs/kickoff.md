# sans_schema — Project Kickoff

> A **Semantic Query Gateway**: clients request data using their *own* field
> names and a plain-language filter, without knowing the backend schema. The
> gateway semantically resolves the request against a data source, executes it,
> and returns the response shaped exactly the way the client asked for it.

_Status: pre-build. Concept is settled; the load-bearing risk is being measured
by a throwaway accuracy spike (`/spike`) before we commit to the build._

---

## 1. The idea

A serving layer that sits between requesters and a data backend. When a request
arrives, the layer **guesses and matches** the requested field/entity names to
the backend storage — semantically, without the client knowing the real schema
or column names — generates the query on the fly, runs it, and transforms the
result to fit the request.

Worked example: a client asks for the `writer` of a book. The DB column is
`author`. The gateway resolves `writer → author`, queries it, and returns
`{"writer": "SansWord"}` — the client never learns the real column name.

The guessing uses an LLM.

## 2. Prior art (why this is worth trying)

The idea decomposes into pieces that all exist, plus one combination that
doesn't ship anywhere:

| Piece | Exists as | Verdict |
|---|---|---|
| GraphQL/REST → SQL from a known schema | Hasura, PostGraphile | commodity |
| NL → SQL (text-to-SQL) | Vanna, WrenAI, DB-GPT | mature |
| Semantic layer (define metrics/entities once) | Cube.dev, dbt Semantic Layer | mature |
| LLM schema matching (arbitrary field → column) | research + ETL tools | used at *config* time, not live serving |
| Data federation / connectors | Trino, Steampipe, GraphQL Mesh, Airbyte | commodity |
| Query IR + planner + pushdown | Apache Calcite, Ibis | commodity |

**What's unoccupied:** a *traditional REST endpoint* where the client posts a
desired shape with **arbitrary keys it invented**, and the server does
**runtime** semantic resolution against an **unknown** backend, returning the
client's own keys filled with data. The industry splits this two ways — resolve
at ETL/config time (not per-request), or take natural language in (not a
structured request with fuzzy field names). Our niche sits between them.

There is a conceptually-close patent (**US 12045656**, "Client-defined field
resolvers for database query language gateway") — worth a freedom-to-operate
check before commercializing.

## 3. Where the value actually lives

Almost everything in the architecture is commodity we reuse. **~100% of the
economic value is concentrated in one layer: semantic resolution** (client
vocabulary → real columns, and NL filter → predicate). Value is a *step
function of resolution accuracy*, not a smooth function of features. Hence the
spike (§8) comes before the build.

**Who it's worth the most to** (ranked):

1. **AI agents / LLM-generated frontends** — agents invent field names; a
   tolerant gateway means no exact-schema knowledge required. Fast-growing,
   most defensible. This is the wedge.
2. **Multi-tenant / data-marketplace / integration platforms** — one API over
   many differing schemas.
3. Internal tools / prototyping / no-code — speed, zero config (low WTP).
4. Schema-drift decoupling — clients don't break when a column is renamed.
5. Conventional app with a known schema and human devs — **~zero value**; don't
   build for this.

**Costs to manage:** LLM latency/cost (mitigated by caching resolved mappings —
steady-state per-request LLM cost trends toward zero), correctness ceiling
(need a confidence gate + "did you mean X?" path), and a security boundary
(dynamic field access needs an allowlist / field-level authz).

## 4. The request contract

The two halves of a request have opposite complexity, so they get opposite
treatment:

- **Naming what you want back** has zero inherent complexity — you just list
  fields, in your own vocabulary. Structure it (it's not a DSL).
- **Expressing filter conditions** is where all DSL complexity lives
  (operators, boolean logic, nesting, relative dates). Use **natural language**.

```json
POST /query
{
  "want":  { "title": null, "writer": null, "genre": null, "releaseDate": null },
  "where": "published this year, fiction only"
}
```

The client learns **nothing**: not the schema (semantic resolution), not a
filter syntax (NL). Response comes back in the client's own keys:

```json
{
  "interpreted": {
    "want":  { "writer": "→ author", "genre": "→ category", "releaseDate": "→ published_at" },
    "where": "published_at >= 2026-01-01 AND category = 'fiction'",
    "confidence": 0.94
  },
  "data": [ { "title": "...", "writer": "SansWord", "genre": "fiction", "releaseDate": "2026-03-01" } ]
}
```

**Why structured-`want` + NL-`where` is optimal (not a compromise):** the output
keys must equal the client's own keys. Structured `want` makes that
*deterministic*, so the **response shape is stable** (clients can parse/render
it reliably) even while the filter is flexible NL. Determinism is spent only
where flexibility is worth it.

You don't need GraphQL. Any protocol that carries the desired field names works;
a JSON shape body is the most "traditional API, works with any frontend" fit and
was chosen for that reason. GraphQL/OData/etc. can be added later as adapters
(§6).

### NL filtering — the one non-negotiable discipline

**NL → validated AST → execute. Never NL → SQL.** The LLM emits a *constrained
predicate AST* (whitelisted operators + real field paths only), which is
validated before it touches a connector. This buys:

- **No injection** — the model can't emit arbitrary SQL, only whitelisted AST.
- **Determinism via cache** — key the NL→AST result on `(normalized phrase +
  schema version)`; same phrase → same filter.
- **Reuse** — flows through the same planner/pushdown as structured filters.

Always **echo the interpretation** in the response so the magic is inspectable;
offer a **confirm-before-execute** mode for agents / high-stakes callers.

## 5. Value/enum & relative-value handling

- **Relative dates** ("this year" → `2026`): a deterministic normalizer
  (Elasticsearch-style `now/year` date-math) handles the common cases; the LLM
  doesn't have to.
- **Enum-value fuzzing** (`sci-fi` vs `"Science Fiction"`): a second semantic
  step — resolve the *value* against the column's real domain, distinct from
  resolving the *field*.
- **Underspecification** ("recent", "popular"): documented defaults or a
  clarify path — never a silent arbitrary mapping.

## 6. Architecture — two-sided narrow waist (hourglass)

Every request protocol compiles **up** to a canonical IR; every backend compiles
**down** from it. N fronts → 1 waist → M backs. The novel part (semantic
resolution) sits in the shared middle and is written once.

```
GraphQL ┐                                                 ┌ SQL DB
OData   ┤                                                 ┤ Data catalog
JSON/MQL┼─► RequestAdapter ─► RawQuery ─► [resolver] ─────┼ REST/OpenAPI
?params ┤    (parse/format)   (client    (semantic layer) │ CanonicalQueryIR ─► Connector ┤ CSV/S3
NL text ┘                      vocab)     + value norm.    └                                └ ...
             ▲ ingress: N protocols       ▲ shared middle (written once)      ▲ egress: M backends
```

Two split translations:

- **Syntactic** (protocol-specific, deterministic): adapter parses the wire
  format into a `RawQuery` (unresolved IR, still in client vocabulary).
- **Semantic** (protocol-agnostic, shared): resolver turns `RawQuery` →
  `CanonicalQueryIR` (client keys → canonical fields, value normalization).

Because resolution happens *after* parsing, every protocol gets "you don't need
to know the field names" for free.

### The two pluggable interfaces

```
interface RequestAdapter {          // ingress (one per protocol)
  matches(req): boolean
  parse(req): RawQuery
  format(result, req): Response
}

interface Connector {               // egress (one per backend)
  describe(): CanonicalSchema        // auto-introspect + LLM-enriched descriptions
  capabilities(): Capabilities       // canFilter? canSort? canJoin? pushdown limits
  execute(plan: CanonicalQueryIR): Rows
}
```

- `describe()` is what delivers **"less configuration"** — point at a source, it
  introspects (SQL `information_schema`, a catalog API, OpenAPI, CSV headers)
  and the gateway auto-enriches with LLM-generated descriptions/synonyms.
- `capabilities()` is what makes "any backend" real: the planner pushes down
  what a connector supports and evaluates the rest in the gateway (Calcite
  model). The operator set is also a capability contract.

### Reuse, don't rebuild

Federation plumbing under the semantic layer is solved — steal it: **Trino**
(capability-based pushdown), **Steampipe** (SQL over any API), **GraphQL Mesh**
(any source → unified graph), **Airbyte/Singer** (connector catalog + schema
discovery), **Apache Calcite / Ibis** (query IR + planner + partial pushdown).
Our actual new code is the glue + caching + confidence-gate + security boundary.

## 7. Stack decision

The hard/valuable part is semantic resolution (AI + data ecosystem, dev speed),
not raw throughput — so optimize for those in v1 and rewrite a hot path later.
That rules out Go/Rust for v1.

- **Spike → Python.** Pure resolution accuracy; LiteLLM + a few schemas + a
  scoring loop is fastest, richest model coverage for the benchmark matrix.
- **Gateway → TypeScript (leaning).** GraphQL Mesh / graphql-js give the
  adapter + federation plumbing nearly free; JSON-native request model;
  audience is frontend/agent devs; Vercel AI SDK + AI Gateway = clean
  multi-vendor LLM. **Flip to Python + Ibis** if, after the spike, the weight is
  on cross-source federation/planning rather than protocol breadth.

**Multi-vendor LLM:** never call a vendor SDK directly. Depend on two tiny
interfaces — `LLM.json` and `Embed.embed` (embeddings matter as much as
completions for the semantic match) — and inject the impl. Concrete options:
**LiteLLM** (Python), **Vercel AI SDK + AI Gateway** (TS), **OpenRouter**
(hosted, any language).

_Model/pricing reference (per 1M tokens, current): Haiku 4.5 $1/$5, Sonnet 4.6
$3/$15, Opus 4.8 $5/$25. Cold resolution ≈ a fraction of a cent; cached
mappings make steady-state per-request LLM cost ≈ zero._

## 8. The de-risking spike (do this before building)

All value rides on resolution accuracy, so measure it before building the
gateway. See [`/spike`](../spike/README.md). It measures, across models:

1. **`want`-resolution** — top-1 field mapping + confidence-gate correctness.
2. **NL-`where` → AST** — does the compiled predicate match the expected
   canonical AST (field paths, operators, normalized values)?

Decision rule:

- **≥95% on both, gate catches misses** → real product, go build.
- **~80–90%** → viable only for agent/prototype use with a clarify/retry loop.
- **<80% or bad AST silently passes** → a demo, not a product. Stop.

Run: `pip install -r spike/requirements.txt && python -m spike.score`
(set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` for whichever models you benchmark).

### First-run result (Haiku 4.5 / Sonnet 4.6 / Opus 4.8)

- **WANT resolution: 100%** across all three models — including the cheapest
  (Haiku). Synonyms, paraphrases, `state→status`, cross-entity fields, and
  correctly *declining* the unresolvable `vibes` field all worked.
- **WHERE → AST: ~100% semantically.** The first run reported 57%, but the raw
  output showed all three models produced *correct* predicates — in two cases
  **more** correct than the hand-written ground truth ("this year" as a bounded
  range; "last 30 days" bounded on both ends). The 57% was an over-strict
  exact-match oracle. Switching the scorer to **execution equivalence** (do both
  ASTs select the same sample rows?) removed the false failures; verified
  against the actual recorded model outputs.

### Expanded-set result (52 cases, subagent simulation)

Ran the full 52-case set (125 want-mappings + 40 where-predicates, 4 domains)
against three Claude tiers, executed as **subagents** (no API key available), and
scored with the deterministic code the models never saw:

| Model | WANT | WHERE → AST |
|---|---|---|
| Haiku 4.5 | 98% (123/125) | 100% (40/40) |
| Sonnet 4.6 | 100% (125/125) | 98% (39/40) |
| Opus 4.8 | 100% (125/125) | 100% (40/40) |

Aggregate ~99.5% / 99.2%. Every miss was a prompt gap or genuine ambiguity, not
a capability failure:
- Sonnet's 1 WHERE miss exposed an **underspecified `between` value shape** in the
  prompt (it emitted `low`/`high` instead of `value:[lo,hi]`) — since fixed in
  `prompts.py`. Exactly the kind of contract gap the spike is meant to catch.
- Haiku's 2 WANT misses were borderline synonyms (`penName→author.name`, declined
  at 0 confidence; `launchedIn`, genuinely ambiguous between release year and
  catalog-add date).

**Fidelity caveat:** this is a subagent simulation (agent-wrapped Claude tiers,
multiple prompts per turn), not bare per-request API calls — directionally
strong and consistent with the earlier run, but not a certified production
number. A real per-request run (any provider key via LiteLLM — Anthropic /
OpenAI / Gemini) remains the certified version.

### First-run result (Haiku 4.5 / Sonnet 4.6 / Opus 4.8)

- **WANT resolution: 100%** across all three models — including the cheapest
  (Haiku). Synonyms, paraphrases, `state→status`, cross-entity fields, and
  correctly *declining* the unresolvable `vibes` field all worked.
- **WHERE → AST: ~100% semantically.** The first run reported 57%, but the raw
  output showed all three models produced *correct* predicates — in two cases
  **more** correct than the hand-written ground truth ("this year" as a bounded
  range; "last 30 days" bounded on both ends). The 57% was an over-strict
  exact-match oracle. Switching the scorer to **execution equivalence** (do both
  ASTs select the same sample rows?) removed the false failures; verified
  against the actual recorded model outputs.

**Read:** strong green light on the core value. Remaining caveat: ambiguous
filter *values* ("fiction" → SF? Fantasy?)
are a real product gap, not a model failure — they need the value-resolution
step plus a clarify path. Even the cheap model was accurate, so the cost model
holds (cache resolved mappings → steady-state per-request LLM cost ≈ 0).

## 9. Open decisions / next steps

- [x] **Run the spike** across Haiku/Sonnet/Opus — WANT 100%, WHERE ~100%
      (after switching to execution-equivalence scoring). Green light. See §8.
- [x] Expand the case set — now **52 cases across 4 domains** (library, shop,
      hr, streaming), validated offline (every scored predicate selects a proper
      non-empty subset). Awaiting a re-run for the certified accuracy number.
- [x] Run the expanded set across Haiku/Sonnet/Opus via subagent simulation —
      ~99.5% WANT / 99.2% WHERE; found + fixed the `between` prompt gap. See §8.
- [ ] Certified per-request run via LiteLLM (needs a provider key) across
      Anthropic + a non-Anthropic model — **Gemini** (`gemini/*`, `GEMINI_API_KEY`)
      and/or OpenAI — for the official cross-vendor number.
- [ ] Lock the `RawQuery` and `CanonicalQueryIR` type definitions (the public
      contracts everything hangs off).
- [ ] Decide gateway language (TS vs Python) using the spike's federation-vs-
      protocol weighting.
- [ ] Design the confidence-gate + "did you mean X?" clarify path.
- [ ] Design the security boundary (field allowlist / field-level authz).
- [ ] Value-resolution strategy (enum fuzzing) as its own step.
- [ ] Freedom-to-operate check on US 12045656 if commercializing.
- [ ] MVP seam test: build the Postgres connector so nothing above the connector
      interface knows it's SQL — a fake in-memory connector must swap in without
      touching resolver/planner.
- [ ] (Suggested) add `docs/devlog.md` to track learnings as we build.
