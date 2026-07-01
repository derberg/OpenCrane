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

    def test_default_resolver_builds_pyjwkclient_at_jwks_url(self, monkeypatch):
        captured = {}

        class FakeKey:
            key = "the-key"

        class FakePyJWKClient:
            def __init__(self, url):
                captured["url"] = url

            def get_signing_key_from_jwt(self, token):
                return FakeKey()

        monkeypatch.setattr(jwt, "PyJWKClient", FakePyJWKClient)
        v = build_token_verifier(self._config())
        # Exercise the default resolver so the PyJWKClient is actually constructed.
        key = v._signing_key_resolver("some-token")
        assert key == "the-key"
        assert captured["url"] == f"{ISSUER}/.well-known/jwks.json"

    def test_default_resolver_strips_trailing_slash(self, monkeypatch):
        captured = {}

        class FakeKey:
            key = "k"

        class FakePyJWKClient:
            def __init__(self, url):
                captured["url"] = url

            def get_signing_key_from_jwt(self, token):
                return FakeKey()

        monkeypatch.setattr(jwt, "PyJWKClient", FakePyJWKClient)
        cfg = AuthConfig(
            type="oauth",
            oidc_issuer=ISSUER + "/",
            oidc_audience=AUDIENCE,
            scope_claim="scope",
        )
        v = build_token_verifier(cfg)
        v._signing_key_resolver("tok")
        assert captured["url"] == f"{ISSUER}/.well-known/jwks.json"
