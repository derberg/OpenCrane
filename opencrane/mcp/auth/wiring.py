"""Select and build the FastMCP auth kwargs from a parsed :class:`AuthConfig`.

This is the single seam between OpenCrane's auth configuration and FastMCP's
constructor: :func:`build_fastmcp_auth` maps an :class:`AuthConfig` to the keyword
arguments that get splatted into ``FastMCP(...)``.

* ``type == "none"``: return ``{}`` — the app is open, no auth routes are mounted.
* ``type == "custom"``: load ``OpenCraneConfig`` via ``load_config(None)`` and read
  ``auth_provider`` / ``token_verifier``.  If ``auth_provider`` is set, wire a
  self-hosted authorization server (requires ``PUBLIC_URL``).  If ``token_verifier``
  is set, wire a resource server (requires ``PUBLIC_URL``).  If neither is set,
  return ``{}`` (open — the operator has not wired a custom provider).
* ``type == "local"``: build the self-hosted :class:`OpenCraneAuthProvider` and the
  matching :class:`AuthSettings`. Requires ``PUBLIC_URL`` (fail-closed).
* ``type == "oauth"``: OpenCrane is an OAuth 2.0 resource server delegating token
  issuance to an external IdP. Build a :class:`JwtTokenVerifier` and the matching
  :class:`AuthSettings` (``issuer_url`` = the external IdP, ``resource_server_url`` =
  this server's ``PUBLIC_URL``). Requires ``PUBLIC_URL`` (fail-closed).

``build_app`` checks ``"auth_server_provider" in kwargs`` to decide whether to mount
the ``/login`` route.
"""

from __future__ import annotations

import os
import time

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

from opencrane.mcp.auth.config_model import AuthConfig, AuthConfigError
from opencrane.mcp.auth.local_provider import OpenCraneAuthProvider
from opencrane.mcp.auth.oauth_verifier import build_token_verifier


def build_fastmcp_auth(auth_config: AuthConfig) -> dict:
    """Return the ``FastMCP(...)`` kwargs implementing ``auth_config`` (fail-closed).

    Args:
        auth_config: The parsed auth configuration.

    Returns:
        A dict of kwargs to splat into ``FastMCP(...)``. Empty for open modes.

    Raises:
        AuthConfigError: For ``local`` or ``oauth`` mode when ``PUBLIC_URL`` is
            unset, or for ``oauth`` mode when the ``opencrane[auth]`` extra is
            not installed.
    """
    if auth_config.type == "none":
        return {}

    if auth_config.type == "custom":
        from opencrane.cli import load_config
        oc = load_config(None)
        if oc.auth_provider is not None:
            public_url = (os.environ.get("PUBLIC_URL") or "").strip()
            if not public_url:
                raise AuthConfigError(
                    "custom auth with auth_provider requires PUBLIC_URL to be set to "
                    "this server's public base URL (used as the OAuth issuer)"
                )
            return {
                "auth_server_provider": oc.auth_provider,
                "auth": AuthSettings(
                    issuer_url=public_url,
                    resource_server_url=public_url,
                    client_registration_options=ClientRegistrationOptions(enabled=True),
                ),
            }
        if oc.token_verifier is not None:
            public_url = (os.environ.get("PUBLIC_URL") or "").strip()
            if not public_url:
                raise AuthConfigError(
                    "custom auth with token_verifier requires PUBLIC_URL to be set to "
                    "this server's public base URL (used as the OAuth resource-server identifier)"
                )
            return {
                "token_verifier": oc.token_verifier,
                "auth": AuthSettings(
                    issuer_url=public_url,
                    resource_server_url=public_url,
                ),
            }
        # Neither hook set — custom type with no wiring means open.
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

    # type == "oauth": resource-server mode — validate external-IdP JWTs.
    public_url = (os.environ.get("PUBLIC_URL") or "").strip()
    if not public_url:
        raise AuthConfigError(
            "oauth auth requires PUBLIC_URL to be set to this server's public "
            "base URL (used as the OAuth resource-server identifier)"
        )
    return {
        "token_verifier": build_token_verifier(auth_config),
        "auth": AuthSettings(
            # issuer_url is the external IdP; resource_server_url is THIS server.
            issuer_url=auth_config.oidc_issuer,
            resource_server_url=public_url,
            # No transport-level required_scopes: Layer-2 scope->sources handles
            # content authorization; requiring scopes here would over-restrict.
            required_scopes=None,
        ),
    }
