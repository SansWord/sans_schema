"""The layer under test.

Two LLM tasks, both operating against an UNKNOWN backend schema:

1. resolve_want(schema, client_keys)  -> {client_key: field_path | None, confidence}
2. parse_where(schema, nl_string)     -> canonical predicate AST

Discipline (mirrors the real product):
  - NL -> validated AST -> (later) SQL. Never NL -> SQL directly.
  - The model may only emit a whitelisted operator set and field paths that
    exist in the schema. Anything else is rejected, not executed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .llm import LLM
from .schemas import Schema

OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "nin",
       "contains", "between", "is_null", "and", "or", "not"}


def resolve_want(llm: LLM, schema: Schema, client_keys: List[str]) -> Dict[str, Any]:
    system = (
        "You map a client's requested field names onto a backend database "
        "schema. The client does not know the real schema and uses its own "
        "vocabulary. For each requested key, return the single best matching "
        "field path from the schema, or null if nothing matches semantically. "
        "Also return a confidence 0.0-1.0 per key.\n"
        "Respond as JSON: "
        '{"mapping": {"<key>": {"field": "<table.column>|null", "confidence": 0.0}}}'
    )
    user = (
        schema.as_prompt()
        + "\n\nClient requested fields: "
        + ", ".join(client_keys)
    )
    out = llm.json(system, user)
    return out.get("mapping", {})


def parse_where(llm: LLM, schema: Schema, nl: str, today: str) -> Optional[Dict[str, Any]]:
    system = (
        "You compile a natural-language filter into a canonical predicate AST "
        "against a backend database schema. Use ONLY these operators: "
        + ", ".join(sorted(OPS))
        + ".\n"
        "Rules:\n"
        "- Leaf node: {\"op\": \"gte\", \"field\": \"<table.column>\", \"value\": <v>}\n"
        "- Boolean node: {\"op\": \"and\", \"clauses\": [ ... ]} (also 'or'); "
        "{\"op\": \"not\", \"clause\": { ... }}\n"
        "- `field` MUST be a real path from the schema.\n"
        "- Normalize relative dates against today. Normalize a bare year Y to a "
        "range Y-01-01 .. Y-12-31 using an 'and' of gte/lte.\n"
        "- Match filter values to the schema's real enum/sample values "
        "(e.g. 'sci-fi' -> 'Science Fiction').\n"
        "- Numbers as numbers, booleans as booleans, dates as 'YYYY-MM-DD' strings.\n"
        "Respond as JSON with the AST under key \"where\": {\"where\": { ... }}"
    )
    user = (
        schema.as_prompt()
        + f"\n\nToday is {today}."
        + f"\n\nNatural-language filter: {nl!r}"
    )
    out = llm.json(system, user)
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
