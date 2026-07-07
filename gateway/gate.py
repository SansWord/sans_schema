"""Confidence gate (spec §7). Threshold applied at READ time so changing it never
invalidates a cache (caches store raw confidence)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from gateway.contracts import ResolvedField


@dataclass
class GateConfig:
    threshold: float = 0.7


def gate_want(want_keys: List[str], mapping: Dict[str, Any], cfg: GateConfig,
              valid_fields: Optional[Set[str]] = None) -> List[ResolvedField]:
    """One ResolvedField per key, in request order. Below threshold, no field, or
    (when `valid_fields` is given) a field the model invented that is not a real
    schema path → field_path=None (declined, not dropped — still a null column).

    The `valid_fields` check is the SELECT-side mirror of `validate_ast`: a resolved
    path is only trusted if it exists in the schema. It keeps a hijacked/mis-resolved
    `want` from putting a non-existent column into `SELECT` (which would otherwise
    surface as an uncaught backend error)."""
    out: List[ResolvedField] = []
    for key in want_keys:
        cell = mapping.get(key) or {}
        field = cell.get("field")
        raw_conf = cell.get("confidence", 0.0)
        conf = float(raw_conf) if isinstance(raw_conf, (int, float)) else 0.0
        ok = field is not None and conf >= cfg.threshold
        if ok and valid_fields is not None and field not in valid_fields:
            ok = False                              # resolved to a non-schema path → decline
        out.append(ResolvedField(client_key=key,
                                 field_path=(field if ok else None), confidence=conf))
    return out


def where_passes(confidence: Optional[float], cfg: GateConfig) -> bool:
    return confidence is not None and confidence >= cfg.threshold
