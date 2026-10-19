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
import re
import shlex
import sys
from pathlib import Path
from typing import Dict, Optional

from opencrane.shared.config import Config, resolve_trust_remote_code

# The header is read in chunks of this size. The ``embeddings`` list is skipped
# without decoding, so the read uses little memory whatever the file size and
# wherever the list sits among the keys.
_HEADER_BYTES = 64 * 1024
# A value other than the list, such as a prompt, is at most this many characters.
_MAX_VALUE_CHARS = 1024 * 1024
_EMBEDDINGS_KEY = "embeddings"
_DECODER = json.JSONDecoder()
_WHITESPACE = " \t\n\r"
# Characters that continue a number that raw_decode stopped before.
_NUMBER_TAIL = ".eE+-"
_STRUCTURE = re.compile(r'["\[\]{}]')
_STRING_END = re.compile(r'["\\]')

# Runtime-only settings, forwarded only when the build sets them.
_FORWARDED_IF_SET = ("EMBEDDING_DTYPE", "EMBEDDING_DEVICE")


class ContainerEnvError(Exception):
    """The build cannot determine consistent embedding settings."""


class _JsonStream:
    """Read a JSON document from a text file in chunks, a value at a time."""

    def __init__(self, f):
        self._file = f
        self._buf = ""
        self._pos = 0
        self._eof = False

    def _more(self) -> bool:
        """Append the next chunk of the file and drop the consumed text."""
        if self._eof:
            return False
        data = self._file.read(_HEADER_BYTES)
        if not data:
            self._eof = True
            return False
        self._buf = self._buf[self._pos:] + data
        self._pos = 0
        return True

    def peek(self) -> str:
        """Return the next character that is not whitespace, or ``""`` at the end."""
        while True:
            while self._pos < len(self._buf) and self._buf[self._pos] in _WHITESPACE:
                self._pos += 1
            if self._pos < len(self._buf):
                return self._buf[self._pos]
            if not self._more():
                return ""

    def expect(self, chars: str) -> str:
        """Consume the next character, which must be one of *chars*."""
        char = self.peek()
        if not char or char not in chars:
            raise ValueError(f"expected one of {chars!r}, found {char or 'end of file'!r}")
        self._pos += 1
        return char

    def _more_for_value(self) -> bool:
        """Read more text for a value, up to a bound, so a broken file is not read whole."""
        return len(self._buf) - self._pos < _MAX_VALUE_CHARS and self._more()

    def value(self):
        """Decode the next value. Values other than the ``embeddings`` list are short."""
        self.peek()
        while True:
            try:
                value, end = _DECODER.raw_decode(self._buf, self._pos)
            except json.JSONDecodeError:
                if self._more_for_value():
                    continue
                raise
            # A number can continue in the next chunk. A chunk that ends in "-1." or
            # "2e" decodes as -1 or 2 and leaves the tail, so decode it again with
            # more text.
            at_end = end == len(self._buf)
            if (at_end or self._buf[end] in _NUMBER_TAIL) and self._more_for_value():
                continue
            self._pos = end
            return value

    def skip_value(self) -> None:
        """Consume the next value without decoding it."""
        if self.peek() not in ("[", "{"):
            self.value()
            return
        depth = 0
        in_string = False
        while True:
            pattern = _STRING_END if in_string else _STRUCTURE
            match = pattern.search(self._buf, self._pos)
            if match is None:
                self._pos = len(self._buf)
                if not self._more():
                    raise ValueError("unexpected end of file")
                continue
            char = match.group()
            self._pos = match.end()
            if char == "\\":
                # The escaped character can be in the next chunk.
                if self._pos == len(self._buf) and not self._more():
                    raise ValueError("unexpected end of file")
                self._pos += 1
            elif char == '"':
                in_string = not in_string
            elif char in "[{":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return


def _parse_header(f) -> Dict:
    stream = _JsonStream(f)
    stream.expect("{")
    header = {}
    if stream.peek() == "}":
        return header
    while True:
        if stream.peek() != '"':
            raise ValueError("expected a key")
        key = stream.value()
        stream.expect(":")
        if key == _EMBEDDINGS_KEY:
            stream.skip_value()
        else:
            header[key] = stream.value()
        if stream.expect(",}") == "}":
            return header


def read_embeddings_header(path: Path) -> Optional[Dict]:
    """Return the top-level fields of an embeddings file, without the ``embeddings`` list.

    The fields can come in any order. The list is skipped without decoding it.
    Returns ``None`` when the file does not exist.

    Raises:
        ContainerEnvError: the file exists but cannot be parsed.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _parse_header(f)
    except FileNotFoundError:
        return None
    except ValueError as exc:
        # json.JSONDecodeError and UnicodeDecodeError are ValueErrors too
        raise ContainerEnvError(
            f"{path} exists but cannot be parsed as an embeddings file: {exc}. "
            "Run 'opencrane embed --force' to write it again."
        ) from exc


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
    header = read_embeddings_header(embeddings_path)
    fields = header or {}
    recorded_model = fields.get("model") or None
    arg_model = os.getenv("EMBEDDING_MODEL") or None

    if arg_model and recorded_model and arg_model != recorded_model:
        raise ContainerEnvError(
            f"EMBEDDING_MODEL is {arg_model!r} but {embeddings_path} was built with "
            f"{recorded_model!r}, and the server refuses to serve an index with another "
            "model. Unset EMBEDDING_MODEL, or run 'opencrane embed --force' with the new model."
        )
    model = arg_model or recorded_model
    if not model:
        problem = "is missing" if header is None else "has no model field"
        raise ContainerEnvError(
            f"Cannot determine the embedding model: the EMBEDDING_MODEL build arg is "
            f"empty and {embeddings_path} {problem}. Run "
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
        if "query_prompt" in fields and fields["query_prompt"] != query_prompt:
            raise ContainerEnvError(
                f"EMBEDDING_QUERY_PROMPT is {query_prompt!r} but {embeddings_path} records "
                f"{fields['query_prompt']!r}, and the server refuses to serve an index with "
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
