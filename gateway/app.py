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
                                install_guardrails, validate_limits)
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
                    verbose=bool(body.get("isVerbose", False)),
                    debug=bool(body.get("isDebug", False)))


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
    validate_limits(cfg)   # fail fast — slowapi would swallow a bad limit string (fail-open)
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
    # Registration order is load-bearing: slowapi evaluates limits in registration
    # order and stops at the first failure, so the per-IP limit MUST be registered
    # before the global cap — otherwise requests already rejected per-IP would
    # still drain the shared daily budget (one hammering IP griefs the whole demo).
    if cfg.rate_limit_per_ip:
        query = limiter.limit(cfg.rate_limit_per_ip, error_message=PER_IP_CODE)(query)
    if cfg.daily_request_cap:
        # param name `request` is load-bearing — slowapi passes the request by param name
        query = limiter.limit(cfg.daily_request_cap,
                              key_func=lambda request: "global",
                              error_message=GLOBAL_CODE)(query)
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
