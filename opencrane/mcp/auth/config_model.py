"""Auth config model and parser for OpenCrane MCP server."""

from dataclasses import dataclass, field


ALLOWED_TYPES = frozenset({"none", "local", "oauth", "custom"})
ALLOWED_LOCAL_METHODS = frozenset({"token", "password"})


class AuthConfigError(Exception):
    """Raised when the auth block in config.yaml is invalid."""


def _parse_audiences(raw) -> tuple[str, ...]:
    """Normalize ``oidc.audience`` (a string or list of strings) to a tuple.

    Accepting a list lets one MCP server trust tokens from several front-end
    OAuth clients (e.g. a local-CLI client and a web-app client) — with Dex each
    carries its own client_id as the ``aud`` claim, so the server must accept a
    set of audiences.

    Raises:
        AuthConfigError: If ``raw`` is not a non-empty string or a non-empty list
            of non-empty strings.
    """
    if isinstance(raw, str) and raw:
        return (raw,)
    if isinstance(raw, list) and raw and all(isinstance(a, str) and a for a in raw):
        return tuple(raw)
    raise AuthConfigError(
        "oauth requires oidc.audience to be a non-empty string or list of strings"
    )


@dataclass(frozen=True)
class AuthConfig:
    """Parsed and validated auth configuration."""

    type: str = "none"
    oidc_issuer: str | None = None
    oidc_audiences: tuple[str, ...] = ()
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
    for scope, sources in raw_scope_sources.items():
        if not isinstance(sources, list):
            raise AuthConfigError(
                f"scope_sources[{scope!r}] must be a list of strings, got {type(sources).__name__}"
            )
        for src_name in sources:
            if known_sources and src_name not in known_sources:
                raise AuthConfigError(
                    f"unknown source {src_name!r} in scope_sources (known: {sorted(known_sources)})"
                )
        scope_sources[scope] = tuple(sources)

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
    oidc_audiences: tuple[str, ...] = ()
    scope_claim = "scope"

    if auth_type == "oauth":
        oidc_raw = auth.get("oidc")
        if oidc_raw is not None and not isinstance(oidc_raw, dict):
            raise AuthConfigError("oauth requires oidc to be a mapping")
        oidc_block = oidc_raw or {}
        oidc_issuer = oidc_block.get("issuer")
        if not oidc_issuer:
            raise AuthConfigError("oauth requires oidc.issuer to be set")
        oidc_audiences = _parse_audiences(oidc_block.get("audience"))
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
        oidc_audiences=oidc_audiences,
        scope_claim=scope_claim,
        scope_sources=scope_sources,
        default_sources=default_sources,
        local_method=local_method,
        local_scopes=local_scopes,
    )
