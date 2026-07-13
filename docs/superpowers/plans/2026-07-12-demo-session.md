# Demo Session Implementation Plan (v0.3.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the 25-minute demo session: a public-hardened gateway (CORS + rate limits), a Next.js playground on Vercel, a Fly.io deployment, and a self-contained HTML slide deck + demo script.

**Architecture:** Four sequenced phases from the approved spec ([`docs/superpowers/specs/2026-07-12-demo-session-design.md`](../specs/2026-07-12-demo-session-design.md)). Phase 1 adds env-driven, **off-by-default** guardrails (slowapi + Starlette CORS) behind a new `create_app()` factory so per-instance limits are testable; Phase 2 builds the playground (browser → gateway directly over CORS, no proxy); Phase 3 deploys gateway+Postgres on Fly.io and the playground on Vercel; Phase 4 writes the deck + script and closes the doc loop.

**Tech Stack:** Python 3.9+ / FastAPI / slowapi / pytest (gateway) · Next.js 15 + TypeScript, hand-rolled scaffold, no Tailwind (playground) · Fly.io + Vercel (deploy) · single-file HTML deck.

**Docs consulted:** `CLAUDE.md`, the spec above, `todo.md`, `docs/architecture.md` (§1, §3, §6), `gateway/{app,config,pipeline}.py`, `gateway/connectors/postgres.py`, `gateway/demo/rows.py`, `gateway/README.md`, `.env.example`, `Dockerfile`, `tests/gateway/test_app.py`.

**One addition beyond the spec (flagged):** a `DB_VIEW` env setting (default `books_view`, so nothing changes for the demo or tests). Today `app.py` constructs `PostgresConnector(dsn)` with the hardcoded default view, so the spec's "run it against your own data" deliverable literally requires naming your view `books_view`. One config field makes the own-data quickstart honest.

**Out of scope (per spec):** bot/abuse detection, endpoint auth / field-level authz, windowed cache metrics, spend accounting, multi-replica rate limiting, `bind_today`. The richer demo dataset is a stretch goal — **not planned here**; ship the core first.

---

## File structure

**Phase 1 — gateway hardening**
- Modify: `gateway/config.py` — five new `Settings` fields (defaults = off)
- Create: `gateway/guardrails.py` — client-IP key fn, 429 handler, limiter/CORS install
- Modify: `gateway/app.py` — refactor to `create_app()` factory; conditional limit decorators
- Modify: `pyproject.toml` — add `slowapi`
- Modify: `.env.example`, `gateway/README.md` — document new vars
- Create: `tests/gateway/test_config.py`, `tests/gateway/test_guardrails.py`

**Phase 2 — playground**
- Create: `playground/` — `package.json`, `tsconfig.json`, `next.config.mjs`, `.gitignore`,
  `app/layout.tsx`, `app/globals.css`, `app/page.tsx`, `app/own-data/page.tsx`,
  `lib/api.ts`, `lib/examples.ts`,
  `components/{RequestBuilder,ResultsTable,InterpretedPanel,StatusPanel}.tsx`

**Phase 3 — deployment**
- Create: `fly.toml`, `gateway/DEPLOY.md` (runbook incl. the vendor quota backstop)

**Phase 4 — deck + script + doc loop**
- Create: `playground/public/slides.html` (single copy — hosted at `<playground>/slides.html`), `docs/demo/script.md`
- Modify: `docs/architecture.md`, `docs/system-design.md`, `docs/devlog.md`, `todo.md`

---

# Phase 1 — Gateway demo-hardening

Everything is **off unless configured**: the existing suite must pass untouched, and the default request path must contain no limiter code at all.

### Task 1: Guardrail + DB_VIEW settings

**Files:**
- Modify: `gateway/config.py`
- Create: `tests/gateway/test_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/gateway/test_config.py`:

```python
"""Settings.from_env parsing for the guardrail + DB_VIEW additions (demo-session spec)."""
from gateway.config import Settings

GUARDRAIL_VARS = ("RATE_LIMIT_PER_IP", "DAILY_REQUEST_CAP", "CORS_ORIGINS",
                  "CLIENT_IP_HEADER", "DB_VIEW")


def _clear(monkeypatch):
    for var in GUARDRAIL_VARS:
        monkeypatch.delenv(var, raising=False)


def test_guardrails_default_off(monkeypatch):
    _clear(monkeypatch)
    s = Settings.from_env()
    assert s.rate_limit_per_ip == ""
    assert s.daily_request_cap == ""
    assert s.cors_origins == []
    assert s.client_ip_header == ""
    assert s.db_view == "books_view"


def test_guardrails_parse_from_env(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "10/minute")
    monkeypatch.setenv("DAILY_REQUEST_CAP", "1000/day")
    monkeypatch.setenv("CORS_ORIGINS", "https://play.example.com, http://localhost:3000")
    monkeypatch.setenv("CLIENT_IP_HEADER", "Fly-Client-IP")
    monkeypatch.setenv("DB_VIEW", "inventory_view")
    s = Settings.from_env()
    assert s.rate_limit_per_ip == "10/minute"
    assert s.daily_request_cap == "1000/day"
    assert s.cors_origins == ["https://play.example.com", "http://localhost:3000"]
    assert s.client_ip_header == "Fly-Client-IP"
    assert s.db_view == "inventory_view"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/gateway/test_config.py -v`
Expected: FAIL — `TypeError` / `AttributeError` (fields don't exist yet)

- [ ] **Step 3: Implement — replace `gateway/config.py` with:**

```python
"""Env-driven config (spec §10). Container-portable; no config file in v1."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Settings:
    database_url: str
    llm_model: str
    gate_threshold: float
    result_limit: int
    max_want_fields: int      # cap on how many fields one request may ask for
    max_field_len: int        # cap on the length of a single `want` field name
    max_where_len: int        # cap on the length of the NL `where` string
    enable_debug_endpoints: bool  # expose /debug/* (discloses schema+samples) — dev only
    # Public-demo guardrails (demo-session spec). All OFF by default — an empty
    # value disables the guardrail, so local dev and the existing tests see no change.
    rate_limit_per_ip: str = ""    # slowapi limit string per visitor IP, e.g. "10/minute"
    daily_request_cap: str = ""    # global request-count cap, e.g. "1000/day" (count, not spend)
    cors_origins: List[str] = field(default_factory=list)  # browser origins allowed to call the API
    client_ip_header: str = ""     # proxy header carrying the real visitor IP (e.g. Fly-Client-IP)
    db_view: str = "books_view"    # the denormalized view the Postgres connector introspects

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("DATABASE_URL", ""),
            llm_model=os.environ.get("LLM_MODEL", "gemini/gemini-3.1-flash-lite"),
            gate_threshold=float(os.environ.get("GATE_THRESHOLD", "0.7")),
            result_limit=int(os.environ.get("RESULT_LIMIT", "100")),
            # Ingress limits — bound the untrusted request so a huge `want`/`where`
            # can't inflate the LLM prompt (cost/DoS). Generous defaults; tune per deploy.
            max_want_fields=int(os.environ.get("MAX_WANT_FIELDS", "50")),
            max_field_len=int(os.environ.get("MAX_FIELD_LEN", "200")),
            max_where_len=int(os.environ.get("MAX_WHERE_LEN", "2000")),
            # Debug introspection (system + schema prompts). OFF by default — the schema
            # view discloses column names, descriptions, and sample values.
            enable_debug_endpoints=os.environ.get(
                "ENABLE_DEBUG_ENDPOINTS", "0").strip().lower() in ("1", "true", "yes", "on"),
            rate_limit_per_ip=os.environ.get("RATE_LIMIT_PER_IP", "").strip(),
            daily_request_cap=os.environ.get("DAILY_REQUEST_CAP", "").strip(),
            cors_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",")
                          if o.strip()],
            client_ip_header=os.environ.get("CLIENT_IP_HEADER", "").strip(),
            db_view=os.environ.get("DB_VIEW", "books_view").strip() or "books_view",
        )
```

Note: the new fields have defaults, so existing `Settings(**kwargs)` constructions in `tests/gateway/test_app.py` keep working unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/gateway/test_config.py tests/gateway/test_app.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add gateway/config.py tests/gateway/test_config.py
git commit -m "feat(gateway): guardrail + DB_VIEW settings (all off by default)"
```

### Task 2: `gateway/guardrails.py` — proxy-aware client-IP key + friendly 429s

**Files:**
- Create: `gateway/guardrails.py`
- Create: `tests/gateway/test_guardrails.py`
- Modify: `pyproject.toml` (add slowapi)

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, change the `dependencies` list to:

```toml
dependencies = [
    "litellm>=1.40",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "psycopg[binary]>=3.1",
    "slowapi>=0.1.9",
]
```

Run: `pip install -e ".[dev]"`
Expected: installs `slowapi` (and its `limits` dependency) cleanly.

- [ ] **Step 2: Write the failing tests**

Create `tests/gateway/test_guardrails.py` (more tests join this file in Tasks 4–6):

```python
"""Guardrail tests (demo-session spec): proxy-header key fn, per-IP limit,
global daily cap, CORS, friendly 429 bodies, defaults-off."""
from fastapi.testclient import TestClient
from starlette.requests import Request

from gateway.config import Settings
from gateway.guardrails import client_ip


def _settings(**kw):
    base = dict(database_url="", llm_model="fake", gate_threshold=0.7, result_limit=100,
                max_want_fields=50, max_field_len=200, max_where_len=2000,
                enable_debug_endpoints=False)
    base.update(kw)
    return Settings(**base)


def _request(headers=None, client=("10.0.0.1", 1234)):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/query",
                    "headers": raw, "client": client, "query_string": b"",
                    "server": ("testserver", 80), "scheme": "http"})


def test_client_ip_reads_configured_header_first_hop():
    s = _settings(client_ip_header="X-Forwarded-For")
    r = _request({"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
    assert client_ip(r, s) == "203.0.113.9"


def test_client_ip_falls_back_to_socket_peer():
    # header configured but absent on the request → socket peer
    assert client_ip(_request(), _settings(client_ip_header="Fly-Client-IP")) == "10.0.0.1"
    # no header configured at all → socket peer
    assert client_ip(_request(), _settings()) == "10.0.0.1"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/gateway/test_guardrails.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.guardrails'`

- [ ] **Step 4: Create `gateway/guardrails.py`:**

```python
"""Public-demo guardrails (demo-session spec): CORS + per-IP rate limit + global
daily request cap. Everything here is OFF unless configured in Settings — local
dev and the test suite run with no limiter in the request path at all."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from gateway.config import Settings

# Error codes double as slowapi `error_message`s so the 429 handler can tell
# which limit tripped. The playground renders these codes as friendly states.
PER_IP_CODE = "rate_limited"
GLOBAL_CODE = "demo_budget_exhausted"

_MESSAGES = {
    PER_IP_CODE: "Too many requests from your address — wait a minute and try again.",
    GLOBAL_CODE: ("The public demo's daily request budget is used up. The gateway is "
                  "open source — run it locally against your own data and API key."),
}


def client_ip(request: Request, settings: Settings) -> str:
    """Rate-limit key. Behind a PaaS proxy `request.client` is the proxy, so read
    the platform's client-IP header when configured (first hop of a comma list) —
    otherwise every visitor would share one bucket."""
    if settings.client_ip_header:
        value = request.headers.get(settings.client_ip_header)
        if value:
            return value.split(",")[0].strip()
    return get_remote_address(request)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Friendly 429 body the playground can render. `exc.detail` carries the
    error_message attached to whichever limit tripped (per-IP vs global)."""
    code = GLOBAL_CODE if exc.detail == GLOBAL_CODE else PER_IP_CODE
    return JSONResponse(status_code=429,
                        content={"error": code, "message": _MESSAGES[code]})


def build_limiter(settings: Settings) -> Limiter:
    return Limiter(key_func=lambda request: client_ip(request, settings))


def install_guardrails(app: FastAPI, settings: Settings, limiter: Limiter) -> None:
    """Wire the 429 handler + CORS onto the app. The rate-limit decorators are
    applied where the /query endpoint is defined (they wrap the endpoint fn)."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_methods=["POST", "GET", "OPTIONS"],
                           allow_headers=["*"])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/gateway/test_guardrails.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add gateway/guardrails.py tests/gateway/test_guardrails.py pyproject.toml
git commit -m "feat(gateway): guardrails module — proxy-aware IP key + friendly 429 handler"
```

### Task 3: Refactor `gateway/app.py` to a `create_app()` factory

Pure refactor — no new behavior; the existing suite is the test. The factory lets guardrail tests build an app per `Settings` (each with a fresh in-memory limiter, so rate-limit state never bleeds between tests). Route handlers keep using `Depends(get_settings)` for per-request config (still overridable); only construction-time concerns (CORS, limits, which view the connector introspects) come from the factory argument.

**Files:**
- Modify: `gateway/app.py`

- [ ] **Step 1: Replace `gateway/app.py` with:**

```python
"""FastAPI surface + the JSON RequestAdapter (spec §3, §5). POST /query only.
Dependencies (llm / connector / cache / settings) are injected so tests override
them. The app is built by create_app() so construction-time guardrails (CORS,
rate limits — see gateway/guardrails.py) can be configured per instance; the
module-level `app` is built from env settings with everything off by default."""
from __future__ import annotations

import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional, Union

from fastapi import Body, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from core.llm import LiteLLM
from core.prompts import OPS, want_system, where_system
from gateway.cache import ResolutionCache
from gateway.config import Settings
from gateway.connectors.base import schema_version
from gateway.connectors.postgres import PostgresConnector
from gateway.contracts import RawQuery
from gateway.gate import GateConfig
from gateway.guardrails import (GLOBAL_CODE, PER_IP_CODE, build_limiter,
                                install_guardrails)
from gateway.pipeline import GatewayError, run_query


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache(maxsize=1)
def get_cache() -> ResolutionCache:
    return ResolutionCache()


@lru_cache(maxsize=1)
def get_connector() -> PostgresConnector:
    s = get_settings()
    return PostgresConnector(s.database_url, view=s.db_view)


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


def check_input_limits(raw: RawQuery, settings: Settings):
    """Ingress size caps (config-driven). Returns (code, message) on violation, else
    None. Bounds the untrusted request before it reaches the LLM (cost/DoS)."""
    if len(raw.want) > settings.max_want_fields:
        return ("too_many_want_fields",
                f"`want` has {len(raw.want)} fields (max {settings.max_want_fields})")
    over = next((k for k in raw.want if len(k) > settings.max_field_len), None)
    if over is not None:
        return ("field_name_too_long",
                f"a `want` field name exceeds {settings.max_field_len} chars")
    if raw.where is not None and len(raw.where) > settings.max_where_len:
        return ("where_too_long",
                f"`where` exceeds {settings.max_where_len} chars")
    return None


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Build the app. `settings` fixes construction-time guardrails (CORS + rate
    limits); per-request config still flows through the get_settings dependency."""
    cfg = settings or get_settings()
    app = FastAPI(title="sans_schema — Semantic Query Gateway")
    limiter = build_limiter(cfg)
    install_guardrails(app, cfg, limiter)

    def query(request: Request,
              body: Dict[str, Any] = Body(...),
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
        violation = check_input_limits(raw, settings)
        if violation is not None:
            return JSONResponse(status_code=422,
                                content={"error": violation[0], "message": violation[1],
                                         "interpreted": {"want": {}}})
        try:
            return run_query(raw, connector, llm, cache,
                             GateConfig(threshold=settings.gate_threshold),
                             limit=settings.result_limit)
        except GatewayError as e:
            return JSONResponse(status_code=e.status,
                                content={"error": e.code, "message": e.message,
                                         "interpreted": e.interpreted})

    # slowapi decorators wrap the endpoint fn; applied only when configured so the
    # default (local dev / tests) request path contains no limiter at all. slowapi
    # requires the `request: Request` parameter above.
    if cfg.daily_request_cap:
        query = limiter.limit(cfg.daily_request_cap,
                              key_func=lambda request: "global",
                              error_message=GLOBAL_CODE)(query)
    if cfg.rate_limit_per_ip:
        query = limiter.limit(cfg.rate_limit_per_ip, error_message=PER_IP_CODE)(query)
    app.post("/query")(query)

    # --- debug introspection (dev only; OFF unless ENABLE_DEBUG_ENDPOINTS is set) --
    # When disabled these 404 (not advertised). /debug/schema and /debug/cache
    # DISCLOSE backend schema, sample values, and query history — never expose
    # publicly.

    disabled = JSONResponse(status_code=404, content={"error": "not_found"})

    @app.get("/debug/prompts")
    def debug_prompts(settings: Settings = Depends(get_settings)):
        """The static resolver prompts the gateway sends the model (no backend data)."""
        if not settings.enable_debug_endpoints:
            return disabled
        return {
            "system": {"want": want_system(), "where": where_system()},
            "operators": sorted(OPS),
            "prompt_cache_layout":
                "system[instructions] + system[schema + cache_control] + user[request]",
        }

    @app.get("/debug/schema")
    def debug_schema(settings: Settings = Depends(get_settings),
                     connector=Depends(get_connector)):
        """The introspected backend schema as the resolver sees it — the 'schema
        prompt'. DISCLOSES column names, descriptions, and sample values."""
        if not settings.enable_debug_endpoints:
            return disabled
        try:
            schema = connector.describe()
        except Exception as e:  # noqa: BLE001
            return JSONResponse(status_code=502,
                                content={"error": "backend_error", "message": str(e)})
        return {
            "backend_id": connector.backend_id,
            "schema_version": schema_version(schema),
            "as_prompt": schema.as_prompt(),
            "fields": [{"path": f.path, "type": f.type, "description": f.description,
                        "samples": f.samples} for f in schema.fields],
        }

    @app.get("/debug/cache")
    def debug_cache(settings: Settings = Depends(get_settings),
                    cache: ResolutionCache = Depends(get_cache)):
        """Current resolution-cache contents — the cached `want`-field and
        `where`-phrase resolutions (raw field/ast + confidence, before the gate)."""
        if not settings.enable_debug_endpoints:
            return disabled
        snap = cache.snapshot()
        return {
            "stats": cache.stats(),             # hit/miss counters + hit_rate since start
            "field": snap["field"],
            "where": snap["where"],
            "field_count": len(snap["field"]) if snap["field"] is not None else None,
            "where_count": len(snap["where"]) if snap["where"] is not None else None,
        }

    return app


app = create_app()
```

- [ ] **Step 2: Run the full suite (the refactor's safety net)**

Run: `pytest tests/ -v`
Expected: everything that passed before still passes (Postgres-backed tests skip without a local DB — that's normal). `tests/gateway/test_app.py` imports `app, get_llm, get_connector, get_settings, get_cache` — all still module-level, so it runs unmodified.

- [ ] **Step 3: Write + run a test for the DB_VIEW wiring**

Append to `tests/gateway/test_config.py`:

```python
def test_get_connector_uses_db_view(monkeypatch):
    monkeypatch.setenv("DB_VIEW", "inventory_view")
    import gateway.app as ga
    ga.get_settings.cache_clear()
    ga.get_connector.cache_clear()
    try:
        assert ga.get_connector().view == "inventory_view"
        assert ga.get_connector().backend_id == "postgres:inventory_view"
    finally:
        ga.get_settings.cache_clear()   # don't leak the patched settings
        ga.get_connector.cache_clear()
```

Run: `pytest tests/gateway/test_config.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add gateway/app.py tests/gateway/test_config.py
git commit -m "refactor(gateway): create_app() factory; connector view from DB_VIEW"
```

### Task 4: CORS

**Files:**
- Modify: `tests/gateway/test_guardrails.py`

- [ ] **Step 1: Add the app-level test helpers + failing CORS tests**

Add to `tests/gateway/test_guardrails.py` (top: extend the imports; bottom: the tests):

```python
from gateway.app import create_app, get_connector, get_llm
from gateway.connectors.fake import FakeConnector
from tests.fakes import FakeLLM

WANT_OK = {"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}}
BODY = {"want": ["book_title"]}


def _client(settings):
    """A fresh app per test — fresh in-memory limiter storage, no state bleed."""
    app = create_app(settings)
    app.dependency_overrides[get_connector] = lambda: FakeConnector()
    app.dependency_overrides[get_llm] = lambda: FakeLLM(want=WANT_OK)
    return TestClient(app)


def test_cors_preflight_allows_configured_origin():
    c = _client(_settings(cors_origins=["https://play.example.com"]))
    r = c.options("/query", headers={"Origin": "https://play.example.com",
                                     "Access-Control-Request-Method": "POST"})
    assert r.headers["access-control-allow-origin"] == "https://play.example.com"


def test_cors_rejects_unlisted_origin():
    c = _client(_settings(cors_origins=["https://play.example.com"]))
    r = c.options("/query", headers={"Origin": "https://evil.example.com",
                                     "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/gateway/test_guardrails.py -v`
Expected: PASS already — `install_guardrails` (Task 2) adds `CORSMiddleware` when origins are configured, and Task 3 wired it into `create_app`. If these fail, the wiring is broken; fix before proceeding. (Green-on-first-run is expected here because CORS shipped inside Task 2's module to keep it one coherent file.)

- [ ] **Step 3: Commit**

```bash
git add tests/gateway/test_guardrails.py
git commit -m "test(gateway): CORS allowlist behavior"
```

### Task 5: Per-IP rate limit + friendly 429

**Files:**
- Modify: `tests/gateway/test_guardrails.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_per_ip_limit_returns_friendly_429():
    c = _client(_settings(rate_limit_per_ip="2/minute"))
    assert c.post("/query", json=BODY).status_code == 200
    assert c.post("/query", json=BODY).status_code == 200
    r = c.post("/query", json=BODY)
    assert r.status_code == 429
    assert r.json() == {"error": "rate_limited",
                        "message": r.json()["message"]}   # code exact; message non-empty
    assert r.json()["message"]


def test_per_ip_limit_keys_on_proxy_header():
    c = _client(_settings(rate_limit_per_ip="1/minute", client_ip_header="Fly-Client-IP"))
    ok = c.post("/query", json=BODY, headers={"Fly-Client-IP": "1.1.1.1"})
    assert ok.status_code == 200
    # a different visitor is NOT throttled by the first one's traffic
    other = c.post("/query", json=BODY, headers={"Fly-Client-IP": "2.2.2.2"})
    assert other.status_code == 200
    # the first visitor again → limited
    again = c.post("/query", json=BODY, headers={"Fly-Client-IP": "1.1.1.1"})
    assert again.status_code == 429
```

- [ ] **Step 2: Run tests to verify the state**

Run: `pytest tests/gateway/test_guardrails.py -v`
Expected: PASS if Tasks 2–3 are correct (the decorator wiring already exists). If `test_per_ip_limit_keys_on_proxy_header` fails with everyone sharing one bucket, the limiter's `key_func` isn't reading `client_ip` — that's the exact proxy gotcha the spec calls load-bearing; fix `build_limiter`/`client_ip` until green.

- [ ] **Step 3: Commit**

```bash
git add tests/gateway/test_guardrails.py
git commit -m "test(gateway): per-IP rate limit + proxy-header keying + friendly 429"
```

### Task 6: Global daily cap

**Files:**
- Modify: `tests/gateway/test_guardrails.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_global_daily_cap_throttles_across_ips():
    c = _client(_settings(daily_request_cap="2/day", client_ip_header="Fly-Client-IP"))
    assert c.post("/query", json=BODY, headers={"Fly-Client-IP": "1.1.1.1"}).status_code == 200
    assert c.post("/query", json=BODY, headers={"Fly-Client-IP": "2.2.2.2"}).status_code == 200
    r = c.post("/query", json=BODY, headers={"Fly-Client-IP": "3.3.3.3"})
    assert r.status_code == 429
    assert r.json()["error"] == "demo_budget_exhausted"
```

- [ ] **Step 2: Run it**

Run: `pytest tests/gateway/test_guardrails.py::test_global_daily_cap_throttles_across_ips -v`
Expected: PASS (constant `"global"` key_func from Task 3). If it returns `rate_limited` instead of `demo_budget_exhausted`, the `error_message` → handler mapping is broken in `guardrails.py`.

- [ ] **Step 3: Commit**

```bash
git add tests/gateway/test_guardrails.py
git commit -m "test(gateway): global daily request cap with budget-exhausted 429"
```

### Task 7: Defaults-off regression + docs for the new config

**Files:**
- Modify: `tests/gateway/test_guardrails.py`, `.env.example`, `gateway/README.md`

- [ ] **Step 1: Write the defaults-off test**

Append to `tests/gateway/test_guardrails.py`:

```python
def test_defaults_off_no_limits_no_cors():
    c = _client(_settings())
    for _ in range(30):                       # far past any accidental default limit
        assert c.post("/query", json=BODY).status_code == 200
    r = c.post("/query", json=BODY, headers={"Origin": "https://anywhere.example"})
    assert "access-control-allow-origin" not in r.headers
```

Run: `pytest tests/ -v` — full suite green.

- [ ] **Step 2: Document the new env vars**

Append to `.env.example`:

```bash

# --- Public-demo guardrails (ALL OFF when empty — leave empty for local dev) ---
# slowapi rate strings (https://limits.readthedocs.io/): "10/minute", "1000/day".
RATE_LIMIT_PER_IP=
DAILY_REQUEST_CAP=
# Comma-separated browser origins allowed to call the API (the playground URL).
CORS_ORIGINS=
# Proxy header carrying the real visitor IP (Fly-Client-IP on Fly.io,
# X-Forwarded-For on Render/Railway). Empty → the socket peer address.
CLIENT_IP_HEADER=

# --- Backend view ---
# The flat (denormalized) view the gateway introspects. Point at your own view
# when running against your own data.
DB_VIEW=books_view
```

Add these rows to the config table in `gateway/README.md` (section 2):

```markdown
| `DB_VIEW`        | `books_view`                     | Flat view the connector introspects        |
| `RATE_LIMIT_PER_IP` | *(empty = off)*               | Per-visitor-IP rate limit, e.g. `10/minute`|
| `DAILY_REQUEST_CAP` | *(empty = off)*               | Global daily request cap, e.g. `1000/day`  |
| `CORS_ORIGINS`   | *(empty = off)*                  | Comma-separated browser origins allowed    |
| `CLIENT_IP_HEADER` | *(empty = off)*                | Proxy header with the real visitor IP      |
```

- [ ] **Step 3: Commit — Phase 1 done**

```bash
git add tests/gateway/test_guardrails.py .env.example gateway/README.md
git commit -m "feat(gateway): document demo guardrails; defaults-off regression test"
```

---

# Phase 2 — Playground frontend

Hand-rolled Next.js scaffold (deterministic — no `create-next-app` interactivity), TypeScript, no Tailwind. The browser calls the gateway directly (`NEXT_PUBLIC_GATEWAY_URL`); every request sends `isVerbose: true` so the `interpreted` echo — the star — is always present. Testing is a manual pass per the spec.

### Task 8: Scaffold

**Files:**
- Create: `playground/package.json`, `playground/tsconfig.json`, `playground/next.config.mjs`, `playground/.gitignore`, `playground/app/layout.tsx`, `playground/app/globals.css`, `playground/app/page.tsx` (placeholder, replaced in Task 10)

- [ ] **Step 1: Create `playground/package.json`**

```json
{
  "name": "sans-schema-playground",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "next": "^15",
    "react": "^19",
    "react-dom": "^19"
  },
  "devDependencies": {
    "@types/node": "^22",
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "typescript": "^5"
  }
}
```

- [ ] **Step 2: Create `playground/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Create `playground/next.config.mjs`**

```js
/** @type {import('next').NextConfig} */
const nextConfig = {};

export default nextConfig;
```

- [ ] **Step 4: Create `playground/.gitignore`**

```
node_modules/
.next/
out/
*.tsbuildinfo
.env*.local
.vercel
```

- [ ] **Step 5: Create `playground/app/layout.tsx`**

```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "sans_schema playground",
  description: "Query a database you've never seen, in your own words.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 6: Create `playground/app/globals.css`**

```css
:root {
  --bg: #f7f6f3;
  --panel: #ffffff;
  --ink: #1f2328;
  --muted: #6a737d;
  --accent: #6d4aff;
  --accent-soft: #efeaff;
  --border: #e1e0dc;
  --good: #1a7f37;
  --mid: #b58a00;
  --bad: #c0392b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 16px/1.55 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
}
main { max-width: 880px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
header h1 { margin: 0 0 0.25rem; font-size: 1.7rem; }
header > p { margin: 0 0 2rem; color: var(--muted); }
h2 { font-size: 1.05rem; margin: 0 0 0.75rem; }
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.25rem;
  margin-bottom: 1.25rem;
}
.framing { margin: 0 0 1rem; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.25rem; }
.chip {
  border: 1px solid var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: 999px;
  padding: 0.3rem 0.9rem;
  font-size: 0.85rem;
  cursor: pointer;
}
.chip:hover:not(:disabled) { background: var(--accent); color: #fff; }
.label { display: block; font-weight: 600; font-size: 0.85rem; margin: 0.9rem 0 0.35rem; }
.want-row { display: flex; gap: 0.5rem; margin-bottom: 0.5rem; }
input, textarea {
  width: 100%;
  padding: 0.5rem 0.65rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  font: inherit;
}
.want-row button {
  border: 1px solid var(--border);
  background: none;
  border-radius: 6px;
  width: 2.2rem;
  cursor: pointer;
}
.add { border: none; background: none; color: var(--accent); cursor: pointer; padding: 0; font-size: 0.85rem; }
.run {
  margin-top: 1rem;
  width: 100%;
  padding: 0.65rem;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.run:disabled { opacity: 0.5; cursor: default; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border); }
th { color: var(--accent); font-size: 0.8rem; }
.interpreted { border: 2px solid var(--accent); background: var(--accent-soft); }
.interpreted ul { list-style: none; margin: 0; padding: 0; }
.interpreted li { margin-bottom: 0.4rem; }
code.yours { background: #fff; border: 1px solid var(--accent); border-radius: 4px; padding: 0.1rem 0.35rem; }
code.theirs { background: var(--ink); color: #fff; border-radius: 4px; padding: 0.1rem 0.35rem; }
.conf { font-size: 0.75rem; font-weight: 700; margin-left: 0.35rem; }
.conf.high { color: var(--good); }
.conf.mid { color: var(--mid); }
.conf.low { color: var(--bad); }
.where-echo pre {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.75rem;
  overflow-x: auto;
  font-size: 0.8rem;
}
.status { border-left: 4px solid var(--mid); }
.status.budget { border-left-color: var(--bad); }
.status .raw { color: var(--muted); font-size: 0.8rem; }
.empty { color: var(--muted); }
footer { margin-top: 2rem; }
pre.block {
  background: #14161a;
  color: #e6e6e6;
  padding: 1rem;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 0.85rem;
}
.steps li { margin-bottom: 1.25rem; }
```

- [ ] **Step 7: Create a placeholder `playground/app/page.tsx`** (replaced in Task 10)

```tsx
export default function Home() {
  return (
    <main>
      <h1>sans_schema playground</h1>
    </main>
  );
}
```

- [ ] **Step 8: Verify it boots**

```bash
cd playground && npm install && npm run dev
```

Expected: `http://localhost:3000` renders the placeholder heading. Stop the server.

- [ ] **Step 9: Commit**

```bash
git add playground/package.json playground/package-lock.json playground/tsconfig.json \
        playground/next.config.mjs playground/.gitignore playground/app
git commit -m "feat(playground): Next.js scaffold"
```

### Task 9: API client + example chips

**Files:**
- Create: `playground/lib/api.ts`, `playground/lib/examples.ts`

- [ ] **Step 1: Create `playground/lib/api.ts`**

Mirrors the gateway contract: 200 → `{rows, interpreted}` (we always send `isVerbose: true`); 4xx/5xx → `{error, message, interpreted?}` (`interpreted` present on 422 gate refusals — worth rendering).

```tsx
export type Interpreted = {
  want: Record<string, { field: string | null; confidence: number }>;
  where?: { raw: string; ast: unknown; confidence: number | null };
};

export type QueryResponse = {
  rows: Record<string, unknown>[];
  interpreted?: Interpreted;
};

export type QueryError = {
  error: string;
  message: string;
  interpreted?: Interpreted;
};

export type QueryResult =
  | { ok: true; data: QueryResponse }
  | { ok: false; status: number; data: QueryError };

const GATEWAY = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";

export async function runQuery(want: string[], where: string | null): Promise<QueryResult> {
  const res = await fetch(`${GATEWAY}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ want, where, isVerbose: true }),
  });
  const data = await res.json();
  return res.ok ? { ok: true, data } : { ok: false, status: res.status, data };
}
```

- [ ] **Step 2: Create `playground/lib/examples.ts`**

The chips double as the live-demo script (order matters — `docs/demo/script.md` walks them top to bottom) and as cache-warmed cheap queries. Field names are deliberately NOT the backend's column names — guessing fields is the pitch.

```tsx
export type Example = { label: string; want: string[]; where: string | null };

export const EXAMPLES: Example[] = [
  { label: "Just the basics",
    want: ["book name", "writer"], where: null },
  { label: "Same data, different words",
    want: ["headline", "penned by"], where: null },
  { label: "Sci-fi under $25",
    want: ["book name", "cost", "genre"],
    where: "science fiction cheaper than 25 dollars" },
  { label: "Too vague (watch it refuse)",
    want: ["book name"], where: "only the good ones" },
  { label: "Written in French",
    want: ["book name", "tongue"], where: "written in French" },
  { label: "Young authors",
    want: ["book name", "author", "author's birth year"],
    where: "author born after 1980" },
];
```

- [ ] **Step 3: Commit**

```bash
git add playground/lib
git commit -m "feat(playground): typed gateway client + example chips"
```

### Task 10: Components + main page

**Files:**
- Create: `playground/components/RequestBuilder.tsx`, `playground/components/ResultsTable.tsx`, `playground/components/InterpretedPanel.tsx`, `playground/components/StatusPanel.tsx`
- Modify: `playground/app/page.tsx` (replace the placeholder)

- [ ] **Step 1: Create `playground/components/RequestBuilder.tsx`**

```tsx
"use client";
import { Example, EXAMPLES } from "@/lib/examples";

type Props = {
  want: string[];
  where: string;
  busy: boolean;
  onWantChange: (fields: string[]) => void;
  onWhereChange: (where: string) => void;
  onRun: () => void;
  onExample: (ex: Example) => void;
};

export default function RequestBuilder(
  { want, where, busy, onWantChange, onWhereChange, onRun, onExample }: Props,
) {
  const setField = (i: number, v: string) =>
    onWantChange(want.map((f, j) => (j === i ? v : f)));
  return (
    <section className="panel">
      <p className="framing">
        This is a database of books. Ask for fields <em>in your own words</em> —
        the backend&apos;s real column names are hidden.
      </p>
      <div className="chips">
        {EXAMPLES.map((ex) => (
          <button key={ex.label} className="chip" disabled={busy}
                  onClick={() => onExample(ex)}>
            {ex.label}
          </button>
        ))}
      </div>
      <label className="label">want — the fields, in your words</label>
      {want.map((f, i) => (
        <div key={i} className="want-row">
          <input value={f} placeholder={`field ${i + 1}`}
                 onChange={(e) => setField(i, e.target.value)} />
          <button aria-label="remove field" disabled={want.length === 1}
                  onClick={() => onWantChange(want.filter((_, j) => j !== i))}>
            ×
          </button>
        </div>
      ))}
      <button className="add" onClick={() => onWantChange([...want, ""])}>
        + add field
      </button>
      <label className="label">where — a plain-language filter (optional)</label>
      <textarea value={where} rows={2}
                placeholder="e.g. science fiction under 25 dollars"
                onChange={(e) => onWhereChange(e.target.value)} />
      <button className="run" disabled={busy || want.every((f) => !f.trim())}
              onClick={onRun}>
        {busy ? "Running…" : "Run"}
      </button>
    </section>
  );
}
```

- [ ] **Step 2: Create `playground/components/ResultsTable.tsx`**

```tsx
export default function ResultsTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return <p className="empty">No rows matched.</p>;
  const cols = Object.keys(rows[0]);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>{row[c] === null ? "—" : String(row[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: Create `playground/components/InterpretedPanel.tsx`**

```tsx
import { Interpreted } from "@/lib/api";

function Confidence({ value }: { value: number | null }) {
  if (value === null) return null;
  const cls = value >= 0.9 ? "conf high" : value >= 0.7 ? "conf mid" : "conf low";
  return <span className={cls}>{Math.round(value * 100)}%</span>;
}

export default function InterpretedPanel({ interpreted }: { interpreted: Interpreted }) {
  return (
    <section className="panel interpreted">
      <h2>What the gateway understood</h2>
      <ul>
        {Object.entries(interpreted.want).map(([key, cell]) => (
          <li key={key}>
            <code className="yours">{key}</code>
            {" → "}
            {cell.field
              ? <code className="theirs">{cell.field}</code>
              : <em>declined (not confident enough)</em>}
            <Confidence value={cell.confidence} />
          </li>
        ))}
      </ul>
      {interpreted.where && (
        <div className="where-echo">
          <p>
            <strong>filter:</strong> “{interpreted.where.raw}”
            <Confidence value={interpreted.where.confidence} />
          </p>
          <pre>{JSON.stringify(interpreted.where.ast, null, 2)}</pre>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Create `playground/components/StatusPanel.tsx`**

Error states rendered as features: gate refusals get the "refusing beats guessing" framing; both 429 codes from Phase 1 get their own copy.

```tsx
import { QueryError } from "@/lib/api";

const FRIENDLY: Record<string, string> = {
  where_low_confidence:
    "The gateway wasn't confident enough about what this filter means, so it " +
    "refused instead of returning possibly-wrong rows. The refusal is the safety " +
    "feature. Try a more specific filter.",
  all_want_declined:
    "None of the field names resolved confidently, so the gateway declined the " +
    "whole request rather than guess.",
  rate_limited:
    "You're sending requests a little fast — wait a minute and try again.",
  demo_budget_exhausted:
    "The public demo's daily budget is used up. The gateway is open source — " +
    "run it against your own data below.",
};

export default function StatusPanel({ status, error }: { status: number; error: QueryError }) {
  const friendly = FRIENDLY[error.error];
  const budget = error.error === "demo_budget_exhausted";
  const title = status === 429 ? "Demo limits"
    : status === 422 ? "The gateway declined"
    : `Error ${status || "— network"}`;
  return (
    <section className={budget ? "panel status budget" : "panel status"}>
      <h2>{title}</h2>
      <p>{friendly ?? error.message}</p>
      {friendly && <p className="raw">({error.error}: {error.message})</p>}
      {budget && <p><a href="/own-data">→ Run it with your own data</a></p>}
    </section>
  );
}
```

- [ ] **Step 5: Replace `playground/app/page.tsx`**

```tsx
"use client";
import { useState } from "react";
import RequestBuilder from "@/components/RequestBuilder";
import ResultsTable from "@/components/ResultsTable";
import InterpretedPanel from "@/components/InterpretedPanel";
import StatusPanel from "@/components/StatusPanel";
import { runQuery, QueryError, QueryResponse } from "@/lib/api";
import { Example } from "@/lib/examples";

export default function Home() {
  const [want, setWant] = useState<string[]>(["book name", "writer"]);
  const [where, setWhere] = useState("");
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState<QueryResponse | null>(null);
  const [err, setErr] = useState<{ status: number; data: QueryError } | null>(null);

  async function run(w: string[] = want, wh: string = where) {
    setBusy(true);
    setOk(null);
    setErr(null);
    try {
      const fields = w.map((f) => f.trim()).filter(Boolean);
      const res = await runQuery(fields, wh.trim() || null);
      if (res.ok) setOk(res.data);
      else setErr({ status: res.status, data: res.data });
    } catch {
      setErr({ status: 0, data: { error: "network", message: "Could not reach the gateway." } });
    } finally {
      setBusy(false);
    }
  }

  function useExample(ex: Example) {
    setWant([...ex.want]);
    setWhere(ex.where ?? "");
    void run(ex.want, ex.where ?? "");
  }

  return (
    <main>
      <header>
        <h1>sans_schema playground</h1>
        <p>Query a database you&apos;ve never seen, in your own words.</p>
      </header>
      <RequestBuilder want={want} where={where} busy={busy}
                      onWantChange={setWant} onWhereChange={setWhere}
                      onRun={() => void run()} onExample={useExample} />
      {err && (
        <>
          <StatusPanel status={err.status} error={err.data} />
          {err.data.interpreted && <InterpretedPanel interpreted={err.data.interpreted} />}
        </>
      )}
      {ok && (
        <>
          <section className="panel">
            <h2>Rows — in <em>your</em> column names</h2>
            <ResultsTable rows={ok.rows} />
          </section>
          {ok.interpreted && <InterpretedPanel interpreted={ok.interpreted} />}
        </>
      )}
      <footer>
        <a href="/own-data">Try it with your own data →</a>
      </footer>
    </main>
  );
}
```

- [ ] **Step 6: Verify against a local gateway (manual, per the spec's testing section)**

```bash
# terminal 1 — Postgres seeded per gateway/README.md §1, then:
CORS_ORIGINS=http://localhost:3000 \
DATABASE_URL=postgresql://postgres:pg@localhost:5432/postgres \
GEMINI_API_KEY=<your key> \
uvicorn gateway.app:app --port 8000

# terminal 2
cd playground && npm run dev
```

Check at `http://localhost:3000`: each chip fills the form and runs; results table shows the made-up words as column headers; the interpreted panel shows resolved column + confidence + AST; the "Too vague" chip renders the friendly refusal (if the model confidently resolves it instead, note it — the chip phrasing gets locked during the Phase 3 dry run); `npm run build` also completes cleanly.

- [ ] **Step 7: Commit**

```bash
git add playground/components playground/app/page.tsx
git commit -m "feat(playground): request builder, results table, interpreted echo, error states"
```

### Task 11: "Try with your own data" page

**Files:**
- Create: `playground/app/own-data/page.tsx`

- [ ] **Step 1: Create the page**

```tsx
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Run it on your own data — sans_schema",
};

const STEP1 = `git clone https://github.com/SansWord/sans_schema.git
cd sans_schema
docker build -t sans-schema .`;

const STEP2 = `docker run -p 8000:8000 \\
  -e DATABASE_URL="postgresql://user:pass@host:5432/yourdb" \\
  -e DB_VIEW="your_flat_view" \\
  -e LLM_MODEL="gemini/gemini-3.1-flash-lite" \\
  -e GEMINI_API_KEY="<your key>" \\
  sans-schema`;

const STEP3 = `curl -s localhost:8000/query \\
  -H 'Content-Type: application/json' \\
  -d '{"want": ["any field, in your words"],
       "where": "a plain-language filter",
       "isVerbose": true}'`;

export default function OwnData() {
  return (
    <main>
      <header>
        <h1>Run it on your own data</h1>
        <p>
          Three steps: build the gateway, point it at your Postgres with your own
          LLM key, and query it in your own words.
        </p>
      </header>
      <section className="panel">
        <ol className="steps">
          <li>
            <strong>Build the image</strong>
            <pre className="block">{STEP1}</pre>
          </li>
          <li>
            <strong>Run it against your database</strong>
            <p>
              The gateway introspects one flat (denormalized) view — point{" "}
              <code>DB_VIEW</code> at yours. Column comments improve resolution.
              Any LiteLLM model id works; set the matching provider key.
            </p>
            <pre className="block">{STEP2}</pre>
          </li>
          <li>
            <strong>Query it in your own words</strong>
            <pre className="block">{STEP3}</pre>
          </li>
        </ol>
        <p>
          Full quickstart (local Postgres, seed data, every env var):{" "}
          <a href="https://github.com/SansWord/sans_schema/blob/main/gateway/README.md">
            gateway/README.md
          </a>
        </p>
      </section>
      <footer>
        <a href="/">← Back to the playground</a>
      </footer>
    </main>
  );
}
```

- [ ] **Step 2: Verify** — with `npm run dev` still up, `http://localhost:3000/own-data` renders the three copy-paste blocks; the footer link on the main page reaches it.

- [ ] **Step 3: Commit**

```bash
git add playground/app/own-data
git commit -m "feat(playground): own-data quickstart page"
```

### Task 12: Manual test pass — error states end-to-end

Per the spec's testing section: happy path, gate refusal, both 429s, rendered in the browser.

- [ ] **Step 1: Restart the local gateway with tiny limits**

```bash
CORS_ORIGINS=http://localhost:3000 RATE_LIMIT_PER_IP=3/minute DAILY_REQUEST_CAP=6/day \
DATABASE_URL=postgresql://postgres:pg@localhost:5432/postgres \
GEMINI_API_KEY=<your key> \
uvicorn gateway.app:app --port 8000
```

- [ ] **Step 2: In the browser, verify all four states**

1. Happy path — a chip returns rows + interpreted panel.
2. Gate refusal — "Too vague" chip shows the friendly refusal copy (+ its interpreted echo with the low confidence).
3. Per-IP 429 — click Run 4× fast → "Demo limits / …wait a minute…" panel.
4. Budget 429 — keep clicking past 6 total → "daily budget is used up" panel with the own-data link.

- [ ] **Step 3: Nothing to commit** (no code changed) — note any copy/behavior fixes and commit those if made.

---

# Phase 3 — Deployment

Operator-in-the-loop tasks (need `fly`/`vercel` auth — run the CLI steps yourself or via `!` in the session). Names assumed throughout: Fly app **`sans-schema-demo`**, Fly Postgres **`sans-schema-demo-db`**, Vercel project **`sans-schema-playground`** (URL `https://sans-schema-playground.vercel.app`). If any name is taken, pick another and update `fly.toml` `CORS_ORIGINS`, the Vercel env var, and the slide/script URLs consistently.

### Task 13: `fly.toml` + deploy runbook

**Files:**
- Create: `fly.toml`
- Create: `gateway/DEPLOY.md`

- [ ] **Step 1: Create `fly.toml`**

```toml
# Fly.io config for the public demo gateway. Runbook: gateway/DEPLOY.md.
app = "sans-schema-demo"
primary_region = "nrt"

[build]
  dockerfile = "Dockerfile"

[env]
  LLM_MODEL = "gemini/gemini-3.1-flash-lite"
  RATE_LIMIT_PER_IP = "10/minute"
  DAILY_REQUEST_CAP = "1000/day"
  CLIENT_IP_HEADER = "Fly-Client-IP"
  CORS_ORIGINS = "https://sans-schema-playground.vercel.app,http://localhost:3000"
  # ENABLE_DEBUG_ENDPOINTS deliberately unset — /debug/* must 404 on the public URL.
  # DATABASE_URL and GEMINI_API_KEY are secrets (fly secrets set / postgres attach).

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

- [ ] **Step 2: Create `gateway/DEPLOY.md`**

```markdown
# Public demo deployment — runbook

Gateway + tiny Postgres on Fly.io, playground on Vercel. Config lives in
`fly.toml` (guardrails on: 10/min per IP, 1000/day global, CORS allowlist,
`Fly-Client-IP` as the rate-limit key). Railway/Render are drop-in fallbacks —
set `CLIENT_IP_HEADER=X-Forwarded-For` there.

## One-time setup

```bash
fly auth login
fly apps create sans-schema-demo

# Tiny Postgres + attach (attach sets the DATABASE_URL secret on the app)
fly postgres create --name sans-schema-demo-db --region nrt \
    --initial-cluster-size 1 --vm-size shared-cpu-1x --volume-size 1
fly postgres attach sans-schema-demo-db -a sans-schema-demo
# ^ prints a connection string — save it for seeding below.

# Seed once (proxy the DB locally; use the credentials attach printed)
fly proxy 15432:5432 -a sans-schema-demo-db
psql "<attach-connection-string, host swapped to localhost:15432>" \
    < gateway/demo/seed.sql

# LLM key
fly secrets set GEMINI_API_KEY=<key> -a sans-schema-demo

fly deploy
```

## Vendor backstop — the money stop (operator action, load-bearing)

Set a **quota limit** (requests/day) on the Gemini API key's Google Cloud
project: Console → APIs & Services → Generative Language API → Quotas →
requests per day → cap it (e.g. 2000/day). A billing *budget* only alerts;
the *quota* cap is what actually stops spend if every other guardrail fails.

## Verify after deploy

```bash
BASE=https://sans-schema-demo.fly.dev
# happy path → 200 with rows in the made-up keys
curl -s $BASE/query -H 'Content-Type: application/json' \
  -d '{"want": ["book name", "writer"], "isVerbose": true}'
# debug endpoints must be dark → 404
curl -s -o /dev/null -w "%{http_code}\n" $BASE/debug/schema
# per-IP limit → 429 {"error":"rate_limited"} after ~10 rapid requests
for i in $(seq 1 12); do curl -s -o /dev/null -w "%{http_code} " \
  -X POST $BASE/query -H 'Content-Type: application/json' \
  -d '{"want":["book name"]}'; done; echo
```

The 429 drill consumes the daily budget — do it before the session day, or bump
`DAILY_REQUEST_CAP` temporarily.

## Playground (Vercel)

```bash
cd playground
vercel link                       # project name: sans-schema-playground
vercel env add NEXT_PUBLIC_GATEWAY_URL production
#   value: https://sans-schema-demo.fly.dev
vercel --prod
```

If the production URL differs from `https://sans-schema-playground.vercel.app`,
update `CORS_ORIGINS` in `fly.toml` and `fly deploy` again.

## Operator introspection

Never enable `ENABLE_DEBUG_ENDPOINTS` on the public deploy (`/debug/schema` and
`/debug/cache` disclose data). Inspect via `fly ssh console -a sans-schema-demo`
or a local deploy instead.

## Teardown

```bash
fly apps destroy sans-schema-demo
fly apps destroy sans-schema-demo-db
```
```

- [ ] **Step 3: Commit**

```bash
git add fly.toml gateway/DEPLOY.md
git commit -m "feat(deploy): Fly.io config + public-demo runbook (incl. vendor quota backstop)"
```

### Task 14: Deploy the gateway (operator)

- [ ] **Step 1:** Run the "One-time setup" block from `gateway/DEPLOY.md` top to bottom.
- [ ] **Step 2:** Set the Gemini quota cap per the "Vendor backstop" section — this is part of done, not optional.
- [ ] **Step 3:** Run the "Verify after deploy" block. Expected: 200 with rows / 404 / trailing `429`s. Confirm the 429 body says `rate_limited` and that a second machine/IP isn't needed (Fly-Client-IP keying verified by the unit tests; here just confirm the limit trips at all).

### Task 15: Deploy the playground (operator)

- [ ] **Step 1:** Run the "Playground (Vercel)" block from `gateway/DEPLOY.md`.
- [ ] **Step 2:** Browser pass against production — happy path chip, refusal chip, `/own-data` page, and the CORS reality check (requests succeed from the Vercel origin; from an unlisted origin they're blocked by the browser).
- [ ] **Step 3:** If the "Too vague" chip does not refuse against production, adjust its `where` phrasing in `playground/lib/examples.ts` until it reliably trips the gate (candidates: "only the good ones", "the interesting ones", "the ones worth reading"), redeploy, and commit:

```bash
git add playground/lib/examples.ts
git commit -m "fix(playground): lock refusal-chip phrasing verified against production"
```

---

# Phase 4 — Slide deck + demo script + close the loop

### Task 16: HTML slide deck

**Files:**
- Create: `playground/public/slides.html` (single copy, lives in the repo, auto-hosted at `https://sans-schema-playground.vercel.app/slides.html`)
- Create: `playground/public/qr.png`

- [ ] **Step 1: Create `playground/public/slides.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sans_schema — query a database you've never seen</title>
<style>
  :root { --bg:#14161a; --ink:#f2f0ea; --muted:#9aa3ad; --accent:#8f7aff;
          --panel:#1e2128; --good:#4cc38a; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--ink);
         font:22px/1.5 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif; }
  .slide { display:none; min-height:100vh; padding:8vh 10vw;
           flex-direction:column; justify-content:center; gap:1.2rem; }
  .slide.active { display:flex; }
  h1 { font-size:2.6rem; line-height:1.15; }
  h2 { font-size:2rem; color:var(--accent); }
  ul { padding-left:1.4rem; display:grid; gap:.6rem; }
  .muted { color:var(--muted); }
  .big { font-size:2rem; font-weight:700; }
  .url { color:var(--accent); font-weight:700; }
  pre, code { font-family:ui-monospace,Menlo,monospace; }
  pre { background:var(--panel); border-radius:10px; padding:1.1rem;
        font-size:.72em; overflow-x:auto; }
  .cols { display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; align-items:start; }
  .qr { width:180px; height:180px; background:#fff; padding:8px; border-radius:8px; }
  .counter { position:fixed; bottom:1rem; right:1.2rem; color:var(--muted); font-size:.7rem; }
  .stat { color:var(--good); font-weight:700; }
  .hourglass { display:flex; flex-direction:column; align-items:flex-start;
               gap:.35rem; font-size:.85em; }
  .hg { border:2px solid var(--muted); border-radius:8px; padding:.35rem 1.1rem; }
  .hg.waist { border-color:var(--good); font-weight:700; }
  .arrow { color:var(--muted); padding-left:1.2rem; }
</style>
</head>
<body>

<section class="slide"><!-- 1 · title -->
  <h1>Query a database you've never seen,<br>in your own words</h1>
  <p class="muted">sans_schema — a Semantic Query Gateway</p>
  <div class="cols">
    <p class="big url">sans-schema-playground.vercel.app</p>
    <img class="qr" src="qr.png" alt="QR code to the playground">
  </div>
  <p class="muted">Open it now — you'll use it during the talk.</p>
</section>

<section class="slide"><!-- 2 · the problem -->
  <h2>Every client hardcodes someone else's schema</h2>
  <ul>
    <li>Your code says <code>author_name</code>. Theirs says <code>writer</code>.
        The next API says <code>author.full_name</code>.</li>
    <li>Every consumer re-learns every backend's vocabulary.</li>
    <li>Every rename breaks every consumer.</li>
  </ul>
</section>

<section class="slide"><!-- 3 · the idea -->
  <h2>{want, where} — your words, their data</h2>
  <div class="cols">
    <pre>POST /query
{
  "want": ["book name", "writer", "cost"],
  "where": "science fiction under 25 dollars"
}</pre>
    <pre>{
  "rows": [
    { "book name": "Future Shock 2026",
      "writer": "SansWord",
      "cost": 15.0 } ],
  "interpreted": {
    "want": { "writer": {
      "field": "books_view.author_name",
      "confidence": 0.95 } },
    "where": { "ast": { "op": "and", … },
               "confidence": 0.9 } }
}</pre>
  </div>
  <p><code>want</code>: fields in <em>your</em> vocabulary ·
     <code>where</code>: a plain-language filter ·
     the answer comes back <em>in your keys</em>, with an inspectable
     <code>interpreted</code> echo.</p>
</section>

<section class="slide"><!-- 4 · how it stays safe -->
  <h2>How it stays safe</h2>
  <p class="big">NL → <span class="stat">validated predicate AST</span> → execute.
     Never NL → SQL.</p>
  <div class="hourglass">
    <span class="hg">RequestAdapter — your protocol, your words</span>
    <span class="arrow">↓ RawQuery</span>
    <span class="hg waist">resolver — AST checked against an operator whitelist
      + the real fields (the injection boundary, in code)</span>
    <span class="arrow">↓ CanonicalQueryIR</span>
    <span class="hg">Connector — parameterized SQL on a real Postgres</span>
  </div>
  <p class="muted">A hijacked model can at worst mis-resolve inside the allowed
     schema — it can never emit SQL.</p>
</section>

<section class="slide"><!-- 5 · does it work -->
  <h2>Does it work?</h2>
  <ul>
    <li>Field resolution (<code>want</code>): <span class="stat">100%</span></li>
    <li>Filter compilation (<code>where</code>): <span class="stat">98%</span></li>
    <li class="muted">across 9 models, 3 vendors — scored by execution
        equivalence (same rows selected)</li>
    <li>Below-confidence requests are <strong>refused, not guessed</strong> —
        the gate is a feature.</li>
  </ul>
</section>

<section class="slide"><!-- 6 · live demo -->
  <h2>Live demo</h2>
  <p class="big url">sans-schema-playground.vercel.app</p>
  <p class="muted">Made-up field names → real answers. Watch the
     <em>interpreted</em> panel.</p>
</section>

<section class="slide"><!-- 7 · your own data -->
  <h2>Try it with your own data</h2>
  <ol style="display:grid;gap:.6rem;padding-left:1.4rem">
    <li><code>git clone</code> + <code>docker build</code></li>
    <li><code>docker run</code> with your <code>DATABASE_URL</code> + your LLM key</li>
    <li><code>curl</code> it in your own words</li>
  </ol>
  <div class="cols">
    <p class="big url">sans-schema-playground.vercel.app/own-data</p>
    <img class="qr" src="qr.png" alt="QR code to the playground">
  </div>
</section>

<section class="slide"><!-- 8 · what's deliberately not solved -->
  <h2>Deliberately not solved yet</h2>
  <ul>
    <li><strong>Authorization</strong> — the gateway is a curated single view today;
        field-level authz is its own milestone.</li>
    <li><strong>Messy schemas</strong> — accuracy is measured on a clean schema;
        cryptic legacy columns are the next benchmark.</li>
    <li><strong>Agent-traffic cache economics</strong> — the cost model leans on
        cache hits; agents invent novel phrasings.</li>
  </ul>
  <p class="muted">Stated limits are how you know the numbers are honest.</p>
</section>

<section class="slide"><!-- 9 · thanks -->
  <h2>Thanks</h2>
  <ul>
    <li>Repo: <span class="url">github.com/SansWord/sans_schema</span></li>
    <li>Playground: <span class="url">sans-schema-playground.vercel.app</span></li>
    <li>Contact: <span class="url">sansword@gmail.com</span></li>
  </ul>
</section>

<div class="counter"><span id="n"></span> · ← →</div>
<script>
  const slides = [...document.querySelectorAll('.slide')];
  let i = Math.min(Math.max((parseInt(location.hash.slice(1)) || 1) - 1, 0),
                   slides.length - 1);
  function show(k) {
    i = (k + slides.length) % slides.length;
    slides.forEach((s, j) => s.classList.toggle('active', j === i));
    location.hash = i + 1;
    document.getElementById('n').textContent = (i + 1) + ' / ' + slides.length;
  }
  addEventListener('keydown', (e) => {
    if (['ArrowRight', 'ArrowDown', ' ', 'PageDown'].includes(e.key)) { e.preventDefault(); show(i + 1); }
    if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(e.key)) { e.preventDefault(); show(i - 1); }
  });
  show(i);
</script>
</body>
</html>
```

If the deployed playground URL differs from `sans-schema-playground.vercel.app`, replace it in slides 1, 6, 7, and 9.

- [ ] **Step 2: Generate the QR code**

```bash
brew install qrencode   # if not installed
qrencode -o playground/public/qr.png -s 10 "https://sans-schema-playground.vercel.app"
```

- [ ] **Step 3: Verify** — `open playground/public/slides.html`: arrow keys move through 9 slides, counter updates, QR renders and scans to the playground.

- [ ] **Step 4: Commit + redeploy**

```bash
git add playground/public/slides.html playground/public/qr.png
git commit -m "feat(demo): self-contained HTML slide deck + QR"
cd playground && vercel --prod   # deck now live at /slides.html
```

### Task 17: Demo script

**Files:**
- Create: `docs/demo/script.md`

- [ ] **Step 1: Create `docs/demo/script.md`**

```markdown
# Demo script — 25-minute session

~8 min slides (`playground/public/slides.html`, hosted at
`https://sans-schema-playground.vercel.app/slides.html`) → ~12 min live demo →
~5 min "now you try it". The playground URL/QR is on screen from slide 1.

The live demo is driven by the playground's example chips, top to bottom
(`playground/lib/examples.ts` — chip order IS the script order).

## Live demo (~12 min)

### 1. Want-only — chip "Just the basics" (~2 min)
Click it. Point at the column headers: `book name`, `writer` — words we made up
seconds ago, now column headers. Say: "I never read this database's schema. The
gateway resolved my words to its columns — see the interpreted panel."

### 2. The core trick — chip "Same data, different words" (~2 min)
Click it. Same rows, but the columns are now `headline` / `penned by`. Say:
"Two clients with different vocabularies, zero shared schema, same backend.
That's the pitch in one click."

### 3. Plain-language filter — chip "Sci-fi under $25" (~3 min)
Click it. Walk the interpreted panel slowly: each want field → resolved column
+ confidence; the where phrase → the predicate AST. Emphasize: "the model emits
a constrained AST, code validates it against an operator whitelist and the real
fields, and only then does parameterized SQL run. Natural language never touches
SQL."

### 4. Refusal as a feature — chip "Too vague (watch it refuse)" (~2 min)
Click it. The gateway declines: confidence below threshold → HTTP 422, no rows.
Say: "silently returning plausible-but-wrong rows is the real failure mode.
Refusing to guess is the safety feature." (Phrasing was locked during the dry
run — if it ever resolves confidently, make the filter vaguer live and let it
refuse.)

### 5. The cache — re-click chip "Sci-fi under $25" (~1.5 min)
Instant this time. Say: "resolution is cached per backend schema — a repeat
question skips the LLM entirely. Repeat queries cost approximately nothing."

### 6. Invite the room (~1.5 min)
Back to slide 6/7: "the URL is on screen — try your own words while I take
questions. If it says the demo budget ran out, that's a guardrail, not a crash —
the own-data page shows how to run it yourself in three steps."

Extra chips ("Written in French", "Young authors") are ammunition for audience
suggestions, not scripted.

## Dry run — the day before (spec: one full pass on the real deployment)

- [ ] Open the production playground; click every chip once (warms the
      resolution cache AND validates the happy paths).
- [ ] Chip 4 refuses (422, friendly copy). If not: adjust its phrasing in
      `playground/lib/examples.ts`, redeploy, re-verify.
- [ ] Re-click chip 3 — visibly faster (cache hit).
- [ ] `curl -s -o /dev/null -w "%{http_code}" https://sans-schema-demo.fly.dev/debug/schema` → 404.
- [ ] Slides load at `/slides.html`; arrow keys work; QR on slide 1 scans from a
      phone to the playground.
- [ ] `fly.toml` caps are the session values (10/minute, 1000/day) and the
      Gemini quota cap is still set.
- [ ] `/own-data` page: copy-paste the three blocks into a terminal — they run.
```

- [ ] **Step 2: Commit**

```bash
git add docs/demo/script.md
git commit -m "docs(demo): 25-minute session script + dry-run checklist"
```

### Task 18: Dry run (operator)

- [ ] **Step 1:** Execute the "Dry run" checklist at the bottom of `docs/demo/script.md` against production. Fix anything that fails (chip phrasing, caps, URLs) and commit those fixes with explicit paths.

### Task 19: Close the loop — maintained docs, devlog, todo

Per `CLAUDE.md`, this is a gate: the milestone isn't done until the maintained docs match the shipped state.

**Files:**
- Modify: `docs/architecture.md`, `docs/system-design.md`, `docs/devlog.md`, `todo.md`

- [ ] **Step 1: `docs/architecture.md`** — two edits:

(a) In **§6 Security**, append to the "Boundaries and hardening in place" list:

```markdown
- **Public-demo guardrails** (`gateway/guardrails.py`, env-driven, all OFF by default) —
  CORS origin allowlist (`CORS_ORIGINS`), per-visitor-IP rate limit (`RATE_LIMIT_PER_IP`,
  slowapi, in-memory), and a global daily request cap (`DAILY_REQUEST_CAP`, constant-key
  limit — request count, not spend; the vendor quota cap is the money backstop, see
  `gateway/DEPLOY.md`). Both 429s return friendly bodies (`rate_limited` /
  `demo_budget_exhausted`). Behind a PaaS proxy the limit keys on the platform's
  client-IP header (`CLIENT_IP_HEADER`, e.g. `Fly-Client-IP`) — `request.client` is the
  proxy and would throttle all visitors as one.
```

(b) In **§3**, at the end of the `Connector` bullet's field-path sub-bullet, add:

```markdown
    The view the Postgres connector introspects is configurable (`DB_VIEW`, default
    `books_view`) so an own-data deploy can point at its own flat view.
```

- [ ] **Step 2: `docs/system-design.md`** — add the playground to the component map: a `Playground (Next.js on Vercel)` box calling `POST /query` directly over CORS (no proxy layer), and a swap-matrix row noting the guardrail middleware (slowapi + CORSMiddleware) sits in front of `/query`, env-toggled. Match the file's existing Mermaid/table style when making the edit.

- [ ] **Step 3: `docs/devlog.md`** — newest-on-top entry + TL;DR row. Heading format `## v0.3.0 — Demo session: guardrails, playground, deploy, deck (YYYY-MM-DD HH:MM)` with the timestamp from `git log` (the docs/final commit). Skeleton — fill the learnings from what actually happened during execution:

```markdown
## v0.3.0 — Demo session: guardrails, playground, deploy, deck (YYYY-MM-DD HH:MM)

**Review:** not yet
**Design docs:**
- Demo Session: [Spec](superpowers/specs/2026-07-12-demo-session-design.md) [Plan](superpowers/plans/2026-07-12-demo-session.md)

**What was built:**
- Gateway demo-hardening: env-driven CORS + per-IP rate limit + global daily cap
  (slowapi), friendly 429s, proxy-aware IP keying, `DB_VIEW` — all off by default;
  `create_app()` factory for per-instance guardrail testing.
- Playground (`playground/`, Next.js on Vercel): request builder + example chips,
  results in the client's own keys, the `interpreted` echo as the centerpiece,
  error states rendered as features, own-data quickstart page.
- Deployment: Fly.io gateway + tiny Postgres (`fly.toml`, `gateway/DEPLOY.md`
  incl. the vendor quota backstop), playground on Vercel.
- 9-slide self-contained HTML deck (`playground/public/slides.html`) +
  demo script (`docs/demo/script.md`).

**Key technical learnings:**
- <fill from the session — tag each `[note]` / `[insight]` / `[gotcha]`>

**Process learnings:**
- <fill from the session, or drop the section>
```

- [ ] **Step 4: `todo.md`** — mark the "Demo site / playground" item (under *MVP shape & setup*) done with a pointer to v0.3.0; replace the "Next milestone: undecided" block (the demo site was picked and shipped; remaining candidates: `bind_today`, security milestone, richer demo dataset — the dataset item stays open as the stretch goal that didn't ship).

- [ ] **Step 5: Full suite + secret scan + commit**

```bash
pytest tests/ -v            # green
git diff --name-only        # confirm scope: only the files this plan names
# secret scan (load-bearing before any push — public repo):
git diff --cached -U0 | grep -iE "api[_-]?key|secret|token|password" || true
git add docs/architecture.md docs/system-design.md docs/devlog.md todo.md
git commit -m "docs: close the loop for v0.3.0 (demo session)"
```

Then stop — pushing/tagging (`v0.3.0`) and any PR/merge is the user's call.

---

## Self-review notes (spec coverage)

Checked task-by-task against the spec: CORS ✓ (T2/T4) · per-IP limit ✓ (T5) · global cap ✓ (T6) · friendly 429s ✓ (T2/T5/T6) · config off-by-default ✓ (T1/T7) · proxy gotcha unit-tested ✓ (T2/T5) · vendor quota backstop documented ✓ (T13) · request builder + chips ✓ (T9/T10) · results table in client keys ✓ (T10) · interpreted echo emphasized ✓ (T10, `.interpreted` styling) · no field discovery, framing line instead ✓ (T10 RequestBuilder) · error states as features ✓ (T10 StatusPanel) · own-data page ✓ (T11) · Fly + seed + secrets + debug-off ✓ (T13/T14) · Vercel ✓ (T15) · 9 slides ✓ (T16) · demo script with all 6 beats ✓ (T17) · testing = guardrail unit tests + manual playground pass + one dry run ✓ (T5–T7/T12/T18) · stretch dataset explicitly excluded ✓.

Known judgment calls an executor should not "fix" silently: the `DB_VIEW` addition (flagged in the header), the `create_app()` factory refactor (test isolation for limiter state), and the deck living at `playground/public/slides.html` (one copy, auto-hosted) instead of `docs/`.
