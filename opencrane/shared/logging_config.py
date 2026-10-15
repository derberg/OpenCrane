import logging
import os
import sys
from pathlib import Path

LOG_LEVEL_ENV = 'LOG_LEVEL'
_VALID_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
_warned_values: set[str] = set()
_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# `opencrane fetch` appends its log to this file.
FETCH_LOG_FILE = Path('.opencrane') / 'fetch_docs.log'


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


def _add_file_handler(log_file):
    """Append the root log to ``log_file`` once, creating its directory."""
    log_path = Path(log_file).resolve()
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == str(log_path):
            return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, mode='a')
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)


def setup_logging(level=None, log_file=None):
    """Setup logging configuration for the application.

    Without an explicit ``level``, the level comes from LOG_LEVEL (default INFO).
    The log always goes to stderr. With ``log_file``, it is also appended to
    that file. Without it, no file is created.
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
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stderr)]
    )
    if log_file is not None:
        _add_file_handler(log_file)
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


# Set up stderr logging on import. No file is written here: importing
# opencrane must not create files in the working directory.
setup_logging()
