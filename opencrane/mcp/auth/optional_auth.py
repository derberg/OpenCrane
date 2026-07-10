"""Optional-auth ASGI middleware for ``oauth`` mode with ``allow_anonymous: true``.

The MCP SDK's auth wiring is all-or-nothing: configuring a token verifier wraps
the endpoint in ``RequireAuthMiddleware``, which rejects every tokenless request
with 401. That prevents a "public docs without login, more docs when logged in"
setup on a single endpoint.

This middleware provides the missing middle ground. It validates a bearer token
if the request carries one (recording the caller's scopes for the access
policy), but never rejects a tokenless request. Anonymous callers are recorded
with no scopes and fall through to ``default_sources`` in the access policy.
"""

from __future__ import annotations

from opencrane.mcp.auth.runtime import set_optional_scopes


def _extract_bearer(headers) -> str | None:
    """Return the bearer token from raw ASGI headers, or None.

    Args:
        headers: The ASGI ``scope["headers"]`` list of ``(name, value)`` byte pairs.

    Returns:
        The token string when an ``Authorization: Bearer <token>`` header is
        present, otherwise ``None``.
    """
    for name, value in headers:
        if name.lower() == b"authorization":
            if value[:7].lower() == b"bearer ":
                return value[7:].decode("latin-1").strip()
            return None
    return None


class OptionalAuthMiddleware:
    """Validate a bearer token if present; never require one.

    Wraps the MCP ASGI app. For each HTTP request it records the caller's scopes
    (empty when anonymous or when the token is invalid) so the access policy can
    resolve the allowed sources. It does not send 401.
    """

    def __init__(self, app, verifier) -> None:
        """Initialize the middleware.

        Args:
            app: The wrapped ASGI application.
            verifier: A token verifier exposing ``async verify_token(token)``.
        """
        self.app = app
        self._verifier = verifier

    async def __call__(self, scope, receive, send):
        """Record scopes for HTTP requests, then delegate to the wrapped app."""
        if scope.get("type") == "http":
            scopes: tuple[str, ...] = ()
            token = _extract_bearer(scope.get("headers") or [])
            if token is not None:
                access = await self._verifier.verify_token(token)
                if access is not None:
                    scopes = tuple(access.scopes)
            set_optional_scopes(scopes)
        await self.app(scope, receive, send)
