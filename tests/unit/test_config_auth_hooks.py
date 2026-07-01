"""Tests for OpenCraneConfig auth escape-hatch hooks and wiring.py custom branch."""

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.mcp.auth import build_fastmcp_auth
from opencrane.mcp.auth.config_model import AuthConfig, AuthConfigError


# ---------------------------------------------------------------------------
# OpenCraneConfig defaults
# ---------------------------------------------------------------------------

class TestOpenCraneConfigAuthDefaults:
    def test_token_verifier_default_is_none(self):
        assert OpenCraneConfig.token_verifier is None

    def test_auth_provider_default_is_none(self):
        assert OpenCraneConfig.auth_provider is None

    def test_instance_token_verifier_default_is_none(self):
        cfg = OpenCraneConfig()
        assert cfg.token_verifier is None

    def test_instance_auth_provider_default_is_none(self):
        cfg = OpenCraneConfig()
        assert cfg.auth_provider is None


# ---------------------------------------------------------------------------
# build_fastmcp_auth — custom branch
# ---------------------------------------------------------------------------

class _StubAuthProvider:
    """Minimal stub for an OAuthAuthorizationServerProvider."""


class _StubTokenVerifier:
    """Minimal stub for a TokenVerifier."""


class _StubConfigWithProvider(OpenCraneConfig):
    auth_provider = _StubAuthProvider()


class _StubConfigWithVerifier(OpenCraneConfig):
    token_verifier = _StubTokenVerifier()


class _StubConfigNeitherHook(OpenCraneConfig):
    pass  # both remain None


class TestBuildFastmcpAuthCustomBranch:
    def test_custom_with_auth_provider_returns_provider_kwargs(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")
        monkeypatch.setattr(
            "opencrane.cli.load_config",
            lambda _: _StubConfigWithProvider(),
        )
        kwargs = build_fastmcp_auth(AuthConfig(type="custom"))
        assert "auth_server_provider" in kwargs
        assert isinstance(kwargs["auth_server_provider"], _StubAuthProvider)
        assert "auth" in kwargs
        # AnyHttpUrl normalises by appending a trailing slash
        assert str(kwargs["auth"].issuer_url).rstrip("/") == "https://docs.example.com"
        assert str(kwargs["auth"].resource_server_url).rstrip("/") == "https://docs.example.com"

    def test_custom_with_auth_provider_missing_public_url_raises(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        monkeypatch.setattr(
            "opencrane.cli.load_config",
            lambda _: _StubConfigWithProvider(),
        )
        with pytest.raises(AuthConfigError):
            build_fastmcp_auth(AuthConfig(type="custom"))

    def test_custom_with_token_verifier_returns_verifier_kwargs(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_URL", "https://docs.example.com")
        monkeypatch.setattr(
            "opencrane.cli.load_config",
            lambda _: _StubConfigWithVerifier(),
        )
        kwargs = build_fastmcp_auth(AuthConfig(type="custom"))
        assert "token_verifier" in kwargs
        assert isinstance(kwargs["token_verifier"], _StubTokenVerifier)
        assert "auth" in kwargs
        # AnyHttpUrl normalises by appending a trailing slash
        assert str(kwargs["auth"].issuer_url).rstrip("/") == "https://docs.example.com"
        assert str(kwargs["auth"].resource_server_url).rstrip("/") == "https://docs.example.com"

    def test_custom_with_token_verifier_missing_public_url_raises(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        monkeypatch.setattr(
            "opencrane.cli.load_config",
            lambda _: _StubConfigWithVerifier(),
        )
        with pytest.raises(AuthConfigError):
            build_fastmcp_auth(AuthConfig(type="custom"))

    def test_custom_with_neither_hook_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "opencrane.cli.load_config",
            lambda _: _StubConfigNeitherHook(),
        )
        kwargs = build_fastmcp_auth(AuthConfig(type="custom"))
        assert kwargs == {}
