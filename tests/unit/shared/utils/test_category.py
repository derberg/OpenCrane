"""Tests for category inference utility."""
from pathlib import Path
from opencrane.shared.utils.category import infer_category_from_path


def test_infer_category_product_by_default():
    """Test that paths not matching guidelines patterns return 'product'."""
    assert infer_category_from_path("external-sources/extension-cdm/README.md") == "product"
    assert infer_category_from_path("docs/chunking.md") == "product"
    assert infer_category_from_path("random/path/file.md") == "product"


def test_infer_category_guidelines_from_content_guidelines():
    """Test that content-guidelines/ paths return 'guidelines'."""
    assert infer_category_from_path("content-guidelines/README.md") == "guidelines"
    assert infer_category_from_path("content-guidelines/writing-guidelines/style.md") == "guidelines"


def test_infer_category_guidelines_from_llmstxt_others():
    """Test that llmstxt/others/ paths return 'product' (no longer in guidelines patterns)."""
    assert infer_category_from_path("llmstxt/others/likec4/docs.md") == "product"
    assert infer_category_from_path("llmstxt/others/tool.md") == "product"


def test_infer_category_with_pathlib():
    """Test that Path objects are handled correctly."""
    assert infer_category_from_path(Path("content-guidelines/templates/api.md")) == "guidelines"
    assert infer_category_from_path(Path("external-sources/extension-5g/README.md")) == "product"


def test_infer_category_with_absolute_paths():
    """Test that absolute paths work correctly."""
    assert infer_category_from_path("/workspace/content-guidelines/guide.md") == "guidelines"
    assert infer_category_from_path("/workspace/llmstxt/others/tool.md") == "product"
    assert infer_category_from_path("/workspace/external-sources/ext/README.md") == "product"
