"""Resolve the embedding settings of a container image build.

The generated Dockerfile runs ``python3 -m opencrane.container_env`` in its
``settings`` stage. The command writes a shell file that the index stage, the
model download stage and the runtime entrypoint source, so all three use the
same embedding model, prompts and ``trust_remote_code`` settings.

The embedding model comes from the ``EMBEDDING_MODEL`` build arg when it is
set, otherwise from the ``model`` field of ``.opencrane/embeddings.json``,
which records the model that ``opencrane embed`` used. An empty model or
``trust_remote_code`` build arg counts as not set. A prompt build arg that is
set, even to an empty value, is forwarded.

Each line of the file sets its variable only when the variable is unset, so a
value given at run time, for example ``docker run -e EMBEDDING_MODEL=...``,
still wins.
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Dict, Optional

# Model ID prefixes whose models ship their own code. Same rule as the
# *_TRUST_REMOTE_CODE "auto" setting of the server.
REMOTE_CODE_MODEL_PREFIXES = ("nomic-ai/",)

# EmbeddingsFile serializes ``model`` as its first field, so the header holds it.
_HEADER_BYTES = 64 * 1024
_MODEL_FIELD = re.compile(r'"model"\s*:\s*("(?:[^"\\]|\\.)*")')

# Prompts are forwarded only when the build sets them, even to an empty value,
# which means no prompt. An unset prompt lets the server apply its default.
_FORWARDED_PROMPTS = ("EMBEDDING_QUERY_PROMPT", "EMBEDDING_DOCUMENT_PROMPT")


class ContainerEnvError(Exception):
    """The build cannot determine its embedding settings."""


def read_embeddings_model(path: Path) -> Optional[str]:
    """Return the ``model`` field of an embeddings file, reading only its header.

    Returns ``None`` when the file does not exist or its header has no model.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            header = f.read(_HEADER_BYTES)
    except FileNotFoundError:
        return None
    match = _MODEL_FIELD.search(header)
    if not match:
        return None
    return json.loads(match.group(1)) or None


def resolve_embedding_model(build_arg: str, embeddings_path: Path) -> str:
    """Return the build arg when set, otherwise the model in the embeddings file."""
    recorded = read_embeddings_model(embeddings_path)
    if build_arg:
        if recorded and recorded != build_arg:
            print(
                f"WARNING: EMBEDDING_MODEL={build_arg} differs from the model "
                f"{recorded} that created {embeddings_path}. The server embeds "
                "queries with a model that did not embed the documents.",
                file=sys.stderr,
            )
        return build_arg
    if recorded:
        return recorded
    raise ContainerEnvError(
        f"Cannot determine the embedding model: the EMBEDDING_MODEL build arg is "
        f"empty and {embeddings_path} is missing or has no model field. Run "
        "'opencrane embed' before the build, or pass "
        "--build-arg EMBEDDING_MODEL={MODEL_ID}."
    )


def resolve_trust_remote_code(model: str, setting: str, name: str = "EMBEDDING_TRUST_REMOTE_CODE") -> bool:
    """Return the ``trust_remote_code`` flag for *model*.

    An explicit true or false setting wins. When it is empty or ``auto``, only
    models with a prefix in ``REMOTE_CODE_MODEL_PREFIXES`` get ``True``. *name*
    is the variable that holds *setting*, for the error message.
    """
    value = setting.strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    if value in ("", "auto"):
        return model.startswith(REMOTE_CODE_MODEL_PREFIXES)
    raise ContainerEnvError(f"{name} must be true, false, or unset (auto), got {setting!r}")


def build_settings(env: Dict[str, str], embeddings_path: Path) -> Dict[str, str]:
    """Return the variables the image sets, from the build args in *env*."""
    model = resolve_embedding_model(env.get("EMBEDDING_MODEL", ""), embeddings_path)
    trust = resolve_trust_remote_code(model, env.get("EMBEDDING_TRUST_REMOTE_CODE", ""))
    settings = {
        "EMBEDDING_MODEL": model,
        "EMBEDDING_TRUST_REMOTE_CODE": "true" if trust else "false",
    }
    reranker = env.get("RERANKER_MODEL", "")
    if reranker:
        reranker_trust = resolve_trust_remote_code(
            reranker, env.get("RERANKER_TRUST_REMOTE_CODE", ""), "RERANKER_TRUST_REMOTE_CODE"
        )
        settings["RERANKER_TRUST_REMOTE_CODE"] = "true" if reranker_trust else "false"
    for name in _FORWARDED_PROMPTS:
        if name in env:
            settings[name] = env[name]
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
        settings = build_settings(dict(os.environ), embeddings_path)
    except ContainerEnvError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_env_file(settings), encoding="utf-8")
    for name, value in settings.items():
        print(f"{name}={value}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
