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
