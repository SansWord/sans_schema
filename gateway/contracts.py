"""The hourglass's narrow waist — the two load-bearing contracts (spec §3).

RawQuery (ingress → core): unresolved, client vocabulary.
CanonicalQueryIR (core → egress): resolved, backend-agnostic — zero SQL specifics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class RawQuery:
    want: List[str]                  # client field names, in request order
    where: Optional[str]             # NL filter, or None
    today: str                       # ISO date for relative-date resolution (per-call)
    verbose: bool = False            # include the `interpreted` echo


@dataclass
class ResolvedField:
    client_key: str                  # maps results back to client vocab
    field_path: Optional[str]        # resolved backend path, or None if the gate declined it
    confidence: float


@dataclass
class CanonicalQueryIR:
    select: List[ResolvedField]      # resolved `want`, in request order
    predicate: Optional[dict]        # validated AST, or None
    where_confidence: Optional[float]  # None when no `where`
    where_raw: Optional[str]         # original NL filter, for the echo
