"""Auth config model and parser for OpenCrane MCP server."""

from dataclasses import dataclass, field


ALLOWED_TYPES = frozenset({"none", "local", "oauth", "custom"})
ALLOWED_LOCAL_METHODS = frozenset({"token", "password"})


class AuthConfigError(Exception):
    """Raised when the auth block in config.yaml is invalid."""


@dataclass(frozen=True)
class AuthConfig:
    """Parsed and validated auth configuration."""

    type: str = "none"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    scope_claim: str = "scope"
    scope_sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    default_sources: tuple[str, ...] = ()
    local_method: str = "token"
    local_scopes: tuple[str, ...] = ()


def parse_auth_config(data: dict, known_sources: set[str]) -> AuthConfig:
    """Parse and validate the auth block from a parsed config.yaml dict.

    Args:
        data: The full parsed config.yaml as a dict.
        known_sources: The set of known source names. When non-empty, any
            source referenced in scope_sources or default_sources that is not
            in this set raises AuthConfigError.

    Returns:
        A frozen AuthConfig instance.

    Raises:
        AuthConfigError: On any validation failure (fail-closed).
    """
    auth = data.get("auth") or {}

    auth_type = auth.get("type", "none")
    if auth_type not in ALLOWED_TYPES:
        raise AuthConfigError(f"unknown auth type: {auth_type!r}. Allowed: {sorted(ALLOWED_TYPES)}")

    # --- scope_sources ---
    raw_scope_sources = auth.get("scope_sources", {})
    if not isinstance(raw_scope_sources, dict):
        raise AuthConfigError(
            f"scope_sources must be a dict[str, list], got {type(raw_scope_sources).__name__}"
        )
    scope_sources: dict[str, tuple[str, ...]] = {}
    for src_name, scopes in raw_scope_sources.items():
        if not isinstance(scopes, list):
            raise AuthConfigError(
                f"scope_sources[{src_name!r}] must be a list of strings, got {type(scopes).__name__}"
            )
        if known_sources and src_name not in known_sources:
            raise AuthConfigError(
                f"unknown source {src_name!r} in scope_sources (known: {sorted(known_sources)})"
            )
        scope_sources[src_name] = tuple(scopes)

    # --- default_sources ---
    raw_default_sources = auth.get("default_sources", [])
    if not isinstance(raw_default_sources, list):
        raise AuthConfigError(
            f"default_sources must be a list, got {type(raw_default_sources).__name__}"
        )
    for src_name in raw_default_sources:
        if known_sources and src_name not in known_sources:
            raise AuthConfigError(
                f"unknown source {src_name!r} in default_sources (known: {sorted(known_sources)})"
            )
    default_sources = tuple(raw_default_sources)

    # --- oauth-specific ---
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    scope_claim = "scope"

    if auth_type == "oauth":
        oidc_block = auth.get("oidc") or {}
        if not isinstance(oidc_block, dict):
            oidc_block = {}
        oidc_issuer = oidc_block.get("issuer")
        oidc_audience = oidc_block.get("audience")
        if not oidc_issuer:
            raise AuthConfigError("oauth requires oidc.issuer to be set")
        if not oidc_audience:
            raise AuthConfigError("oauth requires oidc.audience to be set")
        scope_claim = oidc_block.get("scope_claim", "scope")  # OIDC-only: read from oidc: block

    # --- local-specific ---
    local_method = "token"
    local_scopes: tuple[str, ...] = ()

    if auth_type == "local":
        local_block = auth.get("local") or {}
        if not isinstance(local_block, dict):
            raise AuthConfigError(f"auth.local must be a mapping, got {type(local_block).__name__}")
        local_method = local_block.get("method", "token")
        if local_method not in ALLOWED_LOCAL_METHODS:
            raise AuthConfigError(
                f"local.method must be one of {sorted(ALLOWED_LOCAL_METHODS)}, got {local_method!r}"
            )
        raw_scopes = local_block.get("scopes", [])
        local_scopes = tuple(raw_scopes)

    return AuthConfig(
        type=auth_type,
        oidc_issuer=oidc_issuer,
        oidc_audience=oidc_audience,
        scope_claim=scope_claim,
        scope_sources=scope_sources,
        default_sources=default_sources,
        local_method=local_method,
        local_scopes=local_scopes,
    )
