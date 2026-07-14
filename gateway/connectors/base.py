"""Egress interface (spec §4). One Connector per backend. schema_version() is a stable
hash of describe() output — computed once per process (refresh on restart; drift
invalidation deferred, spec §6)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, List, Optional

from core.schemas import Schema
from gateway.contracts import CanonicalQueryIR

try:
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol, runtime_checkable  # type: ignore


@dataclass
class Capabilities:
    """Static declaration only — no pushdown-negotiation planner consumes it in v1."""
    pushdown_filter: bool = True


@dataclass
class ExecutionTrace:
    """Per-request execution debug info (request-transparency panel spec). Created
    by the pipeline only when debug is on; write-once by the connector, read once
    when the response's `debug` block is assembled — never a mid-flight channel."""
    engine: Optional[str] = None            # e.g. "postgres", "core.predicate"
    sql: Optional[str] = None               # parameterized SQL text, if the backend runs SQL
    params: Optional[List[Any]] = None      # bound values, in placeholder order


@runtime_checkable
class Connector(Protocol):
    backend_id: str
    def describe(self) -> Schema: ...
    def execute(self, ir: CanonicalQueryIR) -> List[dict]: ...
    def capabilities(self) -> Capabilities: ...


def schema_version(schema: Schema) -> str:
    """Stable hash over field path|type|description — order-independent."""
    parts = sorted(f"{f.path}|{f.type}|{f.description}" for f in schema.fields)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
