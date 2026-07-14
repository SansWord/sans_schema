# Request-Transparency Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-request debug info on `POST /query` (parameterized SQL, cache hit/miss, gate threshold) behind an `isDebug` flag + `ENABLE_QUERY_DEBUG` config gate, rendered inside the playground's `InterpretedPanel`.

**Architecture:** The pipeline records cache hit/miss as it resolves; an `ExecutionTrace` dataclass is passed into `connector.execute(ir, limit, trace=...)` (signature-probed, like `limit` today) and the Postgres connector fills it with the SQL it actually ran. `app.py` computes the effective debug flag (`isDebug` AND config gate) and attaches the block to 200s and 4xx errors (502s stay bare). Spec: `docs/superpowers/specs/2026-07-13-request-transparency-panel-design.md`.

**Tech Stack:** Python 3.9+ / FastAPI / psycopg3 / pytest; playground is Next.js 15 + TypeScript (no JS test runner — verification is `npm run build` type-checking).

**Verification commands:** `python -m pytest tests/ -q` (whole suite; Postgres tests auto-skip unless `TEST_DATABASE_URL` is set). Playground: `cd playground && npm run build`.

---

### Task 0: Branch

- [ ] **Step 1: Create the feature branch**

```bash
cd /Users/sansword/Source/github/sans_schema
git checkout -b feat/request-transparency-panel
```

---

### Task 1: Config gate `ENABLE_QUERY_DEBUG`

**Files:**
- Modify: `gateway/config.py`
- Test: `tests/gateway/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/gateway/test_config.py`:

```python
def test_query_debug_gate_default_off(monkeypatch):
    monkeypatch.delenv("ENABLE_QUERY_DEBUG", raising=False)
    assert Settings.from_env().enable_query_debug is False


def test_query_debug_gate_parses_from_env(monkeypatch):
    monkeypatch.setenv("ENABLE_QUERY_DEBUG", "1")
    assert Settings.from_env().enable_query_debug is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/gateway/test_config.py -q`
Expected: FAIL — `TypeError` / `AttributeError`: `Settings` has no field `enable_query_debug`.

- [ ] **Step 3: Implement**

In `gateway/config.py`, add a field right after `enable_debug_endpoints: bool` (it needs a default, so it sits at the head of the defaulted block):

```python
    enable_query_debug: bool = False  # honor isDebug on POST /query (per-request debug block)
```

In `from_env()`, after the `enable_debug_endpoints=` entry:

```python
            # Per-request debug block on POST /query (isDebug). OFF by default —
            # disclosure posture matches ENABLE_DEBUG_ENDPOINTS; demo deploy sets it on.
            enable_query_debug=os.environ.get(
                "ENABLE_QUERY_DEBUG", "0").strip().lower() in ("1", "true", "yes", "on"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/gateway/test_config.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add gateway/config.py tests/gateway/test_config.py
git commit -m "feat(gateway): ENABLE_QUERY_DEBUG setting, default off"
```

---

### Task 2: `RawQuery.debug` + `isDebug` parsing in the adapter

**Files:**
- Modify: `gateway/contracts.py` (RawQuery), `gateway/app.py` (`to_raw_query`)
- Test: `tests/gateway/test_app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_app.py`:

```python
def test_to_raw_query_parses_is_debug():
    from gateway.app import to_raw_query
    assert to_raw_query({"want": ["t"], "isDebug": True}).debug is True
    assert to_raw_query({"want": ["t"]}).debug is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/gateway/test_app.py::test_to_raw_query_parses_is_debug -q`
Expected: FAIL — `RawQuery` has no attribute `debug`.

- [ ] **Step 3: Implement**

`gateway/contracts.py`, add to `RawQuery` after `verbose`:

```python
    debug: bool = False              # include the `debug` block (isDebug; config-gated in app)
```

`gateway/app.py`, in `to_raw_query`, extend the `RawQuery(...)` construction:

```python
    return RawQuery(want=want, where=where,
                    today=datetime.date.today().isoformat(),
                    verbose=bool(body.get("isVerbose", False)),
                    debug=bool(body.get("isDebug", False)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/gateway/test_app.py tests/gateway/test_contracts.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add gateway/contracts.py gateway/app.py tests/gateway/test_app.py
git commit -m "feat(gateway): parse isDebug into RawQuery.debug"
```

---

### Task 3: `ExecutionTrace` + fake connector fills it

**Files:**
- Modify: `gateway/connectors/base.py`, `gateway/connectors/fake.py`
- Test: `tests/gateway/test_fake_connector.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_fake_connector.py` (add any missing imports at the top of the file — `CanonicalQueryIR`/`ResolvedField` come from `gateway.contracts`, `FakeConnector` from `gateway.connectors.fake`):

```python
def test_execute_fills_trace_engine():
    from gateway.connectors.base import ExecutionTrace
    ir = CanonicalQueryIR(select=[ResolvedField("t", "books_view.title", 0.9)],
                          predicate=None, where_confidence=None, where_raw=None)
    trace = ExecutionTrace()
    rows = FakeConnector().execute(ir, trace=trace)
    assert rows                                     # execute still returns rows
    assert trace.engine == "core.predicate"
    assert trace.sql is None and trace.params is None   # no SQL story to tell
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/gateway/test_fake_connector.py -q`
Expected: FAIL — `ImportError: cannot import name 'ExecutionTrace'`.

- [ ] **Step 3: Implement**

`gateway/connectors/base.py` — extend the `typing` import to `from typing import Any, List, Optional` and add below `Capabilities`:

```python
@dataclass
class ExecutionTrace:
    """Per-request execution debug info (request-transparency panel spec). Created
    by the pipeline only when debug is on; write-once by the connector, read once
    when the response's `debug` block is assembled — never a mid-flight channel."""
    engine: Optional[str] = None            # e.g. "postgres", "core.predicate"
    sql: Optional[str] = None               # parameterized SQL text, if the backend runs SQL
    params: Optional[List[Any]] = None      # bound values, in placeholder order
```

`gateway/connectors/fake.py` — update imports and `execute`:

```python
from typing import List, Optional

from gateway.connectors.base import Capabilities, ExecutionTrace
```

```python
    def execute(self, ir: CanonicalQueryIR,
                trace: Optional[ExecutionTrace] = None) -> List[dict]:
        if trace is not None:
            trace.engine = "core.predicate"     # in-memory oracle — no SQL to report
        paths = [f.field_path for f in ir.select if f.field_path is not None]
        rows = [_qualify(r) for r in VIEW_ROWS]
        selected = rows if ir.predicate is None else \
            [r for r in rows if matches(ir.predicate, r)]
        return [{p: row.get(p) for p in paths} for row in selected]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/gateway/test_fake_connector.py tests/gateway/test_seam_parity.py -q`
Expected: PASS (seam parity untouched — it calls `execute(ir)` without `trace`).

- [ ] **Step 5: Commit**

```bash
git add gateway/connectors/base.py gateway/connectors/fake.py tests/gateway/test_fake_connector.py
git commit -m "feat(gateway): ExecutionTrace dataclass; fake connector reports its engine"
```

---

### Task 4: Postgres connector fills the trace with the SQL it ran

**Files:**
- Modify: `gateway/connectors/postgres.py`
- Test: `tests/gateway/test_postgres_connector.py` (runs only with `TEST_DATABASE_URL` set; otherwise auto-skips — that's fine, CI/local-with-DB covers it)

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_postgres_connector.py`:

```python
def test_execute_fills_trace_with_parameterized_sql(pg_connector):
    from gateway.connectors.base import ExecutionTrace
    ir = CanonicalQueryIR(
        select=[ResolvedField("t", "books_view.title", 0.9)],
        predicate={"op": "lt", "field": "books_view.price", "value": 30},
        where_confidence=0.9, where_raw="under $30")
    trace = ExecutionTrace()
    pg_connector.execute(ir, limit=5, trace=trace)
    assert trace.engine == "postgres"
    assert trace.sql == 'SELECT "title" FROM "books_view" WHERE "price" < %s LIMIT %s'
    assert trace.params == [30, 5]              # values stay bound, never inlined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TEST_DATABASE_URL=<your local DSN> python -m pytest tests/gateway/test_postgres_connector.py -q`
Expected: FAIL — `execute() got an unexpected keyword argument 'trace'`. (Without a local Postgres the test skips; in that case rely on Step 4's suite run wherever `TEST_DATABASE_URL` is available, and proceed.)

- [ ] **Step 3: Implement**

`gateway/connectors/postgres.py` — update the import and `execute`:

```python
from gateway.connectors.base import Capabilities, ExecutionTrace
```

```python
    def execute(self, ir: CanonicalQueryIR, limit: int = 100,
                trace: Optional[ExecutionTrace] = None) -> List[dict]:
        fields = [f for f in ir.select if f.field_path is not None]
        select_cols = sql.SQL(", ").join(sql.Identifier(self._col(f.field_path)) for f in fields)
        query = sql.SQL("SELECT {cols} FROM {view}").format(
            cols=select_cols, view=sql.Identifier(self.view))
        params: List[Any] = []
        if ir.predicate is not None:
            clause, params = self._compile(ir.predicate)
            query = query + sql.SQL(" WHERE ") + clause
        query = query + sql.SQL(" LIMIT %s")
        params.append(limit)
        with psycopg.connect(self.dsn) as conn:
            if trace is not None:
                # as_string needs the connection for exact identifier quoting
                trace.engine = "postgres"
                trace.sql = query.as_string(conn)
                trace.params = list(params)
            cur = conn.execute(query, params)
            # re-key each row by the qualified field path (SELECT order == fields order),
            # so remap — which looks up by field_path — finds the value.
            keys = [f.field_path for f in fields]
            return [dict(zip(keys, row)) for row in cur.fetchall()]
```

(Only the signature and the `if trace is not None:` block are new.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `TEST_DATABASE_URL=<your local DSN> python -m pytest tests/gateway/test_postgres_connector.py -q`
Expected: PASS (all 4).

- [ ] **Step 5: Commit**

```bash
git add gateway/connectors/postgres.py tests/gateway/test_postgres_connector.py
git commit -m "feat(gateway): Postgres connector records executed SQL into ExecutionTrace"
```

---

### Task 5: Pipeline assembles the `debug` block (200 path)

**Files:**
- Modify: `gateway/pipeline.py`
- Test: `tests/gateway/test_pipeline.py`

- [ ] **Step 1: Update the test helper and write the failing tests**

In `tests/gateway/test_pipeline.py`, replace the `_run` helper:

```python
def _run(raw, llm, cache=None, debug=False):
    return run_query(raw, FakeConnector(), llm, cache or ResolutionCache(),
                     GateConfig(threshold=0.7), limit=100, debug=debug)
```

Append:

```python
def test_debug_block_reports_cache_threshold_and_execution():
    cache = ResolutionCache()
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}},
                  where=WHERE_OK)
    raw = RawQuery(["book_title"], "sci-fi only", "2026-07-06", verbose=True)
    dbg = _run(raw, llm, cache, debug=True)["debug"]
    assert dbg["gate_threshold"] == 0.7
    assert dbg["cache"] == {"want": {"book_title": "miss"}, "where": "miss"}
    assert dbg["execution"] == {"engine": "core.predicate", "sql": None, "params": None}
    # same request again → both caches hit (the "second click is free" beat)
    raw2 = RawQuery(["book_title"], "sci-fi only", "2026-07-06", verbose=True)
    dbg2 = _run(raw2, llm, cache, debug=True)["debug"]
    assert dbg2["cache"] == {"want": {"book_title": "hit"}, "where": "hit"}


def test_debug_block_omits_where_status_without_a_where():
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}})
    dbg = _run(raw, llm, debug=True)["debug"]
    assert dbg["cache"] == {"want": {"book_title": "miss"}}


def test_debug_off_omits_block():
    raw = RawQuery(["book_title"], None, "2026-07-06", verbose=True)
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}})
    assert "debug" not in _run(raw, llm)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/gateway/test_pipeline.py -q`
Expected: FAIL — `run_query() got an unexpected keyword argument 'debug'`.

- [ ] **Step 3: Implement**

In `gateway/pipeline.py`:

Add to the imports:

```python
from gateway.connectors.base import schema_version, ExecutionTrace
```

(replacing the existing `from gateway.connectors.base import schema_version` line).

Add below `_interpreted`:

```python
def _debug_block(gate: GateConfig, cache_status: Dict[str, Any],
                 trace: Optional[ExecutionTrace]) -> Dict[str, Any]:
    """The `debug` response block (request-transparency spec): gate threshold,
    per-key cache hit/miss, and the execution trace (None until something ran)."""
    execution = None
    if trace is not None and trace.engine is not None:
        execution = {"engine": trace.engine, "sql": trace.sql, "params": trace.params}
    return {"gate_threshold": gate.threshold, "cache": cache_status, "execution": execution}
```

Replace `_accepts_limit` (delete it) with:

```python
def _execute_kwargs(connector, limit: int,
                    trace: Optional[ExecutionTrace]) -> Dict[str, Any]:
    """Pass limit/trace only to connectors whose execute() accepts them — the fake
    ignores bounds, and a connector predating the trace kwarg still works (its
    `execution` just reports as null)."""
    import inspect
    try:
        sig_params = inspect.signature(connector.execute).parameters
    except (TypeError, ValueError):
        return {}
    kw: Dict[str, Any] = {}
    if "limit" in sig_params:
        kw["limit"] = limit
    if "trace" in sig_params and trace is not None:
        kw["trace"] = trace
    return kw
```

Change `run_query`'s signature and body:

```python
def run_query(raw: RawQuery, connector, llm, cache: ResolutionCache,
              gate: GateConfig, limit: int, debug: bool = False) -> Dict[str, Any]:
```

After `valid_fields = ...`, add:

```python
    cache_status: Dict[str, Any] = {"want": {}}

    def _dbg(trace: Optional[ExecutionTrace] = None) -> Optional[Dict[str, Any]]:
        return _debug_block(gate, cache_status, trace) if debug else None
```

Rewrite the step-3 loop to record hit/miss:

```python
    cells: Dict[str, Any] = {}
    missing: List[str] = []
    for key in raw.want:
        hit = cache.get_field(backend, sv, key)
        cache_status["want"][key] = "hit" if hit is not None else "miss"
        if hit is not None:
            cells[key] = hit
        else:
            missing.append(key)
```

In the `where` branch, record the outcome (the `hit = cache.get_where(...)` line already exists):

```python
        hit = cache.get_where(backend, sv, raw.where, raw.today)
        cache_status["where"] = "hit" if hit is not None else "miss"
```

Before the execute call, create the trace and use the kwargs probe:

```python
    trace = ExecutionTrace() if debug else None
    try:
        rows = connector.execute(ir, **_execute_kwargs(connector, limit, trace))
```

(The old `if _accepts_limit(connector) else` form goes away.)

At the end:

```python
    resp: Dict[str, Any] = {"rows": out_rows}
    if raw.verbose:
        resp["interpreted"] = _interpreted(select, raw, predicate, where_conf)
    if debug:
        resp["debug"] = _debug_block(gate, cache_status, trace)
    return resp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/gateway/test_pipeline.py tests/gateway/test_seam_parity.py -q`
Expected: PASS (all — existing tests unaffected: `debug` defaults to False).

- [ ] **Step 5: Commit**

```bash
git add gateway/pipeline.py tests/gateway/test_pipeline.py
git commit -m "feat(gateway): pipeline assembles debug block (cache status, gate, execution trace)"
```

---

### Task 6: Debug block on 4xx errors; 502s stay bare

**Files:**
- Modify: `gateway/pipeline.py` (`GatewayError` + the raise sites)
- Test: `tests/gateway/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/gateway/test_pipeline.py`:

```python
def test_low_confidence_where_422_carries_debug_without_execution():
    raw = RawQuery(["book_title"], "something vague", "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}},
                  where={"where": {"op": "eq", "field": "books_view.category", "value": "x"},
                         "confidence": 0.4})
    with pytest.raises(GatewayError) as e:
        _run(raw, llm, debug=True)
    assert e.value.debug["gate_threshold"] == 0.7
    assert e.value.debug["cache"] == {"want": {"book_title": "miss"}, "where": "miss"}
    assert e.value.debug["execution"] is None      # nothing ran


def test_error_debug_is_none_when_not_requested():
    raw = RawQuery(["book_title"], "something vague", "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}},
                  where={"where": {"op": "eq", "field": "books_view.category", "value": "x"},
                         "confidence": 0.4})
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.debug is None


def test_backend_error_502_carries_no_debug():
    class BoomConnector(FakeConnector):
        def execute(self, ir, trace=None):
            raise RuntimeError("db exploded")
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}})
    with pytest.raises(GatewayError) as e:
        run_query(raw, BoomConnector(), llm, ResolutionCache(), GateConfig(0.7), 100, debug=True)
    assert e.value.status == 502 and e.value.debug is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/gateway/test_pipeline.py -q`
Expected: FAIL — `GatewayError` has no attribute `debug`.

- [ ] **Step 3: Implement**

In `gateway/pipeline.py`, extend `GatewayError` (docstring already says `interpreted` attaches on 4xx — extend it):

```python
class GatewayError(Exception):
    """A non-200 outcome. `interpreted` (and, when requested, `debug` — without
    `execution`, nothing ran) is attached for every 4xx; 502s stay bare (spec §12
    + request-transparency spec)."""

    def __init__(self, status: int, code: str, message: str,
                 interpreted: Optional[Dict[str, Any]] = None,
                 debug: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.interpreted = interpreted
        self.debug = debug
```

Attach `debug=_dbg()` at the three 4xx raise sites in `run_query` (the 502 sites — `llm_error` via `_retry_once`, both `backend_error`s — are untouched):

```python
        raise GatewayError(422, "all_want_declined", "no requested field resolved",
                           _interpreted(select, raw, None, None), debug=_dbg())
```

```python
            raise GatewayError(422, "where_low_confidence", "filter confidence below threshold",
                               _interpreted(select, raw, ast, where_conf), debug=_dbg())
```

```python
                raise GatewayError(422, "invalid_ast", str(e),
                                   _interpreted(select, raw, ast, where_conf), debug=_dbg())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/gateway/test_pipeline.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add gateway/pipeline.py tests/gateway/test_pipeline.py
git commit -m "feat(gateway): debug block on 4xx errors; 502s stay bare"
```

---

### Task 7: App wiring — config gate, `interpreted` implication, error body

**Files:**
- Modify: `gateway/app.py`
- Test: `tests/gateway/test_app.py`

- [ ] **Step 1: Write the failing tests**

In `tests/gateway/test_app.py`, add next to `_debug_on`:

```python
_query_debug_on = _settings(enable_query_debug=True)
```

Append:

```python
def test_is_debug_silently_ignored_when_gate_off():
    c = _client(FakeLLM(want=WANT_OK, where=WHERE_OK))
    r = c.post("/query", json={"want": {"book_title": None}, "where": "sci-fi only",
                               "isDebug": True})
    assert r.status_code == 200
    body = r.json()
    assert "debug" not in body
    assert "interpreted" not in body    # the isVerbose implication is gated too


def test_is_debug_returns_block_and_implies_interpreted():
    app.dependency_overrides[get_settings] = _query_debug_on
    c = _client(FakeLLM(want=WANT_OK, where=WHERE_OK))
    r = c.post("/query", json={"want": {"book_title": None, "genre": None},
                               "where": "sci-fi only", "isDebug": True})
    assert r.status_code == 200
    body = r.json()
    assert body["debug"]["gate_threshold"] == 0.7
    assert body["debug"]["cache"]["want"] == {"book_title": "miss", "genre": "miss"}
    assert body["debug"]["execution"]["engine"] == "core.predicate"
    assert body["interpreted"]["want"]["book_title"]["field"] == "books_view.title"


def test_low_confidence_422_body_carries_debug_when_requested():
    app.dependency_overrides[get_settings] = _query_debug_on
    llm = FakeLLM(want=WANT_OK,
                  where={"where": {"op": "eq", "field": "books_view.category", "value": "x"},
                         "confidence": 0.3})
    c = _client(llm)
    r = c.post("/query", json={"want": {"book_title": None}, "where": "vague",
                               "isDebug": True})
    assert r.status_code == 422
    body = r.json()
    assert body["debug"]["cache"]["where"] == "miss"
    assert body["debug"]["execution"] is None


def test_error_body_omits_debug_key_when_not_requested():
    llm = FakeLLM(want=WANT_OK,
                  where={"where": {"op": "eq", "field": "books_view.category", "value": "x"},
                         "confidence": 0.3})
    c = _client(llm)
    r = c.post("/query", json={"want": {"book_title": None}, "where": "vague"})
    assert r.status_code == 422 and "debug" not in r.json()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/gateway/test_app.py -q`
Expected: the two `_query_debug_on` tests and the 422-carries-debug test FAIL (no `debug` in body); the gate-off test may already pass — fine.

- [ ] **Step 3: Implement**

In `gateway/app.py::create_app`, inside `query()` — after the `violation` check, replace the `run_query` call block:

```python
        debug = raw.debug and settings.enable_query_debug   # config gate: off → isDebug is a no-op
        if debug:
            raw.verbose = True                              # isDebug implies the interpreted echo
        try:
            return run_query(raw, connector, llm, cache,
                             GateConfig(threshold=settings.gate_threshold),
                             limit=settings.result_limit, debug=debug)
        except GatewayError as e:
            content = {"error": e.code, "message": e.message, "interpreted": e.interpreted}
            if e.debug is not None:
                content["debug"] = e.debug
            return JSONResponse(status_code=e.status, content=content)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/gateway/test_app.py -q`
Expected: PASS (all).

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (Postgres tests skip without `TEST_DATABASE_URL`).

- [ ] **Step 6: Commit**

```bash
git add gateway/app.py tests/gateway/test_app.py
git commit -m "feat(gateway): wire isDebug through the config gate; debug in error bodies"
```

---

### Task 8: Playground — send `isDebug`, render the woven panel

**Files:**
- Modify: `playground/lib/api.ts`, `playground/components/InterpretedPanel.tsx`, `playground/app/page.tsx`, `playground/app/globals.css`

No JS test runner in the playground — verification is the type-checking `npm run build` (matches the existing project pattern).

- [ ] **Step 1: Extend `playground/lib/api.ts`**

Add after the `Interpreted` type:

```typescript
export type Debug = {
  gate_threshold: number;
  cache: { want: Record<string, "hit" | "miss">; where?: "hit" | "miss" };
  execution: { engine: string; sql: string | null; params: unknown[] | null } | null;
};
```

Add `debug?: Debug;` to both `QueryResponse` and `QueryError`:

```typescript
export type QueryResponse = {
  rows: Record<string, unknown>[];
  interpreted?: Interpreted;
  debug?: Debug;
};

export type QueryError = {
  error: string;
  message: string;
  interpreted?: Interpreted;
  debug?: Debug;
};
```

In **both** `asCurl` and `runQuery`, extend the body (keep `isVerbose` so the panel still gets `interpreted` from a gate-off/older gateway):

```typescript
  JSON.stringify({ want, where, isVerbose: true, isDebug: true }, ...)
```

(same object in the `fetch` body — the curl echo must stay the exact request).

- [ ] **Step 2: Rewrite `playground/components/InterpretedPanel.tsx`**

```tsx
import { Debug, Interpreted } from "@/lib/api";

function Confidence({ value }: { value: number | null }) {
  if (value === null) return null;
  const cls = value >= 0.9 ? "conf high" : value >= 0.7 ? "conf mid" : "conf low";
  return <span className={cls}>{Math.round(value * 100)}%</span>;
}

function CacheBadge({ status }: { status?: "hit" | "miss" }) {
  if (!status) return null;
  return status === "hit"
    ? <span className="badge hit">CACHE HIT</span>
    : <span className="badge miss">CACHE MISS → LLM</span>;
}

export default function InterpretedPanel(
  { interpreted, debug }: { interpreted: Interpreted; debug?: Debug },
) {
  const gatePct = debug ? Math.round(debug.gate_threshold * 100) : null;
  return (
    <section className="panel interpreted">
      <h2>{debug ? "What the gateway understood — and did" : "What the gateway understood"}</h2>
      <ul>
        {Object.entries(interpreted.want).map(([key, cell]) => (
          <li key={key}>
            <code className="yours">{key}</code>
            {" → "}
            {cell.field
              ? <code className="theirs">{cell.field}</code>
              : <em>declined (not confident enough)</em>}
            <Confidence value={cell.confidence} />
            <CacheBadge status={debug?.cache.want[key]} />
          </li>
        ))}
      </ul>
      {interpreted.where && (
        <div className="where-echo">
          <p>
            <strong>filter:</strong> “{interpreted.where.raw}”
            <Confidence value={interpreted.where.confidence} />
            {gatePct !== null && <span className="gate-note"> (gate: ≥{gatePct}%)</span>}
            <CacheBadge status={debug?.cache.where} />
          </p>
          {interpreted.where.ast == null
            ? <em>(no filter compiled)</em>
            : <pre>{JSON.stringify(interpreted.where.ast, null, 2)}</pre>}
        </div>
      )}
      {debug?.execution?.sql && (
        <div className="sql-echo">
          <h3>SQL the connector ran — values stay bound parameters</h3>
          <pre className="block">
            {debug.execution.sql}
            {"\n-- params: " + JSON.stringify(debug.execution.params)}
          </pre>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Pass the prop in `playground/app/page.tsx`**

Both `InterpretedPanel` usages gain the `debug` prop:

```tsx
          {err.data.interpreted && <InterpretedPanel interpreted={err.data.interpreted} debug={err.data.debug} />}
```

```tsx
          {ok.interpreted && <InterpretedPanel interpreted={ok.interpreted} debug={ok.debug} />}
```

- [ ] **Step 4: Add styles to `playground/app/globals.css`**

Append after the `.conf.low` rule:

```css
.badge {
  display: inline-block;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  border-radius: 4px;
  padding: 0.05rem 0.4rem;
  margin-left: 0.5rem;
  vertical-align: 1px;
}
.badge.hit { background: #d9f2e0; color: var(--good); }
.badge.miss { background: #fdeacc; color: var(--mid); }
.gate-note { color: var(--muted); font-size: 0.8rem; }
.sql-echo h3 { font-size: 0.85rem; margin: 1rem 0 0.4rem; }
```

- [ ] **Step 5: Verify — type-check build**

Run: `cd playground && npm run build`
Expected: build succeeds (this type-checks all four files; a missing `debug` prop or type mismatch fails here).

- [ ] **Step 6: Commit**

```bash
git add playground/lib/api.ts playground/components/InterpretedPanel.tsx playground/app/page.tsx playground/app/globals.css
git commit -m "feat(playground): render debug block woven into the interpreted panel"
```

---

### Task 9: Maintained docs — architecture §1/§6/§8, README, DEPLOY, fly.toml

**Files:**
- Modify: `docs/architecture.md`, `gateway/README.md`, `gateway/DEPLOY.md`, `fly.toml`

- [ ] **Step 1: `docs/architecture.md` §1** — after the `interpreted` echo bullet, add:

```markdown
- `isDebug` (opt-in flag; implies the `interpreted` echo) adds a `debug` block:
  gate threshold, per-`want`-key + `where` resolution-cache hit/miss, and the
  execution trace (engine + parameterized SQL + bound params). Config-gated by
  `ENABLE_QUERY_DEBUG` (default OFF — §6); when the gate is off the flag is
  silently ignored, implication included. On 4xx the block rides alongside
  `interpreted` with `execution: null` (nothing ran); 502s stay bare.
```

- [ ] **Step 2: `docs/architecture.md` §6** — add to the hardening list (after the public-demo guardrails bullet):

```markdown
- **Per-request debug block** (`ENABLE_QUERY_DEBUG`, default OFF) — `POST /query`
  honors `isDebug` only when set: the response gains cache hit/miss, the gate
  threshold, and the parameterized SQL + the caller's own bound values
  (`ExecutionTrace`, filled by the connector during execute). A far narrower
  disclosure than `/debug/*` (the caller's own request only — no samples, no
  query history), but off by default so an own-data operator opts in explicitly.
```

- [ ] **Step 3: `docs/architecture.md` §8 glossary** — the `interpreted` echo entry says "returned only when `isVerbose` is set"; update to:

```markdown
  resolved to + confidence); returned when `isVerbose` (or `isDebug`) is set.
```

- [ ] **Step 4: `gateway/README.md`** — env table (§2) gains a row after `ENABLE_DEBUG_ENDPOINTS`:

```markdown
| `ENABLE_QUERY_DEBUG`     | `0`                      | Honor `isDebug` on `POST /query` (per-request debug block: SQL + params, cache hit/miss, gate threshold) |
```

In §4, after the sentence "`where` is a plain-language filter; `isVerbose` adds the `interpreted` echo.", add:

```markdown
With `ENABLE_QUERY_DEBUG=1`, `isDebug: true` additionally returns a `debug`
block — the parameterized SQL the connector executed, per-field cache
hit/miss, and the confidence-gate threshold. It only ever echoes your own
request's machinery; leave it off on own-data deploys unless you want callers
to see it.
```

- [ ] **Step 5: `fly.toml`** — in `[env]`, after `CORS_ORIGINS`:

```toml
  ENABLE_QUERY_DEBUG = "1"   # playground transparency panel — caller's-own-request disclosure only
```

- [ ] **Step 6: `gateway/DEPLOY.md`** — in the "Operator introspection" section, add a paragraph:

```markdown
The demo sets `ENABLE_QUERY_DEBUG = "1"` (fly.toml) so the playground's
transparency panel works: `isDebug` on `POST /query` returns the caller's own
SQL + cache + gate info. This is per-request-scoped disclosure and safe for the
public demo dataset; it is a different, narrower dial than
`ENABLE_DEBUG_ENDPOINTS`, which stays off.
```

- [ ] **Step 7: Commit**

```bash
git add docs/architecture.md gateway/README.md gateway/DEPLOY.md fly.toml
git commit -m "docs: request-transparency panel — contract, gating, deploy config"
```

---

### Task 10: Devlog + todo (close the loop)

**Files:**
- Modify: `docs/devlog.md`, `todo.md`

- [ ] **Step 1: Devlog entry** — add a newest-on-top `## v0.5.0 — Playground request-transparency panel (YYYY-MM-DD HH:MM)` entry (timestamp from `git log -1 --format=%ci` of the docs commit in Task 9), following the house format:

```markdown
## v0.5.0 — Playground request-transparency panel (YYYY-MM-DD HH:MM)

**Review:** not yet

**Design docs:**
- Request-Transparency Panel: [Spec](superpowers/specs/2026-07-13-request-transparency-panel-design.md) [Plan](superpowers/plans/2026-07-13-request-transparency-panel.md)

**What was built:**
- `isDebug` flag on `POST /query` → `debug` block (gate threshold, per-key +
  where cache hit/miss, execution trace), gated by `ENABLE_QUERY_DEBUG`
  (default OFF; demo deploy sets it on in `fly.toml`).
- `ExecutionTrace` through the connector seam — Postgres records the
  parameterized SQL it actually ran (`as_string(conn)`); the fake reports
  `core.predicate`. `_accepts_limit` generalized to `_execute_kwargs`.
- Debug block rides on 4xx alongside `interpreted` (`execution: null`); 502s bare.
- Playground: cache badges + gate note + SQL box woven into `InterpretedPanel`;
  graceful absence when the gate is off.

**Key technical learnings:**
- `[note]` psycopg's `Composable.as_string()` needs the live connection for
  exact identifier quoting — recording the SQL inside `execute` (trace pattern)
  gets it free; an `explain()`-style second compile would not.
- (add any further learnings observed during implementation; keep the tag
  convention — `[note]` / `[insight]` / `[gotcha]`)
```

Update the TL;DR table at the top of `docs/devlog.md` with a linked `v0.5.0` row (GitHub-style anchor, matching the existing rows).

- [ ] **Step 2: `todo.md`** — mark the "Playground request-transparency panel" item `[x]` with a one-line "built as v0.5.0 (see the devlog top row)" summary, and add the remaining operator steps as sub-items:

```markdown
  - [ ] **Deploy:** `fly deploy` (picks up `ENABLE_QUERY_DEBUG` from fly.toml;
        scale back to 1 machine if the deploy re-adds an HA second machine) and
        redeploy the playground on Vercel (new bundle sends `isDebug`).
        Verify: run a chip twice — panel shows SQL + miss→hit flip.
```

- [ ] **Step 3: Commit**

```bash
git add docs/devlog.md todo.md
git commit -m "docs(devlog+todo): v0.5.0 request-transparency panel"
```

---

### Task 11: Final verification

- [ ] **Step 1: Full suite**

Run: `python -m pytest tests/ -q` — expected: all pass (Postgres tests skip without `TEST_DATABASE_URL`; run them with a local DSN if available).

- [ ] **Step 2: Playground build**

Run: `cd playground && npm run build` — expected: success.

- [ ] **Step 3: Live smoke (optional, needs local Postgres + `GEMINI_API_KEY`)**

Start the gateway with `ENABLE_QUERY_DEBUG=1`, POST a query with `isDebug: true` twice, and confirm: `debug.execution.sql` is parameterized (`%s`, no inlined values), and `cache` flips miss→hit on the second call.
