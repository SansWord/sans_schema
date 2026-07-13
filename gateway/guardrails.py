"""Public-demo guardrails (demo-session spec): CORS + per-IP rate limit + global
daily request cap. Everything here is OFF unless configured in Settings — local
dev and the test suite run with no limiter in the request path at all."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from limits import parse_many
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from gateway.config import Settings

# Error codes double as slowapi `error_message`s so the 429 handler can tell
# which limit tripped. The playground renders these codes as friendly states.
PER_IP_CODE = "rate_limited"
GLOBAL_CODE = "demo_budget_exhausted"

_MESSAGES = {
    PER_IP_CODE: "Too many requests from your address — wait a minute and try again.",
    GLOBAL_CODE: ("The public demo's daily request budget is used up. The gateway is "
                  "open source — run it locally against your own data and API key."),
}


def validate_limits(settings: Settings) -> None:
    """Fail fast on malformed limit strings. slowapi catches parse errors at
    decoration time and only LOGS them — a typo'd limit would silently register
    NO limit at all (fail-open). Parsing eagerly here makes a bad deploy die at
    startup instead of running unprotected."""
    for value in (settings.rate_limit_per_ip, settings.daily_request_cap):
        if value:
            parse_many(value)   # raises ValueError on a malformed rate string


def client_ip(request: Request, settings: Settings) -> str:
    """Rate-limit key. Behind a PaaS proxy `request.client` is the proxy, so read
    the platform's client-IP header when configured (first hop of a comma list) —
    otherwise every visitor would share one bucket. Trust model: the header must
    be one the platform itself sets/overwrites — a client-appendable header (e.g.
    bare X-Forwarded-For) lets visitors mint attacker-chosen keys, defeating the
    per-IP limit (growth stays bounded by the global daily cap)."""
    if settings.client_ip_header:
        value = request.headers.get(settings.client_ip_header)
        if value:
            return value.split(",")[0].strip()
    return get_remote_address(request)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Friendly 429 body the playground can render. `exc.detail` carries the
    error_message attached to whichever limit tripped (per-IP vs global)."""
    code = GLOBAL_CODE if exc.detail == GLOBAL_CODE else PER_IP_CODE
    return JSONResponse(status_code=429,
                        content={"error": code, "message": _MESSAGES[code]})


def build_limiter(settings: Settings) -> Limiter:
    return Limiter(key_func=lambda request: client_ip(request, settings))


def install_guardrails(app: FastAPI, settings: Settings, limiter: Limiter) -> None:
    """Wire the 429 handler + CORS onto the app. The rate-limit decorators are
    applied where the /query endpoint is defined (they wrap the endpoint fn)."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_methods=["POST", "GET", "OPTIONS"],
                           allow_headers=["*"])
