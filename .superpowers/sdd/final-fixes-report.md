# Final-Fixes Wave Report

## Change #1 — Security: Require exp/aud/iss in JWT validation

**File:** `opencrane/mcp/auth/oauth_verifier.py`
**Change:** Added `options={"require": ["exp", "aud", "iss"]}` to the `jwt.decode(...)` call in `JwtTokenVerifier.verify_token`.

**TDD:**
- RED: `test_missing_exp_claim_returns_none` added to `tests/unit/mcp/auth/test_oauth_verifier.py`. A validly-signed token with correct `aud`/`iss` but no `exp` claim returned `AccessToken` (not `None`) — test FAILED before the fix.
- GREEN: After adding the `options={"require": [...]}` argument, `jwt.decode` raises `MissingRequiredClaimError` (a `PyJWTError` subclass) for tokens missing any of `exp`, `aud`, or `iss`, causing `verify_token` to return `None` — test PASSED.

---

## Change #2 — Safety: Warn when custom resolves to open

**File:** `opencrane/mcp/auth/wiring.py`
**Change:** Added `import logging` and `logger = logging.getLogger(__name__)`. In the `custom` branch, when neither `token_verifier` nor `auth_provider` is set, `logger.warning(...)` is emitted before returning `{}` to make clear the server is running UNAUTHENTICATED despite `auth.type: custom`.

The existing test for the "neither hook → {}" custom branch covers this new line. No return value changed.

---

## Change #3 — Doc nit: Fix stale docstring

**File:** `opencrane/mcp/auth/policies.py`
**Change:** `ScopeSourcesPolicy.authorize` docstring updated: "When `requested` is truthy" → "When `requested` is not None" to match the actual `if requested is not None:` guard in the code.

No logic change.

---

## Change #4 — Doc nit: Clarify intentional scope-ignore

**File:** `opencrane/mcp/auth/local_provider.py`
**Change:** Added a two-line comment above `scopes=list(self._scopes)` in `complete_login` explaining that client-requested scopes are intentionally ignored — the operator-configured scopes are granted so the client cannot self-elevate.

No logic change.

---

## Full Gate Result

```
TOTAL   5120   0   100%
1020 passed, 3 skipped, 174 warnings in 150.34s
Coverage 100% meets 100% threshold
EXIT=0
```
