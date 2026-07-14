# Playground Request-Transparency Panel — Design

**Date:** 2026-07-13
**Status:** Approved (brainstorm session)
**Elevates:** todo.md → "Playground request-transparency panel" (Demo improvements)
**Docs consulted:** `todo.md`, `docs/architecture.md` §1/§3/§6, `gateway/pipeline.py`,
`gateway/connectors/postgres.py`, `gateway/cache.py`, `gateway/config.py`,
`gateway/app.py`, `playground/lib/api.ts`,
`playground/components/InterpretedPanel.tsx`, `playground/app/page.tsx`

## Goal

Answer "what did the gateway actually do?" per request, in the playground: show
the parameterized SQL the connector executed, the per-`want`-field and `where`
resolution-cache hit/miss, and the confidence-gate threshold — so the demo shows
the machinery, and the confidence numbers in the `interpreted` echo have visible
meaning.

## Settled decisions (from the brainstorm)

| Question | Decision |
|---|---|
| Debug scope (v1) | **SQL + params, cache hit/miss, gate threshold.** No timing (deferred — YAGNI'd out of v1). |
| Opt-in flag | **New `isDebug` body flag**, implies the `interpreted` echo. Keeps "inspectable product feature" (`isVerbose`) and "machinery disclosure" (`isDebug`) as separate dials. |
| Config gate | **`ENABLE_QUERY_DEBUG`, default OFF** — consistent with the `ENABLE_DEBUG_ENDPOINTS` posture. When off, `isDebug` is silently ignored (treated as absent, including its `interpreted` implication). The demo deploy sets it on. |
| SQL plumbing | **Trace object** (`ExecutionTrace`) passed into `execute(ir, limit, trace=...)` — one execute method, one code path, reports the SQL that *actually ran*; the pattern the observability ecosystem converged on (Django `connection.queries`, SQLAlchemy events, OTel spans). An `explain()`-style second compile was considered and dropped: it reports a re-derivation, and `as_string()` needs a connection that `execute` already holds. |
| Error path | **Debug block on 4xx too** (no `execution` — nothing ran), so a `where_low_confidence` 422 visibly shows *confidence < threshold*. **502s stay bare** (backend failures don't leak detail). |
| Playground UI | **Option B — woven into the existing `InterpretedPanel`**: cache badge per mapping row, threshold next to the confidences, SQL box at the bottom of the same panel. One top-to-bottom narrative; no new panel. |

## 1. Contract change (architecture §1)

Request gains one optional flag:

```json
POST /query
{ "want": { "book name": null, "writer": null },
  "where": "sci-fi under $20",
  "isDebug": true }
```

`isDebug: true` implies the `interpreted` echo (no need to also send
`isVerbose`). The `interpreted` shape itself is **unchanged** — the new info is
a sibling block, so the locked contract only grows:

```json
{ "rows": [ ... ],
  "interpreted": { ...unchanged... },
  "debug": {
    "gate_threshold": 0.7,
    "cache": { "want": { "book name": "hit", "writer": "miss" }, "where": "miss" },
    "execution": { "engine": "postgres",
                   "sql": "SELECT \"title\", \"author\" FROM \"books_view\" WHERE (\"category\" = %s AND \"price\" < %s) LIMIT %s",
                   "params": ["Science Fiction", 20, 100] }
  } }
```

- `cache.want` — one `"hit"` / `"miss"` per requested key. `cache.where` is
  present only when a `where` was sent. (Note the where cache stores the raw
  resolution regardless of the gate — a repeated low-confidence phrase is a
  *hit* that still 422s, which is itself a demo-visible fact.)
- `execution.sql` — the parameterized text the connector actually ran;
  `execution.params` — the bound values. These are the client's own values, so
  no new disclosure class beyond what `interpreted` already echoes.
- `execution` is `null` when the connector doesn't fill a trace (e.g. a
  connector without the `trace` kwarg).
- **4xx errors**: `debug` rides alongside `interpreted` in the error body,
  without `execution`. **502s** carry no debug block.

## 2. Disclosure gating

New env var `ENABLE_QUERY_DEBUG` → `Settings.enable_query_debug`, **default
OFF**. When off, `isDebug` is silently ignored — the response is exactly the
normal one. Rationale: the block only echoes the machinery of the caller's own
request (SQL over field paths the ungated `interpreted` echo already
discloses), but the project posture is off-by-default for every disclosure
surface, and an own-data operator gets an explicit off switch.

Docs: `gateway/DEPLOY.md` gains the env var (demo deploy sets it on);
`gateway/README.md` quickstart mentions it, with an own-data hardening note.

## 3. Plumbing

- **`RawQuery`** gains `debug: bool`; the JSON `RequestAdapter`
  (`to_raw_query`) parses `isDebug`. `app.py` computes the effective flag
  (`raw.debug and settings.enable_query_debug`) and passes it to `run_query`.
- **Cache hit/miss** — `run_query` already branches on hit-vs-miss for both
  caches (`gateway/pipeline.py` steps 3 and 5); it records the outcome per key
  into the debug dict as it goes. No cache-layer change.
- **`ExecutionTrace`** — a small dataclass in `gateway/connectors/base.py`:
  fields `engine`, `sql`, `params`. The pipeline creates one only when debug is
  on and passes it via `execute(ir, limit, trace=...)`, using the same
  signature-probe pattern as `_accepts_limit` so a connector without the kwarg
  still works (its `execution` reports as `null`). Discipline: the trace is
  write-once by the connector, read once by the pipeline when assembling
  `debug` — never a mid-flight grab-bag.
- **Postgres connector** fills the trace inside `execute` —
  `query.as_string(conn)` (the connection is already in hand, so identifier
  quoting is exact), `params`, `engine: "postgres"`. The **fake connector**
  reports `engine: "core.predicate"` and no SQL, keeping the seam honest.
- **`GatewayError`** gains an optional `debug` attribute (same pattern as
  `interpreted`); `app.py` includes it in the error JSON when present.

## 4. Playground UI (option B)

- `lib/api.ts` sends `isDebug: true`; the copyable curl echo shows it, keeping
  the playground "visibly just this one HTTP request". Types gain `debug?` on
  both `QueryResponse` and `QueryError`.
- `InterpretedPanel` takes an optional `debug` prop:
  - a cache badge per `want` mapping row — `CACHE HIT` / `CACHE MISS → LLM`;
  - the gate threshold rendered next to the confidences — `(gate: ≥70%)`;
  - an SQL + params box at the bottom of the panel;
  - the panel title becomes "What the gateway understood — and did" when debug
    is present.
- **Graceful absence:** no `debug` in the response (gate off, older gateway) →
  the panel renders exactly as today. No playground config needed.
- The error path renders the same badges/threshold from `err.data.debug`.

## 5. Error handling

Covered by §1/§3: partial debug on 4xx, bare 502, silent no-op when the config
gate is off, `execution: null` for a trace-less connector.

## 6. Testing

- **Gateway:** `isDebug` ignored when the gate is off; block shape when on;
  hit→miss transition across two identical requests (the "second click is
  free" beat); a 422 carries debug without `execution`; the fake connector's
  trace reports its engine; the seam-parity test is untouched.
- **Playground:** render check that the panel degrades cleanly without `debug`.

## 7. Scope & follow-ups

- This is **v0.5.0**. `docs/architecture.md` §1 (flag + block) and §6 (the new
  gate: default off, what it does and doesn't disclose) are updated in the same
  change, per the workflow; devlog + todo at session close.
- Out of scope: per-stage timing (revisit if the demo wants a latency beat),
  demo-deck/script updates (operator follow-up).
