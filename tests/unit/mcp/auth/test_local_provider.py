"""Unit tests for the local-mode self-hosted OAuth provider and login form.

OpenCrane validates credentials LOCALLY (no downstream API), so these tests never
touch the network. TTL behaviour is driven through an injected ``now`` clock.
"""

import pytest
from pydantic import AnyUrl

from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull

from opencrane.mcp.auth import (
    OpenCraneAuthProvider,
    load_local_credentials,
    render_login_form,
    verify_credentials,
)
from opencrane.mcp.auth.config_model import AuthConfigError


def _client(client_id: str = "client-1") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        redirect_uris=[AnyUrl("https://client.example/callback")],
        client_id=client_id,
    )


def _params(
    *,
    scopes: list[str] | None = None,
    state: str | None = "state-xyz",
    redirect: str = "https://client.example/callback",
) -> AuthorizationParams:
    return AuthorizationParams(
        state=state,
        scopes=scopes,
        code_challenge="challenge-abc",
        redirect_uri=AnyUrl(redirect),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )


def _token_provider(monkeypatch, *, tokens="secret-token", scopes=("docs:public",)):
    monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", tokens)
    return OpenCraneAuthProvider(method="token", scopes=scopes)


def _password_provider(
    monkeypatch, *, user="admin", password="hunter2", scopes=("docs:public",)
):
    monkeypatch.setenv("OPENCRANE_LOGIN_USER", user)
    monkeypatch.setenv("OPENCRANE_LOGIN_PASS", password)
    return OpenCraneAuthProvider(method="password", scopes=scopes)


# --------------------------------------------------------------------------- #
# load_local_credentials — fail-closed loader
# --------------------------------------------------------------------------- #
class TestLoadLocalCredentials:
    def test_token_reads_comma_split_env(self, monkeypatch):
        monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "a, b ,c")
        assert load_local_credentials("token") == {"a", "b", "c"}

    def test_token_single(self, monkeypatch):
        monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "solo")
        assert load_local_credentials("token") == {"solo"}

    def test_token_missing_raises(self, monkeypatch):
        monkeypatch.delenv("OPENCRANE_ACCESS_TOKEN", raising=False)
        with pytest.raises(AuthConfigError, match="OPENCRANE_ACCESS_TOKEN"):
            load_local_credentials("token")

    def test_token_empty_raises(self, monkeypatch):
        monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "   ,  ")
        with pytest.raises(AuthConfigError, match="OPENCRANE_ACCESS_TOKEN"):
            load_local_credentials("token")

    def test_password_reads_user_and_pass(self, monkeypatch):
        monkeypatch.setenv("OPENCRANE_LOGIN_USER", "admin")
        monkeypatch.setenv("OPENCRANE_LOGIN_PASS", "hunter2")
        assert load_local_credentials("password") == ("admin", "hunter2")

    def test_password_missing_user_raises(self, monkeypatch):
        monkeypatch.delenv("OPENCRANE_LOGIN_USER", raising=False)
        monkeypatch.setenv("OPENCRANE_LOGIN_PASS", "hunter2")
        with pytest.raises(AuthConfigError, match="OPENCRANE_LOGIN_USER"):
            load_local_credentials("password")

    def test_password_missing_pass_raises(self, monkeypatch):
        monkeypatch.setenv("OPENCRANE_LOGIN_USER", "admin")
        monkeypatch.delenv("OPENCRANE_LOGIN_PASS", raising=False)
        with pytest.raises(AuthConfigError, match="OPENCRANE_LOGIN_PASS"):
            load_local_credentials("password")

    def test_password_empty_pass_raises(self, monkeypatch):
        monkeypatch.setenv("OPENCRANE_LOGIN_USER", "admin")
        monkeypatch.setenv("OPENCRANE_LOGIN_PASS", "")
        with pytest.raises(AuthConfigError, match="OPENCRANE_LOGIN_PASS"):
            load_local_credentials("password")


# --------------------------------------------------------------------------- #
# verify_credentials — constant-time compare
# --------------------------------------------------------------------------- #
class TestVerifyCredentials:
    def test_token_match(self):
        assert verify_credentials("token", "abc", expected={"abc", "def"}) is True

    def test_token_no_match(self):
        assert verify_credentials("token", "zzz", expected={"abc"}) is False

    def test_token_empty_submitted(self):
        assert verify_credentials("token", "", expected={"abc"}) is False

    def test_password_match(self):
        assert (
            verify_credentials(
                "password", ("admin", "pw"), expected=("admin", "pw")
            )
            is True
        )

    def test_password_wrong_pass(self):
        assert (
            verify_credentials(
                "password", ("admin", "bad"), expected=("admin", "pw")
            )
            is False
        )

    def test_password_wrong_user(self):
        assert (
            verify_credentials(
                "password", ("mallory", "pw"), expected=("admin", "pw")
            )
            is False
        )


# --------------------------------------------------------------------------- #
# render_login_form — HTML escaping + per-method fields
# --------------------------------------------------------------------------- #
class TestRenderLoginForm:
    def test_token_form_has_single_token_field(self):
        html_out = render_login_form("rid-1", "token")
        assert 'name="token"' in html_out
        assert 'type="password"' in html_out
        assert 'name="username"' not in html_out
        assert 'name="password"' not in html_out

    def test_password_form_has_user_and_password_fields(self):
        html_out = render_login_form("rid-1", "password")
        assert 'name="username"' in html_out
        assert 'name="password"' in html_out
        assert 'name="token"' not in html_out

    def test_form_posts_request_id_to_login(self):
        html_out = render_login_form("rid-1", "token")
        assert 'action="/login"' in html_out
        assert 'name="request_id"' in html_out
        assert 'value="rid-1"' in html_out

    def test_request_id_is_escaped(self):
        html_out = render_login_form('"><script>alert(1)</script>', "token")
        assert "<script>alert(1)</script>" not in html_out
        assert "&lt;script&gt;" in html_out

    def test_error_is_escaped_and_rendered(self):
        html_out = render_login_form("rid-1", "token", error="<b>bad</b> & wrong")
        assert "<b>bad</b>" not in html_out
        assert "&lt;b&gt;bad&lt;/b&gt; &amp; wrong" in html_out

    def test_no_error_block_when_error_none(self):
        html_out = render_login_form("rid-1", "token")
        assert 'role="alert"' not in html_out


# --------------------------------------------------------------------------- #
# register_client / get_client
# --------------------------------------------------------------------------- #
class TestClientRegistration:
    @pytest.mark.anyio
    async def test_register_and_get(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        client = _client("known")
        await provider.register_client(client)
        assert await provider.get_client("known") is client

    @pytest.mark.anyio
    async def test_get_unknown_returns_none(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        assert await provider.get_client("nope") is None

    @pytest.mark.anyio
    async def test_register_generates_id_when_missing(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        client = OAuthClientInformationFull(
            redirect_uris=[AnyUrl("https://client.example/callback")],
            client_id="",
        )
        await provider.register_client(client)
        assert client.client_id
        assert await provider.get_client(client.client_id) is client


# --------------------------------------------------------------------------- #
# authorize — stores pending, returns /login redirect
# --------------------------------------------------------------------------- #
class TestAuthorize:
    @pytest.mark.anyio
    async def test_returns_login_path_with_request_id(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        redirect = await provider.authorize(_client(), _params())
        assert redirect.startswith("/login?request_id=")

    @pytest.mark.anyio
    async def test_stores_pending_entry(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        redirect = await provider.authorize(_client("cid"), _params(state="s1"))
        request_id = redirect.split("request_id=", 1)[1]
        pending = provider._pending[request_id]
        assert pending.client_id == "cid"
        assert pending.state == "s1"
        assert pending.redirect_uri == "https://client.example/callback"
        assert pending.code_challenge == "challenge-abc"

    @pytest.mark.anyio
    async def test_none_scopes_stored_as_empty_list(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        redirect = await provider.authorize(_client(), _params(scopes=None))
        request_id = redirect.split("request_id=", 1)[1]
        assert provider._pending[request_id].scopes == []


# --------------------------------------------------------------------------- #
# complete_login
# --------------------------------------------------------------------------- #
class TestCompleteLogin:
    @pytest.mark.anyio
    async def test_valid_token_returns_redirect_with_code_and_state(self, monkeypatch):
        provider = _token_provider(monkeypatch, tokens="secret-token")
        redirect = await provider.authorize(_client(), _params(state="st"))
        request_id = redirect.split("request_id=", 1)[1]

        result = provider.complete_login(request_id, "secret-token")
        assert result.startswith("https://client.example/callback?")
        assert "code=" in result
        assert "state=st" in result

    @pytest.mark.anyio
    async def test_valid_password_returns_code(self, monkeypatch):
        provider = _password_provider(monkeypatch, user="admin", password="pw")
        redirect = await provider.authorize(_client(), _params())
        request_id = redirect.split("request_id=", 1)[1]

        result = provider.complete_login(request_id, ("admin", "pw"))
        assert "code=" in result

    @pytest.mark.anyio
    async def test_invalid_token_raises_valueerror(self, monkeypatch):
        provider = _token_provider(monkeypatch, tokens="secret-token")
        redirect = await provider.authorize(_client(), _params())
        request_id = redirect.split("request_id=", 1)[1]
        with pytest.raises(ValueError, match="Invalid credentials"):
            provider.complete_login(request_id, "wrong")

    @pytest.mark.anyio
    async def test_invalid_password_raises_valueerror(self, monkeypatch):
        provider = _password_provider(monkeypatch, user="admin", password="pw")
        redirect = await provider.authorize(_client(), _params())
        request_id = redirect.split("request_id=", 1)[1]
        with pytest.raises(ValueError, match="Invalid credentials"):
            provider.complete_login(request_id, ("admin", "bad"))

    @pytest.mark.anyio
    async def test_unknown_request_id_raises_valueerror(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        with pytest.raises(ValueError, match="expired"):
            provider.complete_login("does-not-exist", "secret-token")

    @pytest.mark.anyio
    async def test_pending_consumed_after_success(self, monkeypatch):
        provider = _token_provider(monkeypatch, tokens="secret-token")
        redirect = await provider.authorize(_client(), _params())
        request_id = redirect.split("request_id=", 1)[1]
        provider.complete_login(request_id, "secret-token")
        assert request_id not in provider._pending


# --------------------------------------------------------------------------- #
# authorization code lifecycle — single use, TTL, scopes
# --------------------------------------------------------------------------- #
class TestAuthorizationCode:
    @pytest.mark.anyio
    async def test_load_returns_code_with_granted_scopes(self, monkeypatch):
        provider = _token_provider(
            monkeypatch, tokens="secret-token", scopes=("docs:public", "docs:internal")
        )
        client = _client()
        redirect = await provider.authorize(client, _params())
        request_id = redirect.split("request_id=", 1)[1]
        result = provider.complete_login(request_id, "secret-token")
        code = result.split("code=", 1)[1].split("&", 1)[0]

        loaded = await provider.load_authorization_code(client, code)
        assert loaded is not None
        assert loaded.code == code
        assert loaded.scopes == ["docs:public", "docs:internal"]

    @pytest.mark.anyio
    async def test_load_unknown_code_returns_none(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        assert await provider.load_authorization_code(_client(), "nope") is None

    @pytest.mark.anyio
    async def test_load_wrong_client_returns_none(self, monkeypatch):
        provider = _token_provider(monkeypatch, tokens="secret-token")
        redirect = await provider.authorize(_client("cid-a"), _params())
        request_id = redirect.split("request_id=", 1)[1]
        result = provider.complete_login(request_id, "secret-token")
        code = result.split("code=", 1)[1].split("&", 1)[0]
        assert await provider.load_authorization_code(_client("cid-b"), code) is None

    @pytest.mark.anyio
    async def test_load_expired_code_returns_none(self, monkeypatch):
        clock = {"t": 1000.0}
        monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "secret-token")
        provider = OpenCraneAuthProvider(
            method="token", scopes=("docs:public",), now=lambda: clock["t"]
        )
        client = _client()
        redirect = await provider.authorize(client, _params())
        request_id = redirect.split("request_id=", 1)[1]
        result = provider.complete_login(request_id, "secret-token")
        code = result.split("code=", 1)[1].split("&", 1)[0]

        clock["t"] += 3600  # far beyond TTL
        assert await provider.load_authorization_code(client, code) is None

    @pytest.mark.anyio
    async def test_exchange_returns_token_with_scopes_and_stores(self, monkeypatch):
        provider = _token_provider(monkeypatch, tokens="secret-token", scopes=("docs:public",))
        client = _client()
        redirect = await provider.authorize(client, _params())
        request_id = redirect.split("request_id=", 1)[1]
        result = provider.complete_login(request_id, "secret-token")
        code = result.split("code=", 1)[1].split("&", 1)[0]

        loaded = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, loaded)
        assert token.access_token
        assert token.token_type == "Bearer"
        assert token.scope == "docs:public"

        access = await provider.load_access_token(token.access_token)
        assert access is not None
        assert access.scopes == ["docs:public"]

    @pytest.mark.anyio
    async def test_exchange_is_single_use(self, monkeypatch):
        provider = _token_provider(monkeypatch, tokens="secret-token")
        client = _client()
        redirect = await provider.authorize(client, _params())
        request_id = redirect.split("request_id=", 1)[1]
        result = provider.complete_login(request_id, "secret-token")
        code = result.split("code=", 1)[1].split("&", 1)[0]

        loaded = await provider.load_authorization_code(client, code)
        await provider.exchange_authorization_code(client, loaded)
        with pytest.raises(TokenError):
            await provider.exchange_authorization_code(client, loaded)

    @pytest.mark.anyio
    async def test_exchange_expired_code_raises(self, monkeypatch):
        clock = {"t": 1000.0}
        monkeypatch.setenv("OPENCRANE_ACCESS_TOKEN", "secret-token")
        provider = OpenCraneAuthProvider(
            method="token", scopes=("docs:public",), now=lambda: clock["t"]
        )
        client = _client()
        redirect = await provider.authorize(client, _params())
        request_id = redirect.split("request_id=", 1)[1]
        result = provider.complete_login(request_id, "secret-token")
        code = result.split("code=", 1)[1].split("&", 1)[0]
        loaded = await provider.load_authorization_code(client, code)

        clock["t"] += 3600
        with pytest.raises(TokenError):
            await provider.exchange_authorization_code(client, loaded)

    @pytest.mark.anyio
    async def test_exchange_no_scopes_yields_none_scope(self, monkeypatch):
        provider = _token_provider(monkeypatch, tokens="secret-token", scopes=())
        client = _client()
        redirect = await provider.authorize(client, _params())
        request_id = redirect.split("request_id=", 1)[1]
        result = provider.complete_login(request_id, "secret-token")
        code = result.split("code=", 1)[1].split("&", 1)[0]
        loaded = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, loaded)
        assert token.scope is None


# --------------------------------------------------------------------------- #
# access token — presence only
# --------------------------------------------------------------------------- #
class TestAccessToken:
    @pytest.mark.anyio
    async def test_unknown_token_returns_none(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        assert await provider.load_access_token("never-issued") is None

    @pytest.mark.anyio
    async def test_empty_token_returns_none(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        assert await provider.load_access_token("") is None


# --------------------------------------------------------------------------- #
# refresh tokens — unsupported
# --------------------------------------------------------------------------- #
class TestRefreshTokens:
    @pytest.mark.anyio
    async def test_load_refresh_returns_none(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        assert await provider.load_refresh_token(_client(), "rt") is None

    @pytest.mark.anyio
    async def test_exchange_refresh_raises(self, monkeypatch):
        provider = _token_provider(monkeypatch)
        from mcp.server.auth.provider import RefreshToken

        rt = RefreshToken(token="rt", client_id="client-1", scopes=[])
        with pytest.raises(TokenError):
            await provider.exchange_refresh_token(_client(), rt, [])


# --------------------------------------------------------------------------- #
# revoke_token
# --------------------------------------------------------------------------- #
class TestRevokeToken:
    @pytest.mark.anyio
    async def test_revoke_drops_stored_access_token(self, monkeypatch):
        provider = _token_provider(monkeypatch, tokens="secret-token")
        client = _client()
        redirect = await provider.authorize(client, _params())
        request_id = redirect.split("request_id=", 1)[1]
        result = provider.complete_login(request_id, "secret-token")
        code = result.split("code=", 1)[1].split("&", 1)[0]
        loaded = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, loaded)

        from mcp.server.auth.provider import AccessToken

        access = AccessToken(token=token.access_token, client_id="x", scopes=[])
        await provider.revoke_token(access)
        assert await provider.load_access_token(token.access_token) is None

    @pytest.mark.anyio
    async def test_revoke_missing_token_attr_is_noop(self, monkeypatch):
        provider = _token_provider(monkeypatch)

        class _NoToken:
            token = None

        await provider.revoke_token(_NoToken())  # must not raise
