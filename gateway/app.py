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
