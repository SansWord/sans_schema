"""Postgres connector (spec §4, §9). describe() introspects information_schema over the
denormalized view; execute() compiles the VALIDATED AST → parameterized SQL. Field paths
are the view's column names (the view is already flat — no join planning in v1)."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

import psycopg
from psycopg import sql

from core.schemas import Field, Schema
from gateway.connectors.base import Capabilities
from gateway.contracts import CanonicalQueryIR

_BINARY_OPS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


class PostgresConnector:
    def __init__(self, dsn: str, view: str = "books_view"):
        self.dsn = dsn
        self.view = view
        self.backend_id = f"postgres:{view}"
        self._schema: Optional[Schema] = None

    def capabilities(self) -> Capabilities:
        return Capabilities()

    # --- describe (memoized) ------------------------------------------------
    def describe(self) -> Schema:
        if self._schema is not None:
            return self._schema
        with psycopg.connect(self.dsn) as conn:
            cols = conn.execute(
                """
                SELECT column_name, data_type,
                       col_description((%s)::regclass, ordinal_position) AS comment
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
                """,
                (self.view, self.view),
            ).fetchall()
            fields: List[Field] = []
            for name, dtype, comment in cols:
                samples = self._samples(conn, name)
                fields.append(Field(path=name, type=dtype,
                                    description=comment or "", samples=samples))
        self._schema = Schema(name=self.view, fields=fields)
        return self._schema

    def _samples(self, conn, column: str, k: int = 5) -> List[str]:
        q = sql.SQL("SELECT DISTINCT {col} FROM {view} WHERE {col} IS NOT NULL LIMIT %s").format(
            col=sql.Identifier(column), view=sql.Identifier(self.view))
        return [str(r[0]) for r in conn.execute(q, (k,)).fetchall()]

    # --- execute ------------------------------------------------------------
    def execute(self, ir: CanonicalQueryIR, limit: int = 100) -> List[dict]:
        paths = [f.field_path for f in ir.select if f.field_path is not None]
        select_cols = sql.SQL(", ").join(sql.Identifier(p) for p in paths)
        query = sql.SQL("SELECT {cols} FROM {view}").format(
            cols=select_cols, view=sql.Identifier(self.view))
        params: List[Any] = []
        if ir.predicate is not None:
            clause, params = self._compile(ir.predicate)
            query = query + sql.SQL(" WHERE ") + clause
        query = query + sql.SQL(" LIMIT %s")
        params.append(limit)
        with psycopg.connect(self.dsn) as conn:
            cur = conn.execute(query, params)
            names = [d.name for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]

    def _compile(self, node: dict) -> Tuple[sql.Composable, List[Any]]:
        op = node["op"]
        if op in ("and", "or"):
            joiner = sql.SQL(f" {op.upper()} ")
            parts, params = [], []
            for c in node.get("clauses", []):
                clause, p = self._compile(c)
                parts.append(clause); params += p
            return sql.SQL("(") + joiner.join(parts) + sql.SQL(")"), params
        if op == "not":
            clause, params = self._compile(node["clause"])
            return sql.SQL("NOT (") + clause + sql.SQL(")"), params

        col = sql.Identifier(node["field"])
        val = node.get("value")
        if op in _BINARY_OPS:
            return sql.SQL("{} {} %s").format(col, sql.SQL(_BINARY_OPS[op])), [val]
        if op == "in":
            return sql.SQL("{} = ANY(%s)").format(col), [list(val)]
        if op == "nin":
            return sql.SQL("{} <> ALL(%s)").format(col), [list(val)]
        if op == "contains":                       # ILIKE → case-insensitive, matches core.predicate
            return sql.SQL("{} ILIKE %s").format(col), [f"%{val}%"]
        if op == "between":
            return sql.SQL("{} BETWEEN %s AND %s").format(col), [val[0], val[1]]
        if op == "is_null":
            return sql.SQL("{} IS NULL").format(col), []
        raise ValueError(f"uncompilable op: {op!r}")   # unreachable — validate_ast ran first
