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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("DATABASE_URL", ""),
            llm_model=os.environ.get("LLM_MODEL", "gemini/gemini-3.1-flash-lite"),
            gate_threshold=float(os.environ.get("GATE_THRESHOLD", "0.7")),
            result_limit=int(os.environ.get("RESULT_LIMIT", "100")),
        )
