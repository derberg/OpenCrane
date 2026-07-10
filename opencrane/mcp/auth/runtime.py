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

# Module-level per-endpoint policy cache; cleared by reset_auth_runtime().
# Maps endpoint name -> policy. The "" key is the root /mcp endpoint (single-
# endpoint modes); named keys correspond to /mcp/<name> endpoints.
_access_policies: "dict[str, AllowAllPolicy | ScopeSourcesPolicy] | None" = None

# The endpoint name that is serving the current request, set by the per-endpoint
# middleware in http_server. Defaults to "" (the root /mcp endpoint), so single-
# endpoint deployments and stdio need no wiring.
_current_endpoint: ContextVar[str] = ContextVar("opencrane_current_endpoint", default="")

# Per-request scopes set by the optional-auth middleware (oauth allow_anonymous).
# None means "not set" — current_scopes() then falls back to the SDK access token.
_optional_scopes: ContextVar[tuple[str, ...] | None] = ContextVar(
    "opencrane_optional_scopes", default=None
)

# Per-request allowed source names set by a project-supplied middleware. None
# means "not set" — the search path then falls back to the scope->sources access
# policy. When set, it takes precedence over the policy (see current_allowed_sources).
_allowed_sources: ContextVar[tuple[str, ...] | None] = ContextVar(
    "opencrane_allowed_sources", default=None
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


def set_allowed_sources(names) -> None:
    """Record the allowed source names for this request (generic middleware hook).

    A project-supplied middleware (registered via ``OpenCraneConfig.middleware``)
    calls this to declare which source names the current request may access. The
    search path gives this value the highest precedence, above the scope->sources
    access policy. An empty iterable means "no sources permitted" and short-circuits
    the search to zero results.
    """
    _allowed_sources.set(tuple(names))


def current_allowed_sources() -> tuple[str, ...] | None:
    """Return the middleware-declared allowed source names, or ``None`` if unset.

    ``None`` means no middleware set an override for this request, so the search
    path falls back to the scope->sources access policy.
    """
    return _allowed_sources.get()


def set_current_endpoint(name: str) -> None:
    """Record which named MCP endpoint is serving the current request.

    Called by the per-endpoint middleware in http_server. ``get_access_policy()``
    uses this to pick the endpoint's own policy; the default ``""`` is the root
    /mcp endpoint.
    """
    _current_endpoint.set(name)


def _build_access_policies() -> "dict[str, AllowAllPolicy | ScopeSourcesPolicy]":
    """Parse config.yaml and build one access policy per configured endpoint.

    Reads the ``auth`` block from config.yaml (path in ``MAPPING_FILE``, default
    ``.opencrane/config.yaml``). A missing or unparseable file is treated as empty
    config, yielding a single root endpoint with an ``AllowAllPolicy``.
    """
    from opencrane.mcp.auth.config_model import parse_auth_endpoints
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
    endpoints = parse_auth_endpoints(data, known_sources)
    return {name: build_access_policy(cfg) for name, cfg in endpoints.items()}


def get_access_policy() -> "AllowAllPolicy | ScopeSourcesPolicy":
    """Return the access policy for the endpoint serving the current request.

    Policies for every configured endpoint are built and cached on first use
    (keyed by endpoint name) until ``reset_auth_runtime()`` is called. The
    endpoint is chosen from the per-request contextvar set by ``set_current_endpoint``
    (default ``""``, the root /mcp endpoint). If the current endpoint has no
    configured policy (defensive — should not happen in practice), an
    ``AllowAllPolicy`` is returned.
    """
    global _access_policies
    if _access_policies is None:
        _access_policies = _build_access_policies()

    name = _current_endpoint.get()
    policy = _access_policies.get(name)
    if policy is None:
        # Defensive: a request resolved to an endpoint with no configured policy.
        # This should not happen (tool calls always arrive via a configured
        # /mcp/<name>), so fail CLOSED — deny every source rather than leak all.
        from opencrane.mcp.auth.policies import ScopeSourcesPolicy

        logger.warning(
            f"No access policy for endpoint {name!r} — denying all sources (fail-closed)"
        )
        policy = ScopeSourcesPolicy({}, ())
        _access_policies[name] = policy
    return policy


def reset_auth_runtime() -> None:
    """Clear the cached access policies and per-request auth state.

    Call this in tests (via fixture teardown or explicit reset) and whenever
    the project configuration changes at runtime.
    """
    global _access_policies
    _access_policies = None
    _optional_scopes.set(None)
    _allowed_sources.set(None)
    _current_endpoint.set("")
