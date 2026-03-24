"""OpenCrane CLI entry point."""

import sys
import click


def load_config(config_arg: str | None):
    """Load OpenCraneConfig from a module:Class string or YAML file path.

    Resolution order:
    1. Explicit ``--config`` flag or ``OPENCRANE_CONFIG`` env var
    2. Auto-discovery: ``.opencrane/config.py`` with a ``Config`` class
    3. Base ``OpenCraneConfig`` (no customisation)
    """
    import os
    from opencrane.config import OpenCraneConfig

    if config_arg is None:
        config_arg = os.environ.get("OPENCRANE_CONFIG")

    # Auto-discover .opencrane/config.py when nothing is explicit
    if config_arg is None:
        from pathlib import Path
        auto_path = Path(".opencrane/config.py")
        if auto_path.exists():
            import importlib.util
            # Add .opencrane/ to sys.path so sibling imports inside config.py work
            opencrane_dir = str(auto_path.parent.resolve())
            if opencrane_dir not in sys.path:
                sys.path.insert(0, opencrane_dir)
            spec = importlib.util.spec_from_file_location("_opencrane_config", auto_path.resolve())
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return getattr(module, "Config")()

    if config_arg is None:
        return OpenCraneConfig()

    if ":" in config_arg:
        # Python class: "module.path:ClassName"
        module_path, class_name = config_arg.rsplit(":", 1)
        import importlib
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()
    else:
        # YAML file path
        import yaml
        from pathlib import Path
        yaml.safe_load(Path(config_arg).read_text())
        # For now, create base config; YAML overrides are a future enhancement
        config = OpenCraneConfig()
        # TODO: future work - map YAML keys to config attributes
        return config


@click.group()
@click.version_option()
def main():
    """OpenCrane — RAG/MCP library for documentation search."""
    pass


@main.command()
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
        if repo:
            config.fetch_repo = repo
        fetch_main(config=config)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
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
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
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
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
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
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
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
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
def index(config_path):
    """Initialize vector database (Milvus) with chunks and embeddings."""
    try:
        load_config(config_path)  # validate config; init_vector_db uses env-based config internally
        from opencrane.mcp.init_vector_db import main as index_main
        index_main()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
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
            click.echo(f"OpenCrane MCP server starting (HTTP transport, port {port})...", err=True)
            click.echo("", err=True)
            click.echo("  MCP endpoint:  http://localhost:{port}/http".replace("{port}", port), err=True)
            click.echo("  Health check:  http://localhost:{port}/health".replace("{port}", port), err=True)
            click.echo("", err=True)
            click.echo("  Claude Code (HTTP):", err=True)
            click.echo(f"    claude mcp add myopencranemcp --transport http http://localhost:{port}/http", err=True)
            click.echo("", err=True)
            from opencrane.mcp.http_server import main as http_main
            asyncio.run(http_main())
        else:
            click.echo("OpenCrane MCP server starting (stdio transport)...", err=True)
            click.echo("", err=True)
            click.echo("Add to your agentic tool:", err=True)
            click.echo("", err=True)
            click.echo("  Claude Code:", err=True)
            click.echo("    claude mcp add myopencranemcp -- opencrane serve", err=True)
            click.echo("", err=True)
            click.echo("  Cursor / Windsurf / VS Code (mcp.json):", err=True)
            click.echo('    { "mcpServers": { "myopencranemcp": { "command": "opencrane", "args": ["serve"] } } }', err=True)
            click.echo("", err=True)
            click.echo("  Zed (settings.json):", err=True)
            click.echo('    { "context_servers": { "myopencranemcp": { "command": { "path": "opencrane", "args": ["serve"] } } } }', err=True)
            click.echo("", err=True)
            click.echo("  Amazon Q / any MCP-compatible tool:", err=True)
            click.echo('    command: opencrane serve', err=True)
            click.echo("", err=True)
            click.echo("  Or serve over HTTP via Docker:", err=True)
            click.echo("    docker-compose up --build   (after: opencrane init)", err=True)
            click.echo("  Or with Podman:", err=True)
            click.echo("    podman-compose up --build   (after: opencrane init --podman)", err=True)
            click.echo("", err=True)
            from opencrane.mcp.server import main as serve_main
            asyncio.run(serve_main())
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
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

        click.echo("Step 1/5: Fetching documentation...")
        from opencrane.rag.fetch_docs import main as fetch_main
        fetch_main()

        click.echo("Step 2/5: Generating llms-full.txt files...")
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
            click.echo("Nothing to process — no llms-full.txt was generated.")
            click.echo("Add sources with: opencrane add")
            return

        click.echo("Step 3/5: Chunking documentation...")
        from opencrane.rag.chunker import main as chunk_main
        chunk_main(
            config=cfg,
            llmstxt_dir=Path(llmstxt_dir) if llmstxt_dir else None,
            chunks_file=Path(chunks_file) if chunks_file else None,
        )

        click.echo("Step 4/5: Generating embeddings...")
        from opencrane.rag.generate_embeddings import main as embed_main
        embed_main(
            chunks_file=Path(chunks_file) if chunks_file else None,
            embeddings_file=Path(embeddings_file) if embeddings_file else None,
        )

        click.echo("Step 5/5: Initializing vector database...")
        from opencrane.mcp.init_vector_db import main as index_main
        index_main()

        click.echo("Build complete.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--config", "config_path", default=None,
              help="Python config class (module:Class) or YAML file path")
def inspect(config_path):
    """Launch MCP Inspector connected to the server via stdio (no Docker needed)."""
    import shutil
    import subprocess

    if not shutil.which("npx"):
        click.echo("Error: npx is not installed or not in PATH. Install Node.js to use this command.", err=True)
        sys.exit(1)

    config_args = ["--config", config_path] if config_path else []
    serve_cmd = ["opencrane", "serve"] + config_args

    click.echo("Starting MCP Inspector (stdio transport)...", err=True)
    click.echo("Web UI will be available at http://localhost:5173", err=True)

    result = subprocess.run(
        ["npx", "@modelcontextprotocol/inspector@0.20.0", "--transport", "stdio"] + serve_cmd
    )
    sys.exit(result.returncode)


@main.command()
def add():
    """Interactively add documentation sources to the project."""
    from pathlib import Path

    opencrane_dir = Path(".opencrane")
    if not opencrane_dir.exists():
        click.echo("No .opencrane/ directory found. Run 'opencrane init' first.")
        sys.exit(1)

    _add_sources_interactive()


def _add_sources_interactive():
    """Run the interactive source addition loop."""
    from opencrane.add_source import add_github_source, add_llmstxt_source

    while True:
        click.echo("")
        click.echo("What type of source do you want to add?")
        click.echo("  1. GitHub repository (fetch markdown docs)")
        click.echo("  2. Existing llms.txt file (URL or local path)")
        choice = click.prompt("Choice", type=click.IntRange(1, 2), default=1)

        if choice == 1:
            github_url = click.prompt("GitHub repository URL")
            docs_path = click.prompt("Path to docs within the repo", default="docs")
            docs_url = click.prompt("Published docs URL (optional, for source links)", default="")

            # Suggest a name derived from the URL
            parts = github_url.rstrip("/").split("/")
            suggested = f"{parts[-2]}/{parts[-1]}" if len(parts) >= 2 else parts[-1]
            name = click.prompt("Source name", default=suggested)

            try:
                add_github_source(
                    name=name,
                    github_url=github_url,
                    docs_path=docs_path,
                    docs_url=docs_url,
                )
                click.echo(f"Added GitHub source '{name}' to .opencrane/sources.yaml")
            except Exception as e:
                click.echo(f"Error: {e}", err=True)

        elif choice == 2:
            name = click.prompt("Name for this source (used as directory name)")
            while True:
                location = click.prompt("llms.txt URL or local file path")
                try:
                    dest = add_llmstxt_source(name=name, location=location)
                    click.echo(f"Saved to {dest}")
                    break
                except FileNotFoundError as e:
                    click.echo(f"Error: {e}", err=True)
                except Exception as e:
                    click.echo(f"Error downloading: {e}", err=True)
                    click.echo("  Tip: set LOG_LEVEL=DEBUG for detailed error info", err=True)
                if not click.confirm("Try again?", default=True):
                    break

        if not click.confirm("Add another source?", default=False):
            break

    click.echo("")
    click.echo("Next steps:")
    click.echo("  Run: opencrane build")


@main.command()
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
        click.echo("Created:")
        for f in created:
            click.echo(f"  {f}")
    if skipped:
        click.echo("Skipped (already exist — use --force to overwrite):")
        for f in skipped:
            click.echo(f"  {f}")
    if protected:
        click.echo("Protected (user-managed, never overwritten):")
        for f in protected:
            click.echo(f"  {f}")

    click.echo("")
    if no_add:
        click.echo("Next steps:")
        click.echo("  1. Add sources: opencrane add")
        click.echo("  2. Run: opencrane build")
        click.echo("  3. Run: opencrane serve")
    elif click.confirm("Would you like to add documentation sources now?", default=True):
        _add_sources_interactive()
    else:
        click.echo("")
        click.echo("Next steps:")
        click.echo("  1. Add sources: opencrane add")
        click.echo("  2. Run: opencrane build")
        click.echo("  3. Run: opencrane serve")


if __name__ == "__main__":
    main()
