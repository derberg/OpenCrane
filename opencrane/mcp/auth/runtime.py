"""Runtime auth helpers: read caller scopes and resolve the access policy."""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opencrane.mcp.auth.policies import AllowAllPolicy, ScopeSourcesPolicy

logger = logging.getLogger(__name__)

# Module-level policy cache; cleared by reset_auth_runtime().
_access_policy: "AllowAllPolicy | ScopeSourcesPolicy | None" = None

# Per-request scopes set by the optional-auth middleware (oauth allow_anonymous).
# None means "not set" — current_scopes() then falls back to the SDK access token.
_optional_scopes: ContextVar[tuple[str, ...] | None] = ContextVar(
    "opencrane_optional_scopes", default=None
)


def set_optional_scopes(scopes: tuple[str, ...]) -> None:
    """Record the caller's scopes for this request (optional-auth mode).

    Called by :class:`OptionalAuthMiddleware` after validating (or failing to
    validate) a bearer token. An anonymous caller is recorded as ``()``.
    """
    _optional_scopes.set(tuple(scopes))


def current_scopes() -> tuple[str, ...]:
    """Return the caller's OAuth scopes as a tuple.

    In optional-auth mode the middleware records the scopes for the request, so
    that value is used when present. Otherwise the SDK access token is read from
    the current ASGI request context; under stdio transport or when no auth
    middleware is active, ``get_access_token()`` returns ``None`` and this
    returns ``()``.
    """
    optional = _optional_scopes.get()
    if optional is not None:
        return optional

    from mcp.server.auth.middleware.auth_context import get_access_token

    token = get_access_token()
    if token is None:
        return ()
    return tuple(token.scopes)


def get_access_policy() -> "AllowAllPolicy | ScopeSourcesPolicy":
    """Build and cache the access policy from the project's config.yaml.

    The policy is derived from the ``auth`` block in config.yaml (read from the
    path in the ``MAPPING_FILE`` env var, defaulting to ``.opencrane/config.yaml``).
    If the file is missing or unparseable, the config is treated as empty and an
    ``AllowAllPolicy`` is returned.

    The result is cached in a module global until ``reset_auth_runtime()`` is
    called (useful for tests and re-initialisation).
    """
    global _access_policy
    if _access_policy is not None:
        return _access_policy

    from opencrane.mcp.auth.config_model import parse_auth_config
    from opencrane.mcp.auth.policies import build_access_policy
    from opencrane.mcp.server import _get_source_keys

    mapping_file = Path(os.environ.get("MAPPING_FILE", ".opencrane/config.yaml"))
    data: dict = {}
    if mapping_file.exists():
        try:
            import yaml as _yaml

            data = _yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning(f"Failed to parse {mapping_file}: {exc} — using AllowAll policy")
            data = {}

    known_sources = set(_get_source_keys())
    auth_config = parse_auth_config(data, known_sources)
    _access_policy = build_access_policy(auth_config)
    return _access_policy


def reset_auth_runtime() -> None:
    """Clear the cached access policy.

    Call this in tests (via fixture teardown or explicit reset) and whenever
    the project configuration changes at runtime.
    """
    global _access_policy
    _access_policy = None
    _optional_scopes.set(None)
