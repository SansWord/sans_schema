"""The 10-step flow (spec §5) + error semantics (spec §12). Steps 3/5 are lifted from
core/ (resolve_want, where_resolve); the rest is thin gateway glue."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.resolver import (resolve_want, where_resolve, validate_ast,
                           type_check_ast, WhereResult)
from core.schemas import Schema
from gateway.cache import ResolutionCache
from gateway.connectors.base import schema_version, ExecutionTrace
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


def _debug_block(gate: GateConfig, cache_status: Dict[str, Any],
                 trace: Optional[ExecutionTrace]) -> Dict[str, Any]:
    """The `debug` response block (request-transparency spec): gate threshold,
    per-key cache hit/miss, and the execution trace (None until something ran)."""
    execution = None
    if trace is not None and trace.engine is not None:
        execution = {"engine": trace.engine, "sql": trace.sql, "params": trace.params}
    return {"gate_threshold": gate.threshold, "cache": cache_status, "execution": execution}


def run_query(raw: RawQuery, connector, llm, cache: ResolutionCache,
              gate: GateConfig, limit: int, debug: bool = False) -> Dict[str, Any]:
    try:
        schema: Schema = connector.describe()                   # step 2 (memoized in-connector)
    except Exception as e:  # noqa: BLE001 — backend unreachable / introspection failed
        raise GatewayError(502, "backend_error",
                           f"backend schema introspection failed: {e}")
    sv = schema_version(schema)
    backend = connector.backend_id
    valid_fields = {f.path for f in schema.fields}
    cache_status: Dict[str, Any] = {"want": {}}

    # step 3 — resolve want, field cache + miss-path batching (spec §6)
    cells: Dict[str, Any] = {}
    missing: List[str] = []
    for key in raw.want:
        hit = cache.get_field(backend, sv, key)
        cache_status["want"][key] = "hit" if hit is not None else "miss"
        if hit is not None:
            cells[key] = hit
        else:
            missing.append(key)
    if missing:
        mapping = _retry_once(resolve_want, llm, schema, missing)
        for key in missing:
            cell = (mapping.get(key) if isinstance(mapping, dict) else None) \
                or {"field": None, "confidence": 0.0}
            cache.set_field(backend, sv, key, cell)
            cells[key] = cell

    # step 4 — gate want (valid_fields = the SELECT-side injection/robustness check)
    select = gate_want(raw.want, cells, gate, valid_fields)
    if all(f.field_path is None for f in select):               # spec §12
        raise GatewayError(422, "all_want_declined", "no requested field resolved",
                           _interpreted(select, raw, None, None))

    # steps 5–7 — resolve where, gate, validate
    predicate: Optional[dict] = None
    where_conf: Optional[float] = None
    if raw.where is not None:
        hit = cache.get_where(backend, sv, raw.where, raw.today)
        cache_status["where"] = "hit" if hit is not None else "miss"
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
                type_check_ast(ast, schema)                     # + static type check (pre-execute)
            except ValueError as e:
                raise GatewayError(422, "invalid_ast", str(e),
                                   _interpreted(select, raw, ast, where_conf))
        predicate = ast

    # steps 8–10 — assemble, execute, remap
    ir = CanonicalQueryIR(select=select, predicate=predicate,
                          where_confidence=where_conf, where_raw=raw.where)
    # trace is created fresh per request; on the 502 path below it is never read
    # (502s carry no debug block), so a partially-filled trace can't leak.
    trace = ExecutionTrace() if debug else None
    try:
        rows = connector.execute(ir, **_execute_kwargs(connector, limit, trace))
    except GatewayError:
        raise
    except Exception as e:  # noqa: BLE001 — a compiled query the backend rejected (bad
        # value type, empty clause, unreachable DB): a clean 502, never an unhandled 500.
        raise GatewayError(502, "backend_error", f"query execution failed: {e}",
                           _interpreted(select, raw, predicate, where_conf))
    out_rows = [remap_row(r, select) for r in rows]
    resp: Dict[str, Any] = {"rows": out_rows}
    if raw.verbose:
        resp["interpreted"] = _interpreted(select, raw, predicate, where_conf)
    if debug:
        resp["debug"] = _debug_block(gate, cache_status, trace)
    return resp


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
