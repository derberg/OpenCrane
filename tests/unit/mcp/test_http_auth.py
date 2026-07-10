"""Unit tests for wiring the local-mode OAuth provider into the FastMCP HTTP app."""

import pytest
from unittest.mock import patch, AsyncMock

from starlette.testclient import TestClient

import opencrane.mcp.http_server as http_server
from opencrane.mcp.http_server import build_app
from opencrane.mcp.auth import build_fastmcp_auth
from opencrane.mcp.auth.config_model import AuthConfig, AuthConfigError, parse_auth_config


@pytest.fixture(autouse=True)
def reset_module_globals():
    """Reset module-level state before and after each test for isolation."""
    http_server._services_ready = False
    http_server._milvus_stats = None
    yield
    http_server._services_ready = False
    http_server._milvus_stats = None


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    """Write a local-token config.yaml and point MAPPING_FILE at it, with env set."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("auth:\n  type: local\n  local:\n    method: token\n", encoding="utf-8")
    monkeypatch.setenv("MAPPING_FILE", str(cfg))
    monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")
    monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "s3cret-token")
    return cfg


class TestBuildFastmcpAuth:
    def test_none_returns_empty(self):
        assert build_fastmcp_auth(AuthConfig(type="none")) == {}

    def test_custom_returns_empty(self):
        assert build_fastmcp_auth(AuthConfig(type="custom")) == {}

    def test_local_returns_provider_and_settings(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")
        monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "s3cret-token")
        kwargs = build_fastmcp_auth(AuthConfig(type="local", local_method="token"))
        assert "auth_server_provider" in kwargs
        assert "auth" in kwargs
        from opencrane.mcp.auth.local_provider import OpenCraneAuthProvider
        assert isinstance(kwargs["auth_server_provider"], OpenCraneAuthProvider)

    def test_local_missing_public_url_raises(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "s3cret-token")
        with pytest.raises(AuthConfigError):
            build_fastmcp_auth(AuthConfig(type="local", local_method="token"))

    def test_oauth_not_yet_available(self):
        with pytest.raises(AuthConfigError):
            build_fastmcp_auth(AuthConfig(type="oauth"))

    def test_oauth_returns_token_verifier_and_settings(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")
        stub_verifier = object()
        monkeypatch.setattr(
            "opencrane.mcp.auth.wiring.build_token_verifier",
            lambda cfg: stub_verifier,
        )
        cfg = AuthConfig(
            type="oauth",
            oidc_issuer="https://idp.example.com",
            oidc_audiences=("https://docs.example.com",),
        )
        kwargs = build_fastmcp_auth(cfg)
        assert kwargs["token_verifier"] is stub_verifier
        assert kwargs["auth"].issuer_url is not None
        assert kwargs["auth"].resource_server_url is not None

    def test_oauth_missing_public_url_raises(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        cfg = AuthConfig(
            type="oauth",
            oidc_issuer="https://idp.example.com",
            oidc_audiences=("https://docs.example.com",),
        )
        with pytest.raises(AuthConfigError):
            build_fastmcp_auth(cfg)

    def test_oauth_allow_anonymous_returns_open_kwargs(self, monkeypatch):
        """optional-auth (allow_anonymous) leaves FastMCP open; no PUBLIC_URL needed."""
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        cfg = AuthConfig(
            type="oauth",
            allow_anonymous=True,
            oidc_issuer="https://idp.example.com",
            oidc_audiences=("cennso-knowledge-mcp",),
        )
        assert build_fastmcp_auth(cfg) == {}


class TestBuildAsgiApp:
    def test_oauth_allow_anonymous_wraps_with_optional_auth(self, tmp_path, monkeypatch):
        """optional-auth mode wraps the app in OptionalAuthMiddleware."""
        from opencrane.mcp.auth.optional_auth import OptionalAuthMiddleware

        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n"
            "  type: oauth\n"
            "  allow_anonymous: true\n"
            "  oidc:\n"
            "    issuer: https://idp.example.com\n"
            "    audience: cennso-knowledge-mcp\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        app = http_server.build_asgi_app()
        assert isinstance(app, OptionalAuthMiddleware)

    def test_non_optional_returns_plain_app(self, tmp_path, monkeypatch):
        """Modes other than oauth+allow_anonymous return the app unwrapped."""
        from opencrane.mcp.auth.optional_auth import OptionalAuthMiddleware

        cfg = tmp_path / "config.yaml"
        cfg.write_text("auth:\n  type: none\n", encoding="utf-8")
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        app = http_server.build_asgi_app()
        assert not isinstance(app, OptionalAuthMiddleware)


class TestOauthModeApp:
    def test_serves_protected_resource_metadata_and_401s(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n"
            "  type: oauth\n"
            "  oidc:\n"
            "    issuer: https://idp.example.com\n"
            "    audience: https://docs.example.com\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")

        class StubVerifier:
            async def verify_token(self, token):
                return None

        # Inject a stub verifier so no network/JWKS lookup happens.
        monkeypatch.setattr(
            "opencrane.mcp.auth.wiring.build_token_verifier",
            lambda c: StubVerifier(),
        )
        app = build_app().streamable_http_app()
        client = TestClient(app)
        meta = client.get("/.well-known/oauth-protected-resource")
        assert meta.status_code == 200
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401


class TestNoneModeApp:
    def test_mcp_endpoint_open_no_auth_routes(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("", encoding="utf-8")
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        app = build_app().streamable_http_app()
        paths = {getattr(r, "path", None) for r in app.routes}
        assert "/.well-known/oauth-authorization-server" not in paths
        assert "/login" not in paths
        # Open app: the MCP endpoint is reachable (lifespan runs it), not a 401 challenge.
        with patch("opencrane.mcp.http_server.init_services", new=AsyncMock()):
            with TestClient(app) as client:
                resp = client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Accept": "application/json, text/event-stream"},
                )
        assert resp.status_code != 401


class TestLocalModeApp:
    def test_unauthorized_mcp_request_401(self, local_config):
        client = TestClient(build_app().streamable_http_app())
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401

    def test_as_metadata_served(self, local_config):
        client = TestClient(build_app().streamable_http_app())
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200

    def test_login_get_renders_form(self, local_config):
        client = TestClient(build_app().streamable_http_app())
        resp = client.get("/login?request_id=abc123")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert 'name="token"' in resp.text
        assert 'name="request_id"' in resp.text

    def test_login_post_wrong_token_re_renders_error(self, local_config):
        # Seed a pending authorize request so the request_id is known.
        app_mcp = build_app()
        client = TestClient(app_mcp.streamable_http_app())
        provider = app_mcp._auth_server_provider
        import asyncio
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull
        clinfo = OAuthClientInformationFull(
            client_id="c1", redirect_uris=["https://client.example.com/cb"]
        )
        params = AuthorizationParams(
            state="st",
            scopes=[],
            code_challenge="challenge",
            redirect_uri="https://client.example.com/cb",
            redirect_uri_provided_explicitly=True,
            resource=None,
        )
        redirect = asyncio.run(
            provider.authorize(clinfo, params)
        )
        request_id = redirect.split("request_id=")[1]

        resp = client.post(
            "/login",
            data={"request_id": request_id, "token": "wrong-token"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
        assert "Invalid credentials" in resp.text
        assert 'name="token"' in resp.text

    def test_login_post_correct_token_redirects_with_code(self, local_config):
        app_mcp = build_app()
        client = TestClient(app_mcp.streamable_http_app())
        provider = app_mcp._auth_server_provider
        import asyncio
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull
        clinfo = OAuthClientInformationFull(
            client_id="c1", redirect_uris=["https://client.example.com/cb"]
        )
        params = AuthorizationParams(
            state="st",
            scopes=[],
            code_challenge="challenge",
            redirect_uri="https://client.example.com/cb",
            redirect_uri_provided_explicitly=True,
            resource=None,
        )
        redirect = asyncio.run(
            provider.authorize(clinfo, params)
        )
        request_id = redirect.split("request_id=")[1]

        resp = client.post(
            "/login",
            data={"request_id": request_id, "token": "s3cret-token"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "?code=" in resp.headers["location"] or "&code=" in resp.headers["location"]


class TestLocalPasswordModeApp:
    def test_login_post_password_fields_read(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n  type: local\n  local:\n    method: password\n", encoding="utf-8"
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")
        monkeypatch.setenv("OPENCRANE_LOGIN_USER", "admin")
        monkeypatch.setenv("OPENCRANE_LOGIN_PASS", "hunter2")

        app_mcp = build_app()
        client = TestClient(app_mcp.streamable_http_app())
        provider = app_mcp._auth_server_provider
        import asyncio
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull
        clinfo = OAuthClientInformationFull(
            client_id="c1", redirect_uris=["https://client.example.com/cb"]
        )
        params = AuthorizationParams(
            state="st",
            scopes=[],
            code_challenge="challenge",
            redirect_uri="https://client.example.com/cb",
            redirect_uri_provided_explicitly=True,
            resource=None,
        )
        redirect = asyncio.run(
            provider.authorize(clinfo, params)
        )
        request_id = redirect.split("request_id=")[1]

        resp = client.post(
            "/login",
            data={"request_id": request_id, "username": "admin", "password": "hunter2"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "code=" in resp.headers["location"]


class TestMultiEndpointApp:
    """A named ``auth`` map produces one MCP endpoint per name at /mcp/<name>."""

    def _write_two_open_endpoints(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n"
            "  public:\n"
            "    type: none\n"
            "  docs:\n"
            "    type: none\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        return cfg

    def test_route_composition_one_endpoint_per_name(self, tmp_path, monkeypatch):
        """Each named endpoint gets its own /mcp/<name> route; one shared /health; no root /mcp."""
        self._write_two_open_endpoints(tmp_path, monkeypatch)
        app = http_server.build_asgi_app()
        parent = app.app  # unwrap _EndpointRoutingMiddleware
        paths = {getattr(r, "path", None) for r in parent.routes}
        assert {"/mcp/public", "/mcp/docs", "/health"} <= paths
        assert "/mcp" not in paths

    def test_serves_each_endpoint_and_health(self, tmp_path, monkeypatch):
        """Both endpoints route (not 404) and stay open (not 401); /health is 200; unknown path 404."""
        self._write_two_open_endpoints(tmp_path, monkeypatch)
        app = http_server.build_asgi_app()
        with patch("opencrane.mcp.http_server.init_services", new=AsyncMock()):
            with TestClient(app) as client:
                health = client.get("/health")
                assert health.status_code in (200, 503)
                for name in ("public", "docs"):
                    resp = client.post(
                        f"/mcp/{name}",
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                        headers={"Accept": "application/json, text/event-stream"},
                    )
                    assert resp.status_code != 404  # route matched
                    assert resp.status_code != 401  # open, no auth challenge
                missing = client.post(
                    "/mcp/nope",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Accept": "application/json, text/event-stream"},
                )
                assert missing.status_code == 404

    def test_named_oauth_endpoint_challenges_while_public_stays_open(self, tmp_path, monkeypatch):
        """public=none stays open; private=oauth issues a 401 with its own scoped PRM."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n"
            "  public:\n"
            "    type: none\n"
            "  private:\n"
            "    type: oauth\n"
            "    oidc:\n"
            "      issuer: https://idp.example.com\n"
            "      audience: https://docs.example.com/mcp/private\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")

        class StubVerifier:
            async def verify_token(self, token):
                return None

        monkeypatch.setattr(
            "opencrane.mcp.auth.wiring.build_token_verifier",
            lambda c: StubVerifier(),
        )
        app = http_server.build_asgi_app()
        parent = app.app
        paths = {getattr(r, "path", None) for r in parent.routes}
        # RFC 9728 metadata for the private endpoint is scoped to its own path.
        assert "/.well-known/oauth-protected-resource/mcp/private" in paths

        client = TestClient(app)
        challenge = client.post(
            "/mcp/private",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert challenge.status_code == 401
        meta = client.get("/.well-known/oauth-protected-resource/mcp/private")
        assert meta.status_code == 200
        assert meta.json()["resource"].rstrip("/") == "https://docs.example.com/mcp/private"

    def test_two_authenticated_endpoints_rejected(self, tmp_path, monkeypatch):
        """Only one token-verifier endpoint is supported; a second fails closed."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n"
            "  first:\n"
            "    type: oauth\n"
            "    oidc:\n"
            "      issuer: https://idp.example.com\n"
            "      audience: a\n"
            "  second:\n"
            "    type: oauth\n"
            "    oidc:\n"
            "      issuer: https://idp2.example.com\n"
            "      audience: b\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")

        class StubVerifier:
            async def verify_token(self, token):
                return None

        monkeypatch.setattr(
            "opencrane.mcp.auth.wiring.build_token_verifier",
            lambda c: StubVerifier(),
        )
        with pytest.raises(AuthConfigError, match="multiple authenticated endpoints"):
            http_server.build_asgi_app()

    def test_two_local_endpoints_rejected(self, tmp_path, monkeypatch):
        """Two 'type: local' endpoints also count as authenticated → rejected."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n"
            "  one:\n"
            "    type: local\n"
            "    local:\n"
            "      method: token\n"
            "  two:\n"
            "    type: local\n"
            "    local:\n"
            "      method: token\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")
        monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "s3cret-token")
        with pytest.raises(AuthConfigError, match="multiple authenticated endpoints"):
            http_server.build_asgi_app()

    def test_named_allow_anonymous_is_rejected(self, tmp_path, monkeypatch):
        """allow_anonymous is unsupported for named endpoints — fail closed at build."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n"
            "  public:\n"
            "    type: none\n"
            "  loose:\n"
            "    type: oauth\n"
            "    allow_anonymous: true\n"
            "    oidc:\n"
            "      issuer: https://idp.example.com\n"
            "      audience: x\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        with pytest.raises(AuthConfigError, match="allow_anonymous is not supported"):
            http_server.build_asgi_app()


class TestEndpointRoutingMiddleware:
    """The routing middleware tags each request with its endpoint name."""

    @pytest.mark.anyio
    async def test_sets_endpoint_name_from_path(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "opencrane.mcp.auth.runtime.set_current_endpoint",
            lambda name: captured.setdefault("names", []).append(name),
        )

        async def inner(scope, receive, send):
            captured.setdefault("reached", []).append(scope.get("path"))

        mw = http_server._EndpointRoutingMiddleware(inner, ["public", "private"])

        async def recv():
            return {}

        async def send(_m):
            return None

        for path, expected in [
            ("/mcp/private", "private"),
            ("/mcp/public/sub", "public"),
            ("/health", ""),
            ("/.well-known/oauth-protected-resource/mcp/private", ""),
        ]:
            await mw({"type": "http", "path": path}, recv, send)
        assert captured["names"] == ["private", "public", "", ""]
        # All requests still reached the inner app.
        assert len(captured["reached"]) == 4

    @pytest.mark.anyio
    async def test_non_http_scope_passes_through_without_tagging(self, monkeypatch):
        called = {"set": 0}
        monkeypatch.setattr(
            "opencrane.mcp.auth.runtime.set_current_endpoint",
            lambda name: called.__setitem__("set", called["set"] + 1),
        )
        reached = {"ok": False}

        async def inner(scope, receive, send):
            reached["ok"] = True

        mw = http_server._EndpointRoutingMiddleware(inner, ["public"])
        await mw({"type": "lifespan"}, None, None)
        assert reached["ok"] is True
        assert called["set"] == 0


class TestNoopLifespan:
    @pytest.mark.anyio
    async def test_noop_lifespan_yields(self):
        async with http_server._noop_lifespan(object()):
            pass


class TestBuildAppMissingPublicUrl:
    def test_local_without_public_url_raises(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n  type: local\n  local:\n    method: token\n", encoding="utf-8"
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "s3cret-token")
        with pytest.raises(AuthConfigError):
            build_app()
