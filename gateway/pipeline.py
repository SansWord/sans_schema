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
