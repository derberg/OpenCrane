"""Resolve the embedding settings of a container image build.

The generated Dockerfile runs ``python3 -m opencrane.container_env`` in its
``settings`` stage. The command writes a shell file that the model download
stage, the index stage and the runtime entrypoint source, so the model in the
image is the model that the index records and the server loads.

The settings come from the build args, read like the server reads its env
(``opencrane.shared.config``), and from the header of
``.opencrane/embeddings.json``, which ``opencrane index`` records in the
collection:

- ``EMBEDDING_MODEL``: the recorded model. An explicit build arg must match it,
  because the server refuses to start when its env differs from the index. An
  empty build arg counts as not set.
- ``EMBEDDING_QUERY_PROMPT``: written only when the build sets it. It must match
  the recorded query prompt, if the embeddings file records one.
- ``EMBEDDING_TRUST_REMOTE_CODE`` and ``RERANKER_TRUST_REMOTE_CODE``: resolved
  with ``resolve_trust_remote_code``, so the download and the server agree.
- ``EMBEDDING_DTYPE`` and ``EMBEDDING_DEVICE``: written only when the build sets
  them.

Each line of the file sets its variable only when the variable is unset, so a
value given at run time, for example ``docker run -e``, still wins.
"""

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Dict, Optional

from opencrane.shared.config import Config, resolve_trust_remote_code

# EmbeddingsFile serializes its scalar fields before the ``embeddings`` list,
# so a short read of the file holds them.
_HEADER_BYTES = 64 * 1024
_EMBEDDINGS_KEY = '"embeddings"'

# Runtime-only settings, forwarded only when the build sets them.
_FORWARDED_IF_SET = ("EMBEDDING_DTYPE", "EMBEDDING_DEVICE")


class ContainerEnvError(Exception):
    """The build cannot determine consistent embedding settings."""


def read_embeddings_header(path: Path) -> Optional[Dict]:
    """Return the scalar fields of an embeddings file, reading only its start.

    Returns ``None`` when the file does not exist or its start holds no
    complete header before the ``embeddings`` list.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            start = f.read(_HEADER_BYTES)
    except FileNotFoundError:
        return None
    end = start.find(_EMBEDDINGS_KEY)
    if end < 0:
        return None
    try:
        return json.loads(start[:end].rstrip().rstrip(",") + "}")
    except json.JSONDecodeError:
        return None


def _bool(value: bool) -> str:
    return "true" if value else "false"


def build_settings(embeddings_path: Path) -> Dict[str, str]:
    """Return the variables the image sets, from the build args in the env.

    Raises:
        ContainerEnvError: no model can be determined, or a build arg differs
            from the value that the embeddings file records.
        ValueError: a build arg has an invalid value (from ``Config``).
    """
    config = Config()
    header = read_embeddings_header(embeddings_path) or {}
    recorded_model = header.get("model") or None
    arg_model = os.getenv("EMBEDDING_MODEL") or None

    if arg_model and recorded_model and arg_model != recorded_model:
        raise ContainerEnvError(
            f"EMBEDDING_MODEL is {arg_model!r} but {embeddings_path} was built with "
            f"{recorded_model!r}, and the server refuses to serve an index with another "
            "model. Unset EMBEDDING_MODEL, or run 'opencrane embed --force' with the new model."
        )
    model = arg_model or recorded_model
    if not model:
        raise ContainerEnvError(
            f"Cannot determine the embedding model: the EMBEDDING_MODEL build arg is "
            f"empty and {embeddings_path} is missing or has no model field. Run "
            "'opencrane embed' before the build, or pass "
            "--build-arg EMBEDDING_MODEL={MODEL_ID}."
        )

    settings = {
        "EMBEDDING_MODEL": model,
        "EMBEDDING_TRUST_REMOTE_CODE": _bool(
            resolve_trust_remote_code(model, config.embedding_trust_remote_code)
        ),
    }

    query_prompt = config.embedding_query_prompt
    if query_prompt is not None:
        if "query_prompt" in header and header["query_prompt"] != query_prompt:
            raise ContainerEnvError(
                f"EMBEDDING_QUERY_PROMPT is {query_prompt!r} but {embeddings_path} records "
                f"{header['query_prompt']!r}, and the server refuses to serve an index with "
                "another query prompt. Unset EMBEDDING_QUERY_PROMPT, or run "
                "'opencrane embed' with the new prompt."
            )
        settings["EMBEDDING_QUERY_PROMPT"] = query_prompt

    for name in _FORWARDED_IF_SET:
        if os.getenv(name):
            settings[name] = os.environ[name]

    if config.reranker_model:
        settings["RERANKER_TRUST_REMOTE_CODE"] = _bool(
            resolve_trust_remote_code(config.reranker_model, config.reranker_trust_remote_code)
        )
    return settings


def render_env_file(settings: Dict[str, str]) -> str:
    """Render *settings* as POSIX shell that sets each variable only when unset."""
    lines = [
        f'if [ -z "${{{name}+x}}" ]; then {name}={shlex.quote(value)}; fi; export {name}'
        for name, value in settings.items()
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    """Write the env file: ``python -m opencrane.container_env <embeddings.json> <out>``."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m opencrane.container_env <embeddings.json> <env-file>", file=sys.stderr)
        return 2
    embeddings_path, out_path = Path(args[0]), Path(args[1])
    try:
        settings = build_settings(embeddings_path)
    except (ContainerEnvError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_env_file(settings), encoding="utf-8")
    for name, value in settings.items():
        print(f"{name}={value!r}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
