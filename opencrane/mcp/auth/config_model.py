"""Auth config model and parser for OpenCrane MCP server."""

from dataclasses import dataclass, field


ALLOWED_TYPES = frozenset({"none", "local", "oauth", "custom"})
ALLOWED_LOCAL_METHODS = frozenset({"token", "password"})

# Keys that only appear inside a single (flat) auth block. Their presence at the
# top level of the ``auth`` mapping marks it as one endpoint's config rather than
# a map of named endpoints. Endpoint names must therefore avoid these words.
_FLAT_AUTH_KEYS = frozenset(
    {"type", "allow_anonymous", "scope_sources", "default_sources", "oidc", "local"}
)


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
    oidc_verify_audience: bool = True
    scope_claim: str = "scope"
    scope_sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    default_sources: tuple[str, ...] = ()
    local_method: str = "token"
    local_scopes: tuple[str, ...] = ()
    allow_anonymous: bool = False


def parse_auth_config(data: dict, known_sources: set[str]) -> AuthConfig:
    """Parse and validate a single flat ``auth:`` block from config.yaml.

    Kept for backward compatibility and single-endpoint callers. Multi-endpoint
    callers should use :func:`parse_auth_endpoints`.

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
    return _parse_auth_entry(data.get("auth") or {}, known_sources)


def parse_auth_endpoints(data: dict, known_sources: set[str]) -> dict[str, AuthConfig]:
    """Parse ``auth`` into a map of endpoint name -> :class:`AuthConfig`.

    Three shapes are supported:

    * **No ``auth`` block (or empty):** ``{"": AuthConfig(type="none")}`` — one
      open endpoint at the root MCP path.
    * **Flat block** (contains any single-block key such as ``type``,
      ``scope_sources``, ``default_sources``, ``oidc`` …): ``{"": <parsed>}`` —
      one endpoint at the root MCP path (unchanged legacy behavior).
    * **Named map** (e.g. ``{public: {...}, private: {...}}``): one entry per
      name, each becoming an endpoint served at ``<root>/<name>``.

    The ``""`` key denotes the root MCP endpoint (single-endpoint modes).
    Endpoint names must not collide with the reserved single-block keys
    (``type``, ``allow_anonymous``, ``scope_sources``, ``default_sources``,
    ``oidc``, ``local``); such a name makes the block parse as flat instead.

    Raises:
        AuthConfigError: On any validation failure, including invalid endpoint
            names or non-mapping entries (fail-closed).
    """
    auth = data.get("auth") or {}
    if not auth:
        return {"": AuthConfig()}
    if _FLAT_AUTH_KEYS & set(auth):
        return {"": _parse_auth_entry(auth, known_sources)}

    endpoints: dict[str, AuthConfig] = {}
    for name, entry in auth.items():
        if not isinstance(name, str) or not name or not all(
            c.isalnum() or c in "-_" for c in name
        ):
            raise AuthConfigError(
                f"invalid auth endpoint name {name!r}: use letters, digits, '-' or '_'"
            )
        if not isinstance(entry, dict):
            raise AuthConfigError(
                f"auth endpoint {name!r} must be a mapping, got {type(entry).__name__}"
            )
        endpoints[name] = _parse_auth_entry(entry, known_sources)
    return endpoints


def _parse_auth_entry(auth: dict, known_sources: set[str]) -> AuthConfig:
    """Parse and validate one auth block dict into an :class:`AuthConfig`."""
    auth_type = auth.get("type", "none")
    if auth_type not in ALLOWED_TYPES:
        raise AuthConfigError(f"unknown auth type: {auth_type!r}. Allowed: {sorted(ALLOWED_TYPES)}")

    # When true (oauth mode only), a bearer token is validated if present but not
    # required: anonymous callers are allowed and fall through to default_sources.
    allow_anonymous = bool(auth.get("allow_anonymous", False))

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
    oidc_verify_audience = True
    scope_claim = "scope"

    if auth_type == "oauth":
        oidc_raw = auth.get("oidc")
        if oidc_raw is not None and not isinstance(oidc_raw, dict):
            raise AuthConfigError("oauth requires oidc to be a mapping")
        oidc_block = oidc_raw or {}
        oidc_issuer = oidc_block.get("issuer")
        if not oidc_issuer:
            raise AuthConfigError("oauth requires oidc.issuer to be set")
        # verify_audience gates the confused-deputy (aud-binding) defense. It
        # defaults to True. Set it to False only for IdPs that cannot stamp the
        # token audience — e.g. Ory Hydra ignores the RFC 8707 `resource`
        # parameter and issues tokens with an empty `aud`. When disabled,
        # oidc.audience becomes optional.
        oidc_verify_audience = bool(oidc_block.get("verify_audience", True))
        raw_audience = oidc_block.get("audience")
        if oidc_verify_audience:
            oidc_audiences = _parse_audiences(raw_audience)
        elif raw_audience is not None:
            oidc_audiences = _parse_audiences(raw_audience)
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
        oidc_verify_audience=oidc_verify_audience,
        scope_claim=scope_claim,
        scope_sources=scope_sources,
        default_sources=default_sources,
        local_method=local_method,
        local_scopes=local_scopes,
        allow_anonymous=allow_anonymous,
    )
