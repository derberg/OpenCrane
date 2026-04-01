"""Pytest configuration for test isolation."""
import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import MagicMock
from opencrane.shared.config import get_config


# Session-level temp directory for mapping file
_session_temp_root = None


@pytest.fixture(scope="session", autouse=True)
def setup_session_temp_root():
    """Create a session-level temp directory for ROOT and copy test fixture mapping."""
    global _session_temp_root
    _session_temp_root = tempfile.mkdtemp()
    session_root = Path(_session_temp_root)
    
    # Get the mapping filename from config (default is .opencrane/config.yaml)
    config = get_config()
    mapping_filename = config.mapping_file.name
    
    # Copy test fixture mapping to temp location so tests can modify it without polluting the fixture
    test_fixture_mapping = Path(__file__).parent / "fixtures" / "test-mapping.yaml"
    temp_mapping = session_root / mapping_filename
    if test_fixture_mapping.exists():
        shutil.copy(test_fixture_mapping, temp_mapping)
    
    yield session_root
    # Cleanup after all tests
    shutil.rmtree(_session_temp_root, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_outputs(monkeypatch, setup_session_temp_root):
    """Isolate output directories and use temp copy of test fixture mapping to prevent writing to production files."""
    # Point MAPPING_FILE env var to temp copy of fixture (created in setup_session_temp_root)
    config = get_config()
    temp_mapping = setup_session_temp_root / config.mapping_file.name
    monkeypatch.setenv("MAPPING_FILE", str(temp_mapping))
    
    # Reset global state before each test
    monkeypatch.setattr('opencrane.rag.generate_llms_txt._source_mapping', None)
    monkeypatch.setattr('opencrane.mcp.server._keyword_service', None)
    monkeypatch.setattr('opencrane.mcp.server._chunk_index', None)
    monkeypatch.setattr('opencrane.mcp.server._milvus_service', None)
    monkeypatch.setattr('opencrane.mcp.server._embeddings_service', None)

    # Patch ROOT in generate_llms_txt to point to session temp directory
    monkeypatch.setattr('opencrane.rag.generate_llms_txt.ROOT', setup_session_temp_root)

    # Patch all global directory constants to point to temp
    monkeypatch.setattr('opencrane.rag.generate_llms_txt.SOURCES_BASE', setup_session_temp_root / "external-sources")
    monkeypatch.setattr('opencrane.rag.generate_llms_txt.LLMSTXT_BASE', setup_session_temp_root / "llmstxt")
    monkeypatch.setattr('opencrane.rag.generate_llms_txt.SOURCE_ROOT', setup_session_temp_root / "external-sources" / "product-docs")
    monkeypatch.setattr('opencrane.rag.generate_llms_txt.OUTPUT_ROOT', setup_session_temp_root / "llmstxt" / "product-docs")

    yield

    # Reset global state after each test
    monkeypatch.setattr('opencrane.rag.generate_llms_txt._source_mapping', None)
    monkeypatch.setattr('opencrane.mcp.server._keyword_service', None)
    monkeypatch.setattr('opencrane.mcp.server._chunk_index', None)
    monkeypatch.setattr('opencrane.mcp.server._milvus_service', None)
    monkeypatch.setattr('opencrane.mcp.server._embeddings_service', None)
