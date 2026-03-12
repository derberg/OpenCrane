"""Unit tests for logging configuration."""

import logging
import pytest
from unittest.mock import patch, mock_open
from opencrane.shared.logging_config import setup_logging


class TestLoggingConfig:
    """Test cases for logging setup."""

    @patch('logging.basicConfig')
    @patch('logging.FileHandler')
    @patch('logging.StreamHandler')
    def test_setup_logging(self, mock_stream, mock_file, mock_basic):
        """Test logging setup with default level."""
        setup_logging(logging.DEBUG)

        mock_basic.assert_called_once()
        call_kwargs = mock_basic.call_args[1]
        assert call_kwargs['level'] == logging.DEBUG
        assert 'handlers' in call_kwargs