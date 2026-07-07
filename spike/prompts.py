"""Prompt templates — the LLM-facing contract, in one inspectable place.

Structured as layers so the safe, high-value customization is separated from the
parts that must stay in sync with the validator:

  Layer 1 — CONTRACT  : AST grammar, operator whitelist, JSON output shape.
                        Must match validate_ast(). Not a user-tuning surface.
  Layer 2 — SCHEMA     : auto-generated from Schema.as_prompt() (describe()).
  Layer 3 — DOMAIN HINTS: synonyms, glossary, rules, few-shot examples.
                        The safe, per-tenant knob — improves accuracy without
                        touching the contract. Injected via DomainHints below.
  Layer 4 — REQUEST    : the actual want / where (per call).

Keeping prompts here (not inline in resolver.py) makes them:
  - inspectable   (`python -m spike.score --show-prompts`)
  - git-diffable  (a prompt edit is its own diff, attributable in the spike)
  - A/B-able      (swap a variant, re-run the same cases, compare scores)

SAFETY: injection protection lives in validate_ast() (code), never in the
prompt. A mangled prompt can hurt accuracy but cannot bypass the whitelist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# Operator whitelist — part of the CONTRACT. validate_ast() enforces exactly
# this set, so prompt and validator share this single source of truth.
OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "nin",
       "contains", "between", "is_null", "and", "or", "not"}


@dataclass
class DomainHints:
    """Layer-3 customization. Safe to expose per tenant; empty = no change.

    Example:
        DomainHints(
            glossary=["MRR = monthly recurring revenue"],
            synonyms=["writer, author -> author.name"],
            rules=["all prices are in USD"],
            where_examples=['"big spenders" -> orders.total_amount gt 1000'],
        )
    """
    glossary: List[str] = field(default_factory=list)
    synonyms: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    want_examples: List[str] = field(default_factory=list)
    where_examples: List[str] = field(default_factory=list)

    def block(self, which: str) -> str:
        parts: List[str] = []
        if self.glossary:
            parts.append("Glossary:\n" + "\n".join(f"  - {g}" for g in self.glossary))
        if self.synonyms:
            parts.append("Known synonyms:\n" + "\n".join(f"  - {s}" for s in self.synonyms))
        if self.rules:
            parts.append("Domain rules:\n" + "\n".join(f"  - {r}" for r in self.rules))
        ex = self.want_examples if which == "want" else self.where_examples
        if ex:
            parts.append("Examples:\n" + "\n".join(f"  - {e}" for e in ex))
        return ("\n\n" + "\n\n".join(parts)) if parts else ""


NO_HINTS = DomainHints()


# --- want-resolution -------------------------------------------------------

def want_system(hints: DomainHints = NO_HINTS) -> str:
    return (
        "You map a client's requested field names onto a backend database "
        "schema. The client does not know the real schema and uses its own "
        "vocabulary. For each requested key, return the single best matching "
        "field path from the schema, or null if nothing matches semantically. "
        "Also return a confidence 0.0-1.0 per key.\n"
        "Respond as JSON: "
        '{"mapping": {"<key>": {"field": "<table.column>|null", "confidence": 0.0}}}'
        + hints.block("want")
    )


def want_user(schema_prompt: str, client_keys: List[str]) -> str:
    return schema_prompt + "\n\nClient requested fields: " + ", ".join(client_keys)


# --- where -> AST ----------------------------------------------------------

def where_system(hints: DomainHints = NO_HINTS) -> str:
    return (
        "You compile a natural-language filter into a canonical predicate AST "
        "against a backend database schema. Use ONLY these operators: "
        + ", ".join(sorted(OPS))
        + ".\n"
        "Rules:\n"
        "- Leaf node: {\"op\": \"gte\", \"field\": \"<table.column>\", \"value\": <v>}\n"
        "- Boolean node: {\"op\": \"and\", \"clauses\": [ ... ]} (also 'or'); "
        "{\"op\": \"not\", \"clause\": { ... }}\n"
        "- `field` MUST be a real path from the schema.\n"
        "- Normalize relative dates against today. Normalize a bare year Y to a "
        "range Y-01-01 .. Y-12-31 using an 'and' of gte/lte.\n"
        "- Match filter values to the schema's real enum/sample values "
        "(e.g. 'sci-fi' -> 'Science Fiction').\n"
        "- Numbers as numbers, booleans as booleans, dates as 'YYYY-MM-DD' strings.\n"
        "Respond as JSON with the AST under key \"where\": {\"where\": { ... }}"
        + hints.block("where")
    )


def where_user(schema_prompt: str, nl: str, today: str) -> str:
    return schema_prompt + f"\n\nToday is {today}." + f"\n\nNatural-language filter: {nl!r}"
