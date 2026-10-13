import logging
import os
import sys
from pathlib import Path

LOG_LEVEL_ENV = 'LOG_LEVEL'
_VALID_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
_warned_values: set[str] = set()


def _parse_log_level(default):
    """Return ``(level, invalid_value)`` for the LOG_LEVEL variable."""
    raw = os.environ.get(LOG_LEVEL_ENV, '').strip()
    if not raw:
        return default, None
    name = raw.upper()
    if name in _VALID_LEVELS:
        return getattr(logging, name), None
    return default, raw


def _warn_invalid(raw, default):
    """Log one warning per process for each invalid LOG_LEVEL value."""
    if raw is None or raw in _warned_values:
        return
    _warned_values.add(raw)
    logging.getLogger(__name__).warning(
        "Ignoring invalid %s=%r; expected one of %s. Using %s.",
        LOG_LEVEL_ENV, raw, ', '.join(_VALID_LEVELS),
        logging.getLevelName(default),
    )


def resolve_log_level(default=logging.INFO):
    """Return the log level named by the LOG_LEVEL environment variable.

    The name is case-insensitive. An unset or empty variable returns
    ``default``. An unknown name also returns ``default`` and logs one
    warning per process for that value.
    """
    level, invalid = _parse_log_level(default)
    _warn_invalid(invalid, default)
    return level


def setup_logging(level=None):
    """Setup logging configuration for the application.

    Without an explicit ``level``, the level comes from LOG_LEVEL (default INFO).
    """
    invalid = None
    # Only an explicit level or a valid LOG_LEVEL overrides the root level of
    # a host application that configured logging before importing opencrane.
    explicit = level is not None
    if level is None:
        level, invalid = _parse_log_level(None)
        explicit = level is not None
        if level is None:
            level = logging.INFO
    log_path = Path('.opencrane/fetch_docs.log')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_path, mode='a')
        ]
    )
    # basicConfig is a no-op once the root logger has handlers, so set the
    # level directly; a later call then still applies its level.
    if explicit:
        logging.getLogger().setLevel(level)
    # Warn after the handlers exist, so the warning uses the log format.
    _warn_invalid(invalid, logging.INFO)
    # Suppress noisy loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    # Configure specific loggers for new modules
    logging.getLogger('opencrane.services.embeddings').setLevel(level)
    logging.getLogger('opencrane.services.milvus_client').setLevel(level)
    logging.getLogger('opencrane.mcp_server').setLevel(level)


# Setup default logging
setup_logging()
