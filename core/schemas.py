"""Sample backend schemas — the "unknown" storage layers the resolver must map
client vocabulary onto.

A schema is a flat list of fields. Each field has a canonical path
("table.column"), a type, a human description, and a few sample values. The
resolver sees exactly this — no more privileged than what an auto-introspection
step (information_schema + LLM-generated descriptions) would produce.

Each schema also carries `rows`: a small denormalized (fully joined) sample
dataset, keyed by field path. The scorer uses it for EXECUTION EQUIVALENCE —
two predicate ASTs that select the same rows are semantically equal, regardless
of clause order, gt-vs-gte at a non-boundary, open-range-vs-bounded, or
date-vs-datetime formatting. Rows are chosen so each scored predicate selects a
distinctive, non-empty PROPER subset, and no row sits on a relative-date
boundary (so an off-by-one day in the model's date math can't change selection).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Field:
    path: str          # canonical "table.column"
    type: str          # sql-ish type
    description: str    # what auto-enrichment would generate
    samples: List[str] = field(default_factory=list)


@dataclass
class Schema:
    name: str
    fields: List[Field]
    rows: List[Dict[str, Any]] = field(default_factory=list)

    def as_prompt(self) -> str:
        lines = [f"Backend schema: {self.name}", "Fields:"]
        for f in self.fields:
            s = f", e.g. {', '.join(f.samples)}" if f.samples else ""
            lines.append(f"  - {f.path} ({f.type}): {f.description}{s}")
        return "\n".join(lines)
