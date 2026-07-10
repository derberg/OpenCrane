"""MCP auth package — config model, parser, access policies, and runtime helpers."""

from opencrane.mcp.auth.config_model import (
    AuthConfig,
    AuthConfigError,
    parse_auth_config,
    parse_auth_endpoints,
)
from opencrane.mcp.auth.local_provider import (
    OpenCraneAuthProvider,
    load_local_credentials,
    render_login_form,
    verify_credentials,
)
from opencrane.mcp.auth.oauth_verifier import JwtTokenVerifier, build_token_verifier
from opencrane.mcp.auth.policies import AllowAllPolicy, ScopeSourcesPolicy, build_access_policy
from opencrane.mcp.auth.runtime import (
    current_allowed_sources,
    current_scopes,
    get_access_policy,
    reset_auth_runtime,
    set_allowed_sources,
    set_current_endpoint,
)
from opencrane.mcp.auth.wiring import build_fastmcp_auth

__all__ = [
    "AllowAllPolicy",
    "AuthConfig",
    "AuthConfigError",
    "JwtTokenVerifier",
    "OpenCraneAuthProvider",
    "ScopeSourcesPolicy",
    "build_access_policy",
    "build_fastmcp_auth",
    "build_token_verifier",
    "current_allowed_sources",
    "current_scopes",
    "get_access_policy",
    "load_local_credentials",
    "parse_auth_config",
    "parse_auth_endpoints",
    "render_login_form",
    "reset_auth_runtime",
    "set_allowed_sources",
    "set_current_endpoint",
    "verify_credentials",
]
