from fastapi.testclient import TestClient
from gateway.app import app, get_llm, get_connector
from gateway.connectors.fake import FakeConnector
from tests.fakes import FakeLLM

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
