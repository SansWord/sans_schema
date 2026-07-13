"""Guardrail tests (demo-session spec): proxy-header key fn, per-IP limit,
global daily cap, CORS, friendly 429 bodies, defaults-off."""
import pytest
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


def test_per_ip_limit_returns_friendly_429():
    c = _client(_settings(rate_limit_per_ip="2/minute"))
    assert c.post("/query", json=BODY).status_code == 200
    assert c.post("/query", json=BODY).status_code == 200
    r = c.post("/query", json=BODY)
    assert r.status_code == 429
    assert r.json() == {"error": "rate_limited",
                        "message": r.json()["message"]}   # code exact; message non-empty
    assert r.json()["message"]


def test_per_ip_limit_keys_on_proxy_header():
    c = _client(_settings(rate_limit_per_ip="1/minute", client_ip_header="Fly-Client-IP"))
    ok = c.post("/query", json=BODY, headers={"Fly-Client-IP": "1.1.1.1"})
    assert ok.status_code == 200
    # a different visitor is NOT throttled by the first one's traffic
    other = c.post("/query", json=BODY, headers={"Fly-Client-IP": "2.2.2.2"})
    assert other.status_code == 200
    # the first visitor again → limited
    again = c.post("/query", json=BODY, headers={"Fly-Client-IP": "1.1.1.1"})
    assert again.status_code == 429


def test_global_daily_cap_throttles_across_ips():
    c = _client(_settings(daily_request_cap="2/day", client_ip_header="Fly-Client-IP"))
    assert c.post("/query", json=BODY, headers={"Fly-Client-IP": "1.1.1.1"}).status_code == 200
    assert c.post("/query", json=BODY, headers={"Fly-Client-IP": "2.2.2.2"}).status_code == 200
    r = c.post("/query", json=BODY, headers={"Fly-Client-IP": "3.3.3.3"})
    assert r.status_code == 429
    assert r.json()["error"] == "demo_budget_exhausted"


def test_both_limits_on_per_ip_then_global_cap():
    # The production config: per-IP limit AND global daily cap together. Note that
    # every /query hit — including one rejected 429 by the per-IP limit — consumes
    # the global budget (slowapi evaluates all route limits in one pass).
    c = _client(_settings(rate_limit_per_ip="3/minute", daily_request_cap="5/day",
                          client_ip_header="Fly-Client-IP"))
    ip1 = {"Fly-Client-IP": "1.1.1.1"}
    for _ in range(3):                        # IP1 uses its whole per-IP allowance
        assert c.post("/query", json=BODY, headers=ip1).status_code == 200
    r = c.post("/query", json=BODY, headers=ip1)
    assert r.status_code == 429
    assert r.json()["error"] == "rate_limited"          # per-IP trips first for IP1
    # global budget so far: 3 OK + 1 rate-limited = 4 of 5
    ip2 = {"Fly-Client-IP": "2.2.2.2"}
    assert c.post("/query", json=BODY, headers=ip2).status_code == 200   # 5th hit
    r = c.post("/query", json=BODY, headers=ip2)
    assert r.status_code == 429
    assert r.json()["error"] == "demo_budget_exhausted"  # cap, not IP2's own limit
    # a completely fresh visitor is also refused — the cap is global, not per-IP
    r = c.post("/query", json=BODY, headers={"Fly-Client-IP": "3.3.3.3"})
    assert r.status_code == 429
    assert r.json()["error"] == "demo_budget_exhausted"


def test_malformed_limit_string_fails_fast_at_startup():
    # slowapi catches limit-parse errors at decoration time and only LOGS them —
    # a typo'd limit would silently register no limit at all (fail-open). The
    # gateway must instead refuse to start.
    with pytest.raises(ValueError):
        create_app(_settings(rate_limit_per_ip="10 per minute oops"))
    with pytest.raises(ValueError):
        create_app(_settings(daily_request_cap="not-a-limit"))


def test_defaults_off_no_limits_no_cors():
    c = _client(_settings())
    for _ in range(30):                       # far past any accidental default limit
        assert c.post("/query", json=BODY).status_code == 200
    r = c.post("/query", json=BODY, headers={"Origin": "https://anywhere.example"})
    assert "access-control-allow-origin" not in r.headers
