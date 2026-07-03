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
        audience=AUDIENCE,
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
            audience=AUDIENCE,
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
            audience=AUDIENCE,
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
            audience=AUDIENCE,
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


class TestBuildTokenVerifier:
    def _config(self):
        return AuthConfig(
            type="oauth",
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
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
            def __init__(self, url):
                captured["url"] = url

            def get_signing_key_from_jwt(self, token):
                return FakeKey()

        monkeypatch.setattr(jwt, "PyJWKClient", FakePyJWKClient)
        v = build_token_verifier(self._config())
        key = v._signing_key_resolver("some-token")
        assert key == "the-key"
        assert captured["url"] == discovered

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
            def __init__(self, url):
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

        def fake_urlopen(url, *args, **kwargs):
            captured["url"] = url
            return _FakeResponse(body)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        uri = _discover_jwks_uri("https://accounts.cennso.com")
        assert uri == "https://accounts.cennso.com/keys"
        assert captured["url"] == "https://accounts.cennso.com/.well-known/openid-configuration"

    def test_strips_trailing_slash_from_issuer(self, monkeypatch):
        captured = {}

        def fake_urlopen(url, *args, **kwargs):
            captured["url"] = url
            return _FakeResponse(b'{"jwks_uri": "https://idp/keys"}')

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        _discover_jwks_uri("https://idp.example.com/")
        assert captured["url"] == "https://idp.example.com/.well-known/openid-configuration"

    def test_missing_jwks_uri_raises(self, monkeypatch):
        def fake_urlopen(url, *args, **kwargs):
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
