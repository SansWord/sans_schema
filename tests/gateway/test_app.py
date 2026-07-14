from fastapi.testclient import TestClient
from gateway.app import app, get_llm, get_connector, get_settings, get_cache
from gateway.cache import ResolutionCache
from gateway.config import Settings
from gateway.connectors.fake import FakeConnector
from tests.fakes import FakeLLM

def _settings(**kw):
    base = dict(database_url="", llm_model="fake", gate_threshold=0.7, result_limit=100,
                max_want_fields=50, max_field_len=200, max_where_len=2000,
                enable_debug_endpoints=False)
    base.update(kw)
    return lambda: Settings(**base)

_tiny_limits = _settings(max_want_fields=3, max_field_len=20, max_where_len=15)
_debug_on = _settings(enable_debug_endpoints=True)
_query_debug_on = _settings(enable_query_debug=True)

WANT_OK = {"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95},
                       "genre": {"field": "books_view.category", "confidence": 0.92}}}
WHERE_OK = {"where": {"op": "eq", "field": "books_view.category", "value": "Science Fiction"},
            "confidence": 0.9}

def _client(llm):
    app.dependency_overrides[get_connector] = lambda: FakeConnector()
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)

def teardown_function():
    app.dependency_overrides.clear()

def test_query_returns_rows_in_client_keys():
    c = _client(FakeLLM(want=WANT_OK, where=WHERE_OK))
    r = c.post("/query", json={"want": {"book_title": None, "genre": None},
                               "where": "sci-fi only", "isVerbose": True})
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] and all(set(row) == {"book_title", "genre"} for row in body["rows"])
    # values actually remapped from the qualified field path (guards the view.column round-trip)
    assert all(row["genre"] == "Science Fiction" and row["book_title"] for row in body["rows"])
    assert body["interpreted"]["want"]["book_title"]["field"] == "books_view.title"

def test_low_confidence_where_returns_422_with_interpreted():
    llm = FakeLLM(want=WANT_OK,
                  where={"where": {"op": "eq", "field": "books_view.category", "value": "x"},
                         "confidence": 0.3})
    c = _client(llm)
    r = c.post("/query", json={"want": {"book_title": None}, "where": "vague"})
    assert r.status_code == 422
    assert r.json()["interpreted"]["where"]["confidence"] == 0.3   # present even without isVerbose

def test_want_as_list_is_accepted():
    c = _client(FakeLLM(want={"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}}))
    r = c.post("/query", json={"want": ["book_title"]})
    assert r.status_code == 200

def test_too_many_want_fields_is_422():
    app.dependency_overrides[get_settings] = _tiny_limits
    c = _client(FakeLLM(want=WANT_OK))
    r = c.post("/query", json={"want": {"a": None, "b": None, "c": None, "d": None}})
    assert r.status_code == 422 and r.json()["error"] == "too_many_want_fields"

def test_where_too_long_is_422():
    app.dependency_overrides[get_settings] = _tiny_limits
    c = _client(FakeLLM(want=WANT_OK))
    r = c.post("/query", json={"want": {"book_title": None}, "where": "x" * 100})
    assert r.status_code == 422 and r.json()["error"] == "where_too_long"

def test_long_field_name_is_422():
    app.dependency_overrides[get_settings] = _tiny_limits
    c = _client(FakeLLM(want=WANT_OK))
    r = c.post("/query", json={"want": {"x" * 100: None}})
    assert r.status_code == 422 and r.json()["error"] == "field_name_too_long"

def test_debug_endpoints_404_when_disabled():
    c = _client(FakeLLM())          # default settings → debug off
    assert c.get("/debug/prompts").status_code == 404
    assert c.get("/debug/schema").status_code == 404
    assert c.get("/debug/cache").status_code == 404

def test_debug_prompts_when_enabled():
    app.dependency_overrides[get_settings] = _debug_on
    c = _client(FakeLLM())
    body = c.get("/debug/prompts").json()
    assert "want" in body["system"] and "where" in body["system"]
    assert "eq" in body["operators"]
    assert "cache_control" in body["prompt_cache_layout"]

def test_debug_schema_when_enabled_discloses_fields():
    app.dependency_overrides[get_settings] = _debug_on
    c = _client(FakeLLM())
    body = c.get("/debug/schema").json()
    paths = {f["path"] for f in body["fields"]}
    assert "books_view.title" in paths
    assert body["as_prompt"].startswith("Backend schema:")
    assert body["schema_version"]

def test_debug_cache_when_enabled_lists_entries():
    app.dependency_overrides[get_settings] = _debug_on
    fresh = ResolutionCache()
    fresh.set_field("fake", "v1", "writer", {"field": "author_name", "confidence": 0.9})
    fresh.set_where("fake", "v1", "sci-fi", "2026-07-07", {"ast": {"op": "eq"}, "confidence": 0.8})
    app.dependency_overrides[get_cache] = lambda: fresh
    c = _client(FakeLLM())
    body = c.get("/debug/cache").json()
    assert body["field_count"] == 1 and body["where_count"] == 1
    assert body["field"][0]["key"] == "writer"
    assert body["where"][0]["today"] == "2026-07-07"

def test_debug_cache_reports_hit_rate():
    app.dependency_overrides[get_settings] = _debug_on
    fresh = ResolutionCache()
    fresh.get_field("fake", "v1", "x")                                 # miss
    fresh.set_field("fake", "v1", "x", {"field": "c", "confidence": 0.9})
    fresh.get_field("fake", "v1", "x")                                 # hit
    app.dependency_overrides[get_cache] = lambda: fresh
    c = _client(FakeLLM())
    stats = c.get("/debug/cache").json()["stats"]
    assert stats["field"]["hits"] == 1 and stats["field"]["misses"] == 1
    assert stats["combined"]["hit_rate"] == 0.5

def test_to_raw_query_parses_is_debug():
    from gateway.app import to_raw_query
    assert to_raw_query({"want": ["t"], "isDebug": True}).debug is True
    assert to_raw_query({"want": ["t"]}).debug is False

def test_is_debug_silently_ignored_when_gate_off():
    c = _client(FakeLLM(want=WANT_OK, where=WHERE_OK))
    r = c.post("/query", json={"want": {"book_title": None}, "where": "sci-fi only",
                               "isDebug": True})
    assert r.status_code == 200
    body = r.json()
    assert "debug" not in body
    assert "interpreted" not in body    # the isVerbose implication is gated too

def test_is_debug_returns_block_and_implies_interpreted():
    app.dependency_overrides[get_settings] = _query_debug_on
    app.dependency_overrides[get_cache] = lambda: ResolutionCache()   # fresh — assert on miss below
    c = _client(FakeLLM(want=WANT_OK, where=WHERE_OK))
    r = c.post("/query", json={"want": {"book_title": None, "genre": None},
                               "where": "sci-fi only", "isDebug": True})
    assert r.status_code == 200
    body = r.json()
    assert body["debug"]["gate_threshold"] == 0.7
    assert body["debug"]["cache"]["want"] == {"book_title": "miss", "genre": "miss"}
    assert body["debug"]["execution"]["engine"] == "core.predicate"
    assert body["interpreted"]["want"]["book_title"]["field"] == "books_view.title"

def test_low_confidence_422_body_carries_debug_when_requested():
    app.dependency_overrides[get_settings] = _query_debug_on
    app.dependency_overrides[get_cache] = lambda: ResolutionCache()   # fresh — assert on miss below
    llm = FakeLLM(want=WANT_OK,
                  where={"where": {"op": "eq", "field": "books_view.category", "value": "x"},
                         "confidence": 0.3})
    c = _client(llm)
    r = c.post("/query", json={"want": {"book_title": None}, "where": "vague",
                               "isDebug": True})
    assert r.status_code == 422
    body = r.json()
    assert body["debug"]["cache"]["where"] == "miss"
    assert body["debug"]["execution"] is None

def test_error_body_omits_debug_key_when_not_requested():
    llm = FakeLLM(want=WANT_OK,
                  where={"where": {"op": "eq", "field": "books_view.category", "value": "x"},
                         "confidence": 0.3})
    c = _client(llm)
    r = c.post("/query", json={"want": {"book_title": None}, "where": "vague"})
    assert r.status_code == 422 and "debug" not in r.json()
