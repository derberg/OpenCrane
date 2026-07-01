"""Unit tests for MCP auth access policies."""

import pytest
from opencrane.mcp.auth.policies import AllowAllPolicy, ScopeSourcesPolicy, build_access_policy
from opencrane.mcp.auth.config_model import AuthConfig


class TestAllowAllPolicy:
    """Tests for AllowAllPolicy."""

    def test_passes_none_through(self):
        """AllowAllPolicy returns None when requested is None."""
        policy = AllowAllPolicy()
        assert policy.authorize((), None) is None

    def test_passes_list_through_unchanged(self):
        """AllowAllPolicy returns the same list when requested is a list."""
        policy = AllowAllPolicy()
        requested = ["source-a", "source-b"]
        result = policy.authorize(("docs:public",), requested)
        assert result == ["source-a", "source-b"]

    def test_passes_empty_list_through(self):
        """AllowAllPolicy returns an empty list when requested is []."""
        policy = AllowAllPolicy()
        assert policy.authorize((), []) == []

    def test_ignores_scopes(self):
        """AllowAllPolicy ignores scopes entirely."""
        policy = AllowAllPolicy()
        result = policy.authorize(("scope:a", "scope:b"), ["x"])
        assert result == ["x"]


class TestScopeSourcesPolicyUnion:
    """Tests for ScopeSourcesPolicy scope-to-sources union logic."""

    def test_union_across_multiple_scopes(self):
        """Caller holding two scopes gets the union of their sources, sorted."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw",), "docs:b": ("tsr", "cgw")},
            default_sources=(),
        )
        result = policy.authorize(("docs:a", "docs:b"), None)
        assert result == ["cgw", "tsr"]

    def test_single_scope_match(self):
        """A single matching scope returns only its sources."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw",), "docs:b": ("tsr",)},
            default_sources=(),
        )
        result = policy.authorize(("docs:a",), None)
        assert result == ["cgw"]

    def test_unknown_scope_contributes_nothing(self):
        """A scope the caller holds that is not a key contributes nothing to allowed."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw",)},
            default_sources=(),
        )
        # "other" is not a key; only "docs:a" matches
        result = policy.authorize(("docs:a", "other"), None)
        assert result == ["cgw"]

    def test_no_matching_scope_falls_back_to_default(self):
        """When no caller scope matches, falls back to default_sources."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw",)},
            default_sources=("cennso-glossary",),
        )
        result = policy.authorize(("other",), None)
        assert result == ["cennso-glossary"]

    def test_no_matching_scope_empty_default_returns_empty_list(self):
        """No matching scope + empty default_sources returns []."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw",)},
            default_sources=(),
        )
        result = policy.authorize(("other",), None)
        assert result == []

    def test_empty_scopes_tuple_falls_back_to_default(self):
        """Empty caller scopes trigger default fallback."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw",)},
            default_sources=("fallback-source",),
        )
        result = policy.authorize((), None)
        assert result == ["fallback-source"]

    def test_result_is_sorted(self):
        """Allowed sources are returned in sorted order."""
        policy = ScopeSourcesPolicy(
            scope_sources={"s": ("zzz", "aaa", "mmm")},
            default_sources=(),
        )
        result = policy.authorize(("s",), None)
        assert result == ["aaa", "mmm", "zzz"]


class TestScopeSourcesPolicyIntersection:
    """Tests for ScopeSourcesPolicy intersection (requested filtering)."""

    def test_requested_narrows_to_allowed(self):
        """Requested sources outside allowed are dropped; only intersection returned."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw", "tsr")},
            default_sources=(),
        )
        result = policy.authorize(("docs:a",), ["tsr", "other-source"])
        assert result == ["tsr"]

    def test_all_requested_allowed(self):
        """When all requested are in allowed, all are returned sorted."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw", "tsr")},
            default_sources=(),
        )
        result = policy.authorize(("docs:a",), ["tsr", "cgw"])
        assert result == ["cgw", "tsr"]

    def test_all_requested_disallowed_returns_empty_list(self):
        """When requested sources are all outside allowed, returns []."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw",)},
            default_sources=(),
        )
        result = policy.authorize(("docs:a",), ["forbidden-source"])
        assert result == []

    def test_empty_requested_list_returns_empty_list(self):
        """Empty requested list returns [] (not the full allowed set)."""
        policy = ScopeSourcesPolicy(
            scope_sources={"docs:a": ("cgw",)},
            default_sources=(),
        )
        result = policy.authorize(("docs:a",), [])
        assert result == []

    def test_requested_preserves_order_from_sorted(self):
        """Intersection result is sorted, not order-of-requested."""
        policy = ScopeSourcesPolicy(
            scope_sources={"s": ("aaa", "bbb", "ccc")},
            default_sources=(),
        )
        result = policy.authorize(("s",), ["ccc", "aaa"])
        assert result == ["aaa", "ccc"]


class TestBuildAccessPolicy:
    """Tests for build_access_policy factory."""

    def test_returns_allow_all_when_neither_set(self):
        """Returns AllowAllPolicy when scope_sources and default_sources are both empty."""
        cfg = AuthConfig()  # default: empty scope_sources, empty default_sources
        policy = build_access_policy(cfg)
        assert isinstance(policy, AllowAllPolicy)

    def test_returns_scope_sources_policy_when_scope_sources_set(self):
        """Returns ScopeSourcesPolicy when scope_sources is non-empty."""
        cfg = AuthConfig(scope_sources={"docs:a": ("cgw",)}, default_sources=())
        policy = build_access_policy(cfg)
        assert isinstance(policy, ScopeSourcesPolicy)

    def test_returns_scope_sources_policy_when_only_default_sources_set(self):
        """Returns ScopeSourcesPolicy when only default_sources is non-empty."""
        cfg = AuthConfig(scope_sources={}, default_sources=("cennso-glossary",))
        policy = build_access_policy(cfg)
        assert isinstance(policy, ScopeSourcesPolicy)

    def test_returns_scope_sources_policy_when_both_set(self):
        """Returns ScopeSourcesPolicy when both scope_sources and default_sources set."""
        cfg = AuthConfig(
            scope_sources={"docs:a": ("cgw",)},
            default_sources=("cennso-glossary",),
        )
        policy = build_access_policy(cfg)
        assert isinstance(policy, ScopeSourcesPolicy)

    def test_allow_all_policy_wired_correctly(self):
        """AllowAllPolicy returned by factory passes requests through unchanged."""
        cfg = AuthConfig()
        policy = build_access_policy(cfg)
        assert policy.authorize(("any:scope",), ["src"]) == ["src"]
        assert policy.authorize((), None) is None

    def test_scope_sources_policy_wired_correctly(self):
        """ScopeSourcesPolicy returned by factory applies scope_sources correctly."""
        cfg = AuthConfig(scope_sources={"docs:a": ("cgw",)}, default_sources=())
        policy = build_access_policy(cfg)
        assert policy.authorize(("docs:a",), None) == ["cgw"]
        assert policy.authorize(("other",), None) == []
