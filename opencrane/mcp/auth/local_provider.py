"""Local-mode self-hosted OAuth 2.1 authorization-server provider for OpenCrane.

Unlike a passthrough provider, OpenCrane has **no downstream API** to validate a
credential against. Instead the operator configures the expected credential in
environment variables and we validate it LOCALLY:

* ``method="token"`` — one or more accepted bearer tokens in ``OPENCRANE_ACCESS_TOKEN``
  (comma-separated). The user pastes a token into the login form; it is accepted iff
  it matches one of the configured tokens (constant-time compare).
* ``method="password"`` — a single ``OPENCRANE_LOGIN_USER`` / ``OPENCRANE_LOGIN_PASS``
  pair. The user submits username + password; both must match (constant-time compare).

The provider is **fail-closed at construction**: if the required environment variables
are unset or empty, instantiation raises :class:`AuthConfigError`.

The OAuth flow itself mirrors a standard authorization-code + PKCE handshake:

* ``authorize`` stores a pending request and redirects the browser to ``/login``.
* ``complete_login`` (called by the ``/login`` POST route) verifies the submitted
  credential and mints a single-use authorization code (~30s TTL) bound to the
  request's PKCE/redirect/client context and the provider's granted scopes.
* ``exchange_authorization_code`` pops the code (single use), issues a random opaque
  access token, and records ``access_token -> scopes``.
* ``load_access_token`` is presence-only against that store.
* Refresh tokens are unsupported.

The HTTP route wiring (Starlette) lives elsewhere; this module provides the provider
plus the helpers the route needs (``load_local_credentials``, ``verify_credentials``,
``render_login_form``) and the ``complete_login`` callback.
"""

from __future__ import annotations

import html
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from opencrane.mcp.auth.config_model import AuthConfigError

# How long a freshly-minted authorization code is valid for. Long enough for the
# client to immediately exchange it, short enough that a leaked code is useless.
CODE_TTL_SECONDS = 30

# A non-expiring stand-in client id reported for every access token. Local tokens
# are not tied to a registered OAuth client, so there is nothing better.
ACCESS_TOKEN_CLIENT_ID = "opencrane-user"


def load_local_credentials(method: str) -> set[str] | tuple[str, str]:
    """Load the expected credential(s) from the environment (fail-closed).

    For ``method="token"``: reads ``OPENCRANE_ACCESS_TOKEN`` and splits on commas,
    returning the set of accepted tokens. Raises :class:`AuthConfigError` if the
    variable is unset or contains no non-empty token.

    For ``method="password"``: reads ``OPENCRANE_LOGIN_USER`` and
    ``OPENCRANE_LOGIN_PASS``, returning ``(user, pass)``. Raises
    :class:`AuthConfigError` if either is unset or empty.
    """
    if method == "token":
        raw = os.environ.get("OPENCRANE_ACCESS_TOKEN", "")
        tokens = {part.strip() for part in raw.split(",") if part.strip()}
        if not tokens:
            raise AuthConfigError(
                "local token auth requires OPENCRANE_ACCESS_TOKEN to be set to one "
                "or more comma-separated tokens"
            )
        return tokens

    user = (os.environ.get("OPENCRANE_LOGIN_USER") or "").strip()
    if not user:
        raise AuthConfigError(
            "local password auth requires OPENCRANE_LOGIN_USER to be set"
        )
    password = os.environ.get("OPENCRANE_LOGIN_PASS") or ""
    if not password:
        raise AuthConfigError(
            "local password auth requires OPENCRANE_LOGIN_PASS to be set"
        )
    return (user, password)


def verify_credentials(
    method: str,
    submitted: str | tuple[str, str],
    *,
    expected: set[str] | tuple[str, str],
) -> bool:
    """Return True iff ``submitted`` matches ``expected`` (constant-time compare).

    For ``method="token"``: ``submitted`` is the pasted token string, ``expected`` is
    the set of accepted tokens. True iff it matches any accepted token.

    For ``method="password"``: ``submitted`` is a ``(user, pass)`` tuple, ``expected``
    is the configured ``(user, pass)`` tuple. True iff both match.

    Uses :func:`secrets.compare_digest` throughout to avoid leaking match position via
    timing. For tokens, every candidate is compared (accumulating the result) so the
    comparison work does not short-circuit on the first match.
    """
    if method == "token":
        submitted_token = submitted if isinstance(submitted, str) else ""
        matched = False
        for candidate in expected:
            if secrets.compare_digest(submitted_token, candidate):
                matched = True
        return matched

    submitted_user, submitted_pass = submitted
    expected_user, expected_pass = expected
    user_ok = secrets.compare_digest(submitted_user, expected_user)
    pass_ok = secrets.compare_digest(submitted_pass, expected_pass)
    return user_ok and pass_ok


def render_login_form(request_id: str, method: str, error: str | None = None) -> str:
    """Render the login form HTML for the given auth ``method``.

    The form POSTs ``request_id`` plus the credential field(s) to ``/login``:

    * ``method="token"`` — a single password-type field named ``token``.
    * ``method="password"`` — a ``username`` field and a password-type ``password`` field.

    Every interpolated value (``request_id``, ``error``) is escaped with
    :func:`html.escape` — this is an XSS boundary: ``request_id`` is round-tripped
    through the URL and ``error`` may echo user-influenced content.
    """
    safe_request_id = html.escape(request_id, quote=True)
    if error:
        error_block = (
            f'<p class="error" role="alert">{html.escape(error, quote=True)}</p>'
        )
    else:
        error_block = ""

    if method == "token":
        subtitle = "Paste your access token to connect your AI agent to this documentation server."
        fields = (
            '      <label for="token">Access Token</label>\n'
            '      <input type="password" id="token" name="token" required autofocus\n'
            '             placeholder="Paste your token here" spellcheck="false" autocomplete="off">\n'
        )
    else:
        subtitle = "Sign in to connect your AI agent to this documentation server."
        fields = (
            '      <label for="username">Username</label>\n'
            '      <input type="text" id="username" name="username" required autofocus\n'
            '             spellcheck="false" autocomplete="off">\n'
            '      <label for="password">Password</label>\n'
            '      <input type="password" id="password" name="password" required\n'
            '             autocomplete="off">\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Authenticate — OpenCrane</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #f5f5f5; display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 1rem; }}
    .card {{ background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.12); padding: 2rem; width: 100%; max-width: 480px; }}
    h1 {{ font-size: 1.25rem; margin-bottom: .5rem; }}
    p.subtitle {{ color: #555; font-size: .9rem; margin-bottom: 1.5rem; }}
    label {{ display: block; font-size: .875rem; font-weight: 500; margin-bottom: .4rem; }}
    input[type="text"], input[type="password"] {{ width: 100%; padding: .6rem .75rem; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; margin-bottom: 1rem; }}
    input:focus {{ outline: 2px solid #1869f5; border-color: transparent; }}
    button {{ width: 100%; padding: .7rem; background: #1869f5; color: #fff; border: none; border-radius: 4px; font-size: 1rem; cursor: pointer; }}
    button:hover {{ background: #0f52c7; }}
    .error {{ color: #c0392b; font-size: .875rem; margin-bottom: 1rem; padding: .5rem .75rem; background: #fdf2f2; border-radius: 4px; border: 1px solid #f5c6cb; }}
    .footer {{ margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid #eee; font-size: .75rem; color: #888; text-align: center; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>OpenCrane Documentation Server</h1>
    <p class="subtitle">{subtitle}</p>
    <form method="POST" action="/login" autocomplete="off">
      <input type="hidden" name="request_id" value="{safe_request_id}">
      {error_block}
{fields}      <button type="submit">Authenticate</button>
    </form>
    <div class="footer">
      Powered by <a href="https://github.com/derberg/OpenCrane" target="_blank" rel="noopener">OpenCrane</a>.
    </div>
  </div>
</body>
</html>"""


@dataclass
class _PendingAuth:
    """An authorize request awaiting the user submitting their credential."""

    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    state: str | None
    scopes: list[str] = field(default_factory=list)
    resource: str | None = None


@dataclass
class _CodeEntry:
    """A minted, single-use authorization code bound to its PKCE/redirect context."""

    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    scopes: list[str]
    expires_at: float
    resource: str | None = None


class OpenCraneAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Local-mode OAuth provider backed by env-configured credentials."""

    def __init__(
        self,
        *,
        method: str,
        scopes: tuple[str, ...] = (),
        now: Callable[[], float] = time.time,
    ) -> None:
        # Fail-closed at construction: raises AuthConfigError if env is missing.
        self._expected = load_local_credentials(method)
        self._method = method
        self._scopes: list[str] = list(scopes)
        self._now = now
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._pending: dict[str, _PendingAuth] = {}
        self._codes: dict[str, _CodeEntry] = {}
        self._access_tokens: dict[str, list[str]] = {}

    # -- client registration -------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            client_info.client_id = secrets.token_urlsafe(16)
        self._clients[client_info.client_id] = client_info

    # -- authorize -> login form --------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        request_id = secrets.token_urlsafe(16)
        self._pending[request_id] = _PendingAuth(
            client_id=client.client_id or "",
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            state=params.state,
            scopes=list(params.scopes or []),
            resource=params.resource,
        )
        return f"/login?request_id={request_id}"

    # -- form callback -------------------------------------------------------

    def complete_login(
        self, request_id: str, submitted: str | tuple[str, str]
    ) -> str:
        """Complete login from the ``/login`` POST route.

        Verifies the submitted credential, mints a single-use authorization code
        bound to the pending request's PKCE/redirect/client context and the
        provider's configured (granted) scopes, and returns the client redirect URI
        with ``?code=...&state=...`` appended.

        Raises :class:`ValueError` with a user-facing message if the request is
        unknown/expired or the credential is invalid, so the route can re-render the
        form with an error.
        """
        pending = self._pending.get(request_id)
        if pending is None:
            raise ValueError("Your login session expired. Please start again.")
        if not verify_credentials(self._method, submitted, expected=self._expected):
            raise ValueError("Invalid credentials. Please try again.")

        code = secrets.token_urlsafe(32)
        self._codes[code] = _CodeEntry(
            client_id=pending.client_id,
            redirect_uri=pending.redirect_uri,
            redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
            code_challenge=pending.code_challenge,
            # Client-requested scopes are intentionally ignored: the operator-configured
            # scopes are granted so the client cannot self-elevate its own permissions.
            scopes=list(self._scopes),
            expires_at=self._now() + CODE_TTL_SECONDS,
            resource=pending.resource,
        )
        # Pending request is consumed exactly once.
        del self._pending[request_id]

        return construct_redirect_uri(
            pending.redirect_uri, code=code, state=pending.state
        )

    # -- authorization code --------------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        entry = self._codes.get(authorization_code)
        if entry is None:
            return None
        if entry.expires_at < self._now():
            return None
        if entry.client_id != (client.client_id or ""):
            return None
        return self._to_auth_code(authorization_code, entry)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        # Pop for single use: even an expired or wrong-client code is removed.
        entry = self._codes.pop(authorization_code.code, None)
        if entry is None or entry.expires_at < self._now():
            raise TokenError("invalid_grant", "Invalid or expired authorization code")
        access_token = secrets.token_urlsafe(32)
        self._access_tokens[access_token] = list(entry.scopes)
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            scope=" ".join(entry.scopes) or None,
        )

    @staticmethod
    def _to_auth_code(code: str, entry: _CodeEntry) -> AuthorizationCode:
        return AuthorizationCode(
            code=code,
            scopes=entry.scopes,
            expires_at=entry.expires_at,
            client_id=entry.client_id,
            code_challenge=entry.code_challenge,
            redirect_uri=entry.redirect_uri,
            redirect_uri_provided_explicitly=entry.redirect_uri_provided_explicitly,
            resource=entry.resource,
        )

    # -- refresh tokens: unsupported ----------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        raise TokenError("invalid_grant", "Refresh tokens are not supported")

    # -- access token: presence-only ----------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        scopes = self._access_tokens.get(token)
        if scopes is None:
            return None
        return AccessToken(
            token=token,
            client_id=ACCESS_TOKEN_CLIENT_ID,
            scopes=list(scopes),
            expires_at=None,
        )

    # -- revocation ----------------------------------------------------------

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        value = getattr(token, "token", None)
        if value:
            self._access_tokens.pop(value, None)
            self._codes.pop(value, None)
