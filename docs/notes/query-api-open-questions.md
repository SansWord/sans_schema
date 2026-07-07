# Query API — open design questions (from live use)

**Status:** design notes / open questions — **not** maintained law and **not** an agreed
spec. Captured from a hands-on session running the quickstart (v0.2.0). When one of these
graduates to a milestone, it gets its own brainstorm → spec → plan; until then this is the
scratchpad for the shape of the problem and the leaning. Contracts live in
[`../architecture.md`](../architecture.md); what's queued lives in [`../../todo.md`](../../todo.md).

Both questions below share a root: v1 assumes a **bijection** — each `want` field maps to
exactly one existing column, and each filter leaf is *(existing column, op, literal)*.
Anything that isn't a straight rename (a computation, a field the client can't name because
it doesn't know the schema) pushes past that assumption.

---

## Q1 — "Tiny calculations": derived / computed fields

**The ask (verbatim example):**

```
{"want": {"title": null, "writer": null, "published_date": null, "genra": null,
          "price_in_twd": null, "price_in_usd": null, "price_in_euro": null,
          "currency": null, "author_age": null},
 "where": "with no science fiction, author is older than 30 years old"}
```

Data has `price` (USD) and `birth_year`. The client wants currency conversions, the currency
label itself, and the author's *age*.

### What v1 does with this today

| Field / clause | Outcome today |
|---|---|
| `title`, `writer`, `published_date`, `genra` (typo) | Resolve fine — semantic match handles renames + typos |
| `price_in_usd` | Probably aliases to `price` (description says "USD") — works by luck |
| `price_in_twd`, `price_in_euro`, `currency`, `author_age` | **No backing column.** Best case → `null` column (declined). Worst case → *confidently wrong* (`price_in_twd → price` returns the USD number mislabeled; `author_age → birth_year` returns 1929). |
| `where` "no science fiction" | **Works** — `ne(category, 'Science Fiction')` is in the grammar |
| `where` "older than 30" | Coin flip — no `age` column, so either a non-existent field → `validate_ast` 422, or a lucky rewrite to `birth_year < 1996` |

The silent confident-wrong case (USD number labeled TWD) is the scariest failure and ties to
the existing de-risking item "report a confident-wrong rate."

### The gap: field references → validated expressions

Supporting computation means moving from column references to a small **validated expression
language** in three places, without breaking the two invariants:

| Place | Today | Needs |
|---|---|---|
| Projection (`want`/`select`) | `ResolvedField.field_path` = one column | an expression (`price * rate`, `year(today) − birth_year`, literal `'USD'`) |
| Predicate LHS (`where`) | leaf `field` must be a real column | an expression LHS (`age(birth_year) > 30`) |
| Value source | only what's in a column | data the table lacks: FX rates, constants, `today` |

Invariants the extension must preserve:
- **Injection boundary:** *NL → validated AST → execute, never NL → SQL.* Computation must be
  a whitelisted expression tree (`col`, `lit`, `+ − × ÷`, a few date fns), validated in
  `validate_ast`, compiled to parameterized SQL — never a model-emitted SQL snippet.
- **Execution-equivalence oracle** (`core/predicate.py`) must evaluate the same expressions,
  or the seam-parity test and the spike eval can no longer measure computed fields.

### Three difficulty tiers (in the example)

1. **Pure function of columns + `today`** — `author_age = year(today) − birth_year`.
   Self-contained (the gateway already has `today`). Blockers: expression support + the oracle
   + date precision (year vs birthdate) + the `bind_today` date-dependence already queued.
2. **Constant / metadata** — `currency = 'USD'`. Trivial once expressions exist, and derivable
   from the schema description ("price in USD"). Only meaningful as a *declared/trusted* fact.
3. **Function of columns + EXTERNAL data** — `price_in_twd = price × FX(USD→TWD)`. The hard one:
   the rate isn't in the data and changes daily. If the LLM invents `31.5`, you get plausible,
   stale, wrong money. A new capability (trusted enrichment data), not an expression-grammar gap.

### Options

- **A — Declared virtual/derived fields (recommended for anything business-critical).** The
  backend declares `author_age`, `price_twd`, `currency` as first-class fields (config, a SQL
  view / generated columns, or a `rates` table) with descriptions + a *trusted* expression or
  source. Resolution, gate, cache, authz, and the oracle then work **unchanged** — they're just
  more columns. FX rates live in data, never guessed. Fits the "deterministic, auditable"
  leaning. Cost: the operator predefines them (not zero-config).
- **B — Model-authored expressions (optional, later).** Let the LLM emit a whitelisted
  expression AST; validate arity/types; compile to parameterized SQL; mirror in the oracle. More
  magical + zero-config, but multiplies the confident-wrong surface and **must never touch FX
  rates** (no trusted source). Needs hard gating + confirm-before-execute.

**Leaning:** A for external/business-critical values (currency); B only later as an opt-in layer
for *pure* date/arithmetic derivations behind the gate. A "derived fields v1" milestone could
scope to tiers 1–2 (`author_age`, `currency`) and explicitly defer FX to a rate-source design.

---

## Q2 — Exposing available fields & field discovery

**The ask:** is it okay/safe to expose the fields we have to users, and what's the recommended
way to discover them with the current API (support a wildcard `want: "*"`)?

### Is exposure safe? — not by default on a real backend

The design deliberately hides the backend schema: the client queries in its own vocabulary and
the gateway resolves. A field listing is a **schema disclosure** — it reveals what data exists
(that a `salary` / `email` / `ssn` column *exists*), which is exactly the queued risk
"a cold request must not let a client probe the schema." Escalating factors:

- **Sample values are the biggest leak.** `describe()` collects samples (real names, categories)
  for the prompt. They are **not** returned to clients today (server-side only) — any exposure
  path must keep it that way or gate samples separately.
- **Descriptions can leak business logic** (internal semantics of a column).
- **The `interpreted` echo already leaks, per request.** With `isVerbose`, the response returns
  each *named* key's resolved `field` path + the `where` AST's real field paths — so a client can
  probe the schema by guessing keys and reading the echo. A limited schema oracle that exists
  now. (Mitigations: authz so only allowed fields resolve; make the echo omittable; the
  confidence gate limits weak guesses.)

So exposure on a real backend requires: **field-level authz** (only surface fields this client
may query) + **sample-stripping** + curated descriptions. For the **public demo** (a fixed,
non-sensitive dataset in a bounded sandbox) exposure is fine and useful — that's a special case
already noted in the demo todo.

### Discovery options with the current API

| Approach | Shape | Trade-off |
|---|---|---|
| **Curated capability listing** (recommended) | new discovery call → NL field *descriptions*, authz-filtered, no raw paths, no samples | Preserves vocabulary-independence; safest; needs a curation/authz step |
| **Raw `GET /schema`** | dump introspected fields (paths, types, descriptions) | Simple, but leaks real column names; bypasses the semantic layer; needs authz + sample strip |
| **Wildcard `want: "*"`** | `POST /query` returns all (allowed) columns | Convenient for agents/demo, but keys become **backend field paths** (no client vocab to remap to), which collapses vocabulary-independence and the deterministic response shape; gate behind authz |

### Recommendation

- The **safe, on-brand** discovery path is a **curated capability listing** — natural-language
  descriptions of what you can ask about, authz-filtered, with column names and samples withheld.
  It keeps the real schema hidden while making the gateway self-describing, and it stays true to
  "the client uses its own words."
- `want: "*"` is worth supporting as a **trusted/demo convenience** (agents exploring a sandbox),
  treated as "backend-keyed projection" and gated by the same authz. It is not a safe multi-tenant
  default because it hands the client the real vocabulary and a non-deterministic response shape.
- **Prerequisites for any real-backend exposure:** field-level authz + sample-stripping, and a
  decision on whether the `interpreted` echo stays on by default (it's the current leak channel).

---

## Cross-links

- `bind_today` (queued) — needed for `author_age` and any date-derived threshold to be
  cache-stable and free of LLM date-math error.
- De-risking items in [`../../todo.md`](../../todo.md): "confident-wrong rate", "field allowlist /
  field-level authz", "authz without client schema knowledge / no schema probing",
  "deterministic-SDK baseline". Q1 and Q2 both sharpen these.
