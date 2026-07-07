# First Gateway Slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Consulted before writing:** `docs/specs/2026-07-first-gateway-slice.md` (the agreed spec),
`docs/architecture.md` (maintained law), `docs/system-design.md` (component map),
`todo.md`, and the spike source (`spike/resolver.py`, `spike/llm.py`, `spike/prompts.py`,
`spike/schemas.py`, `spike/score.py`, `spike/cases.py`).

**Goal:** Build the smallest end-to-end gateway that proves the concept — one JSON
`{want, where}` request → resolve fields + compile the filter to a validated AST →
execute against Postgres → return rows in the client's own keys — by lifting the
de-risked spike resolver into a shared `core/`, not rebuilding it.

**Architecture:** Two-sided hourglass (spec §5). A JSON `RequestAdapter` emits `RawQuery`;
the resolver (lifted into `core/`) resolves `want` fields + compiles `where` to a validated
predicate AST; a confidence gate declines low-confidence fields and refuses low-confidence
filters; the assembled `CanonicalQueryIR` is executed by a `Connector` (real Postgres +
a fake in-memory twin for the seam test). Two in-memory resolution caches (field + where)
skip the LLM on repeats.

**Tech Stack:** Python 3.9 · FastAPI + uvicorn · LiteLLM (`gemini/gemini-3.1-flash-lite`
default) · psycopg 3 (Postgres) · pytest. Container-portable (one `Dockerfile`).

**Locked decisions honored (root `CLAUDE.md`):** request contract `{want,where}`;
NL → validated AST → execute (never NL → SQL); `validate_ast` is the injection boundary;
gate threshold 0.7 on both sides; prompt-cache layout stable-first; start on
`gemini-3.1-flash-lite` behind the `LLM` interface; lift the spike resolver into `core/`.

---

## File Structure

Target layout (spec §8). New files unless marked *(moved)*.

```
pyproject.toml            # NEW — makes core / gateway / spike importable (editable install)
Dockerfile                # NEW — container-portable serve
core/
  __init__.py             # NEW
  llm.py                  # (moved from spike/llm.py, unchanged)
  prompts.py              # (moved from spike/prompts.py) + where prompt emits a confidence
  schemas.py              # (moved) TYPES ONLY — Field, Schema, as_prompt; no instances
  resolver.py             # (moved) + where_resolve() returning {ast, confidence}
  predicate.py            # NEW — in-memory AST evaluator (lifted from spike/score.py matcher)
gateway/
  __init__.py             # NEW
  config.py               # NEW — env-driven Settings
  contracts.py            # NEW — RawQuery, ResolvedField, CanonicalQueryIR
  gate.py                 # NEW — GateConfig, gate_want, where_passes
  cache.py                # NEW — normalization + ResolutionCache (field + where dicts)
  pipeline.py             # NEW — the 10-step flow, GatewayError
  app.py                  # NEW — FastAPI, POST /query, JSON RequestAdapter
  connectors/
    __init__.py           # NEW
    base.py               # NEW — Connector Protocol, Capabilities, schema_version()
    fake.py               # NEW — in-memory connector (seam test)
    postgres.py           # NEW — introspect + compile AST → SQL
  demo/
    __init__.py           # NEW
    seed.sql              # NEW — normalized tables + denormalized VIEW (source of truth)
    rows.py               # NEW — in-memory mirror of the view for the fake connector
  README.md               # NEW — copy-paste quickstart
spike/
  llm.py, prompts.py, resolver.py   # DELETED (moved to core/)
  schemas.py              # keeps BOOKS/ECOMMERCE/HR/STREAMING instances; imports types from core
  score.py                # imports resolver/llm/prompts from core; matcher from core.predicate
  cases.py                # unchanged
tests/
  __init__.py
  fakes.py                # FakeLLM
  core/test_where_confidence.py
  gateway/test_gate.py
  gateway/test_cache.py
  gateway/test_remap.py
  gateway/test_fake_connector.py
  gateway/test_pipeline.py
  gateway/test_app.py
  gateway/conftest.py     # pg_connector fixture (skips without TEST_DATABASE_URL)
  gateway/test_seam_parity.py
  live/test_live_smoke.py # skipped unless RUN_LIVE_LLM=1
```

**Decision — `core/predicate.py` (a small addition beyond the spec's listed core files):**
the fake connector must filter rows in-memory with the *same* semantics the spike scorer
trusts for execution equivalence. Rather than duplicate that matcher, lift `spike/score.py`'s
`_norm`/`_match`/`_selected` into `core/predicate.py` and have both the fake connector and the
spike scorer import it. This is DRY and makes the seam parity test meaningful (Postgres is
asserted to agree with the exact oracle the eval uses). Log this in the devlog as a conscious
core addition.

---

## Task 1: Packaging + lift the spike resolver into `core/`

Moves the four reusable spike modules into a shared `core/` package that both the gateway
and the spike import (spec §8 — one copy, no drift). No behavior change yet.

**Files:**
- Create: `pyproject.toml`, `core/__init__.py`
- Move: `spike/llm.py` → `core/llm.py`, `spike/prompts.py` → `core/prompts.py`,
  `spike/resolver.py` → `core/resolver.py`
- Create: `core/schemas.py` (types only)
- Modify: `spike/schemas.py` (drop the type defs, import from core), `spike/score.py` (imports)
- Test: `tests/__init__.py`, `tests/test_packaging.py`

- [ ] **Step 1: Write the failing test**

`tests/test_packaging.py`:
```python
def test_core_exports_resolver_and_types():
    from core.resolver import resolve_want, where_ast, parse_where, validate_ast
    from core.schemas import Schema, Field
    from core.llm import LLM, LiteLLM
    from core.prompts import want_system, where_system, OPS
    assert "eq" in OPS

def test_spike_still_imports_and_reuses_core_types():
    from spike.schemas import BOOKS, ALL_SCHEMAS
    from core.schemas import Schema
    assert isinstance(BOOKS, Schema)
    assert set(ALL_SCHEMAS) == {"library", "shop", "hr", "streaming"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_packaging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core'`

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "sans-schema"
version = "0.1.0"
description = "Semantic Query Gateway — first gateway slice"
requires-python = ">=3.9"
dependencies = [
    "litellm>=1.40",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "psycopg[binary]>=3.1",
]

[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]

[tool.setuptools]
packages = ["core", "gateway", "gateway.connectors", "gateway.demo", "spike"]

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]
```

- [ ] **Step 4: Move the modules and split the types out of `schemas.py`**

```bash
git mv spike/llm.py core/llm.py
git mv spike/prompts.py core/prompts.py
git mv spike/resolver.py core/resolver.py
touch core/__init__.py tests/__init__.py
```

Create `core/schemas.py` with **only** the `Field`/`Schema` types (copy lines 1–42 of the
old `spike/schemas.py` — the module docstring, imports, and both dataclasses through
`as_prompt`). Do **not** include `BOOKS`/`ECOMMERCE`/`HR`/`STREAMING`/`ALL_SCHEMAS`.

Then rewrite `spike/schemas.py` so it imports the types from core and keeps only the
instances. Replace its header (old lines 17–42, the imports + both dataclasses) with:
```python
from __future__ import annotations

from typing import Dict

from core.schemas import Field, Schema
```
Leave everything from `BOOKS = Schema(` onward untouched (including the final
`ALL_SCHEMAS: Dict[str, Schema] = {...}`).

`core/resolver.py` keeps its relative imports (`from .llm import ...`, `from .prompts import
...`, `from .schemas import Schema`) — they resolve within `core/` unchanged.

- [ ] **Step 5: Update `spike/score.py` imports to point at core**

In `spike/score.py`, change lines 16–18 from `.llm` / `.prompts` / `.resolver` to core:
```python
from core.llm import LiteLLM, LLM
from core.prompts import want_system, want_user, where_system, where_user
from core.resolver import resolve_want, validate_ast, where_ast
```
Leave `from .cases import CASES, TODAY, Case` and `from .schemas import ALL_SCHEMAS` as-is.

- [ ] **Step 6: Install editable + run tests**

Run: `python -m pip install -e ".[dev]" && python -m pytest tests/test_packaging.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Confirm the spike still wires up (no API calls)**

Run: `python -m spike.score --show-prompts | head -5`
Expected: prints the assembled prompt banner (proves core+spike imports resolve end-to-end).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml core/ spike/schemas.py spike/score.py tests/__init__.py tests/test_packaging.py
git commit -m "refactor: lift spike resolver into shared core/ package"
```

---

## Task 2: Lift the AST matcher into `core/predicate.py`

The fake connector and the spike scorer need one shared in-memory predicate evaluator
(execution-equivalence semantics). Lift it out of `spike/score.py` so there is a single copy.

**Files:**
- Create: `core/predicate.py`, `tests/core/__init__.py`, `tests/core/test_predicate.py`
- Modify: `spike/score.py` (import matcher from core, delete the local copy)

- [ ] **Step 1: Write the failing test**

`tests/core/test_predicate.py`:
```python
from core.predicate import matches, select_indices

ROWS = [
    {"category": "Science Fiction", "price": 24.0, "published_at": "2026-05-10"},
    {"category": "Fantasy", "price": 9.99, "published_at": "1968-01-01"},
    {"category": "Science Fiction", "price": 30.0, "published_at": "2025-11-20"},
]

def test_eq_and_numeric_and_date_normalization():
    ast = {"op": "and", "clauses": [
        {"op": "eq", "field": "category", "value": "Science Fiction"},
        {"op": "gte", "field": "price", "value": "20"},          # string vs float
    ]}
    assert select_indices(ast, ROWS) == frozenset({0, 2})

def test_between_dates_and_not():
    ast = {"op": "not", "clause": {"op": "between", "field": "published_at",
                                   "value": ["2026-01-01", "2026-12-31"]}}
    assert select_indices(ast, ROWS) == frozenset({1, 2})

def test_in_and_is_null_and_contains():
    rows = [{"status": None, "name": "Wireless Mouse"}, {"status": "shipped", "name": "Desk Lamp"}]
    assert select_indices({"op": "is_null", "field": "status"}, rows) == frozenset({0})
    assert select_indices({"op": "contains", "field": "name", "value": "mouse"}, rows) == frozenset({0})
    assert matches({"op": "in", "field": "status", "value": ["shipped", "delivered"]}, rows[1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_predicate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.predicate'`

- [ ] **Step 3: Create `core/predicate.py`**

Move the matcher out of `spike/score.py` (its lines 100–194: `_parse_dt`, `_norm`, `_match`,
`_selected`, `score_where`) into this module, renaming the two public helpers. `matches`/
`select_indices` keep the exact semantics; `score_where` stays here too (the scorer imports it).

```python
"""In-memory predicate-AST evaluator — the execution-equivalence engine.

Two ASTs are semantically equal iff they select the same rows. This is the shared
oracle: the fake connector filters rows with it, and the spike scorer compares row
sets with it, so a Postgres connector can be asserted equal to the same semantics.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def _parse_dt(s: str):
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _norm(v: Any) -> Any:
    """Normalize so equal-meaning values compare equal regardless of representation
    (int vs "2026", bool vs "true", date vs datetime). bool before number: bool is
    an int subclass."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        dt = _parse_dt(s)
        if dt is not None:
            return dt
        low = s.lower()
        if low in ("true", "false"):
            return low == "true"
        try:
            return float(s)
        except ValueError:
            return low
    return v


def matches(node: Dict[str, Any], row: Dict[str, Any]) -> bool:
    op = node.get("op")
    if op == "and":
        return all(matches(c, row) for c in node.get("clauses", []))
    if op == "or":
        return any(matches(c, row) for c in node.get("clauses", []))
    if op == "not":
        return not matches(node["clause"], row)

    raw = row.get(node.get("field"))
    val = node.get("value")
    lv = _norm(raw)
    rv = [_norm(x) for x in val] if isinstance(val, list) else _norm(val)

    if op == "eq":
        return lv == rv
    if op == "ne":
        return lv != rv
    if op == "in":
        return lv in rv
    if op == "nin":
        return lv not in rv
    if op == "is_null":
        return raw is None
    if op == "contains":
        return isinstance(lv, str) and isinstance(rv, str) and rv in lv
    if op == "between":
        lo, hi = rv[0], rv[1]
        try:
            return lo <= lv <= hi
        except TypeError:
            return False
    try:
        if op == "gt":
            return lv > rv
        if op == "gte":
            return lv >= rv
        if op == "lt":
            return lv < rv
        if op == "lte":
            return lv <= rv
    except TypeError:
        return False
    return False


def select_indices(ast: Dict[str, Any], rows: List[Dict[str, Any]]) -> frozenset:
    return frozenset(i for i, r in enumerate(rows) if matches(ast, r))


def score_where(expected: Optional[Dict[str, Any]], got: Optional[Dict[str, Any]],
                rows: List[Dict[str, Any]]) -> bool:
    if expected is None:
        return got is None
    if got is None:
        return False
    try:
        return select_indices(expected, rows) == select_indices(got, rows)
    except Exception:  # noqa: BLE001
        return False
```

Create empty `tests/core/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_predicate.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Point `spike/score.py` at the shared matcher**

In `spike/score.py`: delete its local matcher block (old lines 95–195: the
`# --- execution equivalence ---` comment through `score_where`, **including** the
`from datetime import datetime` on line 100). Add to the import block near the top:
```python
from core.predicate import select_indices as _selected, score_where
```
`where_debug` calls `_selected(...)` — that alias keeps it working. Confirm no other
local references to `_match`/`_norm`/`_parse_dt` remain (`grep -n "_match\|_norm\|_parse_dt" spike/score.py` → no hits).

- [ ] **Step 6: Verify the spike harness still assembles**

Run: `python -m pytest tests/core/test_predicate.py -v && python -m spike.score --show-prompts | tail -3`
Expected: tests PASS; prompts print (spike imports still resolve).

- [ ] **Step 7: Commit**

```bash
git add core/predicate.py spike/score.py tests/core/__init__.py tests/core/test_predicate.py
git commit -m "refactor: share the AST matcher via core/predicate"
```

---

## Task 3: Add `where` confidence to the resolver (the one v1 resolver change)

Spec §7: the `where` output gains a confidence score. Add it non-invasively — `where_ast`
(used by the frozen eval) keeps its signature; a new `where_resolve` returns `{ast, confidence}`.

**Files:**
- Modify: `core/prompts.py` (where prompt emits `confidence`), `core/resolver.py` (add `where_resolve`)
- Test: `tests/core/test_where_confidence.py`, `tests/fakes.py`

- [ ] **Step 1: Write the FakeLLM + failing test**

`tests/fakes.py`:
```python
from typing import Any, Dict, Optional
from core.llm import LLM


class FakeLLM(LLM):
    """Routes by system-prompt content: want vs where. Canned JSON, no network.
    Pass `fail_times` to simulate transient errors (for retry tests)."""

    def __init__(self, want: Optional[Dict[str, Any]] = None,
                 where: Optional[Dict[str, Any]] = None, fail_times: int = 0):
        self.name = "fake"
        self._want = want or {"mapping": {}}
        self._where = where or {"where": None, "confidence": 0.0}
        self._fail_times = fail_times
        self.calls = 0

    def json(self, system: str, user: str) -> Dict[str, Any]:
        self.calls += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("simulated LLM failure")
        return self._where if "natural-language filter" in system else self._want
```

`tests/core/test_where_confidence.py`:
```python
from core.resolver import where_resolve, where_ast, WhereResult
from core.schemas import Schema, Field
from tests.fakes import FakeLLM

SCHEMA = Schema("demo", [Field("book.category", "text", "genre", ["Science Fiction"])])
CANNED = {"where": {"op": "eq", "field": "book.category", "value": "Science Fiction"},
          "confidence": 0.88}

def test_where_resolve_returns_ast_and_confidence():
    r = where_resolve(FakeLLM(where=CANNED), SCHEMA, "sci-fi only", "2026-07-06")
    assert isinstance(r, WhereResult)
    assert r.ast == CANNED["where"]
    assert r.confidence == 0.88

def test_where_ast_still_returns_bare_ast():
    ast = where_ast(FakeLLM(where=CANNED), SCHEMA, "sci-fi only", "2026-07-06")
    assert ast == CANNED["where"]

def test_missing_confidence_defaults_to_none():
    r = where_resolve(FakeLLM(where={"where": None}), SCHEMA, "x", "2026-07-06")
    assert r.ast is None and r.confidence is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/core/test_where_confidence.py -v`
Expected: FAIL — `ImportError: cannot import name 'where_resolve'`

- [ ] **Step 3: Make the where prompt ask for a confidence**

In `core/prompts.py`, replace the final `Respond as JSON` line of `where_system` (old line 127)
with a version that requests confidence alongside the AST:
```python
        "Also return a confidence 0.0-1.0 that the compiled AST faithfully "
        "captures the filter's intent against THIS schema (lower it when a value, "
        "field, or relative date is uncertain).\n"
        "Respond as JSON with the AST under key \"where\" and the score under key "
        "\"confidence\": {\"where\": { ... }, \"confidence\": 0.0}"
        + hints.block("where")
```
(Keep the whole example block and everything above it byte-identical — the eval measures this
prompt, so only the output-shape instruction changes.)

- [ ] **Step 4: Add `WhereResult` + `where_resolve` to `core/resolver.py`**

Add `from dataclasses import dataclass` to the imports. Replace the existing `where_ast`
(old lines 33–38) with a shared internal call plus the two public entry points:
```python
@dataclass
class WhereResult:
    ast: Optional[Dict[str, Any]]          # raw, UNVALIDATED predicate AST (or None)
    confidence: Optional[float]            # None when the model omitted it


def _where_call(llm: LLM, schema: Schema, nl: str, today: str,
                hints: DomainHints = NO_HINTS) -> Dict[str, Any]:
    return llm.json(where_system(hints), where_user(schema.as_prompt(), nl, today))


def where_ast(llm: LLM, schema: Schema, nl: str, today: str,
              hints: DomainHints = NO_HINTS) -> Optional[Dict[str, Any]]:
    """Raw predicate AST only (UNVALIDATED). Used by the frozen spike eval."""
    return _where_call(llm, schema, nl, today, hints).get("where")


def where_resolve(llm: LLM, schema: Schema, nl: str, today: str,
                  hints: DomainHints = NO_HINTS) -> WhereResult:
    """AST + filter confidence. The gateway's entry point (spec §7)."""
    out = _where_call(llm, schema, nl, today, hints)
    conf = out.get("confidence")
    return WhereResult(ast=out.get("where"),
                       confidence=float(conf) if isinstance(conf, (int, float)) else None)
```
Leave `parse_where` and `validate_ast` unchanged (they still call `where_ast`).

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/core/test_where_confidence.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add core/prompts.py core/resolver.py tests/fakes.py tests/core/test_where_confidence.py
git commit -m "feat(core): where_resolve returns a filter confidence"
```

---

## Task 4: Gateway contracts

The two load-bearing shapes (spec §3) plus `ResolvedField`. Pure dataclasses.

**Files:**
- Create: `gateway/__init__.py`, `gateway/contracts.py`, `tests/gateway/__init__.py`, `tests/gateway/test_contracts.py`

- [ ] **Step 1: Write the failing test**

`tests/gateway/test_contracts.py`:
```python
from gateway.contracts import RawQuery, ResolvedField, CanonicalQueryIR

def test_rawquery_defaults():
    q = RawQuery(want=["title", "writer"], where="sci-fi", today="2026-07-06")
    assert q.verbose is False and q.want == ["title", "writer"]

def test_ir_carries_select_and_predicate():
    ir = CanonicalQueryIR(
        select=[ResolvedField("writer", "author.name", 0.95),
                ResolvedField("bogus", None, 0.10)],
        predicate={"op": "eq", "field": "book.category", "value": "Science Fiction"},
        where_confidence=0.88, where_raw="sci-fi only")
    assert ir.select[1].field_path is None
    assert ir.where_confidence == 0.88
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/gateway/test_contracts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway'`

- [ ] **Step 3: Create the contracts**

`gateway/__init__.py`: empty. `tests/gateway/__init__.py`: empty.

`gateway/contracts.py`:
```python
"""The hourglass's narrow waist — the two load-bearing contracts (spec §3).

RawQuery (ingress → core): unresolved, client vocabulary.
CanonicalQueryIR (core → egress): resolved, backend-agnostic — zero SQL specifics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class RawQuery:
    want: List[str]                  # client field names, in request order
    where: Optional[str]             # NL filter, or None
    today: str                       # ISO date for relative-date resolution (per-call)
    verbose: bool = False            # include the `interpreted` echo


@dataclass
class ResolvedField:
    client_key: str                  # maps results back to client vocab
    field_path: Optional[str]        # resolved backend path, or None if the gate declined it
    confidence: float


@dataclass
class CanonicalQueryIR:
    select: List[ResolvedField]      # resolved `want`, in request order
    predicate: Optional[dict]        # validated AST, or None
    where_confidence: Optional[float]  # None when no `where`
    where_raw: Optional[str]         # original NL filter, for the echo
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/gateway/test_contracts.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add gateway/__init__.py gateway/contracts.py tests/gateway/__init__.py tests/gateway/test_contracts.py
git commit -m "feat(gateway): RawQuery / CanonicalQueryIR / ResolvedField contracts"
```

---

## Task 5: Confidence gate

Spec §7. One threshold (default 0.7) on both sides: `want` below → `field_path=None`
(still a null column); `where` below → the pipeline will 422.

**Files:**
- Create: `gateway/gate.py`, `tests/gateway/test_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/gateway/test_gate.py`:
```python
from gateway.gate import GateConfig, gate_want, where_passes

MAPPING = {
    "writer": {"field": "author.name", "confidence": 0.95},
    "genre":  {"field": "book.category", "confidence": 0.60},   # below 0.7 → declined
    "bogus":  {"field": None, "confidence": 0.0},
}

def test_gate_want_preserves_order_and_declines_low_confidence():
    cfg = GateConfig(threshold=0.7)
    got = gate_want(["writer", "genre", "bogus"], MAPPING, cfg)
    assert [f.client_key for f in got] == ["writer", "genre", "bogus"]
    assert got[0].field_path == "author.name"
    assert got[1].field_path is None and got[1].confidence == 0.60   # confidence retained
    assert got[2].field_path is None

def test_missing_key_becomes_declined_zero_confidence():
    got = gate_want(["ghost"], {}, GateConfig())
    assert got[0].field_path is None and got[0].confidence == 0.0

def test_where_passes():
    cfg = GateConfig(threshold=0.7)
    assert where_passes(0.88, cfg) is True
    assert where_passes(0.60, cfg) is False
    assert where_passes(None, cfg) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/gateway/test_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.gate'`

- [ ] **Step 3: Implement the gate**

`gateway/gate.py`:
```python
"""Confidence gate (spec §7). Threshold applied at READ time so changing it never
invalidates a cache (caches store raw confidence)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from gateway.contracts import ResolvedField


@dataclass
class GateConfig:
    threshold: float = 0.7


def gate_want(want_keys: List[str], mapping: Dict[str, Any],
              cfg: GateConfig) -> List[ResolvedField]:
    """One ResolvedField per key, in request order. Below threshold or no field →
    field_path=None (declined, not dropped — still a null column downstream)."""
    out: List[ResolvedField] = []
    for key in want_keys:
        cell = mapping.get(key) or {}
        field = cell.get("field")
        raw_conf = cell.get("confidence", 0.0)
        conf = float(raw_conf) if isinstance(raw_conf, (int, float)) else 0.0
        resolved = field if (field is not None and conf >= cfg.threshold) else None
        out.append(ResolvedField(client_key=key, field_path=resolved, confidence=conf))
    return out


def where_passes(confidence: Optional[float], cfg: GateConfig) -> bool:
    return confidence is not None and confidence >= cfg.threshold
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/gateway/test_gate.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add gateway/gate.py tests/gateway/test_gate.py
git commit -m "feat(gateway): confidence gate (want decline + where pass check)"
```

---

## Task 6: Resolution cache

Spec §6: two independent caches (field + where), per-key/per-phrase, behind a `CacheStore`
interface, storing **raw** `{field/ast, confidence}` (gate applied later).

**Files:**
- Create: `gateway/cache.py`, `tests/gateway/test_cache.py`

- [ ] **Step 1: Write the failing test**

`tests/gateway/test_cache.py`:
```python
from gateway.cache import ResolutionCache, normalize_key, normalize_phrase

def test_normalization_collapses_case_and_whitespace():
    assert normalize_key("  Release   Date ") == "release date"
    assert normalize_phrase("Sci-Fi   ONLY") == "sci-fi only"

def test_field_cache_hit_and_miss():
    c = ResolutionCache()
    assert c.get_field("pg", "v1", "writer") is None
    c.set_field("pg", "v1", "writer", {"field": "author.name", "confidence": 0.9})
    assert c.get_field("pg", "v1", "Writer") == {"field": "author.name", "confidence": 0.9}
    assert c.get_field("pg", "v2", "writer") is None          # schema_version scopes the key
    assert c.get_field("other", "v1", "writer") is None       # backend scopes the key

def test_where_cache_keys_on_today():
    c = ResolutionCache()
    c.set_where("pg", "v1", "published this year", "2026-07-06",
                {"ast": {"op": "eq"}, "confidence": 0.8})
    assert c.get_where("pg", "v1", "published this year", "2026-07-06")["confidence"] == 0.8
    assert c.get_where("pg", "v1", "published this year", "2026-07-07") is None   # next day misses
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/gateway/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.cache'`

- [ ] **Step 3: Implement the cache**

`gateway/cache.py`:
```python
"""Two-part resolution cache (spec §6). Per-key and per-phrase, never per-whole-request.
In-memory dicts behind a CacheStore Protocol so Redis / semantic lookup swap in later.
Stores RAW {field/ast, confidence}; the gate is applied at read time by the pipeline."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore


def normalize_key(s: str) -> str:
    return " ".join(s.strip().lower().split())


normalize_phrase = normalize_key  # same rule for v1; kept distinct for future divergence


class CacheStore(Protocol):
    def get(self, key: Tuple) -> Optional[Dict[str, Any]]: ...
    def set(self, key: Tuple, value: Dict[str, Any]) -> None: ...


class DictCache:
    """In-memory CacheStore. Swap for Redis behind this same interface."""

    def __init__(self) -> None:
        self._d: Dict[Tuple, Dict[str, Any]] = {}

    def get(self, key: Tuple) -> Optional[Dict[str, Any]]:
        return self._d.get(key)

    def set(self, key: Tuple, value: Dict[str, Any]) -> None:
        self._d[key] = value


class ResolutionCache:
    """The field cache + the where cache, together."""

    def __init__(self, field_store: Optional[CacheStore] = None,
                 where_store: Optional[CacheStore] = None) -> None:
        self._field = field_store or DictCache()
        self._where = where_store or DictCache()

    # field cache: (backend, schema_version, normalized_key)
    def get_field(self, backend: str, sv: str, key: str) -> Optional[Dict[str, Any]]:
        return self._field.get((backend, sv, normalize_key(key)))

    def set_field(self, backend: str, sv: str, key: str, value: Dict[str, Any]) -> None:
        self._field.set((backend, sv, normalize_key(key)), value)

    # where cache: (backend, schema_version, normalized_phrase, today)
    def get_where(self, backend: str, sv: str, phrase: str, today: str) -> Optional[Dict[str, Any]]:
        return self._where.get((backend, sv, normalize_phrase(phrase), today))

    def set_where(self, backend: str, sv: str, phrase: str, today: str,
                  value: Dict[str, Any]) -> None:
        self._where.set((backend, sv, normalize_phrase(phrase), today), value)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/gateway/test_cache.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add gateway/cache.py tests/gateway/test_cache.py
git commit -m "feat(gateway): two-part resolution cache (field + where)"
```

---

## Task 7: Connector base + fake connector + demo mirror

Spec §4, §9. The `Connector` Protocol, `schema_version()`, and the fake in-memory connector
(the seam-test twin) over the demo mirror rows.

**Files:**
- Create: `gateway/connectors/__init__.py`, `gateway/connectors/base.py`,
  `gateway/connectors/fake.py`, `gateway/demo/__init__.py`, `gateway/demo/rows.py`
- Test: `tests/gateway/test_fake_connector.py`

- [ ] **Step 1: Write the failing test**

`tests/gateway/test_fake_connector.py`:
```python
from gateway.connectors.base import schema_version, Capabilities
from gateway.connectors.fake import FakeConnector
from gateway.contracts import CanonicalQueryIR, ResolvedField

def test_describe_exposes_the_view_columns():
    c = FakeConnector()
    schema = c.describe()
    paths = {f.path for f in schema.fields}
    assert {"title", "category", "price", "author_name"} <= paths
    assert c.backend_id == "fake"
    assert isinstance(c.capabilities(), Capabilities)

def test_schema_version_is_stable_and_field_sensitive():
    c = FakeConnector()
    assert schema_version(c.describe()) == schema_version(c.describe())

def test_execute_filters_and_keys_by_field_path():
    c = FakeConnector()
    ir = CanonicalQueryIR(
        select=[ResolvedField("book_title", "title", 0.9),
                ResolvedField("genre", "category", 0.9)],
        predicate={"op": "eq", "field": "category", "value": "Science Fiction"},
        where_confidence=0.9, where_raw="sci-fi")
    rows = c.execute(ir)
    assert rows and all(r["category"] == "Science Fiction" for r in rows)
    assert set(rows[0]) == {"title", "category"}          # only selected paths, keyed by path
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/gateway/test_fake_connector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.connectors'`

- [ ] **Step 3: Create the demo mirror + field metadata**

`gateway/demo/__init__.py`: empty.

`gateway/demo/rows.py` — the denormalized-view mirror (spec §9). Columns and rows MUST match
`seed.sql`'s view (Task 9); a parity test guards the two. Field metadata mirrors what Postgres
introspection would emit (name, type, description, samples).
```python
"""In-memory mirror of the demo denormalized view (spec §9).

SOURCE OF TRUTH for the demo DATA is gateway/demo/seed.sql; this mirror exists for
the fake connector (seam test). A parity test (test_seam_parity) asserts the two agree.
Keep the column set and rows identical to seed.sql's `books_view`."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# (path, type, description, samples) — the shape describe() emits for each column.
VIEW_FIELDS: List[Tuple[str, str, str, List[str]]] = [
    ("book_id",     "integer", "primary key of the book record", []),
    ("title",       "text",    "the title of the book", ["A Wizard of Earthsea"]),
    ("category",    "text",    "genre / subject classification",
        ["Science Fiction", "Fantasy", "Non-Fiction"]),
    ("published_at","date",    "date the book was published", ["1968-01-01", "2026-03-01"]),
    ("price",       "numeric", "retail price in USD", ["9.99", "24.00"]),
    ("page_count",  "integer", "number of pages", ["205", "500"]),
    ("language",    "text",    "language the book is written in", ["en", "fr"]),
    ("author_id",   "integer", "primary key of the author record", []),
    ("author_name", "text",    "full name of the person who wrote the book",
        ["Ursula K. Le Guin"]),
    ("birth_year",  "integer", "year the author was born", ["1929"]),
    ("country",     "text",    "author's country of origin", ["USA", "UK"]),
]

VIEW_ROWS: List[Dict[str, Any]] = [
    {"book_id": 1, "title": "A Wizard of Earthsea", "category": "Fantasy",
     "published_at": "1968-01-01", "price": 9.99, "page_count": 205, "language": "en",
     "author_id": 1, "author_name": "Ursula K. Le Guin", "birth_year": 1929, "country": "USA"},
    {"book_id": 2, "title": "Future Shock 2026", "category": "Science Fiction",
     "published_at": "2026-03-01", "price": 15.00, "page_count": 350, "language": "en",
     "author_id": 2, "author_name": "SansWord", "birth_year": 1985, "country": "USA"},
    {"book_id": 3, "title": "The Long Orbit", "category": "Science Fiction",
     "published_at": "2026-05-10", "price": 24.00, "page_count": 500, "language": "en",
     "author_id": 3, "author_name": "R. Novak", "birth_year": 1970, "country": "UK"},
    {"book_id": 4, "title": "Vieux Roman", "category": "Non-Fiction",
     "published_at": "2010-01-01", "price": 12.00, "page_count": 280, "language": "fr",
     "author_id": 4, "author_name": "Old Writer", "birth_year": 1940, "country": "France"},
    {"book_id": 5, "title": "Orbit of Dreams", "category": "Science Fiction",
     "published_at": "2025-11-20", "price": 30.00, "page_count": 420, "language": "en",
     "author_id": 5, "author_name": "A. Blake", "birth_year": 1960, "country": "UK"},
    {"book_id": 6, "title": "Silent Fields", "category": "Non-Fiction",
     "published_at": "2026-01-15", "price": 18.50, "page_count": 300, "language": "en",
     "author_id": 6, "author_name": "M. Ito", "birth_year": 1988, "country": "Japan"},
]
```

- [ ] **Step 4: Create the connector base**

`gateway/connectors/__init__.py`: empty.

`gateway/connectors/base.py`:
```python
"""Egress interface (spec §4). One Connector per backend. schema_version() is a stable
hash of describe() output — computed once per process (refresh on restart; drift
invalidation deferred, spec §6)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List

from core.schemas import Schema
from gateway.contracts import CanonicalQueryIR

try:
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol, runtime_checkable  # type: ignore


@dataclass
class Capabilities:
    """Static declaration only — no pushdown-negotiation planner consumes it in v1."""
    pushdown_filter: bool = True


@runtime_checkable
class Connector(Protocol):
    backend_id: str
    def describe(self) -> Schema: ...
    def execute(self, ir: CanonicalQueryIR) -> List[dict]: ...
    def capabilities(self) -> Capabilities: ...


def schema_version(schema: Schema) -> str:
    """Stable hash over field path|type|description — order-independent."""
    parts = sorted(f"{f.path}|{f.type}|{f.description}" for f in schema.fields)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
```

- [ ] **Step 5: Create the fake connector**

`gateway/connectors/fake.py`:
```python
"""Fake in-memory connector — the seam-test twin (spec §4, §9). Filters the demo mirror
rows with core.predicate (the same oracle the spike scorer trusts), so a Postgres connector
can be asserted equal to it."""
from __future__ import annotations

from typing import List

from core.predicate import matches
from core.schemas import Field, Schema
from gateway.connectors.base import Capabilities
from gateway.contracts import CanonicalQueryIR
from gateway.demo.rows import VIEW_FIELDS, VIEW_ROWS


class FakeConnector:
    backend_id = "fake"

    def describe(self) -> Schema:
        fields = [Field(path=p, type=t, description=d, samples=list(s))
                  for (p, t, d, s) in VIEW_FIELDS]
        return Schema(name="books_view", fields=fields, rows=list(VIEW_ROWS))

    def execute(self, ir: CanonicalQueryIR) -> List[dict]:
        paths = [f.field_path for f in ir.select if f.field_path is not None]
        selected = VIEW_ROWS if ir.predicate is None else \
            [r for r in VIEW_ROWS if matches(ir.predicate, r)]
        return [{p: row.get(p) for p in paths} for row in selected]

    def capabilities(self) -> Capabilities:
        return Capabilities()
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/gateway/test_fake_connector.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add gateway/connectors/ gateway/demo/__init__.py gateway/demo/rows.py tests/gateway/test_fake_connector.py
git commit -m "feat(gateway): connector base + fake in-memory connector"
```

---

## Task 8: Pipeline (the 10-step flow) + field→client remap

Spec §5, §12. Orchestrates describe → resolve want (field cache + miss-batching) → gate →
resolve where (where cache) → gate/validate → assemble IR → execute → remap. Raises
`GatewayError` for the 4xx/502 cases; the response always carries `interpreted` on a 4xx.

**Files:**
- Create: `gateway/pipeline.py`
- Test: `tests/gateway/test_remap.py`, `tests/gateway/test_pipeline.py`

- [ ] **Step 1: Write the failing remap test**

`tests/gateway/test_remap.py`:
```python
from gateway.pipeline import remap_row
from gateway.contracts import ResolvedField

def test_remap_uses_client_keys_and_nulls_declined_fields():
    select = [ResolvedField("book_title", "title", 0.9),
              ResolvedField("genre", "category", 0.9),
              ResolvedField("mystery", None, 0.2)]   # declined → null column
    row = {"title": "The Long Orbit", "category": "Science Fiction"}
    assert remap_row(row, select) == {
        "book_title": "The Long Orbit", "genre": "Science Fiction", "mystery": None}
```

- [ ] **Step 2: Write the failing pipeline test**

`tests/gateway/test_pipeline.py`:
```python
import pytest
from gateway.pipeline import run_query, GatewayError
from gateway.contracts import RawQuery
from gateway.gate import GateConfig
from gateway.cache import ResolutionCache
from gateway.connectors.fake import FakeConnector
from tests.fakes import FakeLLM

WANT_OK = {"mapping": {
    "book_title": {"field": "title", "confidence": 0.95},
    "genre":      {"field": "category", "confidence": 0.92}}}
WHERE_OK = {"where": {"op": "eq", "field": "category", "value": "Science Fiction"},
            "confidence": 0.9}

def _run(raw, llm, cache=None):
    return run_query(raw, FakeConnector(), llm, cache or ResolutionCache(),
                     GateConfig(threshold=0.7), limit=100)

def test_happy_path_returns_rows_in_client_keys():
    raw = RawQuery(["book_title", "genre"], "sci-fi only", "2026-07-06", verbose=True)
    resp = _run(raw, FakeLLM(want=WANT_OK, where=WHERE_OK))
    assert resp["rows"] and all(set(r) == {"book_title", "genre"} for r in resp["rows"])
    assert all(r["genre"] == "Science Fiction" for r in resp["rows"])
    assert resp["interpreted"]["want"]["book_title"]["field"] == "title"
    assert resp["interpreted"]["where"]["confidence"] == 0.9

def test_non_verbose_omits_interpreted():
    raw = RawQuery(["book_title"], None, "2026-07-06")
    resp = _run(raw, FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}}))
    assert "interpreted" not in resp

def test_all_want_declined_is_422():
    raw = RawQuery(["ghost"], None, "2026-07-06")
    with pytest.raises(GatewayError) as e:
        _run(raw, FakeLLM(want={"mapping": {"ghost": {"field": None, "confidence": 0.0}}}))
    assert e.value.status == 422 and e.value.code == "all_want_declined"

def test_low_confidence_where_is_422_with_interpreted():
    raw = RawQuery(["book_title"], "something vague", "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}},
                  where={"where": {"op": "eq", "field": "category", "value": "x"}, "confidence": 0.4})
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 422 and e.value.code == "where_low_confidence"
    assert e.value.interpreted["where"]["confidence"] == 0.4

def test_invalid_ast_field_is_422():
    raw = RawQuery(["book_title"], "bad filter", "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}},
                  where={"where": {"op": "eq", "field": "not_a_column", "value": 1}, "confidence": 0.9})
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 422 and e.value.code == "invalid_ast"

def test_field_cache_prevents_second_llm_call():
    cache = ResolutionCache()
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}})
    _run(raw, llm, cache); calls_after_first = llm.calls
    _run(raw, llm, cache)
    assert llm.calls == calls_after_first          # served from cache, no new LLM call

def test_llm_failure_retries_once_then_502():
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}},
                  fail_times=3)                     # both attempts fail
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 502
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/gateway/test_remap.py tests/gateway/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.pipeline'`

- [ ] **Step 4: Implement the pipeline**

`gateway/pipeline.py`:
```python
"""The 10-step flow (spec §5) + error semantics (spec §12). Steps 3/5 are lifted from
core/ (resolve_want, where_resolve); the rest is thin gateway glue."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.resolver import resolve_want, where_resolve, validate_ast, WhereResult
from core.schemas import Schema
from gateway.cache import ResolutionCache
from gateway.connectors.base import schema_version
from gateway.contracts import CanonicalQueryIR, RawQuery, ResolvedField
from gateway.gate import GateConfig, gate_want, where_passes


class GatewayError(Exception):
    """A non-200 outcome. `interpreted` is attached for every 4xx (spec §12)."""

    def __init__(self, status: int, code: str, message: str,
                 interpreted: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.interpreted = interpreted


def _retry_once(fn, *args):
    """Call fn(*args); on any exception retry once, then raise 502 (spec §12)."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001
            raise GatewayError(502, "llm_error", f"LLM call failed: {e}")


def remap_row(row: Dict[str, Any], select: List[ResolvedField]) -> Dict[str, Any]:
    """field_path-keyed row → client-key-keyed row; declined fields become null."""
    return {f.client_key: (row.get(f.field_path) if f.field_path is not None else None)
            for f in select}


def _interpreted(select: List[ResolvedField], raw: RawQuery,
                 ast: Optional[dict], where_conf: Optional[float]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "want": {f.client_key: {"field": f.field_path, "confidence": f.confidence}
                 for f in select}}
    if raw.where is not None:
        out["where"] = {"raw": raw.where, "ast": ast, "confidence": where_conf}
    return out


def run_query(raw: RawQuery, connector, llm, cache: ResolutionCache,
              gate: GateConfig, limit: int) -> Dict[str, Any]:
    schema: Schema = connector.describe()                       # step 2 (memoized in-connector)
    sv = schema_version(schema)
    backend = connector.backend_id

    # step 3 — resolve want, field cache + miss-path batching (spec §6)
    cells: Dict[str, Any] = {}
    missing: List[str] = []
    for key in raw.want:
        hit = cache.get_field(backend, sv, key)
        (cells.__setitem__(key, hit) if hit is not None else missing.append(key))
    if missing:
        mapping = _retry_once(resolve_want, llm, schema, missing)
        for key in missing:
            cell = (mapping.get(key) if isinstance(mapping, dict) else None) \
                or {"field": None, "confidence": 0.0}
            cache.set_field(backend, sv, key, cell)
            cells[key] = cell

    # step 4 — gate want
    select = gate_want(raw.want, cells, gate)
    if all(f.field_path is None for f in select):               # spec §12
        raise GatewayError(422, "all_want_declined", "no requested field resolved",
                           _interpreted(select, raw, None, None))

    # steps 5–7 — resolve where, gate, validate
    predicate: Optional[dict] = None
    where_conf: Optional[float] = None
    if raw.where is not None:
        hit = cache.get_where(backend, sv, raw.where, raw.today)
        if hit is not None:
            ast, where_conf = hit["ast"], hit["confidence"]
        else:
            wr: WhereResult = _retry_once(where_resolve, llm, schema, raw.where, raw.today)
            ast, where_conf = wr.ast, wr.confidence
            cache.set_where(backend, sv, raw.where, raw.today,
                            {"ast": ast, "confidence": where_conf})
        if not where_passes(where_conf, gate):                  # spec §7, §12
            raise GatewayError(422, "where_low_confidence", "filter confidence below threshold",
                               _interpreted(select, raw, ast, where_conf))
        if ast is not None:
            try:
                validate_ast(ast, schema)                       # step 7 — injection boundary
            except ValueError as e:
                raise GatewayError(422, "invalid_ast", str(e),
                                   _interpreted(select, raw, ast, where_conf))
        predicate = ast

    # steps 8–10 — assemble, execute, remap
    ir = CanonicalQueryIR(select=select, predicate=predicate,
                          where_confidence=where_conf, where_raw=raw.where)
    rows = connector.execute(ir, limit=limit) if _accepts_limit(connector) \
        else connector.execute(ir)
    out_rows = [remap_row(r, select) for r in rows]
    resp: Dict[str, Any] = {"rows": out_rows}
    if raw.verbose:
        resp["interpreted"] = _interpreted(select, raw, predicate, where_conf)
    return resp


def _accepts_limit(connector) -> bool:
    """Postgres.execute takes a limit; the fake connector ignores bounds. Keep the
    pipeline agnostic without forcing the fake to carry a LIMIT it can't enforce."""
    import inspect
    try:
        return "limit" in inspect.signature(connector.execute).parameters
    except (TypeError, ValueError):
        return False
```

Note: `remap_row` and `_interpreted` are the only pieces the remap test needs; the rest wires
the flow. Keep `_accepts_limit` — Task 9's Postgres connector adds a `limit` param; the fake
one from Task 7 does not, and the pipeline must call both.

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/gateway/test_remap.py tests/gateway/test_pipeline.py -v`
Expected: PASS (1 + 7 passed)

- [ ] **Step 6: Commit**

```bash
git add gateway/pipeline.py tests/gateway/test_remap.py tests/gateway/test_pipeline.py
git commit -m "feat(gateway): pipeline (10-step flow, error semantics, remap)"
```

---

## Task 9: Postgres connector + demo seed

Spec §4, §9. Introspect a denormalized view; compile the validated AST → parameterized SQL.
The seed is the source of truth for the demo data.

**Files:**
- Create: `gateway/demo/seed.sql`, `gateway/connectors/postgres.py`
- Test: `tests/gateway/conftest.py`, `tests/gateway/test_postgres_connector.py`

- [ ] **Step 1: Write the seed**

`gateway/demo/seed.sql` — normalized tables + a denormalized view whose columns match
`gateway/demo/rows.py` exactly (Task 7). Idempotent so tests can re-run it.
```sql
-- Demo dataset (spec §9): normalized authors/books + a denormalized view (v1's flat
-- execution surface). SOURCE OF TRUTH for demo data; gateway/demo/rows.py mirrors it.
DROP VIEW IF EXISTS books_view;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS authors;

CREATE TABLE authors (
    author_id   integer PRIMARY KEY,
    author_name text NOT NULL,
    birth_year  integer,
    country     text
);
COMMENT ON COLUMN authors.author_name IS 'full name of the person who wrote the book';
COMMENT ON COLUMN authors.birth_year  IS 'year the author was born';
COMMENT ON COLUMN authors.country     IS 'author''s country of origin';

CREATE TABLE books (
    book_id      integer PRIMARY KEY,
    title        text NOT NULL,
    category     text,
    published_at date,
    price        numeric(8,2),
    page_count   integer,
    language     text,
    author_id    integer REFERENCES authors(author_id)
);
COMMENT ON COLUMN books.title        IS 'the title of the book';
COMMENT ON COLUMN books.category     IS 'genre / subject classification';
COMMENT ON COLUMN books.published_at IS 'date the book was published';
COMMENT ON COLUMN books.price        IS 'retail price in USD';
COMMENT ON COLUMN books.page_count   IS 'number of pages';
COMMENT ON COLUMN books.language     IS 'language the book is written in';

INSERT INTO authors (author_id, author_name, birth_year, country) VALUES
    (1, 'Ursula K. Le Guin', 1929, 'USA'),
    (2, 'SansWord',          1985, 'USA'),
    (3, 'R. Novak',          1970, 'UK'),
    (4, 'Old Writer',        1940, 'France'),
    (5, 'A. Blake',          1960, 'UK'),
    (6, 'M. Ito',            1988, 'Japan');

INSERT INTO books (book_id, title, category, published_at, price, page_count, language, author_id) VALUES
    (1, 'A Wizard of Earthsea', 'Fantasy',         '1968-01-01',  9.99, 205, 'en', 1),
    (2, 'Future Shock 2026',    'Science Fiction', '2026-03-01', 15.00, 350, 'en', 2),
    (3, 'The Long Orbit',       'Science Fiction', '2026-05-10', 24.00, 500, 'en', 3),
    (4, 'Vieux Roman',          'Non-Fiction',     '2010-01-01', 12.00, 280, 'fr', 4),
    (5, 'Orbit of Dreams',      'Science Fiction', '2025-11-20', 30.00, 420, 'en', 5),
    (6, 'Silent Fields',        'Non-Fiction',     '2026-01-15', 18.50, 300, 'en', 6);

CREATE VIEW books_view AS
    SELECT b.book_id, b.title, b.category, b.published_at, b.price, b.page_count,
           b.language, a.author_id, a.author_name, a.birth_year, a.country
    FROM books b JOIN authors a ON a.author_id = b.author_id;
```

- [ ] **Step 2: Write the failing test (skips without a DB)**

`tests/gateway/conftest.py`:
```python
import os
from pathlib import Path
import pytest

SEED = Path(__file__).resolve().parents[2] / "gateway" / "demo" / "seed.sql"


@pytest.fixture
def pg_connector():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set TEST_DATABASE_URL to run Postgres-backed tests")
    import psycopg
    from gateway.connectors.postgres import PostgresConnector
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(SEED.read_text())
    return PostgresConnector(dsn, view="books_view")
```

`tests/gateway/test_postgres_connector.py`:
```python
from gateway.contracts import CanonicalQueryIR, ResolvedField

def test_describe_introspects_view_columns(pg_connector):
    schema = pg_connector.describe()
    by_path = {f.path: f for f in schema.fields}
    assert {"title", "category", "price", "author_name"} <= set(by_path)
    assert by_path["category"].description == "genre / subject classification"
    assert "Science Fiction" in by_path["category"].samples

def test_execute_compiles_ast_and_keys_by_path(pg_connector):
    ir = CanonicalQueryIR(
        select=[ResolvedField("t", "title", 0.9), ResolvedField("g", "category", 0.9)],
        predicate={"op": "and", "clauses": [
            {"op": "eq", "field": "category", "value": "Science Fiction"},
            {"op": "gte", "field": "price", "value": 20}]},
        where_confidence=0.9, where_raw="expensive sci-fi")
    rows = pg_connector.execute(ir, limit=100)
    assert {r["title"] for r in rows} == {"The Long Orbit", "Orbit of Dreams"}
    assert set(rows[0]) == {"title", "category"}

def test_limit_is_enforced(pg_connector):
    ir = CanonicalQueryIR(select=[ResolvedField("t", "title", 0.9)],
                          predicate=None, where_confidence=None, where_raw=None)
    assert len(pg_connector.execute(ir, limit=2)) == 2
```

- [ ] **Step 3: Run to verify it fails (or skips without a DB)**

Run: `python -m pytest tests/gateway/test_postgres_connector.py -v`
Expected: FAIL (`No module named 'gateway.connectors.postgres'`) if `TEST_DATABASE_URL` set;
otherwise SKIPPED. To run for real, start Postgres and export the DSN, e.g.:
```bash
docker run -d --name sans-pg -e POSTGRES_PASSWORD=pg -p 5432:5432 postgres:16
export TEST_DATABASE_URL="postgresql://postgres:pg@localhost:5432/postgres"
```

- [ ] **Step 4: Implement the Postgres connector**

`gateway/connectors/postgres.py`:
```python
"""Postgres connector (spec §4, §9). describe() introspects information_schema over the
denormalized view; execute() compiles the VALIDATED AST → parameterized SQL. Field paths
are the view's column names (the view is already flat — no join planning in v1)."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

import psycopg
from psycopg import sql

from core.schemas import Field, Schema
from gateway.connectors.base import Capabilities
from gateway.contracts import CanonicalQueryIR

_BINARY_OPS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


class PostgresConnector:
    def __init__(self, dsn: str, view: str = "books_view"):
        self.dsn = dsn
        self.view = view
        self.backend_id = f"postgres:{view}"
        self._schema: Optional[Schema] = None

    def capabilities(self) -> Capabilities:
        return Capabilities()

    # --- describe (memoized) ------------------------------------------------
    def describe(self) -> Schema:
        if self._schema is not None:
            return self._schema
        with psycopg.connect(self.dsn) as conn:
            cols = conn.execute(
                """
                SELECT column_name, data_type,
                       col_description((%s)::regclass, ordinal_position) AS comment
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
                """,
                (self.view, self.view),
            ).fetchall()
            fields: List[Field] = []
            for name, dtype, comment in cols:
                samples = self._samples(conn, name)
                fields.append(Field(path=name, type=dtype,
                                    description=comment or "", samples=samples))
        self._schema = Schema(name=self.view, fields=fields)
        return self._schema

    def _samples(self, conn, column: str, k: int = 5) -> List[str]:
        q = sql.SQL("SELECT DISTINCT {col} FROM {view} WHERE {col} IS NOT NULL LIMIT %s").format(
            col=sql.Identifier(column), view=sql.Identifier(self.view))
        return [str(r[0]) for r in conn.execute(q, (k,)).fetchall()]

    # --- execute ------------------------------------------------------------
    def execute(self, ir: CanonicalQueryIR, limit: int = 100) -> List[dict]:
        paths = [f.field_path for f in ir.select if f.field_path is not None]
        select_cols = sql.SQL(", ").join(sql.Identifier(p) for p in paths)
        query = sql.SQL("SELECT {cols} FROM {view}").format(
            cols=select_cols, view=sql.Identifier(self.view))
        params: List[Any] = []
        if ir.predicate is not None:
            clause, params = self._compile(ir.predicate)
            query = query + sql.SQL(" WHERE ") + clause
        query = query + sql.SQL(" LIMIT %s")
        params.append(limit)
        with psycopg.connect(self.dsn) as conn:
            cur = conn.execute(query, params)
            names = [d.name for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]

    def _compile(self, node: dict) -> Tuple[sql.Composable, List[Any]]:
        op = node["op"]
        if op in ("and", "or"):
            joiner = sql.SQL(f" {op.upper()} ")
            parts, params = [], []
            for c in node.get("clauses", []):
                clause, p = self._compile(c)
                parts.append(clause); params += p
            return sql.SQL("(") + joiner.join(parts) + sql.SQL(")"), params
        if op == "not":
            clause, params = self._compile(node["clause"])
            return sql.SQL("NOT (") + clause + sql.SQL(")"), params

        col = sql.Identifier(node["field"])
        val = node.get("value")
        if op in _BINARY_OPS:
            return sql.SQL("{} {} %s").format(col, sql.SQL(_BINARY_OPS[op])), [val]
        if op == "in":
            return sql.SQL("{} = ANY(%s)").format(col), [list(val)]
        if op == "nin":
            return sql.SQL("{} <> ALL(%s)").format(col), [list(val)]
        if op == "contains":                       # ILIKE → case-insensitive, matches core.predicate
            return sql.SQL("{} ILIKE %s").format(col), [f"%{val}%"]
        if op == "between":
            return sql.SQL("{} BETWEEN %s AND %s").format(col), [val[0], val[1]]
        if op == "is_null":
            return sql.SQL("{} IS NULL").format(col), []
        raise ValueError(f"uncompilable op: {op!r}")   # unreachable — validate_ast ran first
```

- [ ] **Step 5: Run to verify it passes (with a DB)**

Run: `TEST_DATABASE_URL=... python -m pytest tests/gateway/test_postgres_connector.py -v`
Expected: PASS (3 passed). Without the DSN: SKIPPED — that is acceptable for the commit,
but run it against a real Postgres at least once before closing the milestone.

- [ ] **Step 6: Commit**

```bash
git add gateway/demo/seed.sql gateway/connectors/postgres.py tests/gateway/conftest.py tests/gateway/test_postgres_connector.py
git commit -m "feat(gateway): Postgres connector (introspect + AST→SQL) + demo seed"
```

---

## Task 10: Seam parity test (the headline)

Spec §9, §11 tier 2: a fixed `CanonicalQueryIR` selects the **same row-set** from both the
Postgres and fake connectors, and the introspected schema matches the fake mirror. LLM-free.

**Files:**
- Create: `tests/gateway/test_seam_parity.py`

- [ ] **Step 1: Write the failing/skipping test**

`tests/gateway/test_seam_parity.py`:
```python
from gateway.connectors.fake import FakeConnector
from gateway.contracts import CanonicalQueryIR, ResolvedField

IR = CanonicalQueryIR(
    select=[ResolvedField("t", "title", 0.9), ResolvedField("g", "category", 0.9)],
    predicate={"op": "and", "clauses": [
        {"op": "eq", "field": "category", "value": "Science Fiction"},
        {"op": "gte", "field": "price", "value": 20}]},
    where_confidence=0.9, where_raw="expensive sci-fi")

def _rowset(rows):
    return frozenset((r["t"] if "t" in r else r["title"],) for r in rows)  # keyed by field_path

def test_introspected_schema_matches_the_fake_mirror(pg_connector):
    pg_paths = {f.path for f in pg_connector.describe().fields}
    fake_paths = {f.path for f in FakeConnector().describe().fields}
    assert pg_paths == fake_paths

def test_same_ir_selects_the_same_rows(pg_connector):
    pg_rows = pg_connector.execute(IR, limit=100)
    fake_rows = FakeConnector().execute(IR)
    key = lambda rows: frozenset((r["title"], r["category"]) for r in rows)
    assert key(pg_rows) == key(fake_rows)          # order not guaranteed without ORDER BY
    assert key(pg_rows) == {("The Long Orbit", "Science Fiction"),
                            ("Orbit of Dreams", "Science Fiction")}
```
(Uses the `pg_connector` fixture from Task 9's conftest — skips without `TEST_DATABASE_URL`.)

- [ ] **Step 2: Run it**

Run: `TEST_DATABASE_URL=... python -m pytest tests/gateway/test_seam_parity.py -v`
Expected: PASS (2 passed) with a DB; SKIPPED without one.

- [ ] **Step 3: Commit**

```bash
git add tests/gateway/test_seam_parity.py
git commit -m "test(gateway): seam parity — Postgres and fake connectors agree"
```

---

## Task 11: FastAPI app (JSON RequestAdapter + POST /query)

Spec §3, §5, §10, §12. Parse the JSON body → `RawQuery` (server sets `today`), run the
pipeline, map `GatewayError` → HTTP status with `interpreted` on every 4xx.

**Files:**
- Create: `gateway/config.py`, `gateway/app.py`
- Test: `tests/gateway/test_app.py`

- [ ] **Step 1: Write the failing test (fake LLM + fake connector via dependency override)**

`tests/gateway/test_app.py`:
```python
from fastapi.testclient import TestClient
from gateway.app import app, get_llm, get_connector
from gateway.connectors.fake import FakeConnector
from tests.fakes import FakeLLM

WANT_OK = {"mapping": {"book_title": {"field": "title", "confidence": 0.95},
                       "genre": {"field": "category", "confidence": 0.92}}}
WHERE_OK = {"where": {"op": "eq", "field": "category", "value": "Science Fiction"},
            "confidence": 0.9}

def _client(llm):
    app.dependency_overrides[get_connector] = lambda: FakeConnector()
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)

def teardown_function():
    app.dependency_overrides.clear()

def test_query_returns_rows_in_client_keys():
    c = _client(FakeLLM(want=WANT_OK, where=WHERE_OK))
    r = c.post("/query", json={"want": {"book_title": None, "genre": None},
                               "where": "sci-fi only", "isVerbose": True})
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] and all(set(row) == {"book_title", "genre"} for row in body["rows"])
    assert body["interpreted"]["want"]["book_title"]["field"] == "title"

def test_low_confidence_where_returns_422_with_interpreted():
    llm = FakeLLM(want=WANT_OK,
                  where={"where": {"op": "eq", "field": "category", "value": "x"},
                         "confidence": 0.3})
    c = _client(llm)
    r = c.post("/query", json={"want": {"book_title": None}, "where": "vague"})
    assert r.status_code == 422
    assert r.json()["interpreted"]["where"]["confidence"] == 0.3   # present even without isVerbose

def test_want_as_list_is_accepted():
    c = _client(FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}}))
    r = c.post("/query", json={"want": ["book_title"]})
    assert r.status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/gateway/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.app'`

- [ ] **Step 3: Implement config**

`gateway/config.py`:
```python
"""Env-driven config (spec §10). Container-portable; no config file in v1."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str
    llm_model: str
    gate_threshold: float
    result_limit: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("DATABASE_URL", ""),
            llm_model=os.environ.get("LLM_MODEL", "gemini/gemini-3.1-flash-lite"),
            gate_threshold=float(os.environ.get("GATE_THRESHOLD", "0.7")),
            result_limit=int(os.environ.get("RESULT_LIMIT", "100")),
        )
```

- [ ] **Step 4: Implement the app**

`gateway/app.py`:
```python
"""FastAPI surface + the JSON RequestAdapter (spec §3, §5). POST /query only.
Dependencies (llm / connector / cache / settings) are injected so tests override them."""
from __future__ import annotations

import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional, Union

from fastapi import Body, Depends, FastAPI
from fastapi.responses import JSONResponse

from core.llm import LiteLLM
from gateway.cache import ResolutionCache
from gateway.config import Settings
from gateway.connectors.postgres import PostgresConnector
from gateway.contracts import RawQuery
from gateway.gate import GateConfig
from gateway.pipeline import GatewayError, run_query

app = FastAPI(title="sans_schema — Semantic Query Gateway")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache(maxsize=1)
def get_cache() -> ResolutionCache:
    return ResolutionCache()


@lru_cache(maxsize=1)
def get_connector() -> PostgresConnector:
    return PostgresConnector(get_settings().database_url)


@lru_cache(maxsize=1)
def get_llm() -> LiteLLM:
    return LiteLLM(get_settings().llm_model)


def to_raw_query(body: Dict[str, Any]) -> RawQuery:
    """The JSON RequestAdapter: collapse {want:{k:null}} → [k] (spec §3), NL where,
    server-stamped today (per-call, volatile — kept out of the cached system prompt)."""
    raw_want: Union[Dict[str, Any], List[str], None] = body.get("want")
    if isinstance(raw_want, dict):
        want = list(raw_want.keys())
    elif isinstance(raw_want, list):
        want = [str(k) for k in raw_want]
    else:
        want = []
    where = body.get("where")
    return RawQuery(want=want, where=where,
                    today=datetime.date.today().isoformat(),
                    verbose=bool(body.get("isVerbose", False)))


@app.post("/query")
def query(body: Dict[str, Any] = Body(...),
          settings: Settings = Depends(get_settings),
          connector=Depends(get_connector),
          llm=Depends(get_llm),
          cache: ResolutionCache = Depends(get_cache)):
    raw = to_raw_query(body)
    if not raw.want:
        return JSONResponse(status_code=422,
                            content={"error": "empty_want",
                                     "message": "`want` must name at least one field",
                                     "interpreted": {"want": {}}})
    try:
        return run_query(raw, connector, llm, cache,
                         GateConfig(threshold=settings.gate_threshold),
                         limit=settings.result_limit)
    except GatewayError as e:
        return JSONResponse(status_code=e.status,
                            content={"error": e.code, "message": e.message,
                                     "interpreted": e.interpreted})
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/gateway/test_app.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Run the whole LLM-free suite**

Run: `python -m pytest -q`
Expected: all pass; Postgres-backed tests SKIPPED unless `TEST_DATABASE_URL` is set.

- [ ] **Step 7: Commit**

```bash
git add gateway/config.py gateway/app.py tests/gateway/test_app.py
git commit -m "feat(gateway): FastAPI POST /query + JSON RequestAdapter + config"
```

---

## Task 12: Live smoke test (opt-in) + re-run the spike eval

Spec §7, §11 tier 3: a couple of real-LLM tests gated behind an env flag, plus re-measuring
the spike eval after the where-confidence prompt change (must not regress).

**Files:**
- Create: `tests/live/__init__.py`, `tests/live/test_live_smoke.py`

- [ ] **Step 1: Write the opt-in live smoke test**

`tests/live/test_live_smoke.py`:
```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM") != "1",
    reason="set RUN_LIVE_LLM=1 (and an LLM API key + TEST_DATABASE_URL) to run live")


def test_end_to_end_against_real_llm_and_postgres():
    from pathlib import Path
    import psycopg
    from core.llm import LiteLLM
    from gateway.cache import ResolutionCache
    from gateway.connectors.postgres import PostgresConnector
    from gateway.contracts import RawQuery
    from gateway.gate import GateConfig
    from gateway.pipeline import run_query

    dsn = os.environ["TEST_DATABASE_URL"]
    seed = Path(__file__).resolve().parents[2] / "gateway" / "demo" / "seed.sql"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(seed.read_text())

    llm = LiteLLM(os.environ.get("LLM_MODEL", "gemini/gemini-3.1-flash-lite"))
    resp = run_query(
        RawQuery(want=["book_title", "writer"], where="science fiction only",
                 today="2026-07-06", verbose=True),
        PostgresConnector(dsn), llm, ResolutionCache(), GateConfig(0.7), limit=100)
    assert resp["rows"]
    assert resp["interpreted"]["want"]["writer"]["field"] in ("author_name", None)
```

- [ ] **Step 2: Run it (skips by default)**

Run: `python -m pytest tests/live/ -v`
Expected: SKIPPED (1 skipped). It runs only with `RUN_LIVE_LLM=1` + keys + DSN.

- [ ] **Step 3: Re-run the spike eval to confirm no regression (spec §7)**

The where prompt gained a `confidence` line (Task 3). Re-measure against the frozen cases with
the starting model to confirm want/where accuracy did not drop:

Run: `GEMINI_API_KEY=... python -m spike.score --models gemini/gemini-3.1-flash-lite`
Expected: WANT resolution and WHERE→AST percentages hold at the pre-change level (the spike
README records the baseline). If WHERE regresses, the confidence instruction is interfering —
adjust prompt wording in `core/prompts.py`, not the validator, and re-run. Record the numbers
in the devlog entry (Task 13).

- [ ] **Step 4: Commit**

```bash
git add tests/live/__init__.py tests/live/test_live_smoke.py
git commit -m "test: opt-in live smoke + spike re-measure note"
```

---

## Task 13: Packaging, quickstart, and close the loop

Spec §10; root `CLAUDE.md` "End of session — close the loop". Dockerfile + quickstart README,
then update the maintained docs, devlog, and todo in the same change (the doc gate).

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `gateway/README.md`
- Modify: `docs/architecture.md`, `docs/system-design.md`, `docs/devlog.md`, `todo.md`, `CLAUDE.md`

- [ ] **Step 1: Dockerfile + .dockerignore**

`Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY core/ ./core/
COPY gateway/ ./gateway/
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
```
`.dockerignore`:
```
spike/
tests/
docs/
*.log
__pycache__/
.git/
```
(The image ships `core/` + `gateway/` only — the resolver lives in `core/`, which is copied;
`spike/` is eval-only and excluded.)

- [ ] **Step 2: Build the image to verify it assembles**

Run: `docker build -t sans-schema:dev .`
Expected: builds clean (no `spike` import at gateway import time — verify with:
`docker run --rm sans-schema:dev python -c "import gateway.app"` → no error).

- [ ] **Step 3: Write the quickstart README**

`gateway/README.md` — the copy-paste on-ramp (todo "Onboarding flow"). Include: (a) run Postgres
+ seed `gateway/demo/seed.sql`; (b) `export DATABASE_URL=... LLM_MODEL=... GEMINI_API_KEY=...`;
(c) `docker build` + `docker run -p 8000:8000 --env-file .env sans-schema:dev`, or
`uvicorn gateway.app:app --reload`; (d) a `curl -X POST localhost:8000/query -d '{"want":{"title":null,"writer":null},"where":"science fiction only","isVerbose":true}'`
example with the expected shape; (e) the env-var table (`DATABASE_URL`, `LLM_MODEL`,
`GATE_THRESHOLD`, `RESULT_LIMIT`). No secrets committed.

- [ ] **Step 4: Fold decisions into the maintained docs**

- `docs/architecture.md`: flip the status legend where now implemented — §1 HTTP surface
  (`POST /query` built), §2 where-confidence (now in `core.where_resolve`), §3 `RawQuery`/
  `CanonicalQueryIR` (now defined — cite `gateway/contracts.py`), §7 stack (built). Add a
  line noting `core/predicate.py` as the shared execution-equivalence engine (glossary §8).
- `docs/system-design.md`: flip ✅/📐 on the swap-point matrix rows that shipped (Ingress JSON,
  Cache in-mem dicts, Backend Postgres + fake). Note `core/predicate.py` if it affects the map.

- [ ] **Step 5: Append the devlog entry (newest-on-top) + TL;DR row**

Add `## v0.1.0 — First gateway slice (YYYY-MM-DD HH:MM)` (timestamp from the final commit's
`git log`). Sections per the house format: `**Review:** not yet`, `**Design docs:**` linking
the spec + this plan, `**What was built:**`, `**Key technical learnings:**` (tag each
`[note]`/`[insight]`/`[gotcha]`), including the spike re-measure numbers from Task 12 Step 3.
Add the matching TL;DR table row with a section-anchor link.

- [ ] **Step 6: Update `todo.md`**

Check off "Write the implementation plan" and the MVP setup items now settled (serve/package =
Docker; DB = Postgres; LLM wiring; config surface = env; quickstart README shipped). Promote
the **symbolic/relative dates (`bind_today`)** fast-follow to the top of "Now" as the next
milestone. Leave the de-risking section intact (this slice doesn't close it — spec §14).

- [ ] **Step 7: Full suite + final commit**

Run: `python -m pytest -q` (LLM-free green; Postgres tests pass with `TEST_DATABASE_URL`).
```bash
git add Dockerfile .dockerignore gateway/README.md docs/architecture.md docs/system-design.md docs/devlog.md todo.md CLAUDE.md
git commit -m "docs: package the gateway slice + close the loop (v0.1.0)"
```

---

## Self-Review

**Spec coverage (spec §-by-§):**
- §2 scope: JSON adapter (T11) · resolver in `core/` (T1) · `RawQuery`/`CanonicalQueryIR` (T4) ·
  Postgres + fake connectors (T7, T9) · two-part cache (T6) · gate both sides (T5, T8) ·
  response in client keys + `interpreted` behind `isVerbose` (T8, T11). ✅
- §3 contracts: T4 (shapes), T11 (request/response JSON). ✅
- §4 connector interface: T7 (base + fake), T9 (Postgres describe/execute/capabilities). ✅
- §5 ten-step flow: T8 pipeline. ✅
- §6 two-part cache incl. miss-batching + gate-at-read + `today` in where key: T6, T8. ✅
- §7 gate (0.7, want-decline, where-422, NEW where confidence): T3, T5, T8. ✅
- §8 code organization (`core/` + `gateway/`): T1, T2, and every gateway task. ✅
- §9 demo dataset + dynamic detection + parity: T7 (mirror), T9 (seed + introspect), T10 (parity). ✅
- §10 packaging/config (env, LIMIT, Docker): T11 (config), T13 (Dockerfile/README). ✅
- §11 three test tiers: unit (T2–T8), seam (T10), live (T12). ✅
- §12 error semantics (all-declined 422, invalid AST 422, where-low 422, LLM 502, interpreted on 4xx): T8, T11. ✅
- §13 fast-follow / §14 de-risking: not built (correctly); surfaced in todo (T13). ✅

**Type/name consistency:** `RawQuery`, `ResolvedField`, `CanonicalQueryIR`, `GateConfig`,
`gate_want`, `where_passes`, `WhereResult`, `where_resolve`, `ResolutionCache`
(`get_field`/`set_field`/`get_where`/`set_where`), `schema_version`, `FakeConnector`/
`PostgresConnector.backend_id`, `run_query`, `remap_row`, `GatewayError(status, code, message,
interpreted)`, `matches`/`select_indices` — used identically across tasks. `PostgresConnector.execute`
takes `limit`; `FakeConnector.execute` does not — reconciled by `_accepts_limit` in T8, and both
appear in the same test set.

**Placeholder scan:** no TBD/"handle errors"/"similar to" — every code step carries full code;
error handling is concrete (`GatewayError`, retry-once → 502).

**One conscious deviation from the spec's file list:** `core/predicate.py` (T2) is added beyond
the spec §8 core files, to share the execution-equivalence matcher between the fake connector and
the spike scorer (DRY, and it makes the parity test meaningful). Flagged for the devlog.
