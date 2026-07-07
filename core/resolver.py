"""The layer under test.

Two LLM tasks, both operating against an UNKNOWN backend schema:

1. resolve_want(schema, client_keys)  -> {client_key: field_path | None, confidence}
2. parse_where(schema, nl_string)     -> canonical predicate AST

Discipline (mirrors the real product):
  - NL -> validated AST -> (later) SQL. Never NL -> SQL directly.
  - The model may only emit a whitelisted operator set and field paths that
    exist in the schema. Anything else is rejected, not executed.

Prompts live in prompts.py (see that module for the layer model). An optional
DomainHints lets a caller inject per-tenant synonyms/glossary/examples without
touching the contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .llm import LLM
from .predicate import _parse_dt          # reuse the exact date parsing execution uses
from .prompts import (DomainHints, NO_HINTS, OPS, want_system, want_user,
                      where_system, where_user)
from .schemas import Schema


def resolve_want(llm: LLM, schema: Schema, client_keys: List[str],
                 hints: DomainHints = NO_HINTS) -> Dict[str, Any]:
    out = llm.json(want_system(hints), want_user(schema.as_prompt(), client_keys))
    return out.get("mapping", {})


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


def parse_where(llm: LLM, schema: Schema, nl: str, today: str,
                hints: DomainHints = NO_HINTS) -> Optional[Dict[str, Any]]:
    ast = where_ast(llm, schema, nl, today, hints)
    if ast is None:
        return None
    validate_ast(ast, schema)  # the injection boundary — reject off-contract ASTs
    return ast


def validate_ast(node: Any, schema: Schema) -> None:
    """Reject anything outside the whitelist. This is the injection boundary.

    Also validates node SHAPE (a `not` has a `clause`; a `between` value is a
    two-element list; `in`/`nin` values are lists) so a malformed model output is
    rejected here as a ValueError — which the gateway turns into a 422 — rather
    than surfacing later as a KeyError/TypeError (an unhandled 500) when compiled
    or matched.
    """
    valid_fields = {f.path for f in schema.fields}
    if not isinstance(node, dict):
        raise ValueError(f"AST node is not an object: {node!r}")
    op = node.get("op")
    if op not in OPS:
        raise ValueError(f"illegal operator: {op!r}")
    if op in ("and", "or"):
        clauses = node.get("clauses")
        if not isinstance(clauses, list) or not clauses:
            raise ValueError(f"{op!r} node needs a non-empty 'clauses' list")
        for c in clauses:
            validate_ast(c, schema)
    elif op == "not":
        clause = node.get("clause")
        if clause is None:
            raise ValueError("'not' node needs a 'clause'")
        validate_ast(clause, schema)
    else:
        fld = node.get("field")
        if fld not in valid_fields:
            raise ValueError(f"unknown field: {fld!r}")
        value = node.get("value")
        if op == "between" and not (isinstance(value, list) and len(value) == 2):
            raise ValueError(f"'between' value must be a two-element list, got {value!r}")
        if op in ("in", "nin") and not isinstance(value, list):
            raise ValueError(f"{op!r} value must be a list, got {value!r}")


# --- static type check (a robustness layer over the injection boundary) --------
# Postgres would reject a type-mismatched query at execute time (a 502); checking the
# AST against each field's DECLARED type here turns that into a deterministic 422,
# with no DB round-trip and identical behavior across connectors. Conservative by
# design: unknown declared types are skipped and only clear mismatches are rejected —
# the pipeline's 502 containment stays as the backstop.

_NUMBER_TYPES = {"int", "integer", "bigint", "smallint", "numeric", "decimal",
                 "real", "double precision", "float", "money"}
_STRING_TYPES = {"text", "character varying", "varchar", "char", "character",
                 "citext", "uuid", "name"}
_BOOL_TYPES = {"boolean", "bool"}
_TEMPORAL_TYPES = {"date", "timestamp", "timestamp without time zone",
                   "timestamp with time zone", "timestamptz", "datetime",
                   "time", "time without time zone"}


def _kind_of(type_str: Optional[str]) -> Optional[str]:
    """Map a declared column type to a logical kind, or None (→ skip the check)."""
    t = (type_str or "").strip().lower()
    if t in _NUMBER_TYPES:
        return "number"
    if t in _BOOL_TYPES:
        return "bool"
    if t in _TEMPORAL_TYPES:
        return "temporal"
    if t in _STRING_TYPES:
        return "string"
    return None


def _value_ok(value: Any, kind: str) -> bool:
    if kind == "number":
        if isinstance(value, bool):
            return False                     # a bool is not a number for a numeric column
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            try:
                float(value)                 # numeric string ("20") is coercible
                return True
            except ValueError:
                return False
        return False
    if kind == "bool":
        if isinstance(value, bool):
            return True
        return isinstance(value, str) and value.strip().lower() in ("true", "false")
    if kind == "temporal":
        return isinstance(value, str) and _parse_dt(value) is not None
    if kind == "string":
        return isinstance(value, str)
    return True


def type_check_ast(node: Any, schema: Schema) -> None:
    """Reject leaf values that are clearly incompatible with the field's declared
    type (a non-numeric value on an int column, an unparseable date on a date
    column, `contains` on a non-text field). Assumes validate_ast already ran, so
    op/field/shape are known-good. Raises ValueError on a mismatch."""
    op = node["op"]
    if op in ("and", "or"):
        for c in node["clauses"]:
            type_check_ast(c, schema)
        return
    if op == "not":
        type_check_ast(node["clause"], schema)
        return
    if op == "is_null":
        return

    field = node["field"]
    kind = _kind_of({f.path: f.type for f in schema.fields}.get(field))
    value = node.get("value")
    values = value if op in ("in", "nin", "between") else [value]
    for v in values:
        if isinstance(v, (list, dict)):
            raise ValueError(f"{field!r}: expected a scalar value, got {type(v).__name__}")
        if op == "contains" and kind is not None and kind != "string":
            raise ValueError(f"'contains' needs a text field; {field!r} is a {kind} column")
        if kind is not None and not _value_ok(v, kind):
            raise ValueError(
                f"{field!r}: value {v!r} is not compatible with a {kind} column")
