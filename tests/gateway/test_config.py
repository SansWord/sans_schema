"""Settings.from_env parsing for the guardrail + DB_VIEW additions (demo-session spec)."""
from gateway.config import Settings

GUARDRAIL_VARS = ("RATE_LIMIT_PER_IP", "DAILY_REQUEST_CAP", "CORS_ORIGINS",
                  "CLIENT_IP_HEADER", "DB_VIEW")


def _clear(monkeypatch):
    for var in GUARDRAIL_VARS:
        monkeypatch.delenv(var, raising=False)


def test_guardrails_default_off(monkeypatch):
    _clear(monkeypatch)
    s = Settings.from_env()
    assert s.rate_limit_per_ip == ""
    assert s.daily_request_cap == ""
    assert s.cors_origins == []
    assert s.client_ip_header == ""
    assert s.db_view == "books_view"


def test_guardrails_parse_from_env(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "10/minute")
    monkeypatch.setenv("DAILY_REQUEST_CAP", "1000/day")
    monkeypatch.setenv("CORS_ORIGINS", "https://play.example.com, http://localhost:3000")
    monkeypatch.setenv("CLIENT_IP_HEADER", "Fly-Client-IP")
    monkeypatch.setenv("DB_VIEW", "inventory_view")
    s = Settings.from_env()
    assert s.rate_limit_per_ip == "10/minute"
    assert s.daily_request_cap == "1000/day"
    assert s.cors_origins == ["https://play.example.com", "http://localhost:3000"]
    assert s.client_ip_header == "Fly-Client-IP"
    assert s.db_view == "inventory_view"


def test_get_connector_uses_db_view(monkeypatch):
    monkeypatch.setenv("DB_VIEW", "inventory_view")
    import gateway.app as ga
    ga.get_settings.cache_clear()
    ga.get_connector.cache_clear()
    try:
        assert ga.get_connector().view == "inventory_view"
        assert ga.get_connector().backend_id == "postgres:inventory_view"
    finally:
        ga.get_settings.cache_clear()   # don't leak the patched settings
        ga.get_connector.cache_clear()


def test_query_debug_gate_default_off(monkeypatch):
    monkeypatch.delenv("ENABLE_QUERY_DEBUG", raising=False)
    assert Settings.from_env().enable_query_debug is False


def test_query_debug_gate_parses_from_env(monkeypatch):
    monkeypatch.setenv("ENABLE_QUERY_DEBUG", "1")
    assert Settings.from_env().enable_query_debug is True
