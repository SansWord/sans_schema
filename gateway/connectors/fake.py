"""Fake in-memory connector — the seam-test twin (spec §4, §9). Filters the demo mirror
rows with core.predicate (the same oracle the spike scorer trusts), so a Postgres connector
can be asserted equal to it."""
from __future__ import annotations

from typing import List

from core.predicate import matches
from core.schemas import Field, Schema
from gateway.connectors.base import Capabilities
from gateway.contracts import CanonicalQueryIR
from gateway.demo.rows import VIEW_FIELDS, VIEW_NAME, VIEW_ROWS


def _qualify(row: dict) -> dict:
    """Bare-column mirror row → row keyed by qualified `view.column` paths, matching
    what describe() exposes (and what Postgres introspection produces after the fix)."""
    return {f"{VIEW_NAME}.{k}": v for k, v in row.items()}


class FakeConnector:
    backend_id = "fake"

    def describe(self) -> Schema:
        fields = [Field(path=f"{VIEW_NAME}.{p}", type=t, description=d, samples=list(s))
                  for (p, t, d, s) in VIEW_FIELDS]
        return Schema(name=VIEW_NAME, fields=fields,
                      rows=[_qualify(r) for r in VIEW_ROWS])

    def execute(self, ir: CanonicalQueryIR) -> List[dict]:
        paths = [f.field_path for f in ir.select if f.field_path is not None]
        rows = [_qualify(r) for r in VIEW_ROWS]
        selected = rows if ir.predicate is None else \
            [r for r in rows if matches(ir.predicate, r)]
        return [{p: row.get(p) for p in paths} for row in selected]

    def capabilities(self) -> Capabilities:
        return Capabilities()
