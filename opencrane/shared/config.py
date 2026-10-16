from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import os

# Values accepted by EMBEDDING_DTYPE; the embedding service maps each to a torch dtype.
EMBEDDING_DTYPES = ("float32", "bfloat16", "float16")

# Model ID prefixes whose models ship custom modeling code and fail to load
# without trust_remote_code. Nomic Embed (v1, v1.5, v2) uses its own nomic_bert /
# NomicBert architecture. The *_TRUST_REMOTE_CODE "auto" setting trusts only these.
REMOTE_CODE_MODEL_PREFIXES = ("nomic-ai/",)


def _prompt_env(name: str) -> Optional[str]:
    """Read an embedding prompt from env, unescaping a literal ``\\n`` to a newline.

    Returns ``None`` when the variable is unset, so an explicit empty value
    ("no prompt") stays distinct from "use the model's default prompt".
    """
    value = os.getenv(name)
    return None if value is None else value.replace("\\n", "\n")


def _optional_bool_env(name: str) -> Optional[bool]:
    """Read a true/false env var; unset or empty means None (auto)."""
    value = os.getenv(name, "").strip().lower()
    if not value or value == "auto":
        return None
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    raise ValueError(f"{name} must be true, false, or unset (auto), got {value!r}")


def _int_env(name: str, default: int, minimum: int) -> int:
    """Read an integer env var that must be at least *minimum*."""
    raw = os.getenv(name, "").strip() or str(default)
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


def _dtype_env(name: str) -> str:
    """Read EMBEDDING_DTYPE, rejecting values outside EMBEDDING_DTYPES."""
    value = os.getenv(name, "").strip().lower() or "float32"
    if value not in EMBEDDING_DTYPES:
        raise ValueError(f"{name} must be one of {', '.join(EMBEDDING_DTYPES)}, got {value!r}")
    return value


def resolve_trust_remote_code(model_name: str, setting: Optional[bool]) -> bool:
    """Decide whether a model may run its own code.

    An explicit setting wins. Unset (None) trusts only models known to need
    remote code (REMOTE_CODE_MODEL_PREFIXES), so naming an arbitrary model does
    not run arbitrary code from it.
    """
    if setting is not None:
        return setting
    return model_name.startswith(REMOTE_CODE_MODEL_PREFIXES)


def remote_code_error(exc: Exception, trusted: bool, env_name: str) -> Optional[Exception]:
    """A clearer error for a model that failed to load because it needs remote code.

    Returns ``None`` when *exc* is not about remote code, or when remote code
    was already trusted, so the caller re-raises *exc* as is.
    """
    message = str(exc)
    if trusted or ("remote code" not in message.lower() and "trust_remote_code" not in message):
        return None
    return RuntimeError(
        f"{message}\nThe model runs its own code, which OpenCrane trusts only for known "
        f"models. If you trust this model, set {env_name}=true."
    )


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
    # Prose chunking: deepest heading level that starts a new chunk (3 = #, ##, ###)
    prose_split_heading_depth: int = field(default_factory=lambda: int(os.getenv("PROSE_SPLIT_HEADING_DEPTH", "3")))
    # Prose chunking: token cap per chunk; oversized sections split at paragraph/line boundaries (0 = off)
    prose_max_chunk_tokens: int = field(default_factory=lambda: int(os.getenv("PROSE_MAX_CHUNK_TOKENS", "0")))
    # Prose chunking: emit sections that hold only a heading instead of dropping them
    prose_keep_heading_only_sections: bool = field(default_factory=lambda: os.getenv("PROSE_KEEP_HEADING_ONLY_SECTIONS", "false").lower() == "true")
    default_output_format: str = field(default_factory=lambda: os.getenv("DEFAULT_OUTPUT_FORMAT", "json"))
    # Milvus configuration
    milvus_host: str = field(default_factory=lambda: os.getenv("MILVUS_HOST", "localhost"))
    milvus_port: int = field(default_factory=lambda: int(os.getenv("MILVUS_PORT", "19530")))
    milvus_collection: str = field(default_factory=lambda: os.getenv("MILVUS_COLLECTION", "ai_docs_chunks_v1"))
    milvus_insert_batch_size: int = field(default_factory=lambda: int(os.getenv("MILVUS_INSERT_BATCH_SIZE", "2000")))
    # Embedding configuration
    # An empty EMBEDDING_MODEL names no model, so it falls back to the default too.
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL") or "nomic-ai/nomic-embed-text-v1.5")
    # Task prompts for asymmetric embedding models. None (unset) = the model's
    # default, see shared/utils/embedding_prompts.py; empty = encode text as-is.
    # A literal backslash-n in the env value becomes a newline (for Qwen3-style templates).
    embedding_document_prompt: Optional[str] = field(default_factory=lambda: _prompt_env("EMBEDDING_DOCUMENT_PROMPT"))
    embedding_query_prompt: Optional[str] = field(default_factory=lambda: _prompt_env("EMBEDDING_QUERY_PROMPT"))
    # Weight dtype for the embedding model: float32, bfloat16 (about half the RAM), or float16
    embedding_dtype: str = field(default_factory=lambda: _dtype_env("EMBEDDING_DTYPE"))
    # Torch device for the embedding model. CPU by default, because MPS runs out of memory on macOS.
    embedding_device: str = field(default_factory=lambda: os.getenv("EMBEDDING_DEVICE", "").strip() or "cpu")
    embedding_batch_size: int = field(default_factory=lambda: _int_env("EMBEDDING_BATCH_SIZE", 8, 1))
    # Token cap per input (0 = the model's own maximum); bounds memory on long-context models
    embedding_max_seq_length: int = field(default_factory=lambda: _int_env("EMBEDDING_MAX_SEQ_LENGTH", 0, 0))
    # true / false / unset (auto: only models in REMOTE_CODE_MODEL_PREFIXES)
    embedding_trust_remote_code: Optional[bool] = field(default_factory=lambda: _optional_bool_env("EMBEDDING_TRUST_REMOTE_CODE"))
    # Search configuration
    hybrid_alpha: float = field(default_factory=lambda: float(os.getenv("HYBRID_ALPHA", "0.6")))
    # Results fetched per arm (semantic, keyword) before hybrid fusion; 0 = the requested limit
    hybrid_candidate_pool: int = field(default_factory=lambda: int(os.getenv("HYBRID_CANDIDATE_POOL", "0")))
    # Hybrid fusion method: "minmax" (min-max normalised alpha blend) or "rrf" (reciprocal rank fusion)
    hybrid_fusion: str = field(default_factory=lambda: os.getenv("HYBRID_FUSION", "minmax").strip().lower())
    # RRF smoothing constant k in 1 / (k + rank)
    hybrid_rrf_k: int = field(default_factory=lambda: int(os.getenv("HYBRID_RRF_K", "60")))
    # BM25 tokenizer: "simple" (split on non-alphanumerics) or "identifier" (keeps 5.4.1 / GTP-U intact)
    bm25_tokenizer: str = field(default_factory=lambda: os.getenv("BM25_TOKENIZER", "simple"))
    # Optional reranking stage: a sentence-transformers CrossEncoder model name
    # (unset = no reranker). RERANK_DEPTH is how many fused candidates are
    # fetched and passed to the reranker before cutting to the requested limit.
    reranker_model: str = field(default_factory=lambda: os.getenv("RERANKER_MODEL", ""))
    rerank_depth: int = field(default_factory=lambda: int(os.getenv("RERANK_DEPTH", "50")))
    # true / false / unset (auto: only models in REMOTE_CODE_MODEL_PREFIXES)
    reranker_trust_remote_code: Optional[bool] = field(default_factory=lambda: _optional_bool_env("RERANKER_TRUST_REMOTE_CODE"))
    # Source mapping file configuration
    mapping_file: Path = field(default_factory=lambda: Path(os.getenv("MAPPING_FILE", ".opencrane/config.yaml")))
    # Optional: restrict fetch to a single repo by path key (e.g. "external-sources/cgw")
    fetch_repo: str = field(default_factory=lambda: os.getenv("FETCH_REPO", ""))


def get_config() -> Config:
    """Get configuration from environment variables."""
    return Config()


__all__ = ["Config", "EMBEDDING_DTYPES", "REMOTE_CODE_MODEL_PREFIXES", "get_config", "resolve_trust_remote_code"]