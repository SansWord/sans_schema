"""Env-driven config (spec §10). Container-portable; no config file in v1."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str
    llm_model: str
    gate_threshold: float
    result_limit: int
    max_want_fields: int      # cap on how many fields one request may ask for
    max_field_len: int        # cap on the length of a single `want` field name
    max_where_len: int        # cap on the length of the NL `where` string
    enable_debug_endpoints: bool  # expose /debug/* (discloses schema+samples) — dev only

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("DATABASE_URL", ""),
            llm_model=os.environ.get("LLM_MODEL", "gemini/gemini-3.1-flash-lite"),
            gate_threshold=float(os.environ.get("GATE_THRESHOLD", "0.7")),
            result_limit=int(os.environ.get("RESULT_LIMIT", "100")),
            # Ingress limits — bound the untrusted request so a huge `want`/`where`
            # can't inflate the LLM prompt (cost/DoS). Generous defaults; tune per deploy.
            max_want_fields=int(os.environ.get("MAX_WANT_FIELDS", "50")),
            max_field_len=int(os.environ.get("MAX_FIELD_LEN", "200")),
            max_where_len=int(os.environ.get("MAX_WHERE_LEN", "2000")),
            # Debug introspection (system + schema prompts). OFF by default — the schema
            # view discloses column names, descriptions, and sample values.
            enable_debug_endpoints=os.environ.get(
                "ENABLE_DEBUG_ENDPOINTS", "0").strip().lower() in ("1", "true", "yes", "on"),
        )
