import pytest
from gateway.pipeline import run_query, GatewayError
from gateway.contracts import RawQuery
from gateway.gate import GateConfig
from gateway.cache import ResolutionCache
from gateway.connectors.fake import FakeConnector
from tests.fakes import FakeLLM

WANT_OK = {"mapping": {
    "book_title": {"field": "title", "confidence": 0.95},
    "genre":      {"field": "category", "confidence": 0.92}}}
WHERE_OK = {"where": {"op": "eq", "field": "category", "value": "Science Fiction"},
            "confidence": 0.9}

def _run(raw, llm, cache=None):
    return run_query(raw, FakeConnector(), llm, cache or ResolutionCache(),
                     GateConfig(threshold=0.7), limit=100)

def test_happy_path_returns_rows_in_client_keys():
    raw = RawQuery(["book_title", "genre"], "sci-fi only", "2026-07-06", verbose=True)
    resp = _run(raw, FakeLLM(want=WANT_OK, where=WHERE_OK))
    assert resp["rows"] and all(set(r) == {"book_title", "genre"} for r in resp["rows"])
    assert all(r["genre"] == "Science Fiction" for r in resp["rows"])
    assert resp["interpreted"]["want"]["book_title"]["field"] == "title"
    assert resp["interpreted"]["where"]["confidence"] == 0.9

def test_non_verbose_omits_interpreted():
    raw = RawQuery(["book_title"], None, "2026-07-06")
    resp = _run(raw, FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}}))
    assert "interpreted" not in resp

def test_all_want_declined_is_422():
    raw = RawQuery(["ghost"], None, "2026-07-06")
    with pytest.raises(GatewayError) as e:
        _run(raw, FakeLLM(want={"mapping": {"ghost": {"field": None, "confidence": 0.0}}}))
    assert e.value.status == 422 and e.value.code == "all_want_declined"

def test_low_confidence_where_is_422_with_interpreted():
    raw = RawQuery(["book_title"], "something vague", "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}},
                  where={"where": {"op": "eq", "field": "category", "value": "x"}, "confidence": 0.4})
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 422 and e.value.code == "where_low_confidence"
    assert e.value.interpreted["where"]["confidence"] == 0.4

def test_invalid_ast_field_is_422():
    raw = RawQuery(["book_title"], "bad filter", "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}},
                  where={"where": {"op": "eq", "field": "not_a_column", "value": 1}, "confidence": 0.9})
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 422 and e.value.code == "invalid_ast"

def test_malformed_ast_is_422_not_500():
    # a `not` node with no `clause` and a `between` with a scalar value are
    # malformed model outputs; validate_ast must reject them as 422 invalid_ast
    # rather than letting a KeyError/TypeError escape as a 500.
    for bad in ({"op": "not"},
                {"op": "between", "field": "category", "value": "oops"}):
        raw = RawQuery(["book_title"], "bad filter", "2026-07-06")
        llm = FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}},
                      where={"where": bad, "confidence": 0.9})
        with pytest.raises(GatewayError) as e:
            _run(raw, llm)
        assert e.value.status == 422 and e.value.code == "invalid_ast"

def test_field_cache_prevents_second_llm_call():
    cache = ResolutionCache()
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}})
    _run(raw, llm, cache); calls_after_first = llm.calls
    _run(raw, llm, cache)
    assert llm.calls == calls_after_first          # served from cache, no new LLM call

def test_llm_failure_retries_once_then_502():
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "title", "confidence": 0.95}}},
                  fail_times=3)                     # both attempts fail
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 502
