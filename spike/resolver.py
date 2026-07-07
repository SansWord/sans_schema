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

from typing import Any, Dict, List, Optional

from .llm import LLM
from .prompts import (DomainHints, NO_HINTS, OPS, want_system, want_user,
                      where_system, where_user)
from .schemas import Schema


def resolve_want(llm: LLM, schema: Schema, client_keys: List[str],
                 hints: DomainHints = NO_HINTS) -> Dict[str, Any]:
    out = llm.json(want_system(hints), want_user(schema.as_prompt(), client_keys))
    return out.get("mapping", {})


def parse_where(llm: LLM, schema: Schema, nl: str, today: str,
                hints: DomainHints = NO_HINTS) -> Optional[Dict[str, Any]]:
    out = llm.json(where_system(hints), where_user(schema.as_prompt(), nl, today))
    ast = out.get("where")
    if ast is None:
        return None
    validate_ast(ast, schema)
    return ast


def validate_ast(node: Any, schema: Schema) -> None:
    """Reject anything outside the whitelist. This is the injection boundary."""
    valid_fields = {f.path for f in schema.fields}
    if not isinstance(node, dict):
        raise ValueError(f"AST node is not an object: {node!r}")
    op = node.get("op")
    if op not in OPS:
        raise ValueError(f"illegal operator: {op!r}")
    if op in ("and", "or"):
        for c in node.get("clauses", []):
            validate_ast(c, schema)
    elif op == "not":
        validate_ast(node["clause"], schema)
    else:
        fld = node.get("field")
        if fld not in valid_fields:
            raise ValueError(f"unknown field: {fld!r}")
