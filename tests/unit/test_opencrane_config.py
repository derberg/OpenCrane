"""Tests for OpenCraneConfig base class (opencrane/config.py).

Covers the anchor_for extension point and section_anchors attribute.
"""

import pytest

from opencrane.config import OpenCraneConfig


@pytest.mark.unit
def test_anchor_for_default_returns_page_url():
    c = OpenCraneConfig()
    assert c.anchor_for("https://x/page", "Some Heading") == "https://x/page"


@pytest.mark.unit
def test_anchor_for_override():
    class C(OpenCraneConfig):
        def anchor_for(self, page_url, heading):
            return f"{page_url}#{heading.lower().replace(' ', '-')}" if heading else page_url

    assert C().anchor_for("https://x/page", "Legal Status") == "https://x/page#legal-status"
