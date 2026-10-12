# Write Markdown for OpenCrane chunking

This guide describes how to structure Markdown documentation so that OpenCrane produces high-quality chunks that search can retrieve. It applies to `.md` source files written for a documentation site, such as Docusaurus, Nextra, or a plain Markdown repository. It does not cover hand-written `llms-full.txt` files.

## How OpenCrane chunks Markdown

When OpenCrane processes a Markdown file, it tries the following chunking strategies in this order. The first strategy that matches a part of the content claims that part:

1. Fenced `yaml` and `yml` blocks go to the YAML chunker. OpenCrane takes these blocks out of the page before the other strategies run. [Embedded specifications](#embedded-specifications) describes how the YAML chunker handles each kind of YAML.
2. Other fenced code blocks usually go to the code chunker. A block whose lines look like `key: value` pairs can go to the YAML chunker instead.
3. A section that contains a Markdown table outside code fences goes to the table chunker. It emits one chunk for each table data row and passes the surrounding text to the list and prose chunkers.
4. Sections that contain Markdown list markers outside code fences go to the list chunker. It emits one chunk for each list item, plus prose chunks for the text around the list.
5. All remaining content goes to the prose chunker. It splits the text into chunks at heading boundaries.

How you write the content determines which strategy claims each part of it and how well each chunk stands alone.

## Headings

Headings are the main chunk boundary. When each heading starts one focused section, most chunking problems do not occur. The following sections describe which headings split the content and how to use them.

### Headings that create chunk boundaries

The `#`, `##`, and `###` headings create chunk boundaries. Everything between two such headings, including the opening heading, becomes one chunk.

The following example produces three chunks:

````md
# Getting Started

Installation instructions go here.

## Prerequisites

Requirements go here.

## First Run

First-run steps go here.
````

### Headings that do not split chunks

The `####` heading and deeper headings do not split chunks. Content under a `####` sub-heading stays in the parent `###` chunk. Use `####` and deeper headings on purpose, for sub-structure that search must retrieve together with the parent topic.

The following example produces one chunk, not two:

````md
### Error Handling

The client retries on transient errors.

#### Retry policy

Default is three retries with exponential backoff.
````

If search must retrieve the content under a `####` heading on its own, promote that heading to `###`. The following structure keeps the `#### Rotating keys` content inside the parent chunk:

````md
## Authentication

#### Rotating keys

Keys must be rotated every 90 days.
````

The following structure gives the key rotation content its own chunk:

````md
## Authentication
...

### Rotating keys

Keys must be rotated every 90 days.
````

### Start every page with a title

Start every page with a `#` title. The breadcrumb of every prose chunk on the page starts with the title.

The following page is correct:

````md
# Database Migrations

## Running a migration
...
````

Avoid the following page. It has no `#` title, so OpenCrane uses the first heading, "Running a migration", as the page title. A search result does not say that the page is about database migrations rather than data migrations or network migrations:

````md
## Running a migration
...
````

### Give each section one topic

Give each `##` or `###` section one focused topic. Each such section is one chunk, so make sure it holds everything a reader needs to understand the topic. The heading is part of the chunk and gives the chunk its subject.

The following section is correct:

````md
## Configuring the Retry Policy

The retry policy controls how failed requests are re-attempted.
Set `retries` and `backoff_ms` in `config.yaml` to tune behavior.
````

Avoid the following section. It is one chunk that covers four unrelated topics. A search for "retry policy" or "authentication" retrieves the whole section, and the reader has to find the answer inside it:

````md
## Configuration

Set `retries` and `backoff_ms` to tune retry behavior.
Set `request_timeout_ms` for timeouts.
Auth tokens go in `auth.token`. Log level is set via `log_level`.
````

The following version is better. It produces four focused chunks, and search can retrieve each one on its own:

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

### Add body text under every heading

The prose chunker drops a heading that has no body text, whatever the length of the heading. It also drops any section shorter than 15 characters. Do not leave placeholder headings with no body.

Avoid the following placeholder:

````md
## TODO
````

### Split long sections by topic

OpenCrane does not split a section by size. A long `#`, `##`, or `###` section stays one chunk, however long it is. Keep sections focused, and split them by topic.

If a section grows past a few hundred words, it usually covers more than one sub-topic. Break it into sibling `###` sections, one for each sub-topic.

### Keep URLs out of headings

Do not start a section with a URL heading such as `## https://example.com/page Title`. The URL stays in list-item breadcrumbs and in section anchors. If a page has no front matter `title`, its first heading, at any level, becomes the page title in the `llms.txt` index. A URL in that heading becomes part of the page title. Keep headings readable.

Avoid the following heading:

````md
## https://docs.example.com/api/auth Authentication
````

The following heading is correct:

````md
## Authentication
````

## Prose sections

Search retrieves each prose chunk on its own, without the rest of the page. The following sections help each prose chunk make sense in a search result.

### Write sections that stand alone

Do not use pronouns or references that depend on the previous section. A `##` or `###` chunk reaches the reader without the text around it.

Avoid the following section:

````md
## Configuring timeouts

As mentioned above, the tool described earlier reads these values
from the same file.
````

The following section is correct:

````md
## Configuring timeouts

The OpenCrane CLI reads `request_timeout_ms` and `connect_timeout_ms`
from `.opencrane/config.yaml` on every invocation.
````

### Put the topic in the first sentence

State the topic of a section in its first sentence. In every search mode, a reader can then judge the search result quickly.

The following section is correct:

````md
### Hybrid search scoring

OpenCrane blends vector cosine similarity and BM25 using
`HYBRID_ALPHA * vector + (1 - HYBRID_ALPHA) * BM25`.
````

Avoid the following section, because it states the topic late:

````md
### Hybrid search scoring

There are several ways to score search results. Some systems use
only vectors, others only BM25. OpenCrane blends both…
````

### Use concrete search terms

Include the concrete terms a user searches for. Use a noun instead of a vague reference. The following terms are typical:

- Product names
- Command names
- Error strings
- Configuration keys

The following sentence is correct: "Run `opencrane build` to execute the full pipeline."

Avoid sentences like this one: "Run the main command to execute it all."

## Lists

Every list item, including each nested item, becomes its own chunk. Each item chunk carries a `breadcrumb_path` built from the headings the list sits under. The following sections help each item chunk stand alone.

### Put every list under a heading

Place every list in a section that has a `##` or `###` heading. OpenCrane builds the breadcrumb of each list-item chunk from the headings the list sits under, starting at the page title. Prose between the heading and the list does not cause a problem. A list that appears before the first `##` heading, usually at the top of a file, gets only the page title as its breadcrumb. A code block earlier on the page shortens the breadcrumb: for a list after a code block, the breadcrumb holds only the headings between that code block and the list.

The following list is correct:

````md
### Supported Embedding Models

- `nomic-ai/nomic-embed-text-v1.5` — default
- `BAAI/bge-small-en-v1.5` — smaller, faster
- `sentence-transformers/all-MiniLM-L6-v2` — legacy
````

Avoid the following list. It has no section heading before it, so its items carry only the page title as their breadcrumb:

````md
OpenCrane supports these models:

- `nomic-ai/nomic-embed-text-v1.5`
- `BAAI/bge-small-en-v1.5`
````

### Start each list item with its key phrase

Make each item meaningful on its own, and put its key phrase at the start of the first line. Each list-item chunk carries short previews of the other items in the same list, called sibling previews. A sibling preview shows up to 30 characters of the first line of an item. The 30 characters include the ellipsis and, in an ordered list, the item number. Put the explanation on continuation lines or in nested items.

The following item is meaningful on its own: `- Click **Next** to advance the installer to disk selection.`

Avoid items like this one: `- Click Next.`

The following item puts its key phrase first:

````md
- **Retry policy** — governs behavior on transient 5xx responses.
  Default is three retries with exponential backoff starting at 500ms.
````

Avoid the following item. Its key phrase comes late, so the preview shows filler text:

````md
- Something you might want to tune is the retry policy, which governs…
````

### Nest list items only for real hierarchy

Use nesting for real hierarchy, not for visual indentation. Each nested item gets the first lines of its parent items as a content prefix, so the chunk stays self-contained. If the nested items are not logical children of the parent, use a paragraph or a separate list instead.

The following list is correct:

````md
- **Chunking strategies**
  - Prose — splits at heading boundaries
  - Code — one chunk per fenced block
  - List — one chunk per list item
````

Avoid the following list, because the nested items do not relate to the parent:

````md
- **Chunking strategies**
  - See also: MCP server
  - Contact: support@example.com
````

### Keep lists short

Keep top-level lists short. Aim for five to eight items, and never use more than 15.

Every retrieved list-item chunk includes the sibling previews of all other items in its list. In a 15-item list, every search result carries 14 preview strings, so the token overhead grows with the length of the list. A chunk shows at most 15 sibling previews. In a list of more than 16 items, OpenCrane replaces the rest with `... +N more`. The AI agent that queries the Model Context Protocol (MCP) server then cannot rebuild the full list from a single chunk without more search calls.

If a list grows past eight items, check whether the items form sub-topics. If they do, split them into `###` sub-sections, each with a shorter list. Retrieval improves, and each chunk carries less overhead.

### Keep prose outside the list

Do not put prose paragraphs between list items. Keep descriptive prose before or after the list. A paragraph between items ends the list. OpenCrane treats the items after the paragraph as a separate list. The positions and sibling previews of each item then cover only part of the list.

Avoid the following structure:

````md
- First step: install the CLI.

Some background on why this matters…

- Second step: run `opencrane init`.
````

The following structure is correct:

````md
Install the CLI first, then initialize the project.

- First step: install the CLI.
- Second step: run `opencrane init`.
````

### Use one marker for each indentation level

Use the same marker for all items at the same indentation level. If you mix `1.` and `-` at the same level of one list, the items of that list get different `list_style` values. Mixing markers across levels is a normal pattern, for example ordered top-level steps with unordered nested options. The chunker handles this pattern correctly, because it finds the nesting from the indentation, not from the marker type.

The following list mixes markers across levels correctly:

````md
1. Install the CLI.
2. Choose an output format:
   - JSON
   - YAML
3. Run `opencrane build`.
````

### Code blocks in list items

OpenCrane splits each page at every fenced code block before the list chunker runs. A code block inside a list item therefore does not stay with the item. It becomes its own `code_snippet` chunk, and that chunk has no heading breadcrumb. The list items after the code block lose their breadcrumb, because the breadcrumb holds only the headings between the most recent code block and the list.

The following list produces four chunks:

````md
1. Install the CLI:
   ```bash
   pip install opencrane
   ```
2. Initialize the project:
   ```bash
   opencrane init
   ```
````

The first chunk contains `1. Install the CLI:`, with the breadcrumb of its section. The second chunk is the `pip install opencrane` code block. The third chunk contains `2. Initialize the project:`, with an empty breadcrumb. The fourth chunk is the `opencrane init` code block.

Put each step that needs a code block under its own heading instead, and introduce the code block with a sentence. The prose chunk of each step then carries the page title and the step heading in its breadcrumb. The following page is correct:

````md
## Install the CLI

Run the following command to install the CLI:

```bash
pip install opencrane
```

## Initialize the project

Run the following command to initialize the project:

```bash
opencrane init
```
````

If a list follows a code block, put a heading between them. The list items then carry that heading as their breadcrumb.

## Tables

Every data row of a Markdown table becomes its own chunk. OpenCrane renders the row as `Column: value.` lines, so the row reads like a sentence when it is embedded. Each row chunk carries a `breadcrumb_path` from its heading ancestry, and it carries the lead-in sentence of the table. It links to its sibling rows through `table_id` and `sibling_ids`. The following sections help each row chunk stand alone.

### Give each table a heading and a lead-in sentence

Give the table a heading and a lead-in sentence. OpenCrane builds the breadcrumb from the heading. The last non-blank line before the table becomes the caption, which OpenCrane includes in every row chunk. Both make each row retrievable on its own.

The following table is correct:

````md
### DIAMETER AVP types

The following AVP types from the base 3GPP Diameter dictionary are used:

| AVP | Code | Type |
|-----|------|------|
| 3GPP-IMSI | 1 | UTF8String |
| 3GPP-Charging-Id | 2 | Unsigned32 |
````

Each row chunk reads like this, where `{PAGE_TITLE}` is the `#` title of the page: `# {PAGE_TITLE} > DIAMETER AVP types` / `The following AVP types from the base 3GPP Diameter dictionary are used:` / `AVP: 3GPP-IMSI.` / `Code: 1.` / `Type: UTF8String.`

### Structure tables for row chunks

The following rules apply to the columns and placement of a table:

- Put the identifying value in the first column. The first column is the `row_key` of the row, and the sibling previews show up to 30 characters of it, including the ellipsis. Start with the name or key, not a description.
- Give every column a header. OpenCrane renders each cell as `Header: value.`, so a blank header produces an unlabeled `: value.` line that reads poorly.
- Keep tables out of code fences. OpenCrane treats a table inside a code fence as code and does not chunk it into rows.
- Add at least one data row. OpenCrane chunks a header line and separator with no data rows as prose, not as a table.

## Fenced code blocks

Each fenced code block becomes one chunk, except the specification YAML that [Embedded specifications](#embedded-specifications) describes. This includes code blocks inside list items, as [Code blocks in list items](#code-blocks-in-list-items) explains. The following sections help each code chunk stay usable on its own.

### Label every code block with its language

Always put the language after the opening fence. OpenCrane tags unlabeled blocks with `language: unknown`, which breaks retrieval filtered by language.

The following code block is correct:

````md
```python
from opencrane import OpenCrane
```
````

Avoid the following code block:

````md
```
from opencrane import OpenCrane
```
````

### Show one concept in each code block

Show one concept in each fenced block, because each fence becomes one chunk. Do not combine a configuration example and an unrelated error trace in the same fence.

Avoid the following code block:

````md
```yaml
# config.yaml
embedding_model: nomic-ai/nomic-embed-text-v1.5

# error seen when misconfigured:
# RuntimeError: model not found
```
````

The following example uses two separate fences:

````md
```yaml
embedding_model: nomic-ai/nomic-embed-text-v1.5
```

If the model is missing you will see:

```text
RuntimeError: model not found
```
````

### Keep code examples complete

Keep examples complete. Each code fence becomes one chunk. If the chunk contains truncated fields, the AI agent cannot act on it without more search calls. To show a large object, use one of the following approaches.

If the surrounding structure does not matter, show only the relevant section, and use prose to say where it goes:

````md
Set `branch` under your source entry in `.opencrane/config.yaml`:

```yaml
branch: main
```
````

If the surrounding structure matters, show the path from the top of the object down to the field, and leave out the sibling fields. Do not mark the omission with a comment. OpenCrane parses the block as YAML and stores it without comments, so the chunk does not show that anything is missing. The following block is correct:

````md
```yaml
sources:
  my-repo:
    branch: main
```
````

Avoid a literal `...`. It is not valid YAML, so a reader who copies the block gets a parse error. OpenCrane keeps the block as plain code instead of parsing it as YAML. Avoid the following block:

````md
```yaml
sources:
  my-repo:
    ...
    branch: main
```
````

### Keep pages mostly prose

Do not write one large document that is mostly code fences with a few paragraphs. The code chunker claims a block of content only if more than half its lines are code, or if the block is under 50 lines. OpenCrane separates each fenced code block from the text around it before chunking, so in ordinary Markdown documentation this rule rarely matters.

## Embedded specifications

The YAML chunker parses each fenced `yaml` or `yml` block. If the YAML is a known structured type, a parser called the tree walker replaces the single-block chunk with detailed chunks, one for each property. Other YAML, including a block of flat `key: value` pairs, becomes one `yaml_content` chunk. The following sections describe what each structured type needs.

### Kubernetes CustomResourceDefinitions

For a Kubernetes CustomResourceDefinition (CRD), paste the real specification. Include the following parts:

- `apiVersion: apiextensions.k8s.io/...`
- `kind: CustomResourceDefinition`
- The full `spec.versions[].schema.openAPIV3Schema`

The tree walker replaces the raw YAML chunk completely, so the original code block produces no chunk of its own. Only `spec.properties` produces chunks. Every property chunk keeps the CRD identity in the following metadata fields:

- `crd_kind`, from `spec.names.kind`
- `crd_api_version`, from `spec.group` and the version
- `crd_version`, from the version name
- `crd_property_path`, from the dot-notation path of the property, starting at `spec`

With these fields, the AI agent can filter and group results by kind and API version.

The tree walker skips the following parts on purpose:

- `status`, because it holds runtime state that the user does not configure
- `metadata.name`, the full CRD name such as `databases.example.com`, because `crd_kind` and `crd_api_version` together carry the same identity

The following CRD produces one chunk for each spec property:

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

### OpenAPI specifications

For an OpenAPI specification, include real versions of the following sections:

- `info`
- `servers`
- `paths`
- `components`

Each operation (`paths.<path>.<method>`) and each named component becomes its own chunk. Write a meaningful `summary` and `description` for every operation, because retrieval relies on them.

The following specification is correct:

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

Avoid the following specification. Its `summary` and `description` are empty, so retrieval ranks the operation poorly:

````md
```yaml
paths:
  /users/{id}:
    get:
      summary: ""
      responses: { "200": { description: "" } }
```
````

### JSON Schema

For a JSON Schema, fill in `title` and `description` at the root and on each property. A schema with empty or generic descriptions produces low-quality chunks.

The following schema is correct:

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

### Split large properties

OpenCrane emits a property under 800 tokens as one chunk. If a property is over 800 tokens and has nested `properties` or `items.properties`, the tree walker splits it, and each child becomes its own chunk. A large property without nested structure stays one chunk. The 800-token limit is fixed in code, and you cannot configure it.

The split property gets no chunk of its own, so its own `description` and `type` do not appear in any chunk. Put the information a reader needs on the child properties.

Every child chunk carries the following fields, so the AI agent can navigate the schema tree from any child chunk:

- `crd_property_path` on CRD chunks and `property_path` on JSON Schema and OpenAPI chunks: the full dot-notation path, for example `spec.config.database` on a CRD chunk or `config.database` on a JSON Schema chunk
- `logical_parent`: the path of the parent
- `neighbor_chunks`: the IDs of the sibling chunks

In a JSON Schema, you can also move a large property into a named definition under `$defs` and reference it with `$ref`. The tree walker chunks each definition separately. Kubernetes CRD schemas do not support `$ref`.

The following schema is correct:

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

## YAML front matter

Front matter is a `---`-delimited YAML block at the top of a file. The following sections describe how OpenCrane uses it.

### Set the page title in front matter

The `llms` step strips the front matter, so the block never reaches chunking. When the block has a `title` field, that title becomes the page title in the `llms.txt` index. The `title` field takes precedence over the first body heading and the file name. For details, see [Page titles](llms-generation.md#page-titles).

OpenCrane adds a `# {TITLE}` heading at the top of the page in `llms-full.txt`, unless the page already starts with exactly that heading. An existing H1 with different text stays under the new one, so the page then has two H1 headings. Make the body H1 match `title` exactly. You can also leave the H1 out, because OpenCrane adds it from `title`.

OpenCrane strips the following block, and its `title` becomes the page title:

````md
---
title: Getting Started
slug: getting-started
author: Lukasz
date: 2026-04-01
---
````

### Keep searchable content out of front matter

Do not put content that search must retrieve in front matter. Keep body content in the Markdown body.

Avoid the following front matter. OpenCrane discards every front matter field except `title`, so search never retrieves the description:

````md
---
title: Getting Started
description: >
  OpenCrane is a standalone RAG pipeline that fetches docs from GitHub,
  generates llms-full.txt bundles, chunks and embeds them, and serves
  them via MCP.
---
````

The following page keeps a short title in the front matter and puts the real description in the body:

````md
---
title: Getting Started
---

# Getting Started

OpenCrane is a standalone RAG pipeline that fetches docs from GitHub,
generates llms-full.txt bundles, chunks and embeds them, and serves
them via MCP.
````

### Keep front matter valid YAML

The `llms` step strips any front matter that parses as a YAML mapping, including mappings whose values are lists or nested maps. If the block is not valid YAML, OpenCrane keeps the whole block in the page body, and the block ends up in the chunks.

OpenCrane keeps the following block in the body, because the unquoted colon in the `title` value is not valid YAML:

````md
---
title: Setup: the first run
---
````

OpenCrane strips the following block, because the quoted value is valid YAML:

````md
---
title: "Setup: the first run"
---
````
