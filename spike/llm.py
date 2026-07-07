"""Vendor-agnostic LLM access.

The resolver depends ONLY on these two interfaces. Swapping GPT <-> Claude <->
Llama <-> a local model is a config change, and the scoring harness can loop the
same test set over different implementations to compare accuracy per vendor.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LLM(ABC):
    """A single-shot completion that returns parsed JSON.

    Implementations must coerce the model into emitting a JSON object and return
    it as a dict. The resolver never sees raw text.
    """

    name: str

    @abstractmethod
    def json(self, system: str, user: str) -> Dict[str, Any]:
        ...


class Embed(ABC):
    """Text -> vector, for the semantic field-match path (optional in v1)."""

    name: str

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        ...


# --- LiteLLM-backed implementations (default) -------------------------------
# LiteLLM gives one interface over 100+ providers. Model strings are LiteLLM
# identifiers, e.g. "anthropic/claude-haiku-4-5", "openai/gpt-4o".


class LiteLLM(LLM):
    def __init__(self, model: str, temperature: Optional[float] = None):
        self.model = model
        self.name = model
        # Some current models (e.g. Anthropic Opus 4.8/4.7) reject temperature;
        # leave it unset unless the caller explicitly asks for one.
        self.temperature = temperature

    def json(self, system: str, user: str) -> Dict[str, Any]:
        import litellm

        kwargs: Dict[str, Any] = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=2000,
            # Ask for a JSON object where the provider supports it; harmless
            # elsewhere because we also parse defensively below.
            response_format={"type": "json_object"},
        )
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature

        try:
            resp = litellm.completion(**kwargs)
        except Exception:
            # Retry once without response_format for providers that reject it.
            kwargs.pop("response_format", None)
            resp = litellm.completion(**kwargs)

        content = resp["choices"][0]["message"]["content"]
        return _extract_json(content)


class LiteEmbed(Embed):
    def __init__(self, model: str = "openai/text-embedding-3-small"):
        self.model = model
        self.name = model

    def embed(self, text: str) -> List[float]:
        import litellm

        resp = litellm.embedding(model=self.model, input=[text])
        return resp["data"][0]["embedding"]


def _extract_json(content: str) -> Dict[str, Any]:
    """Best-effort JSON extraction from a model reply."""
    content = content.strip()
    if content.startswith("```"):
        # strip ```json ... ``` fences
        content = content.split("```", 2)[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Reasoning models (e.g. gemini-pro) may wrap the JSON in prose/thinking, or
    # emit trailing content after it ("Extra data"). Decode the FIRST JSON object
    # starting at the first '{' and ignore anything after it.
    start = content.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in response: {content[:200]!r}")
    obj, _end = json.JSONDecoder().raw_decode(content[start:])
    return obj
