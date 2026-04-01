"""OpenCrane CLI entry point."""

import sys
import click


# ── CLI output helpers ──────────────────────────────────────────────────────
def _step(msg: str) -> None:
    """Print a pipeline step (bold cyan)."""
    click.secho(msg, fg="cyan", bold=True)

def _success(msg: str) -> None:
    """Print a success message (green)."""
    click.secho(msg, fg="green")

def _warn(msg: str) -> None:
    """Print a warning (yellow)."""
    click.secho(msg, fg="yellow")

def _error(msg: str) -> None:
    """Print an error (red, to stderr)."""
    click.secho(msg, fg="red", err=True)

def _info(msg: str, **kwargs) -> None:
    """Print informational text (dim)."""
    click.secho(msg, dim=True, **kwargs)

def _hint(msg: str) -> None:
    """Print a hint/command the user should run (bright white)."""
    click.secho(msg, fg="bright_white")


def load_config(config_arg: str | None):
    """Load OpenCraneConfig from a module:Class string, or auto-discover from config.yaml.

    Resolution order:
    1. Explicit ``--config`` flag or ``OPENCRANE_CONFIG`` env var
    2. Auto-discovery: ``.opencrane/config.yaml`` with an ``extensions`` key
    3. Base ``OpenCraneConfig`` (no customisation)
    """
    import os
    from opencrane.config import OpenCraneConfig

    if config_arg is None:
        config_arg = os.environ.get("OPENCRANE_CONFIG")

    # Auto-discover extensions from .opencrane/config.yaml
    if config_arg is None:
        from pathlib import Path
        config_yaml = Path(".opencrane/config.yaml")
        if config_yaml.exists():
            import yaml
            try:
                data = yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {}
            extensions = data.get("extensions")
            if extensions:
                ext_path = config_yaml.parent / extensions
                if ext_path.exists():
                    import importlib.util
                    opencrane_dir = str(ext_path.parent.resolve())
                    if opencrane_dir not in sys.path:
                        sys.path.insert(0, opencrane_dir)
                    spec = importlib.util.spec_from_file_location("_opencrane_extensions", ext_path.resolve())
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return getattr(module, "Config")()
        return OpenCraneConfig()

    if ":" in config_arg:
        # Python class: "module.path:ClassName"
        module_path, class_name = config_arg.rsplit(":", 1)
        import importlib
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()
    else:
        # Treat as path to Python file
        from pathlib import Path
        import importlib.util
        ext_path = Path(config_arg)
        if ext_path.exists():
            opencrane_dir = str(ext_path.parent.resolve())
            if opencrane_dir not in sys.path:
                sys.path.insert(0, opencrane_dir)
            spec = importlib.util.spec_from_file_location("_opencrane_config", ext_path.resolve())
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return getattr(module, "Config")()
        return OpenCraneConfig()


def _colorize_help(text: str, is_group: bool = False) -> str:
    """Post-process Click help text to add ANSI colors."""
    import re
    lines = text.split("\n")
    result = []

    if is_group:
        result.append(
            click.style("OpenCrane", fg="cyan", bold=True)
            + click.style(" — RAG/MCP pipeline for AI-powered documentation search", dim=True)
        )
        result.append("")

    in_commands = False
    in_options = False

    for line in lines:
        # Color section headings
        if re.match(r"^(Usage|Options|Commands):", line):
            result.append(click.style(line, fg="cyan", bold=True))
            in_commands = line.startswith("Commands:")
            in_options = line.startswith("Options:")
            continue

        # Color command names in Commands section
        if in_commands and line.startswith("  "):
            m = re.match(r"^(\s{2})(\S+)(\s+)(.*)", line)
            if m:
                result.append(
                    m.group(1)
                    + click.style(m.group(2), fg="green", bold=True)
                    + m.group(3)
                    + m.group(4)
                )
                continue

        # Color option names in Options section
        if in_options and line.startswith("  "):
            m = re.match(r"^(\s{2})(--\S+(?:\s\S+)?)(.*)", line)
            if m:
                result.append(
                    m.group(1)
                    + click.style(m.group(2), fg="green")
                    + m.group(3)
                )
                continue

        # Reset section tracking on blank lines
        if not line.strip():
            in_commands = False
            in_options = False

        result.append(line)

    return "\n".join(result)


class _ColorMixin:
    """Mixin that colorizes help output."""

    def get_help(self, ctx):
        text = super().get_help(ctx)
        is_group = isinstance(self, click.Group)
        return _colorize_help(text, is_group=is_group)


class _ColorGroup(_ColorMixin, click.Group):
    pass


class _ColorCommand(_ColorMixin, click.Command):
    pass


@click.group(cls=_ColorGroup)
@click.version_option()
def main():
    """Pipeline: add → fetch → llms → chunk → embed → index → serve"""


@main.command(cls=_ColorCommand)
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
@click.option("--org", default=None,
              help="GitHub organization name (overrides ORG_NAME env var)")
@click.option("--repo", default=None,
              help="Fetch only this repo by its path key in .opencrane/sources.yaml (overrides FETCH_REPO env var)")
def fetch(config_path, org, repo):
    """Fetch documentation from GitHub."""
    try:
        load_config(config_path)
        from opencrane.shared.config import get_config
        from opencrane.rag.fetch_docs import main as fetch_main
        config = get_config()
        if org:
            config.org_name = org
            if org not in config.auto_discovery_orgs:
                config.auto_discovery_orgs.append(org)
        if repo:
            config.fetch_repo = repo
        fetch_main(config=config)
    except Exception as e:
        _error(f"Error: {e}")
        sys.exit(1)


@main.command(cls=_ColorCommand)
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
@click.option("--sources-dir", "sources_dirs", multiple=True, type=click.Path(), default=None,
              help="Source directory to process (repeatable; overrides AI_DOCS_SOURCES_DIRS)")
@click.option("--llmstxt-dir", default=None, type=click.Path(),
              help="Output directory for llms-full.txt files (overrides AI_DOCS_LLMSTXT_DIR)")
@click.option("--force", is_flag=True, default=False,
              help="Regenerate even if no git changes are detected in source directories")
def llms(config_path, sources_dirs, llmstxt_dir, force):
    """Generate llms-full.txt files."""
    try:
        from pathlib import Path
        cfg = load_config(config_path)
        from opencrane.rag.generate_llms_txt import generate_outputs
        generate_outputs(
            config=cfg,
            sources_dirs=[Path(p) for p in sources_dirs] if sources_dirs else None,
            llmstxt_dir=Path(llmstxt_dir) if llmstxt_dir else None,
            force=force,
        )
    except Exception as e:
        _error(f"Error: {e}")
        sys.exit(1)


@main.command(cls=_ColorCommand)
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
@click.option("--llmstxt-dir", default=None, type=click.Path(),
              help="Directory containing llms-full.txt (overrides AI_DOCS_LLMSTXT_DIR)")
@click.option("--chunks-file", default=None, type=click.Path(),
              help="Output path for rag-chunks.json (overrides AI_DOCS_CHUNKS_FILE)")
def chunk(config_path, llmstxt_dir, chunks_file):
    """Generate rag-chunks.json from documentation."""
    try:
        from pathlib import Path
        cfg = load_config(config_path)
        from opencrane.rag.chunker import main as chunk_main
        chunk_main(
            config=cfg,
            llmstxt_dir=Path(llmstxt_dir) if llmstxt_dir else None,
            chunks_file=Path(chunks_file) if chunks_file else None,
        )
    except Exception as e:
        _error(f"Error: {e}")
        sys.exit(1)


@main.command(cls=_ColorCommand)
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
@click.option("--chunks-file", default=None, type=click.Path(),
              help="Input chunks JSON file (overrides AI_DOCS_CHUNKS_FILE)")
@click.option("--embeddings-file", default=None, type=click.Path(),
              help="Output embeddings JSON file (overrides AI_DOCS_EMBEDDINGS_FILE)")
def embed(config_path, chunks_file, embeddings_file):
    """Generate embeddings from rag-chunks.json."""
    try:
        from pathlib import Path
        load_config(config_path)
        from opencrane.rag.generate_embeddings import main as embed_main
        embed_main(
            chunks_file=Path(chunks_file) if chunks_file else None,
            embeddings_file=Path(embeddings_file) if embeddings_file else None,
        )
    except Exception as e:
        _error(f"Error: {e}")
        sys.exit(1)


@main.command(cls=_ColorCommand)
@click.option("--source-dir", default=None, type=click.Path(),
              help="Directory containing llmstxt output to count (overrides TOKEN_SOURCE_DIR)")
@click.option("--output-file", default=None, type=click.Path(),
              help="Output path for the markdown report (overrides TOKEN_OUTPUT_FILE)")
def tokens(source_dir, output_file):
    """Generate token count report for llms-full.txt files."""
    try:
        from pathlib import Path
        from opencrane.rag.token_count import main as tokens_main
        tokens_main(
            source_dir=Path(source_dir) if source_dir else None,
            output_file=Path(output_file) if output_file else None,
        )
    except Exception as e:
        _error(f"Error: {e}")
        sys.exit(1)


@main.command(cls=_ColorCommand)
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
def index(config_path):
    """Initialize vector database (Milvus) with chunks and embeddings."""
    try:
        load_config(config_path)  # validate config; init_vector_db uses env-based config internally
        from opencrane.mcp.init_vector_db import main as index_main
        index_main()
    except Exception as e:
        _error(f"Error: {e}")
        sys.exit(1)


@main.command(cls=_ColorCommand)
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
@click.option("--transport", "transport",
              type=click.Choice(["stdio", "http"], case_sensitive=False),
              default="stdio",
              help="Transport mode: stdio (default, for local MCP clients) or http (for Docker/Podman, port 8000)")
def serve(config_path, transport):
    """Start the MCP server (stdio or HTTP transport)."""
    try:
        import asyncio
        load_config(config_path)

        if transport == "http":
            port = __import__("os").environ.get("MCP_HTTP_PORT", "8000")
            click.secho("OpenCrane MCP server starting (HTTP transport)...", fg="cyan", bold=True, err=True)
            click.echo("", err=True)
            _info(f"  MCP endpoint:  http://localhost:{port}/http", err=True)
            _info(f"  Health check:  http://localhost:{port}/health", err=True)
            click.echo("", err=True)
            _info("  Claude Code (HTTP):", err=True)
            click.secho(f"    claude mcp add myopencranemcp --transport http http://localhost:{port}/http", fg="bright_white", err=True)
            click.echo("", err=True)
            from opencrane.mcp.http_server import main as http_main
            asyncio.run(http_main())
        else:
            # All output MUST go to stderr — stdout is reserved for MCP JSON-RPC messages
            click.secho("OpenCrane MCP server starting (stdio transport)...", fg="cyan", bold=True, err=True)
            click.echo("", err=True)
            _info("  Add to your agentic tool:", err=True)
            click.echo("", err=True)
            _info("  Claude Code:", err=True)
            click.secho("    claude mcp add myopencranemcp -- opencrane serve", fg="bright_white", err=True)
            click.echo("", err=True)
            _info("  Cursor / Windsurf / VS Code (mcp.json):", err=True)
            click.secho('    { "mcpServers": { "myopencranemcp": { "command": "opencrane", "args": ["serve"] } } }', fg="bright_white", err=True)
            click.echo("", err=True)
            _info("  Zed (settings.json):", err=True)
            click.secho('    { "context_servers": { "myopencranemcp": { "command": { "path": "opencrane", "args": ["serve"] } } } }', fg="bright_white", err=True)
            click.echo("", err=True)
            _info("  Amazon Q / any MCP-compatible tool:", err=True)
            click.secho("    command: opencrane serve", fg="bright_white", err=True)
            click.echo("", err=True)
            _info("  Or serve over HTTP via Docker:", err=True)
            click.secho("    docker-compose up --build   (after: opencrane init)", fg="bright_white", err=True)
            _info("  Or with Podman:", err=True)
            click.secho("    podman-compose up --build   (after: opencrane init --podman)", fg="bright_white", err=True)
            click.echo("", err=True)
            from opencrane.mcp.server import main as serve_main
            asyncio.run(serve_main())
    except Exception as e:
        _error(f"Error: {e}")
        sys.exit(1)


@main.command(cls=_ColorCommand)
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
@click.option("--sources-dir", "sources_dirs", multiple=True, type=click.Path(), default=None,
              help="Source directory to process (repeatable; overrides AI_DOCS_SOURCES_DIRS)")
@click.option("--llmstxt-dir", default=None, type=click.Path(),
              help="Output directory for llms-full.txt files (overrides AI_DOCS_LLMSTXT_DIR)")
@click.option("--chunks-file", default=None, type=click.Path(),
              help="Output path for rag-chunks.json (overrides AI_DOCS_CHUNKS_FILE)")
@click.option("--embeddings-file", default=None, type=click.Path(),
              help="Output path for rag-embeddings.json (overrides AI_DOCS_EMBEDDINGS_FILE)")
def build(config_path, sources_dirs, llmstxt_dir, chunks_file, embeddings_file):
    """Run the full pipeline: fetch → llms → chunk → embed → index."""
    try:
        from pathlib import Path
        cfg = load_config(config_path)

        _step("Step 1/5: Fetching documentation...")
        from opencrane.rag.fetch_docs import main as fetch_main
        fetch_main()

        _step("Step 2/5: Generating llms-full.txt files...")
        from opencrane.rag.generate_llms_txt import generate_outputs
        generate_outputs(
            config=cfg,
            sources_dirs=[Path(p) for p in sources_dirs] if sources_dirs else None,
            llmstxt_dir=Path(llmstxt_dir) if llmstxt_dir else None,
        )

        # Check if there's anything to chunk
        effective_llmstxt_dir = Path(llmstxt_dir) if llmstxt_dir else Path(".opencrane/llmstxt")
        if not (effective_llmstxt_dir / "llms-full.txt").exists():
            click.echo("")
            _warn("Nothing to process — no llms-full.txt was generated.")
            _hint("  Add sources with: opencrane add")
            return

        _step("Step 3/5: Chunking documentation...")
        from opencrane.rag.chunker import main as chunk_main
        chunk_main(
            config=cfg,
            llmstxt_dir=Path(llmstxt_dir) if llmstxt_dir else None,
            chunks_file=Path(chunks_file) if chunks_file else None,
        )

        _step("Step 4/5: Generating embeddings...")
        from opencrane.rag.generate_embeddings import main as embed_main
        embed_main(
            chunks_file=Path(chunks_file) if chunks_file else None,
            embeddings_file=Path(embeddings_file) if embeddings_file else None,
        )

        _step("Step 5/5: Initializing vector database...")
        from opencrane.mcp.init_vector_db import main as index_main
        index_main()

        _success("Build complete.")
    except Exception as e:
        _error(f"Error: {e}")
        sys.exit(1)


@main.command(cls=_ColorCommand)
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
def inspect(config_path):
    """Launch MCP Inspector connected to the server via stdio (no Docker needed)."""
    import shutil
    import subprocess

    if not shutil.which("npx"):
        _error("npx is not installed or not in PATH. Install Node.js to use this command.")
        sys.exit(1)

    config_args = ["--config", config_path] if config_path else []
    serve_cmd = ["opencrane", "serve"] + config_args

    _step("Starting MCP Inspector (stdio transport)...")
    _info("Web UI will be available at http://localhost:5173", err=True)

    result = subprocess.run(
        ["npx", "@modelcontextprotocol/inspector@0.20.0", "--transport", "stdio"] + serve_cmd
    )
    sys.exit(result.returncode)


@main.command(cls=_ColorCommand)
def add():
    """Interactively add documentation sources to the project."""
    from pathlib import Path

    opencrane_dir = Path(".opencrane")
    if not opencrane_dir.exists():
        _warn("No .opencrane/ directory found.")
        _hint("  Run: opencrane init")
        sys.exit(1)

    _add_sources_interactive()


def _add_sources_interactive():
    """Run the interactive source addition loop."""
    from opencrane.add_source import add_github_source, add_llmstxt_source

    while True:
        click.echo("")
        _step("What type of source do you want to add?")
        click.echo("  " + click.style("1.", fg="green", bold=True) + " GitHub repository (fetch markdown docs)")
        click.echo("  " + click.style("2.", fg="green", bold=True) + " Existing llms.txt file (URL or local path)")
        choice = click.prompt(click.style("Choice", fg="cyan"), type=click.IntRange(1, 2), default=1)

        if choice == 1:
            github_url = click.prompt(click.style("GitHub repository URL", fg="cyan"))
            docs_path = click.prompt(click.style("Path to docs within the repo", fg="cyan"), default="docs")
            docs_url = click.prompt(click.style("Published docs URL (optional, for source links)", fg="cyan"), default="")

            # Suggest a name derived from the URL
            parts = github_url.rstrip("/").split("/")
            suggested = f"{parts[-2]}/{parts[-1]}" if len(parts) >= 2 else parts[-1]
            name = click.prompt(click.style("Source name", fg="cyan"), default=suggested)

            try:
                add_github_source(
                    name=name,
                    url=github_url,
                    docs_path=docs_path,
                    docs_url=docs_url,
                )
                _success(f"Added GitHub source '{name}' to .opencrane/sources.yaml")
            except Exception as e:
                _error(f"Error: {e}")

        elif choice == 2:
            name = click.prompt(click.style("Name for this source (used as directory name)", fg="cyan"))
            location = click.prompt(click.style("llms.txt URL or local file path", fg="cyan"))
            docs_url = click.prompt(click.style("Published docs URL (optional, for source links)", fg="cyan"), default="")
            try:
                add_llmstxt_source(name=name, url=location, docs_url=docs_url)
                _success(f"Added llmstxt source '{name}' to .opencrane/sources.yaml")
            except Exception as e:
                _error(f"Error: {e}")

        if not click.confirm(click.style("Add another source?", fg="cyan"), default=False):
            break

    click.echo("")
    _info("Next steps:")
    _hint("  Run: opencrane build")


@main.command(cls=_ColorCommand)
@click.option("--name", "name", default=None,
              help="Package name (e.g. my-docs-mcp)")
@click.option("--output", "output", default=None, type=click.Path(),
              help="Output directory (default: .opencrane/pack/<name>/)")
@click.option("--version", "version", default="1.0.0",
              help="Package version (default: 1.0.0)")
def pack(name, output, version):
    """Package the MCP server for distribution via uvx."""
    from pathlib import Path
    from opencrane.pack import pack as do_pack

    if name is None:
        name = click.prompt(click.style("Package name (e.g. my-docs-mcp)", fg="cyan"))

    output_path = Path(output) if output else None
    output_dir, wheel_path = do_pack(name=name, version=version, output=output_path)

    _success(f"Packed MCP server to {output_dir}/")
    if wheel_path:
        _info(f"Wheel built: {wheel_path}")
    else:
        _warn("Wheel not built (install 'build' package: pip install build)")
    click.echo("")
    _info("Share it:")
    click.echo("")
    _info("  1. Push to GitHub, then others run:")
    _hint(f'     claude mcp add {name} -- uvx --from "git+https://github.com/you/{name}" {name}')
    click.echo("")
    _info("  2. Or publish to PyPI:")
    _hint(f"     pip install build twine && python -m build {output_dir} && twine upload {output_dir}/dist/*")
    _info("     Then others run:")
    _hint(f"     claude mcp add {name} -- uvx {name}")
    click.echo("")
    _info("  3. Or use locally:")
    _hint(f"     claude mcp add {name} -- uvx --from {output_dir} {name}")


@main.command(cls=_ColorCommand)
@click.option("--podman", is_flag=True, default=False,
              help="Generate Containerfile instead of Dockerfile")
@click.option("--force", is_flag=True, default=False,
              help="Overwrite existing files")
@click.option("--no-add", is_flag=True, default=False,
              help="Skip the interactive source addition prompt")
def init(podman, force, no_add):
    """Scaffold a new OpenCrane project with .opencrane/ directory and container files."""
    from pathlib import Path
    from opencrane.templates import CONFIG_PY, SOURCES_YAML, DOCKERFILE, DOCKER_COMPOSE, readme

    created = []
    skipped = []
    protected = []

    def write_file(path: Path, content: str, user_managed: bool = False):
        if path.exists():
            if user_managed:
                protected.append(str(path))
                return
            if not force:
                skipped.append(str(path))
                return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        created.append(str(path))

    opencrane_dir = Path(".opencrane")
    write_file(opencrane_dir / "config.py", CONFIG_PY)
    write_file(opencrane_dir / "sources.yaml", SOURCES_YAML, user_managed=True)
    write_file(opencrane_dir / "README.md", readme(podman=podman))

    dockerfile_name = "Containerfile" if podman else "Dockerfile"
    write_file(opencrane_dir / dockerfile_name, DOCKERFILE)
    write_file(opencrane_dir / "docker-compose.yml", DOCKER_COMPOSE)

    if created:
        _success("Created:")
        for f in created:
            click.echo(f"  {f}")
    if skipped:
        _warn("Skipped (already exist — use --force to overwrite):")
        for f in skipped:
            click.echo(f"  {f}")
    if protected:
        _info("Protected (user-managed, never overwritten):")
        for f in protected:
            click.echo(f"  {f}")

    click.echo("")
    if no_add:
        _info("Next steps:")
        _hint("  1. Add sources: opencrane add")
        _hint("  2. Run: opencrane build")
        _hint("  3. Run: opencrane serve")
    elif click.confirm(click.style("Would you like to add documentation sources now?", fg="cyan"), default=True):
        _add_sources_interactive()
    else:
        click.echo("")
        _info("Next steps:")
        _hint("  1. Add sources: opencrane add")
        _hint("  2. Run: opencrane build")
        _hint("  3. Run: opencrane serve")


if __name__ == "__main__":
    main()
