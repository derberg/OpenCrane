"""Unit tests for the external-IdP JWT token verifier (auth.type 'oauth')."""

import asyncio
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from opencrane.mcp.auth.config_model import AuthConfig, AuthConfigError
from opencrane.mcp.auth.oauth_verifier import (
    JwtTokenVerifier,
    _discover_jwks_uri,
    _extract_scopes,
    build_token_verifier,
)


ISSUER = "https://idp.example.com"
AUDIENCE = "https://docs.example.com"


@pytest.fixture(scope="module")
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def private_key(keypair):
    return keypair[0]


@pytest.fixture
def public_key(keypair):
    return keypair[1]


@pytest.fixture
def verifier(public_key):
    return JwtTokenVerifier(
        issuer=ISSUER,
        audiences=(AUDIENCE,),
        scope_claim="scope",
        signing_key_resolver=lambda token: public_key,
    )


def _mint(private_key, **overrides):
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 3600,
        "azp": "client-abc",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


class TestExtractScopes:
    def test_space_delimited_string(self):
        assert _extract_scopes({"scope": "read write"}, "scope") == ("read", "write")

    def test_list_value(self):
        assert _extract_scopes({"scp": ["read", "write"]}, "scp") == ("read", "write")

    def test_tuple_value(self):
        assert _extract_scopes({"permissions": ("a", "b")}, "permissions") == ("a", "b")

    def test_missing_claim(self):
        assert _extract_scopes({}, "scope") == ()

    def test_scalar_int_claim_returns_empty(self):
        assert _extract_scopes({"scope": 42}, "scope") == ()

    def test_scalar_bool_claim_returns_empty(self):
        assert _extract_scopes({"scope": True}, "scope") == ()


class TestJwtTokenVerifier:
    def test_scalar_scope_claim_returns_access_token_no_scopes(self, public_key, private_key):
        v = JwtTokenVerifier(
            issuer=ISSUER,
            audiences=(AUDIENCE,),
            scope_claim="scope",
            signing_key_resolver=lambda token: public_key,
        )
        token = _mint(private_key, scope=42)
        result = asyncio.run(v.verify_token(token))
        assert result is not None
        assert result.scopes == []

    def test_valid_token_string_scope(self, verifier, private_key):
        token = _mint(private_key, scope="read write")
        result = asyncio.run(verifier.verify_token(token))
        assert result is not None
        assert result.token == token
        assert result.client_id == "client-abc"
        assert result.scopes == ["read", "write"]
        assert result.expires_at is not None

    def test_valid_token_list_scope(self, public_key, private_key):
        v = JwtTokenVerifier(
            issuer=ISSUER,
            audiences=(AUDIENCE,),
            scope_claim="scp",
            signing_key_resolver=lambda token: public_key,
        )
        token = _mint(private_key, scp=["docs:read", "docs:write"])
        result = asyncio.run(v.verify_token(token))
        assert result is not None
        assert result.scopes == ["docs:read", "docs:write"]

    def test_missing_scope_claim_empty_scopes(self, verifier, private_key):
        token = _mint(private_key)
        result = asyncio.run(verifier.verify_token(token))
        assert result is not None
        assert result.scopes == []

    def test_client_id_falls_back_to_client_id_claim(self, public_key, private_key):
        v = JwtTokenVerifier(
            issuer=ISSUER,
            audiences=(AUDIENCE,),
            scope_claim="scope",
            signing_key_resolver=lambda token: public_key,
        )
        token = _mint(private_key, azp=None, client_id="cid-999")
        result = asyncio.run(v.verify_token(token))
        assert result is not None
        assert result.client_id == "cid-999"

    def test_client_id_falls_back_to_external(self, verifier, private_key):
        token = _mint(private_key, azp=None)
        result = asyncio.run(verifier.verify_token(token))
        assert result is not None
        assert result.client_id == "external"

    def test_bad_audience_returns_none(self, verifier, private_key):
        token = _mint(private_key, aud="https://other.example.com")
        assert asyncio.run(verifier.verify_token(token)) is None

    def test_verify_audience_false_accepts_token_with_no_aud(self, public_key, private_key):
        """With verify_audience=False, a token carrying no aud claim is accepted
        (Ory Hydra ignores RFC 8707 resource and issues an empty audience)."""
        v = JwtTokenVerifier(
            issuer=ISSUER,
            audiences=(),
            scope_claim="scope",
            signing_key_resolver=lambda token: public_key,
            verify_audience=False,
        )
        claims = {"iss": ISSUER, "exp": int(time.time()) + 3600, "azp": "client-abc"}
        token = jwt.encode(claims, private_key, algorithm="RS256")
        result = asyncio.run(v.verify_token(token))
        assert result is not None
        assert result.client_id == "client-abc"

    def test_verify_audience_false_accepts_mismatched_aud(self, public_key, private_key):
        """With verify_audience=False, a non-matching aud is not grounds for rejection."""
        v = JwtTokenVerifier(
            issuer=ISSUER,
            audiences=(),
            scope_claim="scope",
            signing_key_resolver=lambda token: public_key,
            verify_audience=False,
        )
        token = _mint(private_key, aud="https://other.example.com")
        assert asyncio.run(v.verify_token(token)) is not None

    def test_verify_audience_false_still_rejects_wrong_issuer(self, public_key, private_key):
        """Disabling audience validation must not loosen issuer validation."""
        v = JwtTokenVerifier(
            issuer=ISSUER,
            audiences=(),
            scope_claim="scope",
            signing_key_resolver=lambda token: public_key,
            verify_audience=False,
        )
        token = _mint(private_key, iss="https://evil.example.com", aud=None)
        assert asyncio.run(v.verify_token(token)) is None

    def test_wrong_issuer_returns_none(self, verifier, private_key):
        token = _mint(private_key, iss="https://evil.example.com")
        assert asyncio.run(verifier.verify_token(token)) is None

    def test_expired_returns_none(self, verifier, private_key):
        token = _mint(private_key, exp=int(time.time()) - 10)
        assert asyncio.run(verifier.verify_token(token)) is None

    def test_malformed_token_returns_none(self, verifier):
        assert asyncio.run(verifier.verify_token("not-a-jwt")) is None

    def test_missing_exp_claim_returns_none(self, verifier, private_key):
        """A token with no exp claim must be rejected (exp is required)."""
        claims = {"iss": ISSUER, "aud": AUDIENCE, "azp": "client-abc"}
        token = jwt.encode(claims, private_key, algorithm="RS256")
        assert asyncio.run(verifier.verify_token(token)) is None

    def test_signing_key_resolution_failure_returns_none_not_raise(self, verifier):
        """When the signing key can't be resolved (IdP discovery/JWKS unreachable,
        e.g. a WAF 403), verify_token fails closed to None (a 401) rather than
        letting the error propagate as a 500."""
        def boom(_token):
            raise AuthConfigError("could not fetch OIDC discovery document: HTTP Error 403")
        verifier._signing_key_resolver = boom
        assert asyncio.run(verifier.verify_token("any-token")) is None


class TestBuildTokenVerifier:
    def _config(self):
        return AuthConfig(
            type="oauth",
            oidc_issuer=ISSUER,
            oidc_audiences=(AUDIENCE,),
            scope_claim="scope",
        )

    def test_import_error_raises_auth_config_error(self, monkeypatch):
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name == "jwt":
                raise ImportError("no jwt")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        with pytest.raises(AuthConfigError):
            build_token_verifier(self._config())

    def test_returns_jwt_token_verifier(self):
        v = build_token_verifier(self._config())
        assert isinstance(v, JwtTokenVerifier)

    def test_default_resolver_uses_discovered_jwks_uri(self, monkeypatch):
        """The resolver builds PyJWKClient at the jwks_uri from OIDC discovery.

        This is what makes the verifier work against IdPs like Dex, whose JWKS
        lives at ``/keys`` rather than the assembled ``/.well-known/jwks.json``.
        """
        captured = {}
        discovered = "https://accounts.cennso.com/keys"

        monkeypatch.setattr(
            "opencrane.mcp.auth.oauth_verifier._discover_jwks_uri",
            lambda issuer: discovered,
        )

        class FakeKey:
            key = "the-key"

        class FakePyJWKClient:
            def __init__(self, url, headers=None):
                captured["url"] = url
                captured["headers"] = headers

            def get_signing_key_from_jwt(self, token):
                return FakeKey()

        monkeypatch.setattr(jwt, "PyJWKClient", FakePyJWKClient)
        v = build_token_verifier(self._config())
        key = v._signing_key_resolver("some-token")
        assert key == "the-key"
        assert captured["url"] == discovered
        # WAF-safe User-Agent is sent on the JWKS fetch too.
        assert captured["headers"] == {"User-Agent": "opencrane"}

    def test_default_resolver_discovers_once_and_caches(self, monkeypatch):
        """Discovery and PyJWKClient construction happen once, then are reused."""
        calls = {"discover": 0, "client": 0}

        def fake_discover(issuer):
            calls["discover"] += 1
            return "https://idp.example.com/keys"

        monkeypatch.setattr(
            "opencrane.mcp.auth.oauth_verifier._discover_jwks_uri", fake_discover
        )

        class FakeKey:
            key = "k"

        class FakePyJWKClient:
            def __init__(self, url, headers=None):
                calls["client"] += 1

            def get_signing_key_from_jwt(self, token):
                return FakeKey()

        monkeypatch.setattr(jwt, "PyJWKClient", FakePyJWKClient)
        v = build_token_verifier(self._config())
        v._signing_key_resolver("tok-1")
        v._signing_key_resolver("tok-2")
        assert calls["discover"] == 1
        assert calls["client"] == 1


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, *_args):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TestDiscoverJwksUri:
    def test_returns_jwks_uri_from_discovery_document(self, monkeypatch):
        body = b'{"issuer": "https://accounts.cennso.com", "jwks_uri": "https://accounts.cennso.com/keys"}'
        captured = {}

        def fake_urlopen(request, *args, **kwargs):
            captured["request"] = request
            return _FakeResponse(body)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        uri = _discover_jwks_uri("https://accounts.cennso.com")
        assert uri == "https://accounts.cennso.com/keys"
        # The fetch goes through a Request carrying a WAF-safe User-Agent (some
        # IdPs 403 the default urllib UA).
        assert captured["request"].full_url == "https://accounts.cennso.com/.well-known/openid-configuration"
        assert captured["request"].get_header("User-agent") == "opencrane"

    def test_strips_trailing_slash_from_issuer(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, *args, **kwargs):
            captured["request"] = request
            return _FakeResponse(b'{"jwks_uri": "https://idp/keys"}')

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        _discover_jwks_uri("https://idp.example.com/")
        assert captured["request"].full_url == "https://idp.example.com/.well-known/openid-configuration"

    def test_missing_jwks_uri_raises(self, monkeypatch):
        def fake_urlopen(request, *args, **kwargs):
            return _FakeResponse(b'{"issuer": "https://idp.example.com"}')

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with pytest.raises(AuthConfigError):
            _discover_jwks_uri("https://idp.example.com")

    def test_network_error_raises_auth_config_error(self, monkeypatch):
        import urllib.error

        def fake_urlopen(url, *args, **kwargs):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with pytest.raises(AuthConfigError):
            _discover_jwks_uri("https://idp.example.com")

    def test_invalid_json_raises_auth_config_error(self, monkeypatch):
        def fake_urlopen(url, *args, **kwargs):
            return _FakeResponse(b"not json")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with pytest.raises(AuthConfigError):
            _discover_jwks_uri("https://idp.example.com")


class TestMultipleAudiences:
    """A token is valid if its ``aud`` matches ANY configured audience.

    This lets one MCP server accept tokens from several front-end OAuth clients
    (e.g. a local-CLI client and a web-app client), each of which — with Dex —
    carries its own client_id as the ``aud``.
    """

    def test_accepts_any_configured_audience(self, public_key, private_key):
        v = JwtTokenVerifier(
            issuer=ISSUER,
            audiences=("cli-client", "web-client"),
            scope_claim="scope",
            signing_key_resolver=lambda token: public_key,
        )
        for aud in ("cli-client", "web-client"):
            token = _mint(private_key, aud=aud)
            result = asyncio.run(v.verify_token(token))
            assert result is not None, f"expected {aud} to be accepted"

    def test_rejects_audience_not_in_set(self, public_key, private_key):
        v = JwtTokenVerifier(
            issuer=ISSUER,
            audiences=("cli-client", "web-client"),
            scope_claim="scope",
            signing_key_resolver=lambda token: public_key,
        )
        token = _mint(private_key, aud="some-other-client")
        assert asyncio.run(v.verify_token(token)) is None
