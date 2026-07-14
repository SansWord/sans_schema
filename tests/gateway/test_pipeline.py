import pytest
from gateway.pipeline import run_query, GatewayError
from gateway.contracts import RawQuery
from gateway.gate import GateConfig
from gateway.cache import ResolutionCache
from gateway.connectors.fake import FakeConnector
from tests.fakes import FakeLLM

WANT_OK = {"mapping": {
    "book_title": {"field": "books_view.title", "confidence": 0.95},
    "genre":      {"field": "books_view.category", "confidence": 0.92}}}
WHERE_OK = {"where": {"op": "eq", "field": "books_view.category", "value": "Science Fiction"},
            "confidence": 0.9}

def _run(raw, llm, cache=None, debug=False):
    return run_query(raw, FakeConnector(), llm, cache or ResolutionCache(),
                     GateConfig(threshold=0.7), limit=100, debug=debug)

def test_happy_path_returns_rows_in_client_keys():
    raw = RawQuery(["book_title", "genre"], "sci-fi only", "2026-07-06", verbose=True)
    resp = _run(raw, FakeLLM(want=WANT_OK, where=WHERE_OK))
    assert resp["rows"] and all(set(r) == {"book_title", "genre"} for r in resp["rows"])
    assert all(r["genre"] == "Science Fiction" for r in resp["rows"])
    assert resp["interpreted"]["want"]["book_title"]["field"] == "books_view.title"
    assert resp["interpreted"]["where"]["confidence"] == 0.9

def test_non_verbose_omits_interpreted():
    raw = RawQuery(["book_title"], None, "2026-07-06")
    resp = _run(raw, FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}}))
    assert "interpreted" not in resp

def test_all_want_declined_is_422():
    raw = RawQuery(["ghost"], None, "2026-07-06")
    with pytest.raises(GatewayError) as e:
        _run(raw, FakeLLM(want={"mapping": {"ghost": {"field": None, "confidence": 0.0}}}))
    assert e.value.status == 422 and e.value.code == "all_want_declined"

def test_low_confidence_where_is_422_with_interpreted():
    raw = RawQuery(["book_title"], "something vague", "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}},
                  where={"where": {"op": "eq", "field": "books_view.category", "value": "x"}, "confidence": 0.4})
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 422 and e.value.code == "where_low_confidence"
    assert e.value.interpreted["where"]["confidence"] == 0.4

def test_invalid_ast_field_is_422():
    raw = RawQuery(["book_title"], "bad filter", "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}},
                  where={"where": {"op": "eq", "field": "books_view.not_a_column", "value": 1}, "confidence": 0.9})
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 422 and e.value.code == "invalid_ast"

def test_malformed_ast_is_422_not_500():
    # a `not` node with no `clause` and a `between` with a scalar value are
    # malformed model outputs; validate_ast must reject them as 422 invalid_ast
    # rather than letting a KeyError/TypeError escape as a 500.
    for bad in ({"op": "not"},
                {"op": "between", "field": "books_view.category", "value": "oops"}):
        raw = RawQuery(["book_title"], "bad filter", "2026-07-06")
        llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}},
                      where={"where": bad, "confidence": 0.9})
        with pytest.raises(GatewayError) as e:
            _run(raw, llm)
        assert e.value.status == 422 and e.value.code == "invalid_ast"

def test_type_mismatched_where_is_422_before_execute():
    # a non-numeric value on the integer book_id column (the case-35 "managers" shape)
    # is caught by the static type check → 422, never reaching the connector / a 502.
    raw = RawQuery(["book_title"], "managers", "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}},
                  where={"where": {"op": "in", "field": "books_view.book_id",
                                   "value": ["select distinct manager_id from x"]}, "confidence": 0.9})
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 422 and e.value.code == "invalid_ast"

def test_field_cache_prevents_second_llm_call():
    cache = ResolutionCache()
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}})
    _run(raw, llm, cache); calls_after_first = llm.calls
    _run(raw, llm, cache)
    assert llm.calls == calls_after_first          # served from cache, no new LLM call

def test_llm_failure_retries_once_then_502():
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}},
                  fail_times=3)                     # both attempts fail
    with pytest.raises(GatewayError) as e:
        _run(raw, llm)
    assert e.value.status == 502

def test_want_resolved_to_unknown_path_is_declined_not_500():
    # a confident resolution to a non-schema column must become a null column, not a
    # bogus SELECT identifier (which the real backend would reject → 500).
    raw = RawQuery(["book_title", "genre"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {
        "book_title": {"field": "books_view.title", "confidence": 0.99},
        "genre":      {"field": "books_view.ghost", "confidence": 0.99}}})  # not a real path
    resp = _run(raw, llm)
    assert resp["rows"] and all(set(r) == {"book_title", "genre"} for r in resp["rows"])
    assert all(r["genre"] is None for r in resp["rows"])          # declined → null column

def test_backend_execute_error_is_502():
    class BoomConnector(FakeConnector):
        def execute(self, ir):
            raise RuntimeError("db exploded")
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}})
    with pytest.raises(GatewayError) as e:
        run_query(raw, BoomConnector(), llm, ResolutionCache(), GateConfig(0.7), 100)
    assert e.value.status == 502 and e.value.code == "backend_error"

def test_backend_describe_error_is_502():
    class NoDescribe(FakeConnector):
        def describe(self):
            raise RuntimeError("introspection failed")
    raw = RawQuery(["book_title"], None, "2026-07-06")
    with pytest.raises(GatewayError) as e:
        run_query(raw, NoDescribe(), FakeLLM(), ResolutionCache(), GateConfig(0.7), 100)
    assert e.value.status == 502 and e.value.code == "backend_error"

def test_debug_block_reports_cache_threshold_and_execution():
    cache = ResolutionCache()
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}},
                  where=WHERE_OK)
    raw = RawQuery(["book_title"], "sci-fi only", "2026-07-06", verbose=True)
    dbg = _run(raw, llm, cache, debug=True)["debug"]
    assert dbg["gate_threshold"] == 0.7
    assert dbg["cache"] == {"want": {"book_title": "miss"}, "where": "miss"}
    assert dbg["execution"] == {"engine": "core.predicate", "sql": None, "params": None}
    # same request again → both caches hit (the "second click is free" beat)
    raw2 = RawQuery(["book_title"], "sci-fi only", "2026-07-06", verbose=True)
    dbg2 = _run(raw2, llm, cache, debug=True)["debug"]
    assert dbg2["cache"] == {"want": {"book_title": "hit"}, "where": "hit"}

def test_debug_block_omits_where_status_without_a_where():
    raw = RawQuery(["book_title"], None, "2026-07-06")
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}})
    dbg = _run(raw, llm, debug=True)["debug"]
    assert dbg["cache"] == {"want": {"book_title": "miss"}}

def test_debug_off_omits_block():
    raw = RawQuery(["book_title"], None, "2026-07-06", verbose=True)
    llm = FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}})
    assert "debug" not in _run(raw, llm)
