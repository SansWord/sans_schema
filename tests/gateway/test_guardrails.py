"""Guardrail tests (demo-session spec): proxy-header key fn, per-IP limit,
global daily cap, CORS, friendly 429 bodies, defaults-off."""
from fastapi.testclient import TestClient
from starlette.requests import Request

from gateway.app import create_app, get_connector, get_llm
from gateway.config import Settings
from gateway.connectors.fake import FakeConnector
from gateway.guardrails import client_ip
from tests.fakes import FakeLLM


def _settings(**kw):
    base = dict(database_url="", llm_model="fake", gate_threshold=0.7, result_limit=100,
                max_want_fields=50, max_field_len=200, max_where_len=2000,
                enable_debug_endpoints=False)
    base.update(kw)
    return Settings(**base)


def _request(headers=None, client=("10.0.0.1", 1234)):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/query",
                    "headers": raw, "client": client, "query_string": b"",
                    "server": ("testserver", 80), "scheme": "http"})


def test_client_ip_reads_configured_header_first_hop():
    s = _settings(client_ip_header="X-Forwarded-For")
    r = _request({"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
    assert client_ip(r, s) == "203.0.113.9"


def test_client_ip_falls_back_to_socket_peer():
    # header configured but absent on the request → socket peer
    assert client_ip(_request(), _settings(client_ip_header="Fly-Client-IP")) == "10.0.0.1"
    # no header configured at all → socket peer
    assert client_ip(_request(), _settings()) == "10.0.0.1"


WANT_OK = {"mapping": {"book_title": {"field": "books_view.title", "confidence": 0.95}}}
BODY = {"want": ["book_title"]}


def _client(settings):
    """A fresh app per test — fresh in-memory limiter storage, no state bleed."""
    app = create_app(settings)
    app.dependency_overrides[get_connector] = lambda: FakeConnector()
    app.dependency_overrides[get_llm] = lambda: FakeLLM(want=WANT_OK)
    return TestClient(app)


def test_cors_preflight_allows_configured_origin():
    c = _client(_settings(cors_origins=["https://play.example.com"]))
    r = c.options("/query", headers={"Origin": "https://play.example.com",
                                     "Access-Control-Request-Method": "POST"})
    assert r.headers["access-control-allow-origin"] == "https://play.example.com"


def test_cors_rejects_unlisted_origin():
    c = _client(_settings(cors_origins=["https://play.example.com"]))
    r = c.options("/query", headers={"Origin": "https://evil.example.com",
                                     "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers
