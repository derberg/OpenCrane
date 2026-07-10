"""Unit tests for MCP auth config model parsing."""

from dataclasses import FrozenInstanceError

import pytest
from opencrane.mcp.auth import (
    AuthConfig,
    AuthConfigError,
    parse_auth_config,
    parse_auth_endpoints,
)


class TestNoAuthBlock:
    """Tests for missing or empty auth block."""

    def test_no_auth_key_returns_none_type(self):
        """Missing auth block returns AuthConfig with type='none'."""
        result = parse_auth_config({}, known_sources=set())
        assert result == AuthConfig()
        assert result.type == "none"

    def test_empty_auth_block_returns_none_type(self):
        """Empty auth block (auth: {}) returns AuthConfig with type='none'."""
        result = parse_auth_config({"auth": {}}, known_sources=set())
        assert result.type == "none"

    def test_auth_none_explicit(self):
        """Explicit type: none is accepted."""
        result = parse_auth_config({"auth": {"type": "none"}}, known_sources=set())
        assert result.type == "none"


class TestUnknownType:
    """Tests for unknown auth type."""

    def test_unknown_type_raises(self):
        """Unknown type raises AuthConfigError."""
        with pytest.raises(AuthConfigError, match="unknown auth type"):
            parse_auth_config({"auth": {"type": "magic"}}, known_sources=set())

    def test_known_types_do_not_raise(self):
        """All valid types are accepted (basic parse, no further validation needed)."""
        for t in ("none", "local", "custom"):
            result = parse_auth_config({"auth": {"type": t}}, known_sources=set())
            assert result.type == t


class TestOAuthParsing:
    """Tests for oauth type parsing."""

    def test_oauth_missing_issuer_raises(self):
        """oauth without oidc.issuer raises AuthConfigError."""
        data = {
            "auth": {
                "type": "oauth",
                "oidc": {"audience": "myapp"},
            }
        }
        with pytest.raises(AuthConfigError, match="oidc.issuer"):
            parse_auth_config(data, known_sources=set())

    def test_oauth_missing_audience_raises(self):
        """oauth without oidc.audience raises AuthConfigError."""
        data = {
            "auth": {
                "type": "oauth",
                "oidc": {"issuer": "https://auth.example.com"},
            }
        }
        with pytest.raises(AuthConfigError, match="oidc.audience"):
            parse_auth_config(data, known_sources=set())

    def test_oauth_missing_oidc_block_raises(self):
        """oauth with no oidc block raises AuthConfigError (both issuer and audience missing)."""
        data = {"auth": {"type": "oauth"}}
        with pytest.raises(AuthConfigError):
            parse_auth_config(data, known_sources=set())

    def test_oauth_full_parse(self):
        """Full oauth config parses correctly with all fields.

        scope_sources maps scope strings (keys) to lists of source names (values).
        Keys are free-form OAuth scopes and are NOT validated against known_sources.
        Values are source names and ARE validated against known_sources.
        """
        data = {
            "auth": {
                "type": "oauth",
                "oidc": {
                    "issuer": "https://auth.example.com",
                    "audience": "myapp",
                    "scope_claim": "permissions",
                },
                "scope_sources": {
                    "docs:read": ["docs", "api"],
                    "docs:write": ["api"],
                },
                "default_sources": ["docs"],
            }
        }
        result = parse_auth_config(data, known_sources={"docs", "api"})
        assert result.type == "oauth"
        assert result.oidc_issuer == "https://auth.example.com"
        assert result.oidc_audiences == ("myapp",)
        assert result.scope_claim == "permissions"
        assert result.scope_sources == {"docs:read": ("docs", "api"), "docs:write": ("api",)}
        assert result.default_sources == ("docs",)

    def test_oauth_scope_claim_defaults_to_scope(self):
        """scope_claim defaults to 'scope' when not specified."""
        data = {
            "auth": {
                "type": "oauth",
                "oidc": {
                    "issuer": "https://auth.example.com",
                    "audience": "myapp",
                },
            }
        }
        result = parse_auth_config(data, known_sources=set())
        assert result.scope_claim == "scope"

    def test_allow_anonymous_defaults_false(self):
        """allow_anonymous defaults to False."""
        data = {
            "auth": {
                "type": "oauth",
                "oidc": {"issuer": "https://auth.example.com", "audience": "myapp"},
            }
        }
        result = parse_auth_config(data, known_sources=set())
        assert result.allow_anonymous is False

    def test_allow_anonymous_true(self):
        """allow_anonymous: true is parsed as True (optional-auth mode)."""
        data = {
            "auth": {
                "type": "oauth",
                "allow_anonymous": True,
                "oidc": {"issuer": "https://auth.example.com", "audience": "myapp"},
            }
        }
        result = parse_auth_config(data, known_sources=set())
        assert result.allow_anonymous is True

    def test_oauth_oidc_none_falls_through_to_issuer_error(self):
        """oauth with oidc: null coerces to empty dict and raises for missing issuer."""
        data = {"auth": {"type": "oauth", "oidc": None}}
        with pytest.raises(AuthConfigError, match="oidc.issuer"):
            parse_auth_config(data, known_sources=set())

    def test_oauth_oidc_non_dict_raises(self):
        """oauth with oidc: <non-mapping string> raises AuthConfigError (fail-closed)."""
        data = {"auth": {"type": "oauth", "oidc": "notadict"}}
        with pytest.raises(AuthConfigError, match="oidc to be a mapping"):
            parse_auth_config(data, known_sources=set())


class TestLocalParsing:
    """Tests for local auth type parsing."""

    def test_local_method_token(self):
        """local with method=token is accepted."""
        data = {"auth": {"type": "local", "local": {"method": "token"}}}
        result = parse_auth_config(data, known_sources=set())
        assert result.type == "local"
        assert result.local_method == "token"

    def test_local_method_password(self):
        """local with method=password is accepted."""
        data = {"auth": {"type": "local", "local": {"method": "password"}}}
        result = parse_auth_config(data, known_sources=set())
        assert result.local_method == "password"

    def test_local_method_invalid_raises(self):
        """local with unknown method raises AuthConfigError."""
        data = {"auth": {"type": "local", "local": {"method": "magic"}}}
        with pytest.raises(AuthConfigError, match="local.method"):
            parse_auth_config(data, known_sources=set())

    def test_local_default_method_is_token(self):
        """local without method block defaults to token."""
        data = {"auth": {"type": "local"}}
        result = parse_auth_config(data, known_sources=set())
        assert result.local_method == "token"

    def test_local_null_block_defaults_to_token(self):
        """local: null coerces to empty dict and defaults to token method."""
        data = {"auth": {"type": "local", "local": None}}
        result = parse_auth_config(data, known_sources=set())
        assert result.local_method == "token"

    def test_local_non_dict_raises(self):
        """local: <non-mapping> raises AuthConfigError (fail-closed)."""
        with pytest.raises(AuthConfigError, match="auth.local must be a mapping"):
            parse_auth_config({"auth": {"type": "local", "local": "bad"}}, set())

    def test_local_scopes_parsed(self):
        """local_scopes are parsed correctly."""
        data = {
            "auth": {
                "type": "local",
                "local": {"method": "token", "scopes": ["read:docs", "admin"]},
            }
        }
        result = parse_auth_config(data, known_sources=set())
        assert result.local_scopes == ("read:docs", "admin")


class TestScopeSourcesValidation:
    """Tests for scope_sources and default_sources validation."""

    def test_scope_sources_happy_path(self):
        """scope_sources maps scope strings (keys) to source name lists (values).

        Keys are free-form OAuth scope strings — NOT validated against known_sources.
        Values are source names — validated against known_sources when non-empty.
        """
        data = {
            "auth": {
                "type": "none",
                "scope_sources": {"docs:public": ["cennso-glossary"], "docs:internal": ["cgw", "tsr"]},
                "default_sources": ["cennso-glossary"],
            }
        }
        result = parse_auth_config(data, known_sources={"cennso-glossary", "cgw", "tsr"})
        assert result.scope_sources == {
            "docs:public": ("cennso-glossary",),
            "docs:internal": ("cgw", "tsr"),
        }
        assert result.default_sources == ("cennso-glossary",)

    def test_scope_key_not_validated_against_known_sources(self):
        """Scope KEY strings (e.g. 'docs:public') are NOT validated against known_sources."""
        data = {
            "auth": {
                "type": "none",
                "scope_sources": {"docs:public": ["cgw"]},
            }
        }
        # 'docs:public' is NOT in known_sources — that's fine, keys are scopes not sources
        result = parse_auth_config(data, known_sources={"cgw"})
        assert result.scope_sources == {"docs:public": ("cgw",)}

    def test_scope_sources_unknown_source_in_value_raises_when_known_nonempty(self):
        """Unknown source in scope_sources VALUE list raises when known_sources is non-empty."""
        data = {
            "auth": {
                "type": "none",
                "scope_sources": {"docs:x": ["nope"]},
            }
        }
        with pytest.raises(AuthConfigError, match="unknown source"):
            parse_auth_config(data, known_sources={"cgw"})

    def test_default_sources_unknown_source_raises_when_known_nonempty(self):
        """Unknown source in default_sources raises when known_sources is non-empty."""
        data = {
            "auth": {
                "type": "none",
                "default_sources": ["unknown_src"],
            }
        }
        with pytest.raises(AuthConfigError, match="unknown source"):
            parse_auth_config(data, known_sources={"docs"})

    def test_unknown_source_skipped_when_known_set_empty(self):
        """Unknown sources are NOT validated when known_sources is empty."""
        data = {
            "auth": {
                "type": "none",
                "scope_sources": {"any_src": ["read:docs"]},
                "default_sources": ["any_src"],
            }
        }
        result = parse_auth_config(data, known_sources=set())
        assert result.scope_sources == {"any_src": ("read:docs",)}
        assert result.default_sources == ("any_src",)

    def test_scope_sources_malformed_not_dict_raises(self):
        """scope_sources not a dict raises AuthConfigError."""
        data = {"auth": {"type": "none", "scope_sources": ["read:docs"]}}
        with pytest.raises(AuthConfigError, match="scope_sources"):
            parse_auth_config(data, known_sources=set())

    def test_scope_sources_malformed_value_not_list_raises(self):
        """scope_sources value not a list raises AuthConfigError."""
        data = {"auth": {"type": "none", "scope_sources": {"docs": "read:docs"}}}
        with pytest.raises(AuthConfigError, match="scope_sources"):
            parse_auth_config(data, known_sources=set())

    def test_default_sources_malformed_not_list_raises(self):
        """default_sources not a list raises AuthConfigError."""
        data = {"auth": {"type": "none", "default_sources": "docs"}}
        with pytest.raises(AuthConfigError, match="default_sources"):
            parse_auth_config(data, known_sources=set())


class TestAuthConfigDefaults:
    """Tests for AuthConfig dataclass defaults."""

    def test_default_authconfig(self):
        """Default AuthConfig has expected field values."""
        cfg = AuthConfig()
        assert cfg.type == "none"
        assert cfg.oidc_issuer is None
        assert cfg.oidc_audiences == ()
        assert cfg.scope_claim == "scope"
        assert cfg.scope_sources == {}
        assert cfg.default_sources == ()
        assert cfg.local_method == "token"
        assert cfg.local_scopes == ()

    def test_authconfig_is_frozen(self):
        """AuthConfig is immutable (frozen dataclass)."""
        cfg = AuthConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.type = "oauth"  # type: ignore[misc]


class TestAudienceParsing:
    """oidc.audience accepts a single string or a list of strings."""

    def _oauth(self, audience):
        return {
            "auth": {
                "type": "oauth",
                "oidc": {"issuer": "https://idp.example.com", "audience": audience},
            }
        }

    def test_string_audience_becomes_single_tuple(self):
        cfg = parse_auth_config(self._oauth("myapp"), known_sources=set())
        assert cfg.oidc_audiences == ("myapp",)

    def test_list_audience_becomes_tuple(self):
        cfg = parse_auth_config(self._oauth(["cli-client", "web-client"]), known_sources=set())
        assert cfg.oidc_audiences == ("cli-client", "web-client")

    def test_empty_list_audience_raises(self):
        with pytest.raises(AuthConfigError):
            parse_auth_config(self._oauth([]), known_sources=set())

    def test_non_string_audience_entry_raises(self):
        with pytest.raises(AuthConfigError):
            parse_auth_config(self._oauth(["ok", 123]), known_sources=set())

    def test_missing_audience_raises(self):
        with pytest.raises(AuthConfigError):
            parse_auth_config(self._oauth(None), known_sources=set())


class TestParseAuthEndpoints:
    """Tests for parse_auth_endpoints — the named-endpoint map parser.

    The `""` key denotes the root MCP endpoint (single-endpoint modes);
    named keys become endpoints served under `<root>/<name>`.
    """

    def test_absent_auth_gives_single_root_none_endpoint(self):
        """No auth block → one open endpoint at the root path."""
        endpoints = parse_auth_endpoints({}, known_sources=set())
        assert set(endpoints) == {""}
        assert endpoints[""] == AuthConfig()
        assert endpoints[""].type == "none"

    def test_empty_auth_block_gives_single_root_none_endpoint(self):
        """auth: {} → one open endpoint at the root path."""
        endpoints = parse_auth_endpoints({"auth": {}}, known_sources=set())
        assert set(endpoints) == {""}
        assert endpoints[""].type == "none"

    def test_flat_block_gives_single_root_endpoint(self):
        """A flat auth block (top-level `type`) → one endpoint at the root path."""
        data = {
            "auth": {
                "type": "oauth",
                "oidc": {"issuer": "https://idp.example.com", "audience": "myapp"},
            }
        }
        endpoints = parse_auth_endpoints(data, known_sources=set())
        assert set(endpoints) == {""}
        assert endpoints[""].type == "oauth"
        assert endpoints[""].oidc_issuer == "https://idp.example.com"

    def test_flat_block_type_none_gives_single_root_endpoint(self):
        """A flat `type: none` block → single root endpoint (legacy behavior)."""
        data = {"auth": {"type": "none", "default_sources": ["docs"]}}
        endpoints = parse_auth_endpoints(data, known_sources={"docs"})
        assert set(endpoints) == {""}
        assert endpoints[""].default_sources == ("docs",)

    def test_flat_block_without_type_key_is_still_flat(self):
        """A flat block that omits `type` (e.g. only scope_sources) stays a single
        root endpoint — it must not be mistaken for a named map."""
        data = {
            "auth": {
                "scope_sources": {"docs:tp": ["cgw"]},
                "default_sources": ["cgw"],
            }
        }
        endpoints = parse_auth_endpoints(data, known_sources={"cgw"})
        assert set(endpoints) == {""}
        assert endpoints[""].type == "none"
        assert endpoints[""].scope_sources == {"docs:tp": ("cgw",)}

    def test_named_map_gives_endpoint_per_name(self):
        """A named map → one AuthConfig per name, each parsed independently."""
        data = {
            "auth": {
                "public": {"type": "none", "default_sources": ["glossary"]},
                "private": {
                    "type": "oauth",
                    "oidc": {"issuer": "https://idp.example.com", "audience": "priv"},
                },
            }
        }
        endpoints = parse_auth_endpoints(data, known_sources={"glossary"})
        assert set(endpoints) == {"public", "private"}
        assert endpoints["public"].type == "none"
        assert endpoints["public"].default_sources == ("glossary",)
        assert endpoints["private"].type == "oauth"
        assert endpoints["private"].oidc_issuer == "https://idp.example.com"
        assert endpoints["private"].oidc_audiences == ("priv",)

    def test_named_entry_not_mapping_raises(self):
        """A named entry that is not a mapping raises AuthConfigError."""
        with pytest.raises(AuthConfigError, match="must be a mapping"):
            parse_auth_endpoints({"auth": {"public": "nope"}}, known_sources=set())

    def test_invalid_endpoint_name_raises(self):
        """An endpoint name with path-unsafe characters raises AuthConfigError."""
        with pytest.raises(AuthConfigError, match="invalid auth endpoint name"):
            parse_auth_endpoints(
                {"auth": {"bad/name": {"type": "none"}}}, known_sources=set()
            )

    def test_named_entry_validation_error_propagates(self):
        """A per-entry validation failure (bad type) propagates as AuthConfigError."""
        with pytest.raises(AuthConfigError, match="unknown auth type"):
            parse_auth_endpoints(
                {"auth": {"x": {"type": "bogus"}}}, known_sources=set()
            )

    def test_named_entry_known_sources_enforced(self):
        """Per-entry default_sources are validated against known_sources."""
        data = {"auth": {"pub": {"type": "none", "default_sources": ["ghost"]}}}
        with pytest.raises(AuthConfigError, match="unknown source"):
            parse_auth_endpoints(data, known_sources={"docs"})

    def test_endpoint_name_with_hyphen_and_underscore_allowed(self):
        """Names of letters, digits, '-' and '_' are accepted."""
        data = {"auth": {"team_a-1": {"type": "none"}}}
        endpoints = parse_auth_endpoints(data, known_sources=set())
        assert set(endpoints) == {"team_a-1"}
