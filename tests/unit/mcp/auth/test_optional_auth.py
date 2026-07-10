"""Unit tests for the optional-auth ASGI middleware (oauth allow_anonymous)."""

import asyncio

from opencrane.mcp.auth.optional_auth import OptionalAuthMiddleware, _extract_bearer
from opencrane.mcp.auth.runtime import current_scopes, reset_auth_runtime


class _AccessToken:
    def __init__(self, scopes):
        self.scopes = scopes


class _FakeVerifier:
    """Verifier stub: returns an access token for 'good', None otherwise."""

    async def verify_token(self, token):
        if token == "good":
            return _AccessToken(["docs:read", "docs:write"])
        return None


def _reset():
    reset_auth_runtime()


def _drive(headers):
    """Run the middleware over an HTTP scope; return the scopes seen downstream."""
    seen = {}

    async def inner(scope, receive, send):
        seen["scopes"] = current_scopes()

    mw = OptionalAuthMiddleware(app=inner, verifier=_FakeVerifier())
    scope = {"type": "http", "headers": headers}

    async def receive():  # pragma: no cover - middleware does not read the body
        return {}

    async def send(_msg):  # pragma: no cover - middleware does not send
        return None

    asyncio.run(mw(scope, receive, send))
    return seen["scopes"]


class TestExtractBearer:
    def test_returns_token_for_bearer(self):
        assert _extract_bearer([(b"authorization", b"Bearer abc123")]) == "abc123"

    def test_case_insensitive_scheme_and_header(self):
        assert _extract_bearer([(b"Authorization", b"bearer xyz")]) == "xyz"

    def test_non_bearer_authorization_returns_none(self):
        assert _extract_bearer([(b"authorization", b"Basic dXNlcg==")]) is None

    def test_missing_header_returns_none(self):
        assert _extract_bearer([(b"content-type", b"application/json")]) is None


class TestOptionalAuthMiddleware:
    def test_valid_token_sets_scopes(self):
        _reset()
        assert _drive([(b"authorization", b"Bearer good")]) == ("docs:read", "docs:write")

    def test_no_token_is_anonymous(self):
        _reset()
        assert _drive([]) == ()

    def test_invalid_token_is_anonymous(self):
        _reset()
        assert _drive([(b"authorization", b"Bearer nope")]) == ()

    def test_non_http_scope_passes_through(self):
        _reset()
        called = {}

        async def inner(scope, receive, send):
            called["ok"] = True

        mw = OptionalAuthMiddleware(app=inner, verifier=_FakeVerifier())

        async def receive():  # pragma: no cover
            return {}

        async def send(_m):  # pragma: no cover
            return None

        asyncio.run(mw({"type": "lifespan"}, receive, send))
        assert called["ok"] is True
