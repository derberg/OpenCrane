"""Tests for routing declared blocks and chunking text from inside them."""

import logging
from pathlib import Path

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.shared.models.chunk import register_metadata_keys

URL = "https://github.com/org/repo/blob/main/a.md"


def _body(text: str, tag: str) -> str:
    """The text between the opening and the closing tag lines of a block."""
    lines = text.split("\n")
    return "\n".join(line for line in lines if not line.strip().startswith((f"<{tag}", f"</{tag}")))


class Wrapper(ProcessingStrategy):
    """Sends the body of its block through chunk_text and tags the chunks."""

    block_tags = ("Wrap",)
    metadata_keys = {"wrap_label": "Label of the Wrap block."}

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        chunks = self.chunk_text(_body(node.text, "Wrap"), node, source_file)
        for chunk in chunks:
            chunk.metadata["wrap_label"] = "W"
        return chunks


class Inner(ProcessingStrategy):
    """Records the inner block it gets and emits nothing."""

    block_tags = ("details",)
    seen: list = []

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        Inner.seen.append(node.text)
        return []


class Echo(ProcessingStrategy):
    """Sends its whole block back, which would loop without a limit."""

    block_tags = ("Echo",)

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        return self.chunk_text(node.text, node, source_file)


class Silent(ProcessingStrategy):
    """Declares a block and returns nothing for it."""

    block_tags = ("Silent",)

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        return []


class Sloppy(ProcessingStrategy):
    """Adds a metadata key it never declared."""

    block_tags = ("Sloppy",)

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        chunks = self.chunk_text(_body(node.text, "Sloppy"), node, source_file)
        for chunk in chunks:
            chunk.metadata["undeclared_key"] = "x"
        return chunks


def _config(*strategies, last=False):
    class Config(OpenCraneConfig):
        chunking_strategies = (
            [*OpenCraneConfig.chunking_strategies, *strategies] if last
            else [*strategies, *OpenCraneConfig.chunking_strategies]
        )
    return Config()


@pytest.fixture(autouse=True)
def _reset():
    Inner.seen = []
    yield
    register_metadata_keys({})


def _chunks(tmp_path, body, config):
    f = tmp_path / "llms-full.txt"
    f.write_text(f"### {URL}\n\n# Page\n\n## Install\n\nIntro text for the install section.\n\n{body}\n", encoding="utf-8")
    return FileProcessor(config).process_file(f)


_WRAP = "<Wrap>\n\n- first item\n- second item\n\n```bash\nrun it\n```\n\n</Wrap>"


def test_block_routed_to_declaring_strategy_listed_last(tmp_path):
    chunks = _chunks(tmp_path, _WRAP, _config(Wrapper(), last=True))
    wrapped = [c for c in chunks if c.metadata.get("wrap_label") == "W"]
    assert {c.chunk_type for c in wrapped} == {"list_item", "code_snippet"}


def test_fallthrough_when_declaring_strategy_returns_nothing(tmp_path):
    chunks = _chunks(tmp_path, "<Silent>\n\nSilent block text that is long enough.\n\n</Silent>", _config(Silent()))
    assert any("Silent block text" in c.content for c in chunks)


def test_chunk_text_splits_list_and_code(tmp_path):
    chunks = _chunks(tmp_path, _WRAP, _config(Wrapper()))
    wrapped = [c for c in chunks if c.metadata.get("wrap_label") == "W"]
    assert [c.chunk_type for c in wrapped] == ["list_item", "list_item", "code_snippet"]
    assert all(c._in_block for c in wrapped)
    assert not any(c._in_block for c in chunks if c not in wrapped)


def test_chunk_text_keeps_parent_headings_and_url(tmp_path):
    chunks = _chunks(tmp_path, _WRAP, _config(Wrapper()))
    items = [c for c in chunks if c.chunk_type == "list_item"]
    assert items[0].metadata["breadcrumb_path"] == "Page > Install"
    assert all(c.metadata.get("source_url") == URL for c in items)


def test_nested_other_tag_found_by_chunk_text(tmp_path):
    body = "<Wrap>\n\nOuter text.\n\n<details>\ninner body\n</details>\n\n</Wrap>"
    _chunks(tmp_path, body, _config(Wrapper(), Inner()))
    assert Inner.seen == ["<details>\ninner body\n</details>"]


def test_nesting_limit_stops_recursion(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        chunks = _chunks(tmp_path, "<Echo>\n\nEcho block text that is long enough.\n\n</Echo>", _config(Echo()))
    assert any("Echo block text" in c.content for c in chunks)
    warnings = [r for r in caplog.records if "Echo" in r.getMessage() and r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_undeclared_prose_key_from_wrapper_raises(tmp_path):
    with pytest.raises(ValueError, match="Sloppy.*undeclared_key"):
        _chunks(tmp_path, "<Sloppy>\n\nSloppy block text that is long enough.\n\n</Sloppy>", _config(Sloppy()))


def test_chunk_text_without_processor_raises():
    class Plain:
        text = "x"

    with pytest.raises(RuntimeError):
        Wrapper().chunk_text("x", Plain(), Path("f"))
