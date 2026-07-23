from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import os


@dataclass
class Config:
    org_name: str = field(default_factory=lambda: os.getenv("ORG_NAME", ""))
    repo_name: str = field(default_factory=lambda: os.getenv("REPO_NAME", ""))
    target_dir: Path = field(default_factory=lambda: Path(os.getenv("TARGET_DIR", ".opencrane/sources")))
    docs_topic: str = field(default_factory=lambda: os.getenv("DOCS_TOPIC", "documentation"))
    # Organizations that should have auto-discovery enabled (comma-separated)
    auto_discovery_orgs: List[str] = field(default_factory=lambda: [
        org.strip() for org in os.getenv("AUTO_DISCOVERY_ORGS", "").split(",") if org.strip()
    ])
    # Multiple source directories for LLMs generation (comma-separated if via env var)
    sources_dirs: List[Path] = field(default_factory=lambda: [
        Path(p.strip()) for p in os.getenv("AI_DOCS_SOURCES_DIRS", "").split(",") if p.strip()
    ])
    schedule_timezone: str = field(default_factory=lambda: os.getenv("SCHEDULE_TZ", "UTC"))
    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    token_source_dir: Path = field(default_factory=lambda: Path(os.getenv("TOKEN_SOURCE_DIR", ".opencrane/llmstxt")))
    token_output_file: Path = field(default_factory=lambda: Path(os.getenv("TOKEN_OUTPUT_FILE", ".opencrane/llmstxt/README.md")))
    token_encoding: str = field(default_factory=lambda: os.getenv("TOKEN_ENCODING", "cl100k_base"))
    # Chunker configuration
    yaml_crd_threshold_tokens: int = field(default_factory=lambda: int(os.getenv("YAML_CRD_THRESHOLD_TOKENS", "1000")))
    yaml_tree_chunking_enabled: bool = field(default_factory=lambda: os.getenv("YAML_TREE_CHUNKING_ENABLED", "true").lower() == "true")
    default_output_format: str = field(default_factory=lambda: os.getenv("DEFAULT_OUTPUT_FORMAT", "json"))
    # Milvus configuration
    milvus_host: str = field(default_factory=lambda: os.getenv("MILVUS_HOST", "localhost"))
    milvus_port: int = field(default_factory=lambda: int(os.getenv("MILVUS_PORT", "19530")))
    milvus_collection: str = field(default_factory=lambda: os.getenv("MILVUS_COLLECTION", "ai_docs_chunks_v1"))
    milvus_insert_batch_size: int = field(default_factory=lambda: int(os.getenv("MILVUS_INSERT_BATCH_SIZE", "2000")))
    # Embedding configuration
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5"))
    # Search configuration
    hybrid_alpha: float = field(default_factory=lambda: float(os.getenv("HYBRID_ALPHA", "0.6")))
    # Source mapping file configuration
    mapping_file: Path = field(default_factory=lambda: Path(os.getenv("MAPPING_FILE", ".opencrane/config.yaml")))
    # Optional: restrict fetch to a single repo by path key (e.g. "external-sources/cgw")
    fetch_repo: str = field(default_factory=lambda: os.getenv("FETCH_REPO", ""))


def get_config() -> Config:
    """Get configuration from environment variables."""
    return Config()


__all__ = ["Config", "get_config"]