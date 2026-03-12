import pytest
from unittest.mock import patch
from opencrane.shared.config import Config, get_config


class TestConfig:
    """Unit tests for configuration management."""

    @patch.dict('os.environ', {}, clear=True)
    def test_config_defaults(self):
        """Test Config with default values."""
        config = Config()
        assert config.org_name == ""
        assert str(config.target_dir) == "external-sources"
        assert config.docs_topic == "documentation"
        assert config.schedule_timezone == "UTC"
        assert config.github_token == ""

    @patch.dict('os.environ', {
        'ORG_NAME': 'test_org',
        'TARGET_DIR': '/tmp/docs',
        'DOCS_TOPIC': 'docs',
        'SCHEDULE_TZ': 'EST',
        'GITHUB_TOKEN': 'test_token'
    })
    def test_config_with_env_vars(self):
        """Test Config with environment variables set."""
        config = Config()
        assert config.org_name == "test_org"
        assert str(config.target_dir) == "/tmp/docs"
        assert config.docs_topic == "docs"
        assert config.schedule_timezone == "EST"
        assert config.github_token == "test_token"

    def test_get_config(self):
        """Test get_config returns a Config instance."""
        config = get_config()
        assert isinstance(config, Config)

    @patch.dict('os.environ', {}, clear=True)
    def test_fetch_repo_default_empty(self):
        """Test fetch_repo defaults to empty string."""
        config = Config()
        assert config.fetch_repo == ""

    @patch.dict('os.environ', {'FETCH_REPO': 'external-sources/cgw'})
    def test_fetch_repo_from_env(self):
        """Test fetch_repo is read from FETCH_REPO env var."""
        config = Config()
        assert config.fetch_repo == "external-sources/cgw"