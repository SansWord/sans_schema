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
