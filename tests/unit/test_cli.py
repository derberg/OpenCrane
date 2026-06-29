"""Tests for the OpenCrane CLI commands (opencrane/cli.py).

Covers every CLI command's success path, error handling, and the
``load_config`` / help-colorizing helpers. All underlying pipeline
functions (fetch, llms, chunk, embed, index, serve, etc.) are mocked so
no network, Milvus, embeddings/torch, or subprocess work happens.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

import opencrane.cli as cli
from opencrane.cli import main as cli_main


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# === load_config helper ===

@pytest.mark.unit
def test_load_config_base_when_no_arg_and_no_yaml(chdir_tmp):
    """No --config, no env var, no config.yaml -> base OpenCraneConfig."""
    from opencrane.config import OpenCraneConfig
    cfg = cli.load_config(None)
    assert isinstance(cfg, OpenCraneConfig)


@pytest.mark.unit
def test_load_config_from_env_var(monkeypatch, chdir_tmp):
    """OPENCRANE_CONFIG env var is used when --config is None."""
    monkeypatch.setenv("OPENCRANE_CONFIG", "opencrane.config:OpenCraneConfig")
    from opencrane.config import OpenCraneConfig
    cfg = cli.load_config(None)
    assert isinstance(cfg, OpenCraneConfig)


@pytest.mark.unit
def test_load_config_module_class_string(chdir_tmp):
    """module:Class form imports and instantiates the class."""
    from opencrane.config import OpenCraneConfig
    cfg = cli.load_config("opencrane.config:OpenCraneConfig")
    assert isinstance(cfg, OpenCraneConfig)


@pytest.mark.unit
def test_load_config_auto_discover_extensions(tmp_path, monkeypatch):
    """A config.yaml with an `extensions` key loads Config from that file."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("extensions: extensions.py\n")
    ext = opencrane_dir / "extensions.py"
    ext.write_text(
        "from opencrane.config import OpenCraneConfig\n"
        "class Config(OpenCraneConfig):\n"
        "    pass\n"
    )
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config(None)
    assert cfg.__class__.__name__ == "Config"


@pytest.mark.unit
def test_load_config_auto_discover_bad_yaml(tmp_path, monkeypatch):
    """Unparseable config.yaml is swallowed -> base config returned."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("::: not valid yaml :::\n[unclosed")
    monkeypatch.chdir(tmp_path)
    from opencrane.config import OpenCraneConfig
    cfg = cli.load_config(None)
    assert isinstance(cfg, OpenCraneConfig)


@pytest.mark.unit
def test_load_config_auto_discover_no_extensions_key(tmp_path, monkeypatch):
    """config.yaml without extensions key -> base config."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("sources: {}\n")
    monkeypatch.chdir(tmp_path)
    from opencrane.config import OpenCraneConfig
    cfg = cli.load_config(None)
    assert isinstance(cfg, OpenCraneConfig)


@pytest.mark.unit
def test_load_config_auto_discover_extensions_path_missing(tmp_path, monkeypatch):
    """extensions key points to a nonexistent file -> base config."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("extensions: nope.py\n")
    monkeypatch.chdir(tmp_path)
    from opencrane.config import OpenCraneConfig
    cfg = cli.load_config(None)
    assert isinstance(cfg, OpenCraneConfig)


@pytest.mark.unit
def test_load_config_from_file_path(tmp_path, monkeypatch):
    """A bare path (no colon) to an existing .py file loads its Config."""
    ext = tmp_path / "myext.py"
    ext.write_text(
        "from opencrane.config import OpenCraneConfig\n"
        "class Config(OpenCraneConfig):\n"
        "    pass\n"
    )
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config(str(ext))
    assert cfg.__class__.__name__ == "Config"


@pytest.mark.unit
def test_load_config_from_file_path_missing(tmp_path, monkeypatch):
    """A bare path that does not exist -> base config."""
    monkeypatch.chdir(tmp_path)
    from opencrane.config import OpenCraneConfig
    cfg = cli.load_config(str(tmp_path / "missing.py"))
    assert isinstance(cfg, OpenCraneConfig)


@pytest.mark.unit
def test_load_config_extensions_dir_already_on_syspath(tmp_path, monkeypatch):
    """When the extensions dir is already on sys.path, it is not re-inserted."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("extensions: extensions.py\n")
    ext = opencrane_dir / "extensions.py"
    ext.write_text(
        "from opencrane.config import OpenCraneConfig\n"
        "class Config(OpenCraneConfig):\n"
        "    pass\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(opencrane_dir.resolve()))
    cfg = cli.load_config(None)
    assert cfg.__class__.__name__ == "Config"


@pytest.mark.unit
def test_load_config_file_path_dir_already_on_syspath(tmp_path, monkeypatch):
    """Bare-path branch: dir already on sys.path is not re-inserted."""
    ext = tmp_path / "myext.py"
    ext.write_text(
        "from opencrane.config import OpenCraneConfig\n"
        "class Config(OpenCraneConfig):\n"
        "    pass\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path.resolve()))
    cfg = cli.load_config(str(ext))
    assert cfg.__class__.__name__ == "Config"


# === help colorizing (main group + a command) ===

@pytest.mark.unit
def test_main_help_colorized(runner):
    result = runner.invoke(cli_main, ["--help"], color=True)
    assert result.exit_code == 0
    assert "OpenCrane" in result.output
    assert "Commands" in result.output


@pytest.mark.unit
def test_command_help_colorized(runner):
    result = runner.invoke(cli_main, ["fetch", "--help"], color=True)
    assert result.exit_code == 0
    assert "Options" in result.output
    assert "--config" in result.output


@pytest.mark.unit
def test_version_option(runner):
    result = runner.invoke(cli_main, ["--version"])
    assert result.exit_code == 0


# === fetch ===

@pytest.mark.unit
def test_fetch_success(runner):
    cfg = MagicMock()
    cfg.auto_discovery_orgs = []
    with patch.object(cli, "load_config"), \
         patch("opencrane.shared.config.get_config", return_value=cfg), \
         patch("opencrane.rag.fetch_docs.main") as fetch_main:
        result = runner.invoke(cli_main, ["fetch"])
    assert result.exit_code == 0
    fetch_main.assert_called_once_with(config=cfg)


@pytest.mark.unit
def test_fetch_with_org_new(runner):
    cfg = MagicMock()
    cfg.auto_discovery_orgs = []
    with patch.object(cli, "load_config"), \
         patch("opencrane.shared.config.get_config", return_value=cfg), \
         patch("opencrane.rag.fetch_docs.main"):
        result = runner.invoke(cli_main, ["fetch", "--org", "myorg"])
    assert result.exit_code == 0
    assert cfg.org_name == "myorg"
    assert "myorg" in cfg.auto_discovery_orgs


@pytest.mark.unit
def test_fetch_with_org_already_present(runner):
    cfg = MagicMock()
    cfg.auto_discovery_orgs = ["myorg"]
    with patch.object(cli, "load_config"), \
         patch("opencrane.shared.config.get_config", return_value=cfg), \
         patch("opencrane.rag.fetch_docs.main"):
        result = runner.invoke(cli_main, ["fetch", "--org", "myorg"])
    assert result.exit_code == 0
    assert cfg.auto_discovery_orgs == ["myorg"]


@pytest.mark.unit
def test_fetch_with_source(runner):
    cfg = MagicMock()
    cfg.auto_discovery_orgs = []
    with patch.object(cli, "load_config"), \
         patch("opencrane.shared.config.get_config", return_value=cfg), \
         patch("opencrane.rag.fetch_docs.main"):
        result = runner.invoke(cli_main, ["fetch", "--source", "likec4,cgw"])
    assert result.exit_code == 0
    assert cfg.fetch_repo == "likec4,cgw"


@pytest.mark.unit
def test_fetch_error(runner):
    with patch.object(cli, "load_config", side_effect=Exception("boom")):
        result = runner.invoke(cli_main, ["fetch"])
    assert result.exit_code == 1
    assert "Error: boom" in result.output


# === llms ===

@pytest.mark.unit
def test_llms_success(runner):
    with patch.object(cli, "load_config", return_value=MagicMock()), \
         patch("opencrane.rag.generate_llms_txt.generate_outputs") as gen:
        result = runner.invoke(cli_main, ["llms"])
    assert result.exit_code == 0
    _, kwargs = gen.call_args
    assert kwargs["sources_dirs"] is None
    assert kwargs["llmstxt_dir"] is None
    assert kwargs["force"] is False


@pytest.mark.unit
def test_llms_with_options(runner):
    with patch.object(cli, "load_config", return_value=MagicMock()), \
         patch("opencrane.rag.generate_llms_txt.generate_outputs") as gen:
        result = runner.invoke(
            cli_main,
            ["llms", "--sources-dir", "a", "--sources-dir", "b",
             "--llmstxt-dir", "out", "--force"],
        )
    assert result.exit_code == 0
    _, kwargs = gen.call_args
    assert kwargs["sources_dirs"] == [Path("a"), Path("b")]
    assert kwargs["llmstxt_dir"] == Path("out")
    assert kwargs["force"] is True


@pytest.mark.unit
def test_llms_error(runner):
    with patch.object(cli, "load_config", side_effect=Exception("llms-fail")):
        result = runner.invoke(cli_main, ["llms"])
    assert result.exit_code == 1
    assert "Error: llms-fail" in result.output


# === chunk ===

@pytest.mark.unit
def test_chunk_success(runner):
    with patch.object(cli, "load_config", return_value=MagicMock()), \
         patch("opencrane.rag.chunker.main") as chunk_main:
        result = runner.invoke(cli_main, ["chunk"])
    assert result.exit_code == 0
    _, kwargs = chunk_main.call_args
    assert kwargs["llmstxt_dir"] is None
    assert kwargs["chunks_file"] is None


@pytest.mark.unit
def test_chunk_with_options(runner):
    with patch.object(cli, "load_config", return_value=MagicMock()), \
         patch("opencrane.rag.chunker.main") as chunk_main:
        result = runner.invoke(
            cli_main,
            ["chunk", "--llmstxt-dir", "ld", "--chunks-file", "cf", "--force"],
        )
    assert result.exit_code == 0
    _, kwargs = chunk_main.call_args
    assert kwargs["llmstxt_dir"] == Path("ld")
    assert kwargs["chunks_file"] == Path("cf")


@pytest.mark.unit
def test_chunk_error(runner):
    with patch.object(cli, "load_config", side_effect=Exception("chunk-fail")):
        result = runner.invoke(cli_main, ["chunk"])
    assert result.exit_code == 1
    assert "Error: chunk-fail" in result.output


# === embed ===

@pytest.mark.unit
def test_embed_success(runner):
    with patch.object(cli, "load_config"), \
         patch("opencrane.rag.generate_embeddings.main") as embed_main:
        result = runner.invoke(cli_main, ["embed"])
    assert result.exit_code == 0
    _, kwargs = embed_main.call_args
    assert kwargs["chunks_file"] is None
    assert kwargs["embeddings_file"] is None
    assert kwargs["force"] is False


@pytest.mark.unit
def test_embed_with_options(runner):
    with patch.object(cli, "load_config"), \
         patch("opencrane.rag.generate_embeddings.main") as embed_main:
        result = runner.invoke(
            cli_main,
            ["embed", "--chunks-file", "cf", "--embeddings-file", "ef", "--force"],
        )
    assert result.exit_code == 0
    _, kwargs = embed_main.call_args
    assert kwargs["chunks_file"] == Path("cf")
    assert kwargs["embeddings_file"] == Path("ef")
    assert kwargs["force"] is True


@pytest.mark.unit
def test_embed_error(runner):
    with patch.object(cli, "load_config", side_effect=Exception("embed-fail")):
        result = runner.invoke(cli_main, ["embed"])
    assert result.exit_code == 1
    assert "Error: embed-fail" in result.output


# === tokens ===

@pytest.mark.unit
def test_tokens_success(runner):
    fake_mod = MagicMock()
    with patch.dict(sys.modules, {"opencrane.rag.token_count": fake_mod}):
        result = runner.invoke(cli_main, ["tokens"])
    assert result.exit_code == 0
    _, kwargs = fake_mod.main.call_args
    assert kwargs["source_dir"] is None
    assert kwargs["output_file"] is None


@pytest.mark.unit
def test_tokens_with_options(runner):
    fake_mod = MagicMock()
    with patch.dict(sys.modules, {"opencrane.rag.token_count": fake_mod}):
        result = runner.invoke(
            cli_main, ["tokens", "--source-dir", "sd", "--output-file", "of"]
        )
    assert result.exit_code == 0
    _, kwargs = fake_mod.main.call_args
    assert kwargs["source_dir"] == Path("sd")
    assert kwargs["output_file"] == Path("of")


@pytest.mark.unit
def test_tokens_error(runner):
    fake_mod = MagicMock()
    fake_mod.main.side_effect = Exception("tok-fail")
    with patch.dict(sys.modules, {"opencrane.rag.token_count": fake_mod}):
        result = runner.invoke(cli_main, ["tokens"])
    assert result.exit_code == 1
    assert "Error: tok-fail" in result.output


# === index ===

@pytest.mark.unit
def test_index_success(runner):
    fake_mod = MagicMock()
    with patch.object(cli, "load_config"), \
         patch.dict(sys.modules, {"opencrane.mcp.init_vector_db": fake_mod}):
        result = runner.invoke(cli_main, ["index"])
    assert result.exit_code == 0
    fake_mod.main.assert_called_once_with()


@pytest.mark.unit
def test_index_error(runner):
    with patch.object(cli, "load_config", side_effect=Exception("index-fail")):
        result = runner.invoke(cli_main, ["index"])
    assert result.exit_code == 1
    assert "Error: index-fail" in result.output


# === serve ===

@pytest.mark.unit
def test_serve_stdio(runner):
    server_mod = MagicMock()
    with patch.object(cli, "load_config"), \
         patch("asyncio.run") as arun, \
         patch.dict(sys.modules, {"opencrane.mcp.server": server_mod}):
        result = runner.invoke(cli_main, ["serve"])
    assert result.exit_code == 0
    assert arun.called
    assert "stdio transport" in result.output


@pytest.mark.unit
def test_serve_http(runner, monkeypatch):
    monkeypatch.setenv("MCP_HTTP_PORT", "9999")
    http_mod = MagicMock()
    with patch.object(cli, "load_config"), \
         patch("asyncio.run") as arun, \
         patch.dict(sys.modules, {"opencrane.mcp.http_server": http_mod}):
        result = runner.invoke(cli_main, ["serve", "--transport", "http"])
    assert result.exit_code == 0
    assert arun.called
    assert "HTTP transport" in result.output
    assert "9999" in result.output


@pytest.mark.unit
def test_serve_error(runner):
    with patch.object(cli, "load_config", side_effect=Exception("serve-fail")):
        result = runner.invoke(cli_main, ["serve"])
    assert result.exit_code == 1
    assert "Error: serve-fail" in result.output


# === build ===

@pytest.mark.unit
def test_build_success(runner, tmp_path, monkeypatch):
    """Full build with llms-full.txt present -> runs all 5 steps."""
    monkeypatch.chdir(tmp_path)
    llmstxt = tmp_path / ".opencrane" / "llmstxt"
    llmstxt.mkdir(parents=True)
    (llmstxt / "llms-full.txt").write_text("content")

    index_mod = MagicMock()
    with patch.object(cli, "load_config", return_value=MagicMock()), \
         patch("opencrane.rag.fetch_docs.main") as fetch_main, \
         patch("opencrane.rag.generate_llms_txt.generate_outputs") as gen, \
         patch("opencrane.rag.chunker.main") as chunk_main, \
         patch("opencrane.rag.generate_embeddings.main") as embed_main, \
         patch.dict(sys.modules, {"opencrane.mcp.init_vector_db": index_mod}):
        result = runner.invoke(cli_main, ["build"])
    assert result.exit_code == 0
    assert "Build complete" in result.output
    fetch_main.assert_called_once()
    gen.assert_called_once()
    chunk_main.assert_called_once()
    embed_main.assert_called_once()
    index_mod.main.assert_called_once()


@pytest.mark.unit
def test_build_with_options(runner, tmp_path, monkeypatch):
    """When --llmstxt-dir is given and the file exists there, build completes."""
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "custom_llms"
    custom.mkdir()
    (custom / "llms-full.txt").write_text("content")

    index_mod = MagicMock()
    with patch.object(cli, "load_config", return_value=MagicMock()), \
         patch("opencrane.rag.fetch_docs.main"), \
         patch("opencrane.rag.generate_llms_txt.generate_outputs"), \
         patch("opencrane.rag.chunker.main") as chunk_main, \
         patch("opencrane.rag.generate_embeddings.main") as embed_main, \
         patch.dict(sys.modules, {"opencrane.mcp.init_vector_db": index_mod}):
        result = runner.invoke(
            cli_main,
            ["build",
             "--sources-dir", "s1",
             "--llmstxt-dir", str(custom),
             "--chunks-file", "cf",
             "--embeddings-file", "ef"],
        )
    assert result.exit_code == 0
    _, ck = chunk_main.call_args
    assert ck["chunks_file"] == Path("cf")
    _, ek = embed_main.call_args
    assert ek["embeddings_file"] == Path("ef")


@pytest.mark.unit
def test_build_nothing_to_process(runner, tmp_path, monkeypatch):
    """No llms-full.txt generated -> warn and stop before chunking."""
    monkeypatch.chdir(tmp_path)
    chunk_main = MagicMock()
    with patch.object(cli, "load_config", return_value=MagicMock()), \
         patch("opencrane.rag.fetch_docs.main"), \
         patch("opencrane.rag.generate_llms_txt.generate_outputs"), \
         patch("opencrane.rag.chunker.main", chunk_main):
        result = runner.invoke(cli_main, ["build"])
    assert result.exit_code == 0
    assert "Nothing to process" in result.output
    chunk_main.assert_not_called()


@pytest.mark.unit
def test_build_error(runner):
    with patch.object(cli, "load_config", side_effect=Exception("build-fail")):
        result = runner.invoke(cli_main, ["build"])
    assert result.exit_code == 1
    assert "Error: build-fail" in result.output


# === inspect ===

@pytest.mark.unit
def test_inspect_no_npx(runner):
    with patch("shutil.which", return_value=None):
        result = runner.invoke(cli_main, ["inspect"])
    assert result.exit_code == 1
    assert "npx is not installed" in result.output


@pytest.mark.unit
def test_inspect_success(runner):
    completed = MagicMock(returncode=0)
    with patch("shutil.which", return_value="/usr/bin/npx"), \
         patch("subprocess.run", return_value=completed) as srun:
        result = runner.invoke(cli_main, ["inspect"])
    assert result.exit_code == 0
    args = srun.call_args[0][0]
    assert "opencrane" in args and "serve" in args
    assert "--config" not in args


@pytest.mark.unit
def test_inspect_with_config_and_nonzero_exit(runner):
    completed = MagicMock(returncode=3)
    with patch("shutil.which", return_value="/usr/bin/npx"), \
         patch("subprocess.run", return_value=completed) as srun:
        result = runner.invoke(cli_main, ["inspect", "--config", "my.cfg"])
    assert result.exit_code == 3
    args = srun.call_args[0][0]
    assert "--config" in args
    assert "my.cfg" in args


# === visualize ===

@pytest.mark.unit
def test_visualize_success(runner):
    viz_mod = MagicMock()
    with patch.dict(sys.modules, {"opencrane.visualize": viz_mod}):
        result = runner.invoke(cli_main, ["visualize", "--text", "hello"])
    assert result.exit_code == 0
    _, kwargs = viz_mod.main.call_args
    assert kwargs["text"] == "hello"
    assert kwargs["dim"] == 3
    assert kwargs["open_browser"] is True


@pytest.mark.unit
def test_visualize_with_options(runner):
    viz_mod = MagicMock()
    with patch.dict(sys.modules, {"opencrane.visualize": viz_mod}):
        result = runner.invoke(
            cli_main,
            ["visualize", "--file", "p.txt",
             "--embeddings-file", "ef", "--chunks-file", "cf",
             "--output", "out.html", "--method", "tsne", "--dim", "2",
             "--viz", "neighbors", "--no-open"],
        )
    assert result.exit_code == 0
    _, kwargs = viz_mod.main.call_args
    assert kwargs["file"] == "p.txt"
    assert kwargs["embeddings_file"] == Path("ef")
    assert kwargs["chunks_file"] == Path("cf")
    assert kwargs["output"] == Path("out.html")
    assert kwargs["method"] == "tsne"
    assert kwargs["dim"] == 2
    assert kwargs["viz"] == "neighbors"
    assert kwargs["open_browser"] is False


@pytest.mark.unit
def test_visualize_systemexit_propagates(runner):
    viz_mod = MagicMock()
    viz_mod.main.side_effect = SystemExit(2)
    with patch.dict(sys.modules, {"opencrane.visualize": viz_mod}):
        result = runner.invoke(cli_main, ["visualize", "--text", "x"])
    assert result.exit_code == 2


@pytest.mark.unit
def test_visualize_error(runner):
    viz_mod = MagicMock()
    viz_mod.main.side_effect = Exception("viz-fail")
    with patch.dict(sys.modules, {"opencrane.visualize": viz_mod}):
        result = runner.invoke(cli_main, ["visualize", "--text", "x"])
    assert result.exit_code == 1
    assert "Error: viz-fail" in result.output


# === add (the branch where .opencrane is missing is covered in test_add_source) ===

@pytest.mark.unit
def test_add_with_opencrane_dir_invokes_interactive(runner, tmp_path, monkeypatch):
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("sources: {}\n")
    monkeypatch.chdir(tmp_path)
    with patch.object(cli, "_add_sources_interactive") as interactive:
        result = runner.invoke(cli_main, ["add"])
    assert result.exit_code == 0
    interactive.assert_called_once()


# === _add_sources_interactive ref-pinning branches ===

@pytest.mark.unit
def test_add_interactive_github_tag_ref(runner, tmp_path, monkeypatch):
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("sources: {}\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        cli_main,
        ["add"],
        input="1\nhttps://github.com/org/repo\ndocs\n\norg/repo\n2\nv1.0.0\nn\n",
    )
    assert result.exit_code == 0
    sources = yaml.safe_load((opencrane_dir / "config.yaml").read_text())
    assert sources["sources"]["org/repo"]["tag"] == "v1.0.0"


@pytest.mark.unit
def test_add_interactive_github_release_ref(runner, tmp_path, monkeypatch):
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("sources: {}\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        cli_main,
        ["add"],
        input="1\nhttps://github.com/org/repo\ndocs\n\norg/repo\n3\nv2.0.0\nn\n",
    )
    assert result.exit_code == 0
    sources = yaml.safe_load((opencrane_dir / "config.yaml").read_text())
    assert sources["sources"]["org/repo"]["release"] == "v2.0.0"


@pytest.mark.unit
def test_add_interactive_github_sha_ref(runner, tmp_path, monkeypatch):
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("sources: {}\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        cli_main,
        ["add"],
        input="1\nhttps://github.com/org/repo\ndocs\n\norg/repo\n4\ndeadbeef\nn\n",
    )
    assert result.exit_code == 0
    sources = yaml.safe_load((opencrane_dir / "config.yaml").read_text())
    assert sources["sources"]["org/repo"]["sha"] == "deadbeef"


@pytest.mark.unit
def test_add_interactive_llmstxt_error(runner, tmp_path, monkeypatch):
    """llmstxt add raising is caught and reported, loop still exits cleanly."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("sources: {}\n")
    monkeypatch.chdir(tmp_path)
    with patch("opencrane.add_source.add_llmstxt_source", side_effect=Exception("bad")):
        result = runner.invoke(
            cli_main,
            ["add"],
            input="2\nproj\nhttps://example.com/llms.txt\n\nn\n",
        )
    assert result.exit_code == 0
    assert "Error: bad" in result.output


@pytest.mark.unit
def test_add_interactive_single_letter_url_name_fallback(runner, tmp_path, monkeypatch):
    """A GitHub URL with a single path segment exercises the name-suggestion
    fallback branch (parts shorter than 2)."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("sources: {}\n")
    monkeypatch.chdir(tmp_path)
    with patch("opencrane.add_source.add_github_source") as add_gh:
        result = runner.invoke(
            cli_main,
            ["add"],
            # github url "solo" -> single segment; accept suggested name; no ref; no more
            input="1\nsolo\ndocs\n\n\n\nn\n",
        )
    assert result.exit_code == 0
    _, kwargs = add_gh.call_args
    assert kwargs["name"] == "solo"


# === pack ===

@pytest.mark.unit
def test_pack_with_wheel(runner, tmp_path):
    pack_mod = MagicMock()
    pack_mod.pack.return_value = (str(tmp_path / "out"), str(tmp_path / "out" / "x.whl"))
    with patch.dict(sys.modules, {"opencrane.pack": pack_mod}):
        result = runner.invoke(cli_main, ["pack", "--name", "my-docs-mcp"])
    assert result.exit_code == 0
    assert "Packed MCP server" in result.output
    assert "Wheel built" in result.output
    _, kwargs = pack_mod.pack.call_args
    assert kwargs["name"] == "my-docs-mcp"
    assert kwargs["version"] == "1.0.0"
    assert kwargs["output"] is None


@pytest.mark.unit
def test_pack_without_wheel_and_with_output(runner, tmp_path):
    pack_mod = MagicMock()
    pack_mod.pack.return_value = (str(tmp_path / "out"), None)
    with patch.dict(sys.modules, {"opencrane.pack": pack_mod}):
        result = runner.invoke(
            cli_main,
            ["pack", "--name", "n", "--output", str(tmp_path / "out"),
             "--version", "2.3.4"],
        )
    assert result.exit_code == 0
    assert "Wheel not built" in result.output
    _, kwargs = pack_mod.pack.call_args
    assert kwargs["version"] == "2.3.4"
    assert kwargs["output"] == Path(tmp_path / "out")


@pytest.mark.unit
def test_pack_prompts_for_name(runner, tmp_path):
    pack_mod = MagicMock()
    pack_mod.pack.return_value = (str(tmp_path / "out"), None)
    with patch.dict(sys.modules, {"opencrane.pack": pack_mod}):
        result = runner.invoke(cli_main, ["pack"], input="prompted-name\n")
    assert result.exit_code == 0
    _, kwargs = pack_mod.pack.call_args
    assert kwargs["name"] == "prompted-name"


# === init ===

@pytest.mark.unit
def test_init_no_add(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init", "--no-add"])
    assert result.exit_code == 0
    assert (tmp_path / ".opencrane" / "config.yaml").exists()
    assert "Created" in result.output
    assert "Next steps" in result.output


@pytest.mark.unit
def test_init_with_extensions(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init", "--no-add", "--extensions"])
    assert result.exit_code == 0
    assert (tmp_path / ".opencrane" / "extensions.py").exists()


@pytest.mark.unit
def test_init_podman(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init", "--no-add", "--podman"])
    assert result.exit_code == 0
    assert (tmp_path / ".opencrane" / "Containerfile").exists()


@pytest.mark.unit
def test_init_skipped_and_protected_and_force(runner, tmp_path, monkeypatch):
    """Pre-existing files: config.yaml is protected; others skipped without
    --force; running with --force overwrites the non-user-managed ones."""
    monkeypatch.chdir(tmp_path)
    # First init creates everything.
    runner.invoke(cli_main, ["init", "--no-add"])

    # Second init without --force: config.yaml protected, others skipped.
    result = runner.invoke(cli_main, ["init", "--no-add"])
    assert result.exit_code == 0
    assert "Protected" in result.output
    assert "Skipped" in result.output

    # Third init with --force: overwrites non-protected files.
    result = runner.invoke(cli_main, ["init", "--no-add", "--force"])
    assert result.exit_code == 0
    assert "Created" in result.output


@pytest.mark.unit
def test_init_decline_add_prompt(runner, tmp_path, monkeypatch):
    """Answering 'n' to the add-sources prompt shows next steps."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init"], input="n\n")
    assert result.exit_code == 0
    assert "Next steps" in result.output


@pytest.mark.unit
def test_init_accept_add_prompt(runner, tmp_path, monkeypatch):
    """Answering 'y' invokes the interactive add loop."""
    monkeypatch.chdir(tmp_path)
    with patch.object(cli, "_add_sources_interactive") as interactive:
        result = runner.invoke(cli_main, ["init"], input="y\n")
    assert result.exit_code == 0
    interactive.assert_called_once()
