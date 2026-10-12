# Authentication and authorization

The OpenCrane HTTP transport supports two independent layers of access control:

- Authentication controls who can connect. OpenCrane implements it with OAuth 2.1 through the Model Context Protocol (MCP) Python software development kit (SDK). The `auth.type` key selects the mode.
- Authorization controls which sources a caller can retrieve. A mapping from each OAuth scope to a list of source names sets the policy. The server applies it to every `search_docs` call. The tools that fetch a chunk, list, or table by ID do not apply it. For details, see [Security notes](#security-notes).

The standard input/output (stdio) transport is always unauthenticated. According to the MCP specification, the stdio transport uses credentials from the environment instead. For details, see [Access control over the stdio transport](#access-control-over-the-stdio-transport).

## Choose an authentication mode

The `auth:` block sets the authentication mode. Place it at the top level of the `.opencrane/config.yaml` file.

> [!CAUTION]
> With the default `type: none`, OpenCrane has no authentication. Anyone who can reach the HTTP port can read every source. Before you expose the server on a network, set another type, or index only sources that anyone may read. `default_sources` limits `search_docs` only. The `get_yaml_definition`, `get_list_members`, and `get_table_members` tools still return chunks from any indexed source.

The following example sets the default mode:

```yaml
# .opencrane/config.yaml
auth:
  type: none          # none | local | oauth | custom  (default: none)
```

The following table lists the values of `type`:

| `type` | Authentication mode |
|--------|---------------------|
| `none` | No authentication. The server accepts every request. This is the default. |
| `local` | Self-hosted OAuth 2.1 authorization server with a browser login form. |
| `oauth` | External identity provider (IdP). OpenCrane acts as an OAuth resource server. |
| `custom` | A `token_verifier` or `auth_provider` hook that you supply in `OpenCraneConfig`. |

---

## Set up the `local` mode with a browser login

In the `local` mode, OpenCrane runs its own OAuth 2.1 authorization server, so you do not need an external identity provider. When an MCP client connects, OpenCrane redirects it to a browser login form. The user signs in once, and the client stores the access token for later requests.

### Choose the login method

The `local.method` key sets what the user enters on the login form. With `token`, the default, the user pastes an access token. With `password`, the user enters a username and a password. The following example sets the login method:

```yaml
auth:
  type: local
  local:
    method: token             # token (default) | password
    scopes: [docs:internal]   # optional; granted to every token this server issues
```

The optional `local.scopes` list sets the scopes of every access token that the login form issues. All users who sign in get the same scopes. Without `local.scopes`, tokens carry no scopes, so `scope_sources` never matches and every caller gets `default_sources`. For `scope_sources` and `default_sources`, see [Restrict sources by scope](#restrict-sources-by-scope).

### Set the environment variables

OpenCrane reads the credentials from environment variables only, never from the `.opencrane/config.yaml` file. The following table lists the variables:

| Variable | Required for | Description |
|----------|-------------|-------------|
| `PUBLIC_URL` | Always | The server's public base URL, for example `https://docs-mcp.example.com`. OpenCrane uses it as the OAuth issuer URL. It must use HTTPS in production, as OAuth 2.1 requires. For development, OpenCrane also accepts `http://localhost`. |
| `OPENCRANE_ACCESS_TOKEN` | `method: token` | One or more accepted tokens, separated by commas. The login form shows a field to paste the token. |
| `OPENCRANE_LOGIN_USER` | `method: password` | The accepted username. |
| `OPENCRANE_LOGIN_PASS` | `method: password` | The accepted password. |

The following Docker Compose file sets the variables for `method: token`. The comments show the variables for `method: password`:

```yaml
# docker-compose.yml
services:
  docs-mcp:
    image: {OPENCRANE_IMAGE}
    environment:
      PUBLIC_URL: https://docs-mcp.example.com
      OPENCRANE_ACCESS_TOKEN: ${OPENCRANE_ACCESS_TOKEN:?set me}
      # For method: password, set these instead:
      # OPENCRANE_LOGIN_USER: admin
      # OPENCRANE_LOGIN_PASS: ${OPENCRANE_LOGIN_PASS:?set me}
```

### Connect a client

To add the server to Claude Code, run the following command:

```bash
claude mcp add --transport http docs https://docs-mcp.example.com/mcp
```

The client detects that it has no access token and asks the user to sign in. The browser opens the OpenCrane login form, where the user pastes the token or enters the username and password. The client then stores the access token for later sessions.

---

## Set up the `oauth` mode with an external identity provider

In the `oauth` mode, OpenCrane acts as an OAuth 2.1 resource server, and an external identity provider (IdP) issues the tokens. For example, the IdP can be one of the following:

- Keycloak
- Auth0
- Microsoft Entra ID

OpenCrane validates each bearer token against the IdP's JSON Web Key Set (JWKS). It also checks the token's issuer, audience, and expiry.

### Install the `auth` extra

The `oauth` mode needs the `auth` extra, which adds `pyjwt[crypto]` for JSON Web Token (JWT) validation. To install it, run the following command:

```bash
pip install 'opencrane[auth]'
```

Without the extra, the `oauth` mode raises an error at startup.

### Connect OpenCrane to the identity provider

The `oidc` block sets the identity provider that issues the tokens. For `scope_sources` and `default_sources`, see [Restrict sources by scope](#restrict-sources-by-scope). The following example configures the `oauth` mode with authorization by scope:

```yaml
auth:
  type: oauth
  oidc:
    issuer: https://login.example.com/realms/docs   # IdP issuer URL (JWKS discovered from here)
    audience: opencrane-docs                         # Expected `aud` claim; reject tokens not for this resource
    scope_claim: scope                               # JWT claim to read scopes from (default: scope)
    advertised_scopes: [openid]                      # Published as scopes_supported; advertised, never enforced
  scope_sources:
    "docs:public":   [public-docs]
    "docs:internal": [product-a, product-b]
  default_sources: [public-docs]
```

The following table describes the `oidc` fields:

| Field | Required | Description |
|-------|----------|-------------|
| `oidc.issuer` | Yes | The external IdP's issuer URL. |
| `oidc.audience` | Yes, unless `oidc.verify_audience` is `false` | The resource identifier, as a string or a list of strings. Each token's `aud` claim must include one of the values. |
| `oidc.scope_claim` | No | The name of the JWT claim that holds the scopes. The default is `scope`. |
| `oidc.verify_audience` | No | Enforces the `aud` check. The default is `true`. With `false`, OpenCrane accepts tokens that the IdP issued for other services. Set it to `false` only for an IdP that cannot set the audience. See [Disable audience validation](#disable-audience-validation). |
| `oidc.advertised_scopes` | No | Scope names that OpenCrane publishes as `scopes_supported` in the protected-resource metadata, which Request for Comments (RFC) 9728 defines. OpenCrane advertises them but never requires them. See [Advertise scopes to clients](#advertise-scopes-to-clients). |

The `oauth` mode also needs the `PUBLIC_URL` environment variable, as the `local` mode does. The exception is `allow_anonymous: true`, described in [Make authentication optional](#make-authentication-optional).

### Advertise scopes to clients

If users must sign in again every time the access token expires, advertise a scope such as `openid`. Some MCP clients request a scope only when the server lists one as `scopes_supported` in its protected-resource metadata (RFC 9728). A client that requests no scope gets no refresh token from an IdP that issues refresh tokens only for the `offline_access` scope. With an advertised scope, a client that wants a refresh token requests that scope and adds `offline_access` when the IdP's own metadata lists it. The IdP then issues a refresh token.

To publish scopes as `scopes_supported`, list the scopes that a client should request in `advertised_scopes`:

```yaml
auth:
  type: oauth
  oidc:
    issuer: https://login.example.com
    audience: opencrane-docs
    advertised_scopes: [openid]
```

OpenCrane advertises these scopes but does not require them, so it does not reject a token that lacks them. Advertising without enforcing has two effects:

- Tokens issued before you advertised the scope keep working.
- If your IdP writes the scope to a claim that OpenCrane does not read, OpenCrane still accepts the token.

Do not list `offline_access` in `advertised_scopes`. The MCP authorization specification says that a protected resource should not advertise it, because a refresh token serves the client session, not the resource.

### Disable audience validation

By default, OpenCrane requires the token's `aud` claim to match `oidc.audience`. This check protects against confused-deputy attacks: a token issued for another service cannot be replayed against this one.

Some IdPs cannot put the audience into the token. For example, Ory Hydra ignores the RFC 8707 `resource` parameter that MCP clients, such as Claude Code, send on the authorization request. Ory Hydra then issues access tokens with an empty `aud`, and OpenCrane rejects every request as `invalid_token`.

> [!CAUTION]
> With `verify_audience: false`, OpenCrane accepts any token that this identity provider issued, including tokens issued for other services. Use it only when the identity provider cannot set the audience. In a custom middleware, reject tokens whose `azp` (authorized party) or `client_id` claim is not your MCP client.

If your IdP cannot set the audience, set `verify_audience: false`. OpenCrane still checks the signature, the issuer, and the expiry, and skips only the audience check:

```yaml
auth:
  type: oauth
  oidc:
    issuer: https://login.example.com
    verify_audience: false   # The IdP cannot set aud, for example Ory Hydra
```

OpenCrane logs a `WARNING` at startup whenever `verify_audience` is disabled. For the middleware check, see [Authorize requests with custom middleware](#authorize-requests-with-custom-middleware).

### Make authentication optional

By default, the `oauth` mode requires a valid bearer token on every request. A request without a token gets `401`.

> [!CAUTION]
> With `allow_anonymous: true`, anyone can read the sources in `default_sources` without a token. If you set neither `scope_sources` nor `default_sources`, anyone can read every source. Set `default_sources`, and list only public documentation in it. For both keys, see [Restrict sources by scope](#restrict-sources-by-scope).

To make the token optional, set `allow_anonymous: true`:

```yaml
auth:
  type: oauth
  allow_anonymous: true
  oidc:
    issuer: https://login.example.com/realms/docs
    audience: opencrane-docs
  scope_sources:
    "docs:internal": [product-a, product-b]
  default_sources: [public-docs]
```

The following table shows how OpenCrane handles each request when `allow_anonymous` is `true`:

| Request | Result |
|---------|--------|
| With a valid bearer token | Authorized by its scopes, as usual. |
| Without a token, or with an invalid token | Allowed through as an anonymous caller with no scopes. The request resolves to `default_sources`. |

With this setup, one endpoint serves public documentation without a login and still gives authenticated callers their scoped access. A caller whose token has expired or is invalid gets the anonymous results, and the client does not ask the user to sign in again.

In this mode, `PUBLIC_URL` is not required, and the server does not publish OAuth discovery metadata. Clients therefore cannot find the IdP on their own. Give each authenticated client a token from your IdP, or configure the client with your IdP's authorization endpoint.

---

## Supply your own authentication with the `custom` mode

To use your own authentication code, set a hook on your `OpenCraneConfig` subclass.

> [!CAUTION]
> If neither hook is set, the `custom` type runs with no authentication and accepts every request. The same happens when OpenCrane does not load `.opencrane/extensions.py`, for example because the `extensions:` key is missing. OpenCrane only logs a warning. Set `token_verifier` or `auth_provider`, and check the startup log before you expose the server.

Set either `token_verifier` or `auth_provider` on your `OpenCraneConfig` subclass in `.opencrane/extensions.py`. OpenCrane loads that file only when `.opencrane/config.yaml` sets `extensions: extensions.py`, or when the `OPENCRANE_CONFIG` environment variable points to your config class. With the `extensions:` key, the class must be named `Config`. Then set `auth.type: custom` in the `.opencrane/config.yaml` file.

### Add a token verifier

Set `token_verifier` to an instance of a class that implements the `TokenVerifier` protocol of the MCP SDK (`mcp.server.auth.provider.TokenVerifier`). OpenCrane then runs as a resource server. This hook requires the `PUBLIC_URL` environment variable. The following example sets the hook:

```python
# .opencrane/extensions.py
from opencrane import OpenCraneConfig
from my_package.auth import MyTokenVerifier

class Config(OpenCraneConfig):
    token_verifier = MyTokenVerifier()
```

### Add an authorization server provider

Set `auth_provider` to an instance of a class that implements the `OAuthAuthorizationServerProvider` protocol of the MCP SDK. OpenCrane adds the OAuth authorization server routes and connects them to your provider. This hook also requires the `PUBLIC_URL` environment variable. The following example sets the hook:

```python
# .opencrane/extensions.py
from opencrane import OpenCraneConfig
from my_package.auth import MyAuthProvider

class Config(OpenCraneConfig):
    auth_provider = MyAuthProvider()
```

---

## Restrict sources by scope

The `scope_sources` key maps an OAuth scope name to the list of sources that the scope grants access to. The `default_sources` key sets the sources for callers that match no scope. Both keys are optional. `default_sources` works in every mode, including `none`. `scope_sources` works in every mode whose tokens carry scopes:

- `oauth`
- `custom`
- `local`, when `local.scopes` is set

The following example maps two scopes and sets the sources for callers that match neither:

```yaml
auth:
  type: oauth
  oidc:
    issuer: {ISSUER_URL}
    audience: {AUDIENCE}
  scope_sources:
    "docs:public":   [public-docs]
    "docs:internal": [product-a, product-b]
  default_sources: [public-docs]
```

Source names in `scope_sources` and `default_sources` must match names in the `sources:` block of the same `.opencrane/config.yaml` file. OpenCrane rejects unknown names at startup.

### How OpenCrane resolves the allowed sources

If neither `scope_sources` nor `default_sources` is set, OpenCrane does not restrict sources, and every caller can access all sources. This suits the `local` mode when every signed-in user can read every source. If only `default_sources` is set, every caller gets `default_sources`.

When either key is set, OpenCrane resolves the sources for each caller at search time, in the following order:

1. OpenCrane reads the caller's scopes from the access token.
2. It combines the sources of all matching scopes. A caller with several scopes sees all the sources that those scopes grant.
3. If no scope matches a key in `scope_sources`, OpenCrane falls back to `default_sources`. If `default_sources` is also absent, the caller sees no results.
4. When the client supplies the `source_names` parameter, OpenCrane keeps only the names that are also allowed. The client can narrow the set but never expand it.
5. If the resulting set is empty, OpenCrane returns zero results immediately.

---

## Authorize requests with custom middleware

If `scope_sources` cannot express your authorization logic, write a middleware. For example, the allowed sources might come from one of the following:

- An external service
- A custom header
- A JWT claim

Write the middleware as an Asynchronous Server Gateway Interface (ASGI) application that wraps the OpenCrane application. Add it to the `middleware` list on your `OpenCraneConfig` subclass in `.opencrane/extensions.py`. OpenCrane loads that file only when `.opencrane/config.yaml` sets `extensions: extensions.py`, or when the `OPENCRANE_CONFIG` environment variable points to your config class. The `opencrane serve --config` flag does not load the middleware or the auth hooks. Each entry in the list is a callable `(app) -> asgi_app`. Typically, the entry is a class that stores the wrapped application and implements `async __call__(self, scope, receive, send)`.

OpenCrane runs the entries on every endpoint, before it validates the token and before the tool handler. The first entry in the list runs first. A middleware declares the permitted source names for the request by calling `set_allowed_sources(...)`.

> [!CAUTION]
> `set_allowed_sources` replaces the source policy of the endpoint that serves the request, including an open endpoint. The following example grants `product-a` and `product-b` to every caller, including callers without a token on a `type: none` endpoint. Check the request path and the caller's token before you grant sources.

The following minimal example grants a fixed set of sources to every caller:

```python
# .opencrane/extensions.py
from opencrane import OpenCraneConfig
from opencrane.mcp.auth.runtime import set_allowed_sources

class SourceAuthorizer:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            set_allowed_sources(["product-a", "product-b"])   # pass [] to permit no sources
        await self.app(scope, receive, send)

class Config(OpenCraneConfig):
    middleware = [SourceAuthorizer]
```

At search time, a source set from `set_allowed_sources` replaces the endpoint's `scope_sources` and `default_sources` policy. The following rules apply:

- When a middleware sets an allowed set, OpenCrane uses that set. OpenCrane keeps only the `source_names` from the client that are in the set, so the client can narrow the set but never expand it.
- An empty allowed set returns zero results.
- If no middleware sets an override, OpenCrane uses the endpoint's `scope_sources` and `default_sources` policy.

By default, the `middleware` list is empty, and OpenCrane ships no built-in middleware.

### Resolve sources from an external permissions service

A common pattern has the following steps:

1. Read the caller's bearer token.
2. Ask an external service which sources the caller can see.
3. Cache the answer for each token.

With this pattern, you keep your authorization logic out of OpenCrane. A missing token or a failed lookup leaves the override unset. The request then falls back to the endpoint's `scope_sources` and `default_sources` policy.

> [!CAUTION]
> The fallback is restricted only if the endpoint sets `scope_sources` or `default_sources`. Without them, any request that the middleware does not resolve, such as a failed lookup, gives the caller every source. The same happens if OpenCrane does not load your `OpenCraneConfig` class. When neither `OPENCRANE_CONFIG` nor the `extensions:` key is set, or the file is missing, OpenCrane starts without the middleware and logs nothing. When the class fails to load, it logs a warning. Set `default_sources` on the endpoint before you rely on this middleware.

The following example implements this pattern:

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
                return None                      # do not cache failures
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
                    set_allowed_sources(names)   # authenticated caller: permitted sources
                # no token, or a failed lookup: override stays unset, scope_sources/default_sources policy applies
        await self.app(scope, receive, send)


class Config(OpenCraneConfig):
    middleware = [PermissionsAuthorizer]
```

Source names that the service returns must match the names in the `sources:` block of the same `.opencrane/config.yaml` file. OpenCrane ignores any returned name that has no matching source.

---

## Serve multiple endpoints with a named `auth:` map

By default, the `auth:` block is a single flat block and produces one MCP endpoint at `/mcp`. To serve several endpoints from one deployment, each with its own authentication, make `auth:` a map of named entries. Each key becomes an endpoint at `/mcp/{NAME}`. Each value is a full `auth:` block and takes the same keys as a flat block, except `allow_anonymous`.

> [!CAUTION]
> A `type: none` endpoint without `default_sources` serves every source to anyone, including sources meant for the authenticated endpoint. Always set `default_sources` on an open endpoint.

The following example serves an open endpoint and an authenticated endpoint:

```yaml
# .opencrane/config.yaml
auth:
  public:              # served at /mcp/public
    type: none         # open, no login
    default_sources:
      - handbook
      - glossary
  private:             # served at /mcp/private; the 401 challenge lets MCP clients find the IdP
    type: oauth        # requires a valid token
    oidc:
      issuer: https://idp.example.com
      audience: https://docs.example.com/mcp/private
```

This configuration runs one process that exposes both `/mcp/public` and `/mcp/private`. A common split is an open endpoint for public documentation and an authenticated endpoint for the additional content that a signed-in user can see.

Each endpoint has its own authorization policy. OpenCrane reads `scope_sources` and `default_sources` from that endpoint's entry. A custom middleware runs on every endpoint. It can read the request path, such as `/mcp/private`, to find the endpoint, and then authorize the request for that endpoint. For details on middleware, see [Authorize requests with custom middleware](#authorize-requests-with-custom-middleware).

For a `type: oauth` endpoint, OpenCrane publishes the protected-resource metadata (RFC 9728) and the `WWW-Authenticate` challenge under that endpoint's path. OpenCrane combines `PUBLIC_URL` with the endpoint path, for example `https://docs.example.com/mcp/private`, to form the OAuth resource identifier. Set `oidc.audience` to that same value.

The following rules and limits apply to named endpoints:

- A missing `auth:` block still means a single endpoint at `/mcp`. So does a flat block with a top-level `type:` or any other single-block key, such as `scope_sources`.
- Endpoint names can contain letters, digits, `-`, and `_`. A name must not match a reserved single-block key. Otherwise, OpenCrane reads the block as a single flat endpoint. The reserved keys are the following:
  - `type`
  - `allow_anonymous`
  - `scope_sources`
  - `default_sources`
  - `oidc`
  - `local`
- Named endpoints do not support `allow_anonymous`. If you set it on a named `oauth` entry, OpenCrane refuses to start. On other types, OpenCrane ignores it. For open access, add a `type: none` endpoint. For authenticated access, add a `type: oauth` endpoint without `allow_anonymous`.
- A deployment can expose at most one authenticated endpoint, together with any number of `type: none` endpoints. An authenticated endpoint is a `local` or `oauth` endpoint, or a `custom` endpoint with a `token_verifier` or `auth_provider` hook. A `custom` endpoint with neither hook is open. With two authenticated endpoints, OpenCrane refuses to start.
- Only a `type: none` endpoint with `default_sources` limits the sources it advertises, in its topic list and in the `source_names` enum of the `search_docs` tool. It advertises only those sources, so it does not expose the names of private topics served elsewhere. Every other endpoint advertises all sources. Advertising does not restrict results. The endpoint's source policy does.
- All endpoints share one readiness probe at `/health`.

---

## Access control over the stdio transport

The stdio transport is always unauthenticated. OAuth applies only to the HTTP transport. When you run `opencrane serve --transport stdio`, the server trusts the process environment for credentials, according to the MCP specification. OpenCrane does not run the `middleware` list on the stdio transport.

A stdio caller has no scopes, so the policy of the root endpoint at `/mcp` determines which sources the caller gets. The following rules apply:

- With a flat `auth:` block, the caller gets `default_sources`. If neither `scope_sources` nor `default_sources` is set, the caller gets all sources.
- With a named `auth:` map, there is no root endpoint, so the caller gets no results.

---

## Security notes

The following notes summarize the security behavior of authentication and authorization:

- `PUBLIC_URL` must use HTTPS in production. The SDK allows `http://localhost` for local development only.
- The `oauth` mode rejects tokens that were not issued for `oidc.audience`, which prevents confused-deputy attacks. The exception is `oidc.verify_audience: false`, which skips this check.
- In the `local` mode, credentials come only from environment variables, never from the `.opencrane/config.yaml` file. Token matching uses a constant-time comparison.
- OpenCrane enforces authorization by source on the server. The `source_names` parameter from the client can only narrow the set of accessible sources, never expand it.
- The source policy applies to `search_docs` only. The `get_yaml_definition`, `get_list_members`, and `get_table_members` tools return any chunk whose ID, `list_id`, or `table_id` the caller supplies, whatever its source.
- An open endpoint without `default_sources`, or `allow_anonymous: true` without a source policy, gives anyone every source.
- Misconfigured authentication fails closed. OpenCrane raises an error at startup and refuses to serve in the following cases:
  - A missing `PUBLIC_URL`
  - Unknown source names
  - A missing `opencrane[auth]` extra
  - `allow_anonymous` on a named `oauth` endpoint
  - More than one authenticated endpoint
- Some problems do not stop the server. OpenCrane logs a warning and serves without the protection in the following cases:
  - OpenCrane cannot parse `.opencrane/config.yaml`, so it treats `auth` as `none`.
  - A `custom` endpoint has no hook.
  - OpenCrane cannot load your `OpenCraneConfig` class, so it starts without the middleware.
- If neither `OPENCRANE_CONFIG` nor the `extensions:` key is set, OpenCrane starts without the middleware and the auth hooks. Only a `custom` endpoint logs a warning.
