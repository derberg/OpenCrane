"""Tests for OpenCraneConfig base class (opencrane/config.py).

Covers the section-anchor extension point: the ``generic`` default slug, the
``section_anchor_style`` selector (including ``none`` and unknown styles), and
custom ``section_anchor_for`` overrides.
"""

import pytest

from opencrane.config import ANCHOR_STYLE_BUILDERS, OpenCraneConfig


@pytest.mark.unit
def test_default_style_is_generic():
    assert OpenCraneConfig().section_anchor_style == "generic"


@pytest.mark.unit
def test_generic_registry_is_present():
    assert "generic" in ANCHOR_STYLE_BUILDERS


@pytest.mark.unit
def test_generic_anchor_slugifies_heading():
    assert OpenCraneConfig().section_anchor_for("Who We Serve") == "who-we-serve"


@pytest.mark.unit
def test_generic_anchor_strips_emoji_and_symbols():
    # GitBook slugs "✅ Eligibility Requirements" as "eligibility-requirements".
    c = OpenCraneConfig()
    assert c.section_anchor_for("✅ Eligibility Requirements") == "eligibility-requirements"


@pytest.mark.unit
def test_no_heading_returns_none():
    assert OpenCraneConfig().section_anchor_for(None) is None


@pytest.mark.unit
def test_style_none_disables_anchors():
    c = OpenCraneConfig()
    c.section_anchor_style = "none"
    assert c.section_anchor_for("Who We Serve") is None


@pytest.mark.unit
def test_unknown_style_returns_none():
    c = OpenCraneConfig()
    c.section_anchor_style = "does-not-exist"
    assert c.section_anchor_for("Who We Serve") is None


@pytest.mark.unit
def test_custom_override_takes_precedence():
    class C(OpenCraneConfig):
        def section_anchor_for(self, heading):
            return heading.strip().lower().replace(" ", "_") if heading else None

    assert C().section_anchor_for("Legal Status") == "legal_status"
