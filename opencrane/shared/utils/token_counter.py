"""Token counting utility using tiktoken."""

import tiktoken
import yaml
from typing import Union, Dict, List
from opencrane.shared.config import get_config


def get_token_count(text: Union[str, Dict, List]) -> int:
    """Count tokens in text using the configured tokenizer.

    Args:
        text: The text, dict, or list to count tokens for.
              Dicts and lists are converted to YAML first.

    Returns:
        Number of tokens.
    """
    # Convert dict/list to YAML string for token counting
    if isinstance(text, (dict, list)):
        text = yaml.dump(text, default_flow_style=False, allow_unicode=True)
    
    config = get_config()
    encoding = tiktoken.get_encoding(config.token_encoding)
    return len(encoding.encode(text))


def get_tokenizer():
    """Get the configured tokenizer encoding."""
    config = get_config()
    return tiktoken.get_encoding(config.token_encoding)