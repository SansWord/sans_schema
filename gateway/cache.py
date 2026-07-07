"""Two-part resolution cache (spec §6). Per-key and per-phrase, never per-whole-request.
In-memory dicts behind a CacheStore Protocol so Redis / semantic lookup swap in later.
Stores RAW {field/ast, confidence}; the gate is applied at read time by the pipeline."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore


def normalize_key(s: str) -> str:
    return " ".join(s.strip().lower().split())


normalize_phrase = normalize_key  # same rule for v1; kept distinct for future divergence


class CacheStore(Protocol):
    def get(self, key: Tuple) -> Optional[Dict[str, Any]]: ...
    def set(self, key: Tuple, value: Dict[str, Any]) -> None: ...


class DictCache:
    """In-memory CacheStore. Swap for Redis behind this same interface.
    Counts hits/misses so the resolution-cache hit rate is observable."""

    def __init__(self) -> None:
        self._d: Dict[Tuple, Dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: Tuple) -> Optional[Dict[str, Any]]:
        if key in self._d:
            self.hits += 1
            return self._d[key]
        self.misses += 1
        return None

    def set(self, key: Tuple, value: Dict[str, Any]) -> None:
        self._d[key] = value

    def items(self):
        """Enumerate (key, value) pairs — used by the debug snapshot. Enumeration
        is not part of the CacheStore contract, so a non-enumerable store (Redis)
        simply won't provide it and the snapshot reports it as unavailable."""
        return list(self._d.items())


class ResolutionCache:
    """The field cache + the where cache, together."""

    def __init__(self, field_store: Optional[CacheStore] = None,
                 where_store: Optional[CacheStore] = None) -> None:
        self._field = field_store or DictCache()
        self._where = where_store or DictCache()

    # field cache: (backend, schema_version, normalized_key)
    def get_field(self, backend: str, sv: str, key: str) -> Optional[Dict[str, Any]]:
        return self._field.get((backend, sv, normalize_key(key)))

    def set_field(self, backend: str, sv: str, key: str, value: Dict[str, Any]) -> None:
        self._field.set((backend, sv, normalize_key(key)), value)

    # where cache: (backend, schema_version, normalized_phrase, today)
    def get_where(self, backend: str, sv: str, phrase: str, today: str) -> Optional[Dict[str, Any]]:
        return self._where.get((backend, sv, normalize_phrase(phrase), today))

    def set_where(self, backend: str, sv: str, phrase: str, today: str,
                  value: Dict[str, Any]) -> None:
        self._where.set((backend, sv, normalize_phrase(phrase), today), value)

    def snapshot(self) -> Dict[str, Any]:
        """A serializable view of both caches (raw {field/ast, confidence}), for the
        debug endpoint. Returns None for a store that can't enumerate (e.g. Redis)."""
        def dump(store, keynames):
            if not hasattr(store, "items"):
                return None
            out = []
            for key, value in store.items():
                entry = dict(zip(keynames, key))
                entry["value"] = value
                out.append(entry)
            return out
        return {
            "field": dump(self._field, ("backend", "schema_version", "key")),
            "where": dump(self._where, ("backend", "schema_version", "phrase", "today")),
        }

    def stats(self) -> Dict[str, Any]:
        """Hit/miss counters since process start — field, where, and combined — for
        observing the resolution-cache hit rate (the primary cost lever). A store
        reports None only if it doesn't expose `hits`/`misses`; a Redis-backed store
        can count these in-process the same way (though the counters would be
        per-replica — aggregate across replicas for a fleet-wide rate)."""
        def one(store):
            h = getattr(store, "hits", None)
            m = getattr(store, "misses", None)
            if h is None or m is None:
                return None
            total = h + m
            return {"hits": h, "misses": m, "lookups": total,
                    "hit_rate": (h / total) if total else None}
        field, where = one(self._field), one(self._where)
        parts = [p for p in (field, where) if p is not None]
        combined = None
        if parts:
            h = sum(p["hits"] for p in parts)
            m = sum(p["misses"] for p in parts)
            total = h + m
            combined = {"hits": h, "misses": m, "lookups": total,
                        "hit_rate": (h / total) if total else None}
        return {"field": field, "where": where, "combined": combined}
