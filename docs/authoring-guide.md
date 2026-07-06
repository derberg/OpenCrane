# Authoring Markdown for OpenCrane Chunking

This guide describes how to structure markdown documentation so OpenCrane produces high-quality, retrievable chunks. It applies to `.md` and `.mdx` source files authored for a docs site (Docusaurus, Nextra, plain markdown repos). It does **not** cover hand-authored `llms-full.txt` files.

## How Chunking Sees Your Markdown

When OpenCrane processes a markdown file, strategies are tried in order and the first match wins:

1. **YAML chunker** — claims YAML documents (front matter is explicitly skipped).
2. **Code chunker** — claims fenced code blocks. Fenced YAML that is a K8s CRD, OpenAPI spec, or JSON Schema is handed off to a tree walker for per-property chunking.
3. **List chunker** — claims any section that contains markdown list markers outside code fences. Emits one chunk per top-level list item plus prose chunks for the text around the list.
4. **Prose chunker** — the catch-all. Splits text into chunks at heading boundaries.

Your authoring choices determine which strategy claims each piece of content and how well each chunk stands alone.

## Headings

Headings are the primary chunk boundary. Get them right and most chunking problems go away.

- **`#`, `##`, and `###` create chunk boundaries.** Everything between two such headings (inclusive of the opening heading) becomes one chunk.

  Example — this produces three chunks:

  ````md
  # Getting Started

  Installation instructions go here.

  ## Prerequisites

  Requirements go here.

  ## First Run

  First-run steps go here.
  ````

- **`####` and deeper do NOT split chunks.** Content under an `####` sub-heading stays embedded in the parent `###` chunk. Use `####+` deliberately for sub-structure you want retrieved *together with* the parent topic.

  Example — one chunk, not two:

  ````md
  ### Error Handling

  The client retries on transient errors.

  #### Retry policy

  Default is three retries with exponential backoff.
  ````

- **One focused topic per `##`/`###` section.** That section is one chunk; make sure everything a reader needs to understand the topic is inside it, including the opening heading (which gives the chunk its subject).

  Good:

  ````md
  ## Configuring the Retry Policy

  The retry policy controls how failed requests are re-attempted.
  Set `retries` and `backoff_ms` in `config.yaml` to tune behavior.
  ````

  Avoid (one chunk covers four unrelated topics — a search for "retry policy" or
  "authentication" retrieves this whole blob and the answer is buried inside it):

  ````md
  ## Configuration

  Set `retries` and `backoff_ms` to tune retry behavior.
  Set `request_timeout_ms` for timeouts.
  Auth tokens go in `auth.token`. Log level is set via `log_level`.
  ````

  Better — four focused chunks, each retrievable on its own:

  ````md
  ## Retry policy

  Set `retries` and `backoff_ms` in `config.yaml` to tune how failed
  requests are re-attempted.

  ## Request timeouts

  Set `request_timeout_ms` to control how long the client waits before
  aborting a request.

  ## Authentication

  Provide your API token via `auth.token` in `config.yaml`.

  ## Logging

  Set `log_level` to `debug`, `info`, or `warn` to control log verbosity.
  ````

- **Lead every page with an `#` title.** It anchors the first chunk and provides breadcrumb context for any lists below.

  Good:

  ````md
  # Database Migrations

  ## Running a migration
  ...
  ````

  Avoid (no `#` — the `## Running a migration` chunk has no page-level context,
  so a retrieval result shows "Running a migration" with no indication this is
  about database migrations versus, say, data migrations or network migrations):

  ````md
  ## Running a migration
  ...
  ````

- **Never indent content under an `##`/`###` with a deeper heading you plan to retrieve separately.** If it deserves its own chunk, promote it to `###`.

  Avoid (`#### Rotating keys` will be buried inside the parent chunk):

  ````md
  ## Authentication

  #### Rotating keys

  Keys must be rotated every 90 days.
  ````

  Good:

  ````md
  ## Authentication
  ...

  ### Rotating keys

  Keys must be rotated every 90 days.
  ````

- **Sections whose total content (heading + body) is under 15 characters are dropped** as garbage. In practice this means very short headings with no body text. Don't leave placeholder headings with no body.

  Avoid:

  ````md
  ## TODO
  ````

- **There is no token-based split inside a section.** An overly long `#`, `##`, or `###` section remains one chunk regardless of size. Keep sections focused; split by topic, not by length.

  If a section grows past a few hundred words, break it into sibling `###` sections by sub-topic rather than letting it balloon.

## Prose Sections

- **Write sections that stand alone.** Each `##`/`###` chunk will be retrieved on its own with no surrounding context. Don't use pronouns or references that depend on the previous section.

  Avoid:

  ````md
  ## Configuring timeouts

  As mentioned above, the tool described earlier reads these values
  from the same file.
  ````

  Good:

  ````md
  ## Configuring timeouts

  The OpenCrane CLI reads `request_timeout_ms` and `connect_timeout_ms`
  from `.opencrane/config.yaml` on every invocation.
  ````

- **Put the key phrasing in the first sentence.** The MCP server supports three search modes — keyword (BM25), semantic (vector), and hybrid. BM25 is position-agnostic: it only cares whether a term appears in the chunk, not where, so first-sentence placement doesn't change keyword results. For semantic and hybrid search, a chunk focused on one clear concept is more likely to match a focused query than one that mixes the topic with preamble. Stating the topic up front also makes chunks easier to evaluate in search results regardless of mode.

  Good:

  ````md
  ### Hybrid search scoring

  OpenCrane blends vector cosine similarity and BM25 using
  `HYBRID_ALPHA * vector + (1 - HYBRID_ALPHA) * BM25`.
  ````

  Avoid (buries the topic):

  ````md
  ### Hybrid search scoring

  There are several ways to score search results. Some systems use
  only vectors, others only BM25. OpenCrane blends both…
  ````

- **Include concrete terms a user would search for** (product names, command names, error strings, config keys). Avoid vague referents when a noun would do.

  Good: "Run `opencrane build` to execute the full pipeline."

  Avoid: "Run the main command to execute it all."

- **Don't open a section with a URL heading** like `## https://example.com/page Title`. The pipeline no longer injects URLs into headings, so a URL in your heading is kept verbatim as heading text — which makes for a noisy chunk title and, if it lands on a page's leading `#`, a noisy page title in the `llms.txt` index. Keep headings human-readable.

  Avoid:

  ````md
  ## https://docs.example.com/api/auth Authentication
  ````

  Good:

  ````md
  ## Authentication
  ````

## Lists

Every top-level list item becomes its own chunk, each carrying a `breadcrumb_path` built from the nearest heading ancestry.

- **Every list must appear within a section that has a heading (`#`/`##`/`###`).** The breadcrumb attached to each list-item chunk is built from all headings seen before the list in the document — not just the immediately preceding line. Prose between the heading and the list is fine. What breaks breadcrumb context is a list that appears before any heading has been encountered, typically at the very top of a file.

  Good:

  ````md
  ### Supported Embedding Models

  - `nomic-ai/nomic-embed-text-v1.5` — default
  - `BAAI/bge-small-en-v1.5` — smaller, faster
  - `sentence-transformers/all-MiniLM-L6-v2` — legacy
  ````

  Avoid (no heading above — items chunk without breadcrumb):

  ````md
  OpenCrane supports these models:

  - `nomic-ai/nomic-embed-text-v1.5`
  - `BAAI/bge-small-en-v1.5`
  ````

- **Make each item meaningful in isolation.**

  Good: `- Click **Next** to advance the installer to disk selection.`

  Avoid: `- Click Next.`

- **First line first.** The item's first line is what appears in sibling previews (capped at 30 characters). Put the key phrase at the start; push explanation to continuation lines or nested bullets.

  Good:

  ````md
  - **Retry policy** — governs behavior on transient 5xx responses.
    Default is three retries with exponential backoff starting at 500ms.
  ````

  Avoid (key phrase arrives late, preview shows filler):

  ````md
  - Something you might want to tune is the retry policy, which governs…
  ````

- **Prefer nesting for real hierarchy, not visual indent.** Nested items inherit their ancestors' first lines as a content prefix, which keeps the chunk self-contained. If the nested bullets aren't logically children of the parent, use a paragraph or a separate list instead.

  Good:

  ````md
  - **Chunking strategies**
    - Prose — splits at heading boundaries
    - Code — one chunk per fenced block
    - List — one chunk per list item
  ````

  Avoid (nested items are unrelated to parent):

  ````md
  - **Chunking strategies**
    - See also: MCP server
    - Contact: support@example.com
  ````

- **Keep top-level lists short — aim for 5–8 items, hard limit 15.** Each list-item chunk carries `sibling_previews` — short text previews of every other item in the same list. Every retrieved chunk brings all those previews with it. A 15-item list means 14 preview strings riding along with every single result, which is token overhead that scales with list length. Beyond 15 items the previews also start truncating to `... +N more` with no text, so the agent can no longer reconstruct the full list from a single chunk without additional search calls.

  If a list is growing past 8 items, ask whether the items naturally group into sub-topics. If so, split under `###` sub-sections with shorter lists under each — better retrieval and less per-chunk overhead.

  If you have more than 15 items, split by sub-topic with `###` sub-sections, each containing a shorter list.

- **Don't interleave prose paragraphs between list items.** Keep descriptive prose above or below the list, not between bullets — it can break list detection and produce odd prose chunks.

  Avoid:

  ````md
  - First step: install the CLI.

  Some background on why this matters…

  - Second step: run `opencrane init`.
  ````

  Good:

  ````md
  Install the CLI first, then initialize the project.

  - First step: install the CLI.
  - Second step: run `opencrane init`.
  ````

- **Use markers consistently at the same indent level.** Mixing `1.` and `-` at the same level in one list is confusing style. Mixing across levels is fine and expected — ordered top-level steps with unordered nested sub-options is a normal pattern and the chunker handles it correctly (nesting is determined by indentation, not marker type).

  Fine — ordered steps, unordered nested options:

  ````md
  1. Install the CLI.
  2. Choose an output format:
     - JSON
     - YAML
  3. Run `opencrane build`.
  ````

- **Code blocks inside list items are included verbatim in the item's chunk — they do not become separate code chunks.** The list chunker tracks fences to avoid treating code content as list markers, and renders each item's full body including any code blocks it contains.

  This example produces **2 chunks** — one per top-level item. Each chunk contains the prose description and the code block together:

  ````md
  1. Install the CLI:
     ```bash
     pip install opencrane
     ```
  2. Initialise the project:
     ```bash
     opencrane init
     ```
  ````

  Chunk 1 content: `1. Install the CLI:` + the bash block.
  Chunk 2 content: `2. Initialise the project:` + the bash block.
  Each chunk also carries a sibling preview of the other item.

  The one edge case: if a list section has so many code blocks that more than half its lines are code, the code chunker claims the whole section first and it is no longer chunked as a list. For typical step-by-step docs the prose lines (markers, descriptions) easily outweigh the code lines, so this rarely applies.

## Fenced Code Blocks

- **Always label the language** after the opening fence. Unlabeled blocks are tagged `language: unknown`, which breaks language-filtered retrieval.

  Good:

  ````md
  ```python
  from opencrane import OpenCrane
  ```
  ````

  Avoid:

  ````md
  ```
  from opencrane import OpenCrane
  ```
  ````

- **One concept per fenced block.** Each fence becomes one chunk. Don't concatenate a config example and an unrelated error trace in the same fence.

  Avoid:

  ````md
  ```yaml
  # config.yaml
  embedding_model: nomic-ai/nomic-embed-text-v1.5

  # error seen when misconfigured:
  # RuntimeError: model not found
  ```
  ````

  Good — two separate fences:

  ````md
  ```yaml
  embedding_model: nomic-ai/nomic-embed-text-v1.5
  ```

  If the model is missing you will see:

  ```text
  RuntimeError: model not found
  ```
  ````

- **Keep examples complete and self-sufficient.** Each code fence becomes one chunk. If that chunk contains truncated fields the agent cannot act on it without additional search calls. When showing a large object, pick one of two approaches:

  If the surrounding structure is irrelevant to the point, show only the relevant section and use prose to say where it goes:

  ````md
  Set `branch` under your source entry in `.opencrane/config.yaml`:

  ```yaml
  branch: main
  ```
  ````

  If the structure context matters, use a comment to mark elision rather than literal `...` — the shown fields stay syntactically valid:

  ````md
  ```yaml
  sources:
    my-repo:
      url: https://github.com/example/repo
      # ... other fields ...
      branch: main
  ```
  ````

  Avoid literal `...` ellipsis syntax — it is not valid YAML and makes the chunk unparseable:

  ````md
  ```yaml
  sources:
    my-repo:
      ...
      branch: main
  ```
  ````

  Good:

  ````md
  ```yaml
  sources:
    - type: github
      repo: example/docs
      branch: main
  ```
  ````

  Avoid:

  ````md
  ```yaml
  sources:
    - type: github
      ...
  ```
  ````

- **Prose-heavy pages stay prose.** The code chunker only claims a node if more than half its lines are code (or the node is under ~50 lines). In ordinary markdown docs each fenced block is its own node, so this is rarely an issue — just don't write one giant document that is mostly code fences with occasional paragraphs if you want the prose chunks to survive.

## Embedded Specs (CRD / OpenAPI / JSON Schema)

Fenced YAML blocks are inspected by the chunker. If the YAML parses to a known structured type, a tree walker replaces the single-block chunk with rich per-property chunks.

- **For Kubernetes CRDs:** paste the real spec — `apiVersion: apiextensions.k8s.io/...`, `kind: CustomResourceDefinition`, full `spec.versions[].schema.openAPIV3Schema`. The tree walker completely replaces the raw YAML chunk — the original code block produces no chunk of its own. Only `spec.properties` produces chunks, but the CRD identity is not lost: every property chunk carries `crd_kind` (from `spec.names.kind`), `crd_api_version` (from `spec.group` + version), `crd_version`, and `crd_property_path` as metadata. The agent can filter and group results by kind and API version. What is intentionally skipped: `status` (runtime state, not user-configurable) and `metadata.name` (the full CRD name like `databases.example.com`, though `crd_kind` + `crd_api_version` together convey the same identity).

  Good — produces one chunk per spec property:

  ````md
  ```yaml
  apiVersion: apiextensions.k8s.io/v1
  kind: CustomResourceDefinition
  metadata:
    name: databases.example.com
  spec:
    group: example.com
    names:
      kind: Database
    versions:
      - name: v1
        schema:
          openAPIV3Schema:
            properties:
              spec:
                properties:
                  engine:
                    type: string
                    description: Database engine (postgres, mysql).
                  size:
                    type: string
                    description: Persistent volume size, e.g. "10Gi".
  ```
  ````

- **For OpenAPI specs:** include real `info`, `servers`, `paths`, and `components`. Each operation (`paths.<path>.<method>`) and each named component becomes its own chunk. Write meaningful `summary` and `description` on every operation — they are the retrieval signal.

  Good:

  ````md
  ```yaml
  openapi: 3.0.3
  info:
    title: Example API
    version: 1.0.0
  paths:
    /users/{id}:
      get:
        summary: Fetch a user by ID
        description: Returns the full user record including profile data.
        parameters:
          - name: id
            in: path
            required: true
            schema: { type: string }
  ```
  ````

  Avoid (empty `summary`/`description` — retrieval can't rank the operation):

  ````md
  ```yaml
  paths:
    /users/{id}:
      get:
        summary: ""
        responses: { "200": { description: "" } }
  ```
  ````

- **For JSON Schema:** populate `title` and `description` at the root and on each property. A schema with empty or generic descriptions produces low-quality chunks.

  Good:

  ````md
  ```yaml
  $schema: https://json-schema.org/draft/2020-12/schema
  title: OpenCrane Source
  description: A single documentation source definition.
  properties:
    type:
      type: string
      description: Source kind — either "github" or "llmstxt".
    repo:
      type: string
      description: GitHub "owner/name" — required when type is "github".
  ```
  ````

- **Properties under 800 tokens are emitted as one chunk. Properties over 800 tokens with nested `properties` or `items` are recursed into — each child becomes its own chunk instead.** No content is lost: every child chunk carries `crd_property_path` (full dot-notation path, e.g. `spec.config.database`), `logical_parent` (the parent's path), and `neighbor_chunks` (sibling IDs), so an agent can navigate the full schema tree from any leaf. The thresholds are hardcoded — there is no config knob. The only authoring lever is `$ref` into `$defs`: a large property broken into named definitions gives the walker more structure to recurse into.

  Good:

  ````md
  ```yaml
  properties:
    database:
      $ref: "#/$defs/DatabaseConfig"
  $defs:
    DatabaseConfig:
      type: object
      description: Database connection configuration.
      properties: { ... }
  ```
  ````

## YAML Front Matter

- **Front matter is ignored by chunking**, but its `title` is used for the page title. Flat `key: value` blocks at the top of a file with only scalar values are detected as front matter and skipped from chunk content. When a `title` field is present, it becomes the page title used in the `llms.txt` index and normalized onto the page's leading `#` heading — taking precedence over the first body heading and the filename. See [Generating bundles](llms-generation.md#page-titles).

  Skipped as front matter (its `title` becomes the page title):

  ````md
  ---
  title: Getting Started
  slug: getting-started
  author: Lukasz
  date: 2026-04-01
  ---
  ````

- **Don't hide retrievable content in front matter.** Keep body content in the markdown body.

  Avoid (the full description will never be retrieved):

  ````md
  ---
  title: Getting Started
  description: >
    OpenCrane is a standalone RAG pipeline that fetches docs from GitHub,
    generates llms-full.txt bundles, chunks and embeds them, and serves
    them via MCP.
  ---
  ````

  Good — keep a short slug in front matter, put the real description in the body:

  ````md
  ---
  title: Getting Started
  ---

  # Getting Started

  OpenCrane is a standalone RAG pipeline that fetches docs from GitHub,
  generates llms-full.txt bundles, chunks and embeds them, and serves
  them via MCP.
  ````

- **Front matter with nested values is NOT skipped.** If your front matter contains lists or maps, it will be chunked as YAML. Keep it flat-scalar or move complex metadata to a dedicated file.

  Chunked as YAML (not skipped):

  ````md
  ---
  title: My Page
  tags:
    - rag
    - mcp
  authors:
    - name: Lukasz
      role: maintainer
  ---
  ````

  Front-matter-safe flat equivalent:

  ````md
  ---
  title: My Page
  tags: "rag, mcp"
  author: Lukasz
  ---
  ````