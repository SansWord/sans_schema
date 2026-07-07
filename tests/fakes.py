from typing import Any, Dict, Optional
from core.llm import LLM


class FakeLLM(LLM):
    """Routes by system-prompt content: want vs where. Canned JSON, no network.
    Pass `fail_times` to simulate transient errors (for retry tests)."""

    def __init__(self, want: Optional[Dict[str, Any]] = None,
                 where: Optional[Dict[str, Any]] = None, fail_times: int = 0):
        self.name = "fake"
        self._want = want or {"mapping": {}}
        self._where = where or {"where": None, "confidence": 0.0}
        self._fail_times = fail_times
        self.calls = 0

    def json(self, system: str, user: str) -> Dict[str, Any]:
        self.calls += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("simulated LLM failure")
        return self._where if "natural-language filter" in system else self._want
