"""Confidence gate (spec §7). Threshold applied at READ time so changing it never
invalidates a cache (caches store raw confidence)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from gateway.contracts import ResolvedField


@dataclass
class GateConfig:
    threshold: float = 0.7


def gate_want(want_keys: List[str], mapping: Dict[str, Any],
              cfg: GateConfig) -> List[ResolvedField]:
    """One ResolvedField per key, in request order. Below threshold or no field →
    field_path=None (declined, not dropped — still a null column downstream)."""
    out: List[ResolvedField] = []
    for key in want_keys:
        cell = mapping.get(key) or {}
        field = cell.get("field")
        raw_conf = cell.get("confidence", 0.0)
        conf = float(raw_conf) if isinstance(raw_conf, (int, float)) else 0.0
        resolved = field if (field is not None and conf >= cfg.threshold) else None
        out.append(ResolvedField(client_key=key, field_path=resolved, confidence=conf))
    return out


def where_passes(confidence: Optional[float], cfg: GateConfig) -> bool:
    return confidence is not None and confidence >= cfg.threshold
