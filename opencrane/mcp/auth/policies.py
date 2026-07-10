"""Access policies for OpenCrane MCP server."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opencrane.mcp.auth.config_model import AuthConfig


class AllowAllPolicy:
    """Policy that never restricts access — passes requests through unchanged."""

    def authorize(
        self,
        scopes: tuple[str, ...],
        requested: list[str] | None,
    ) -> list[str] | None:
        """Return requested unchanged (None or list)."""
        return requested


class ScopeSourcesPolicy:
    """Policy that maps OAuth scopes to allowed source names."""

    def __init__(
        self,
        scope_sources: dict[str, tuple[str, ...]],
        default_sources: tuple[str, ...],
    ) -> None:
        self._scope_sources = scope_sources
        self._default_sources = default_sources

    def authorize(
        self,
        scopes: tuple[str, ...],
        requested: list[str] | None,
    ) -> list[str]:
        """Compute the allowed source set for the caller's scopes, then filter.

        For each scope the caller holds, union the sources mapped to that scope.
        If no caller scope matches any key in scope_sources, fall back to
        default_sources.  When ``requested`` is not None, return the sorted
        intersection of requested and allowed; otherwise return sorted(allowed).
        Always returns a concrete list (never None).
        """
        allowed: set[str] = set()
        matched = False
        for s in scopes:
            if s in self._scope_sources:
                allowed.update(self._scope_sources[s])
                matched = True
        if not matched:
            allowed = set(self._default_sources)

        if requested is not None:
            return sorted(s for s in requested if s in allowed)
        return sorted(allowed)


def build_access_policy(auth_config: AuthConfig) -> AllowAllPolicy | ScopeSourcesPolicy:
    """Return a ScopeSourcesPolicy when scope_sources or default_sources are set,
    else return an AllowAllPolicy."""
    if auth_config.scope_sources or auth_config.default_sources:
        return ScopeSourcesPolicy(auth_config.scope_sources, auth_config.default_sources)
    return AllowAllPolicy()
