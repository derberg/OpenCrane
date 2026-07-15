"""External-IdP JWT token verifier for ``auth.type: oauth``.

In ``oauth`` mode OpenCrane acts as an OAuth 2.0 **resource server**: it does not
issue tokens itself but validates bearer JWTs minted by an external IdP (the
``oidc.issuer``). Validation is fully local — signature (via the IdP's JWKS),
issuer, expiry, and, critically, **audience** are all checked by ``jwt.decode``.

Audience binding is the confused-deputy defense: a token whose ``aud`` claim does
not include *this* resource server (``oidc.audience``) is rejected, so a token
minted for some other service cannot be replayed against OpenCrane.

The network JWKS fetch lives *outside* :class:`JwtTokenVerifier` (injected as
``signing_key_resolver``) so the verifier is unit-testable with a static key.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Callable

from mcp.server.auth.provider import AccessToken, TokenVerifier

from opencrane.mcp.auth.config_model import AuthConfig, AuthConfigError

logger = logging.getLogger(__name__)

# Sent on the OIDC discovery and JWKS fetches. Some IdPs sit behind a WAF/CDN
# that returns 403 for the default ``Python-urllib/x.y`` User-Agent, so an
# explicit one is required for discovery to succeed.
_USER_AGENT = "opencrane"


def _extract_scopes(claims: dict, claim: str) -> tuple[str, ...]:
    """Extract scopes from ``claims[claim]`` regardless of encoding.

    The scope claim may be an OAuth2 space-delimited string (``scope``), a
    list/tuple (``scp`` / ``permissions``), or absent.

    Args:
        claims: The decoded JWT claims.
        claim: The name of the claim holding the scopes.

    Returns:
        A tuple of scope strings; empty if the claim is missing.
    """
    value = claims.get(claim)
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(value.split())
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return ()  # scalar / unexpected claim type → no scopes (fail safe, no raise)


class JwtTokenVerifier(TokenVerifier):
    """Validates external-IdP JWT bearer tokens (SDK ``TokenVerifier`` protocol)."""

    def __init__(
        self,
        *,
        issuer: str,
        audiences: tuple[str, ...],
        scope_claim: str,
        signing_key_resolver: Callable[[str], object],
        verify_audience: bool = True,
    ) -> None:
        """Initialize the verifier.

        Args:
            issuer: Expected ``iss`` claim (the external IdP).
            audiences: Accepted ``aud`` values. A token is valid if its ``aud``
                matches ANY entry — this lets one server trust tokens from
                several front-end OAuth clients (each carrying its own client_id
                as ``aud`` with Dex). Ignored when ``verify_audience`` is False.
            scope_claim: Name of the claim carrying granted scopes.
            signing_key_resolver: Callable mapping a raw token to the key used to
                verify its signature. The (network) JWKS lookup lives here so the
                verifier itself stays unit-testable.
            verify_audience: When True (default), the ``aud`` claim is required
                and must match ``audiences`` (the confused-deputy defense). When
                False, ``aud`` is neither required nor checked — for IdPs that
                cannot stamp the audience (e.g. Ory Hydra ignores the RFC 8707
                ``resource`` parameter and issues an empty ``aud``). Signature,
                issuer, and expiry are still enforced.
        """
        self._issuer = issuer
        self._audiences = audiences
        self._scope_claim = scope_claim
        self._signing_key_resolver = signing_key_resolver
        self._verify_audience = verify_audience

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer JWT and map it to an :class:`AccessToken`.

        Args:
            token: The raw bearer token from the ``Authorization`` header.

        Returns:
            An :class:`AccessToken` when the token is valid, or ``None`` on any
            validation failure (the SDK then emits a 401 challenge).
        """
        import jwt

        decode_kwargs: dict = {
            "algorithms": ["RS256", "ES256"],
            "issuer": self._issuer,
        }
        if self._verify_audience:
            decode_kwargs["audience"] = list(self._audiences)
            decode_kwargs["options"] = {"require": ["exp", "aud", "iss"]}
        else:
            decode_kwargs["options"] = {"require": ["exp", "iss"], "verify_aud": False}

        try:
            key = self._signing_key_resolver(token)
            claims = jwt.decode(token, key, **decode_kwargs)
        except jwt.PyJWTError:
            return None
        except AuthConfigError as exc:
            # Signing key could not be resolved (IdP discovery/JWKS unreachable or
            # misconfigured). Fail closed to a 401 rather than crashing the request
            # with a 500; log so operators can distinguish an outage from a bad token.
            logger.warning(f"token verification could not resolve signing key: {exc}")
            return None

        return AccessToken(
            token=token,
            client_id=claims.get("azp") or claims.get("client_id") or "external",
            scopes=list(_extract_scopes(claims, self._scope_claim)),
            expires_at=claims.get("exp"),
        )


def _discover_jwks_uri(issuer: str) -> str:
    """Return the IdP's ``jwks_uri`` from its OIDC discovery document.

    Fetches ``<issuer>/.well-known/openid-configuration`` and reads the
    ``jwks_uri`` field. This is the OIDC-compliant, IdP-agnostic way to locate the
    signing keys: the path differs per provider (Dex serves ``/keys``, Keycloak
    ``/protocol/openid-connect/certs``, Auth0 ``/.well-known/jwks.json``), so
    assembling a fixed path only works for one IdP.

    Args:
        issuer: The OIDC issuer URL (``oidc.issuer``).

    Returns:
        The absolute ``jwks_uri`` URL advertised by the IdP.

    Raises:
        AuthConfigError: If the discovery document cannot be fetched or parsed, or
            does not advertise a ``jwks_uri``.
    """
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            doc = json.load(response)
    except (urllib.error.URLError, ValueError) as exc:  # network error / invalid JSON
        raise AuthConfigError(
            f"could not fetch OIDC discovery document from {url}: {exc}"
        ) from exc
    jwks_uri = doc.get("jwks_uri")
    if not jwks_uri:
        raise AuthConfigError(
            f"OIDC discovery document at {url} does not advertise a 'jwks_uri'"
        )
    return jwks_uri


def build_token_verifier(auth_config: AuthConfig) -> JwtTokenVerifier:
    """Build a :class:`JwtTokenVerifier` from ``auth_config`` (fail-closed).

    The default ``signing_key_resolver`` locates the IdP's JWKS via OIDC discovery
    (``<issuer>/.well-known/openid-configuration`` → ``jwks_uri``) and returns the
    key matching the token's ``kid``. Discovery runs once on first use and the
    resulting ``PyJWKClient`` is cached for subsequent tokens.

    Args:
        auth_config: The parsed auth configuration (must be ``type: oauth``).

    Returns:
        A configured :class:`JwtTokenVerifier`.

    Raises:
        AuthConfigError: If PyJWT (the ``opencrane[auth]`` extra) is not installed.
    """
    try:
        import jwt
    except ImportError as exc:
        raise AuthConfigError(
            "install opencrane[auth] to use auth.type 'oauth'"
        ) from exc

    cache: dict = {}

    def default_resolver(token: str) -> object:
        client = cache.get("client")
        if client is None:
            jwks_uri = _discover_jwks_uri(auth_config.oidc_issuer)
            client = jwt.PyJWKClient(jwks_uri, headers={"User-Agent": _USER_AGENT})
            cache["client"] = client
        return client.get_signing_key_from_jwt(token).key

    if not auth_config.oidc_verify_audience:
        logger.warning(
            "oidc.verify_audience is disabled for issuer %s: tokens are accepted "
            "without an audience claim (confused-deputy protection off). Enable it "
            "once the IdP can stamp the token audience.",
            auth_config.oidc_issuer,
        )

    return JwtTokenVerifier(
        issuer=auth_config.oidc_issuer,
        audiences=auth_config.oidc_audiences,
        scope_claim=auth_config.scope_claim,
        signing_key_resolver=default_resolver,
        verify_audience=auth_config.oidc_verify_audience,
    )
