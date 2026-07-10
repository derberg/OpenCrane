# Authentication & Authorization

OpenCrane's HTTP transport supports two independent layers of access control:

- **Layer 1 — Authentication** (who may connect): implemented via OAuth 2.1 using the MCP Python SDK. The `auth.type` config key selects the mode. stdio transport is always unauthenticated (per the MCP spec — stdio uses environment credentials).
- **Layer 2 — Authorization** (which sources a caller may retrieve): declarative `scope → [source_name,…]` mapping enforced server-side by constraining every search against the Milvus and BM25 backends.

## The `auth:` configuration block

```yaml
# .opencrane/config.yaml
auth:
  type: none          # none | local | oauth | custom  (default: none)
```

Place the `auth:` block at the top level of `.opencrane/config.yaml`.

| `type` | Authentication mode |
|--------|---------------------|
| `none` | No auth — server is open (current default) |
| `local` | Self-hosted OAuth 2.1 AS with a browser login form |
| `oauth` | External IdP — OpenCrane acts as an OAuth resource server |
| `custom` | Operator-supplied `token_verifier` or `auth_provider` hook in `OpenCraneConfig` |

---

## `local` mode — self-hosted OAuth with browser login

OpenCrane runs its own OAuth 2.1 authorization server. When an MCP client connects, it is redirected to OpenCrane's browser login form. The consumer authenticates once; the resulting access token is stored by the client for subsequent requests. No external identity provider is needed.

### Configuration

```yaml
auth:
  type: local
  local:
    method: token     # token (default) | password
```

### Environment variables

| Variable | Required for | Description |
|----------|-------------|-------------|
| `PUBLIC_URL` | Always | The server's public base URL (e.g. `https://docs-mcp.example.com`). Used as the OAuth issuer URL. **Must be HTTPS in production** (OAuth 2.1 requirement; `http://localhost` is allowed for development). |
| `OPENCRANE_ACCESS_TOKEN` | `method: token` | One or more accepted tokens, comma-separated. The login form presents a token-paste field. |
| `OPENCRANE_LOGIN_USER` | `method: password` | Accepted username. |
| `OPENCRANE_LOGIN_PASS` | `method: password` | Accepted password. |

Credentials are read from environment only; never from the config file.

### Docker Compose example

```yaml
# docker-compose.yml
services:
  docs-mcp:
    image: my-opencrane-image
    environment:
      PUBLIC_URL: https://docs-mcp.example.com
      OPENCRANE_ACCESS_TOKEN: ${OPENCRANE_ACCESS_TOKEN:?set me}
      # OR, for method: password —
      # OPENCRANE_LOGIN_USER: admin
      # OPENCRANE_LOGIN_PASS: ${OPENCRANE_LOGIN_PASS:?set me}
```

### Consumer experience

```bash
claude mcp add --transport http docs https://docs-mcp.example.com/mcp
```

The client detects it is unauthorized → prompts the consumer to authorize → browser opens OpenCrane's login form → consumer pastes the token (or enters user/pass) → done. The client stores the access token for future sessions.

---

## `oauth` mode — external IdP (Keycloak, Auth0, Entra, …)

OpenCrane acts as an OAuth 2.1 resource server. Token issuance is delegated to an external identity provider. Bearer tokens are validated by checking the IdP's JWKS, the audience binding, and expiry.

### Additional dependency

```bash
pip install 'opencrane[auth]'
```

The `[auth]` extra adds `pyjwt[crypto]` for JWT validation. Without it, `oauth` mode raises an error at startup.

### Configuration

```yaml
auth:
  type: oauth
  oidc:
    issuer: https://login.example.com/realms/docs   # IdP issuer URL (JWKS discovered from here)
    audience: opencrane-docs                         # Expected `aud` claim; reject tokens not for this resource
    scope_claim: scope                               # JWT claim to read scopes from (default: scope)
  scope_sources:
    "docs:public":   [cennso-glossary]
    "docs:internal": [cgw, tsr, tposs]
  default_sources: [cennso-glossary]
```

| Field | Required | Description |
|-------|----------|-------------|
| `oidc.issuer` | Yes | External IdP issuer URL |
| `oidc.audience` | Yes | Resource identifier — the `aud` claim in tokens must include this value |
| `oidc.scope_claim` | No | JWT claim name to read scopes from (default: `scope`) |

`PUBLIC_URL` must be set (as with `local` mode).

### Optional authentication (`allow_anonymous`)

By default `oauth` mode requires a valid bearer token on every request (tokenless
requests get `401`). Set `allow_anonymous: true` to make the token **optional**:

```yaml
auth:
  type: oauth
  allow_anonymous: true
  oidc:
    issuer: https://login.example.com/realms/docs
    audience: opencrane-docs
  scope_sources:
    "docs:internal": [cgw, tsr, tposs]
  default_sources: [cennso-glossary]
```

With `allow_anonymous: true`:

- A request **with** a valid bearer token is authorized by its scopes, exactly as normal.
- A request **without** a token (or with an invalid one) is allowed through as an
  anonymous caller with no scopes, and resolves to `default_sources`.

This serves public docs without a login while still giving authenticated callers
their scoped access on the **same endpoint**. `PUBLIC_URL` is not required in this
mode, and the server does not advertise OAuth discovery metadata, so authenticated
clients must be configured with a token or authorization endpoint directly.

---

## Layer 2 — Authorization: `scope_sources` and `default_sources`

`scope_sources` maps an OAuth scope name to the list of source names that scope grants access to. It is optional and works with both `local` and `oauth` modes.

```yaml
auth:
  type: oauth   # or local
  oidc: { issuer: ..., audience: ... }
  scope_sources:
    "docs:public":   [cennso-glossary]
    "docs:internal": [cgw, tsr, tposs]
  default_sources: [cennso-glossary]
```

### Semantics

1. Read the caller's scopes from the access token at search time.
2. `allowed = union(scope_sources[s] for s in caller_scopes)` — callers with multiple scopes see the union of their permitted sources.
3. If no scope matches any key in `scope_sources`, fall back to `default_sources`. If `default_sources` is also absent, the caller sees no results.
4. Intersect `allowed` with any `source_names` parameter supplied by the client (narrow-only — the client can restrict, never expand).
5. If the resulting set is empty, **short-circuit to zero results** — an empty list is never forwarded to the backend (which would disable the filter and return all sources).
6. If `scope_sources` is not configured at all, authenticated callers may access all sources (useful for a simple "authenticated = full access" gate with `local` mode).

Source names in `scope_sources` and `default_sources` must match names in `sources:` in the same config file; unknown names are rejected at startup.

---

## `custom` mode — escape-hatch for operator-supplied auth

Set `auth.type: custom` in config and provide either `token_verifier` or `auth_provider` on your `OpenCraneConfig` subclass in `.opencrane/extensions.py`.

### `token_verifier` (resource-server mode)

Supply a `TokenVerifier` (the MCP SDK's `mcp.server.auth.provider.TokenVerifier`). OpenCrane wires it as a resource server. `PUBLIC_URL` is required.

```python
# .opencrane/extensions.py
from opencrane import OpenCraneConfig
from my_package.auth import MyTokenVerifier

class Config(OpenCraneConfig):
    token_verifier = MyTokenVerifier()
```

### `auth_provider` (self-hosted authorization-server mode)

Supply an `OAuthAuthorizationServerProvider` subclass instance. OpenCrane mounts the full OAuth AS routes and wires your provider. `PUBLIC_URL` is required.

```python
# .opencrane/extensions.py
from opencrane import OpenCraneConfig
from my_package.auth import MyAuthProvider

class Config(OpenCraneConfig):
    auth_provider = MyAuthProvider()
```

If neither hook is set, `custom` type is treated as open (no auth) — this lets you set `auth.type: custom` without wiring a provider yet.

---

## `middleware` hook — custom request middleware / authorizer

For authorization logic that config-driven `scope_sources` cannot express (e.g. resolving allowed sources from an external service, a custom header, or a JWT claim), register your own ASGI middleware on your `OpenCraneConfig` subclass. Each entry is a callable `(app) -> asgi_app` — typically a class that stores the wrapped app and implements `async __call__(self, scope, receive, send)`.

Entries are applied as the **outermost** layers of the HTTP MCP app (the first entry is outermost and runs first), so they execute before the tool handler. A middleware declares the request's permitted source names by calling `set_allowed_sources(...)`:

A minimal example — grant a fixed set of sources to every caller:

```python
# .opencrane/extensions.py
from opencrane import OpenCraneConfig
from opencrane.mcp.auth.runtime import set_allowed_sources

class SourceAuthorizer:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            set_allowed_sources(["cgw", "npp"])   # () means "no sources permitted"
        await self.app(scope, receive, send)

class Config(OpenCraneConfig):
    middleware = [SourceAuthorizer]
```

### Realistic example — resolve sources from an external permissions service

A common pattern: read the caller's bearer token, ask an external service which
sources the caller may see, and cache the answer per token. A missing token or a
failed lookup leaves the override unset, so the request falls back to
`default_sources` (fail closed). This is how a downstream project keeps its own
authorization logic out of OpenCrane.

```python
# .opencrane/extensions.py
import time
import httpx
from opencrane import OpenCraneConfig
from opencrane.mcp.auth.runtime import set_allowed_sources


class PermissionsAuthorizer:
    """Declare allowed sources from an external permissions API, cached per token."""

    API = "https://permissions.example.com/api/allowed-sources"
    TTL = 60  # seconds

    def __init__(self, app):
        self.app = app
        self._cache: dict[str, tuple[float, list[str]]] = {}

    def _bearer(self, headers) -> str | None:
        for name, value in headers:
            if name.lower() == b"authorization" and value[:7].lower() == b"bearer ":
                return value[7:].decode("latin-1").strip()
        return None

    async def _allowed(self, token: str) -> list[str] | None:
        cached = self._cache.get(token)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(self.API, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                return None                      # fail closed — do not cache failures
            names = list(resp.json().keys())
        except Exception:
            return None
        self._cache[token] = (time.monotonic() + self.TTL, names)
        return names

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            token = self._bearer(scope.get("headers") or [])
            if token:
                names = await self._allowed(token)
                if names is not None:
                    set_allowed_sources(names)   # authenticated caller → permitted sources
                # no token, or a failed lookup → override stays unset → default_sources
        await self.app(scope, receive, send)


class Config(OpenCraneConfig):
    middleware = [PermissionsAuthorizer]
```

Source names returned by the service must match the keys in the `sources:` block
of the same `config.yaml`. Names with no matching source are simply never
returned by search.

At search time `set_allowed_sources` takes **highest precedence** — above the `scope_sources` access policy:

- If a middleware set an allowed set, that set is used; any client-supplied `source_names` is intersected narrow-only (the client can restrict, never expand).
- An empty allowed set **short-circuits to zero results** (never disables the filter).
- If no middleware sets an override, authorization falls back to the `scope_sources` policy exactly as before.

`middleware` defaults to an empty list (no-op). This is generic plumbing — OpenCrane ships no built-in middleware.

---

## stdio transport

The stdio transport is always unauthenticated. OAuth applies to the HTTP transport only. When running `opencrane serve --transport stdio`, the server trusts the process's environment for credentials (per the MCP specification) and Layer-2 scope enforcement is bypassed (all sources are accessible).

---

## Security notes

- `PUBLIC_URL` must be HTTPS in production. The SDK permits `http://localhost` for local development only.
- `oauth` mode enforces **audience binding** — tokens not explicitly minted for `oidc.audience` are rejected (prevents confused-deputy attacks).
- `local` mode credentials come from environment variables only — never the config file. Constant-time comparison is used for token matching.
- Layer-2 enforcement is **server-side only** — the client-supplied `source_names` parameter can only narrow, never expand, the set of accessible sources.
- Fail-closed: misconfigured auth (missing `PUBLIC_URL`, unknown source names, missing `opencrane[auth]` extra) raises an error at startup and refuses to serve.
