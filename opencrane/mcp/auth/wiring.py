"""Select and build the FastMCP auth kwargs from a parsed :class:`AuthConfig`.

This is the single seam between OpenCrane's auth configuration and FastMCP's
constructor: :func:`build_fastmcp_auth` maps an :class:`AuthConfig` to the keyword
arguments that get splatted into ``FastMCP(...)``.

* ``type == "none"`` (and, for now, ``type == "custom"``): return ``{}`` — the app
  is open, no auth routes are mounted.
* ``type == "local"``: build the self-hosted :class:`OpenCraneAuthProvider` and the
  matching :class:`AuthSettings`. Requires ``PUBLIC_URL`` (fail-closed).
* ``type == "oauth"``: not wired yet (Task 7) — raises :class:`AuthConfigError`.

``build_app`` checks ``"auth_server_provider" in kwargs`` to decide whether to mount
the ``/login`` route.
"""

from __future__ import annotations

import os
import time

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

from opencrane.mcp.auth.config_model import AuthConfig, AuthConfigError
from opencrane.mcp.auth.local_provider import OpenCraneAuthProvider


def build_fastmcp_auth(auth_config: AuthConfig) -> dict:
    """Return the ``FastMCP(...)`` kwargs implementing ``auth_config`` (fail-closed).

    Args:
        auth_config: The parsed auth configuration.

    Returns:
        A dict of kwargs to splat into ``FastMCP(...)``. Empty for open modes.

    Raises:
        AuthConfigError: For ``local`` mode when ``PUBLIC_URL`` is unset, and for
            ``oauth`` mode (not yet implemented — Task 7).
    """
    if auth_config.type in ("none", "custom"):
        return {}

    if auth_config.type == "local":
        public_url = (os.environ.get("PUBLIC_URL") or "").strip()
        if not public_url:
            raise AuthConfigError(
                "local auth requires PUBLIC_URL to be set to this server's public "
                "base URL (used as the OAuth issuer)"
            )
        provider = OpenCraneAuthProvider(
            method=auth_config.local_method,
            scopes=auth_config.local_scopes,
            now=time.time,
        )
        return {
            "auth_server_provider": provider,
            "auth": AuthSettings(
                issuer_url=public_url,
                resource_server_url=public_url,
                client_registration_options=ClientRegistrationOptions(enabled=True),
            ),
        }

    # type == "oauth": filled in by Task 7.
    raise AuthConfigError("oauth wiring not yet available")
