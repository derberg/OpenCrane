"""Unit tests for advertising scopes in the protected-resource metadata."""

import json

import pytest

from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp.server.auth.routes import create_protected_resource_routes

from opencrane.mcp.auth.config_model import AuthConfigError, parse_auth_config
from opencrane.mcp.http_server import _ScopesSupported, _advertise_scopes


RESOURCE = "https://docs.example.com/mcp/private"
ISSUER = "https://idp.example.com/"
PRM_PATH = "/.well-known/oauth-protected-resource/mcp/private"

BASE_METADATA = {
    "resource": RESOURCE,
    "authorization_servers": [ISSUER],
    "bearer_methods_supported": ["header"],
}


def _routes():
    """Build the metadata route exactly as FastMCP mounts it.

    The route is an ASGI app wrapped in CORS middleware, not a request handler,
    so a test that uses a plain function would not exercise the real shape.
    """
    return create_protected_resource_routes(
        resource_url=AnyHttpUrl(RESOURCE),
        authorization_servers=[AnyHttpUrl(ISSUER)],
    )


def _get(routes):
    return TestClient(Starlette(routes=routes)).get(PRM_PATH)


class TestAdvertiseScopes:
    """Rewriting the protected-resource metadata to carry scopes_supported."""

    def test_adds_scopes_supported(self):
        """The configured scopes appear in the metadata."""
        routes = _routes()
        _advertise_scopes(routes, ("openid",))
        assert _get(routes).json()["scopes_supported"] == ["openid"]

    def test_keeps_every_other_field(self):
        """The endpoint stays the source of truth for the rest of the document."""
        routes = _routes()
        _advertise_scopes(routes, ("openid", "profile"))
        body = _get(routes).json()
        assert {k: body[k] for k in BASE_METADATA} == BASE_METADATA
        assert body["scopes_supported"] == ["openid", "profile"]

    def test_no_scopes_leaves_metadata_untouched(self):
        """An unset advertised_scopes list is a no-op."""
        routes = _routes()
        _advertise_scopes(routes, ())
        assert "scopes_supported" not in _get(routes).json()

    def test_preserves_response_headers(self):
        """Headers the endpoint set, such as CORS, survive the rewrite."""
        routes = _routes()
        _advertise_scopes(routes, ("openid",))
        response = TestClient(Starlette(routes=routes)).get(
            PRM_PATH, headers={"Origin": "https://client.example.com"}
        )
        assert response.headers["access-control-allow-origin"] == "*"

    def test_content_length_matches_the_new_body(self):
        """The rewritten response carries its own length, not the original one."""
        routes = _routes()
        _advertise_scopes(routes, ("openid",))
        response = _get(routes)
        assert int(response.headers["content-length"]) == len(response.content)

    def test_other_routes_are_left_alone(self):
        """Only the protected-resource metadata route is rewritten."""

        async def health(request):
            return PlainTextResponse("ok")

        routes = [Route("/health", health, methods=["GET"]), *_routes()]
        _advertise_scopes(routes, ("openid",))
        client = TestClient(Starlette(routes=routes))
        assert client.get("/health").text == "ok"

    def test_non_json_response_passes_through(self):
        """A response that is not JSON is returned unchanged."""

        async def text(request):
            return PlainTextResponse("not json")

        routes = [Route(PRM_PATH, text, methods=["GET"])]
        _advertise_scopes(routes, ("openid",))
        response = TestClient(Starlette(routes=routes)).get(PRM_PATH)
        assert response.text == "not json"


class TestParseAdvertisedScopes:
    """Parsing oidc.advertised_scopes out of the auth block."""

    def _oauth(self, oidc_extra):
        return {
            "auth": {
                "type": "oauth",
                "oidc": {
                    "issuer": "https://idp.example.com",
                    "audience": "docs",
                    **oidc_extra,
                },
            }
        }

    def test_absent_defaults_to_empty(self):
        """Omitting the key advertises nothing, which is the previous behavior."""
        config = parse_auth_config(self._oauth({}), known_sources=set())
        assert config.oidc_advertised_scopes == ()

    def test_list_is_parsed(self):
        """A list of scope names is kept in order."""
        config = parse_auth_config(
            self._oauth({"advertised_scopes": ["openid", "profile"]}), known_sources=set()
        )
        assert config.oidc_advertised_scopes == ("openid", "profile")

    def test_empty_list_advertises_nothing(self):
        """An empty list is accepted and advertises nothing."""
        config = parse_auth_config(
            self._oauth({"advertised_scopes": []}), known_sources=set()
        )
        assert config.oidc_advertised_scopes == ()

    @pytest.mark.parametrize("raw", ["openid", [""], [1], {"a": "b"}])
    def test_invalid_value_raises(self, raw):
        """Anything but a list of non-empty strings is rejected."""
        with pytest.raises(AuthConfigError, match="advertised_scopes"):
            parse_auth_config(self._oauth({"advertised_scopes": raw}), known_sources=set())

    def test_enforcement_is_not_affected(self):
        """Advertising a scope does not make it a required scope."""
        from opencrane.mcp.auth.wiring import build_fastmcp_auth

        config = parse_auth_config(
            self._oauth({"advertised_scopes": ["openid"]}), known_sources=set()
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("PUBLIC_URL", "https://docs.example.com")
            kwargs = build_fastmcp_auth(config, resource_url_suffix="/mcp/private")
        assert kwargs["auth"].required_scopes is None


class TestScopesSupportedAsgiPaths:
    """The ASGI wrapper's own message handling, driven without a server."""

    @staticmethod
    async def _run(app, scope):
        """Call the wrapper and collect everything it sends."""
        sent = []

        async def send(message):
            sent.append(message)

        async def receive():  # pragma: no cover - never awaited in these paths
            return {"type": "http.request"}

        await _ScopesSupported(app, ("openid",))(scope, receive, send)
        return sent

    @pytest.mark.anyio
    async def test_non_http_scope_passes_through(self):
        """A lifespan message reaches the wrapped app untouched."""
        seen = {}

        async def app(scope, receive, send):
            seen["scope"] = scope

        await self._run(app, {"type": "lifespan"})
        assert seen["scope"] == {"type": "lifespan"}

    @pytest.mark.anyio
    async def test_other_messages_are_forwarded(self):
        """A message that is neither start nor body is passed on as it is."""

        async def app(scope, receive, send):
            await send({"type": "http.response.debug", "info": {}})

        sent = await self._run(app, {"type": "http"})
        assert sent == [{"type": "http.response.debug", "info": {}}]

    @pytest.mark.anyio
    async def test_streamed_body_is_joined_before_rewriting(self):
        """A body split across chunks is buffered, then rewritten once."""

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b'{"a":', "more_body": True})
            await send({"type": "http.response.body", "body": b'1}'})

        sent = await self._run(app, {"type": "http"})
        assert json.loads(sent[-1]["body"]) == {"a": 1, "scopes_supported": ["openid"]}
