import logging
import sys
from pathlib import Path


def setup_logging(level=logging.INFO):
    """Setup logging configuration for the application."""
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
    # Suppress noisy loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    # Configure specific loggers for new modules
    logging.getLogger('opencrane.services.embeddings').setLevel(level)
    logging.getLogger('opencrane.services.milvus_client').setLevel(level)
    logging.getLogger('opencrane.mcp_server').setLevel(level)


# Setup default logging
setup_logging()