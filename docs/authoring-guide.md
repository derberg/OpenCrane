# Write Markdown for OpenCrane chunking

This guide describes how to structure Markdown documentation so that OpenCrane produces high-quality chunks that search can retrieve. It applies to `.md` source files written for a documentation site, such as Docusaurus, Nextra, or a plain Markdown repository. It does not cover hand-written `llms-full.txt` files.

## How OpenCrane chunks Markdown

OpenCrane first splits each page at every fenced code block outside a list. It then chunks each code block, and each part of the page between two code blocks, on its own. Each part keeps the headings that it sits under, so a list or table after a code block gets its full breadcrumb. For the order in which OpenCrane tries the chunking strategies, see [Chunking strategies](chunking.md#chunking-strategies).

How you write the content determines which strategy handles each part and how well each chunk stands alone.

## Headings

Headings are the main chunk boundary. When each heading starts one focused section, most chunking problems do not occur. The following sections describe which headings split the content and how to use them.

### Headings that create chunk boundaries

By default, the `#`, `##`, and `###` headings create chunk boundaries in text that the prose chunker handles, as [Prose sections](chunking.md#prose-sections) describes. Everything between two such headings, including the opening heading, becomes one chunk.

The following example produces three chunks:

````md
# Getting started

Installation instructions go here.

## Prerequisites

Requirements go here.

## First run

First-run steps go here.
````

> [!IMPORTANT]
> In a part of the page that contains a list, the list chunker emits the text before the list as one prose chunk. This happens even when that text spans several `##` sections. The part starts at the previous code block outside a list, or at the top of the page. Search then returns those sections as one result.

### Headings that do not split chunks

By default, the `####` heading and deeper headings do not split chunks. Content under a `####` heading stays in the parent `###` chunk. Use `####` and deeper headings on purpose, for sub-structure that search must retrieve together with the parent topic.

The following example produces one chunk, not two:

````md
### Error handling

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

Start every page with a `#` title. The breadcrumb of every prose chunk on the page starts with the page title.

The following page is correct:

````md
# Database migrations

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
## Configuring the retry policy

The retry policy controls how failed requests are re-attempted.
Set `retries` and `backoff_ms` in `config.yaml` to tune behavior.
````

Avoid the following section. It is one chunk that covers four unrelated topics. A search for "retry policy" or "authentication" retrieves the whole section, and the reader has to find the answer inside it:

````md
## Configuration

Set `retries` and `backoff_ms` to tune retry behavior.
Set `request_timeout_ms` for timeouts.
Auth tokens go in `auth.token`. Log level is set with `log_level`.
````

The following version produces four focused chunks, and search can retrieve each one on its own:

````md
## Retry policy

Set `retries` and `backoff_ms` in `config.yaml` to tune how failed
requests are re-attempted.

## Request timeouts

Set `request_timeout_ms` to control how long the client waits before
aborting a request.

## Authentication

Provide your API token in `auth.token` in `config.yaml`.

## Logging

Set `log_level` to `debug`, `info`, or `warn` to control log verbosity.
````

### Add body text under every heading

By default, the prose chunker drops a section that has a heading but no body text. It always drops a chunk shorter than 15 characters. Do not leave placeholder headings with no body.

Avoid the following placeholder:

````md
## TODO
````

### Split long sections by topic

By default, OpenCrane does not split a section by size. A long `#`, `##`, or `###` section stays one chunk, however long it is. To cap the chunk size, see `PROSE_MAX_CHUNK_TOKENS` in [Prose sections](chunking.md#prose-sections).

If a section grows past a few hundred words, it usually covers more than one sub-topic. Break it into sibling `###` sections, one for each sub-topic.

### Keep URLs out of headings

Do not start a heading with a URL, such as `## https://example.com/page Title`. The URL stays in the breadcrumbs and section anchors of list item and table row chunks. If a page has no front matter `title`, its first heading, at any level, becomes the page title in the `llms.txt` index. A URL in that heading then becomes part of the page title.

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

State the topic of a section in its first sentence. A search result shows only the first 1,000 characters of a chunk, and the embedding model reads only the start of a long chunk.

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

Place every list in a section that has a `##` or `###` heading. Prose between the heading and the list does not cause a problem. OpenCrane builds the breadcrumb from the headings that the list sits under on the page. A code block between the heading and the list does not change the breadcrumb. A list before the first `##` heading gets only the page title as its breadcrumb.

The following list is correct:

````md
### Supported embedding models

- `nomic-ai/nomic-embed-text-v1.5`: default
- `BAAI/bge-small-en-v1.5`: smaller, faster
- `sentence-transformers/all-MiniLM-L6-v2`: legacy
````

Avoid the following list. It has no section heading before it, so its items carry only the page title as their breadcrumb:

````md
OpenCrane supports these models:

- `nomic-ai/nomic-embed-text-v1.5`
- `BAAI/bge-small-en-v1.5`
````

### Start each list item with its key phrase

Make each item meaningful on its own, and put its key phrase at the start of the first line. Each list item chunk carries short previews of the other items in the same list, called sibling previews. A sibling preview shows up to 30 characters of the first line of an item. The 30 characters include the ellipsis, Markdown characters such as `**`, and, in an ordered list, the item number.

The following item is meaningful on its own: `- Click **Next** to advance the installer to disk selection.`

Avoid items like this one: `- Click Next.`

The following item puts its key phrase first:

````md
- **Retry policy**: governs behavior on transient 5xx responses.
  Default is three retries with exponential backoff starting at 500ms.
````

Avoid the following item. Its key phrase comes late, so the preview shows filler text:

````md
- Something you might want to tune is the retry policy, which governs…
````

### Nest list items only for real hierarchy

Use nesting for real hierarchy, not for visual indentation. The chunk of a nested item holds the first line of each parent item and the first line of the nested item. OpenCrane drops the other lines of a nested item, so keep each nested item to one line. If the nested items are not logical children of the parent, use a paragraph or a separate list instead.

The following list is correct:

````md
- **Chunking strategies**
  - Prose: splits at heading boundaries
  - Code: one chunk per fenced block
  - List: one chunk per list item
````

Avoid the following list, because the nested items do not relate to the parent:

````md
- **Chunking strategies**
  - See also: MCP server
  - Contact: support@example.com
````

### Keep lists short

Keep top-level lists short. Aim for five to eight items, and never use more than 15.

When a search matches two or more items of one list, the result shows up to 15 other items as sibling previews. In a list of more than 16 items, the rest appear only as `... +N more`. The AI agent that queries the Model Context Protocol (MCP) server then needs another tool call to see the full list.

If a list grows past eight items, check whether the items form sub-topics. If they do, split them into `###` sub-sections, each with a shorter list.

### Keep prose outside the list

Do not put prose paragraphs between list items. Keep descriptive prose before or after the list. A paragraph between items ends the list, and OpenCrane treats the items after the paragraph as a separate list. The positions and sibling previews of each item then cover only part of the list.

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

Use the same marker for all items at the same indentation level. If you mix `1.` and `-` at the same level of one list, the items of that list get different `list_style` values. You can use different markers on different levels, for example ordered top-level steps with unordered nested options, because OpenCrane finds the nesting from the indentation.

The following list mixes markers across levels correctly:

````md
1. Install the CLI.
2. Choose an output format:
   - JSON
   - YAML
3. Run `opencrane build`.
````

### Code blocks in list items

A code block inside a list item stays with the item, so the list stays one list. Each item chunk contains its code block and the breadcrumb of its section. Indent the opening fence so that it lines up with the item text. A fence at the start of the line ends the list.

The following list produces two chunks:

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

The first chunk contains `1. Install the CLI:` and the `pip install opencrane` code block. The second chunk contains `2. Initialize the project:` and the `opencrane init` code block. Both chunks share one `list_id` and carry the breadcrumb of their section.

A code block inside a list item does not become a `code_snippet` chunk, so it has no `language` metadata. If search must return a code block on its own, put it under its own heading and introduce it with a sentence. The following page is correct:

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

## Tables

Every data row of a Markdown table becomes its own chunk. OpenCrane renders the row as `Column: value.` lines, so the row reads like a sentence when it is embedded. Each row chunk carries a `breadcrumb_path` from its headings and the lead-in sentence of the table. It links to its sibling rows through `table_id` and `sibling_ids`. The following sections help each row chunk stand alone.

### Give each table a heading and a lead-in sentence

Give the table a heading and a lead-in sentence. OpenCrane builds the breadcrumb from the heading, in the same way as for lists. The last non-blank line before the table becomes the caption, which OpenCrane includes in every row chunk. Both make each row retrievable on its own.

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
- Match the number of cells in every row to the header. A row with a different number of cells ends the table, and OpenCrane chunks the rest as prose.
- To put a `|` character in a cell, escape it as `\|` or put it inside backticks. An unescaped `|` outside backticks starts a new cell, so the row gets an extra cell and ends the table.
- Keep tables out of code fences. OpenCrane treats a table inside a code fence as code and does not chunk it into rows.
- Add at least one data row. OpenCrane chunks a header line and separator with no data rows as prose, not as a table.

## Fenced code blocks

Each fenced code block outside a list becomes one chunk, except the specification YAML that [Embedded specifications](#embedded-specifications) describes. A code block inside a list item stays in the chunk of that item, as [Code blocks in list items](#code-blocks-in-list-items) explains. The following sections help each code chunk stay usable on its own.

### Label every code block with its language

Always put the language after the opening fence. OpenCrane tags an unlabeled block with `language: unknown`, so a search filter on the language misses it.

The following code block is correct:

````md
```python
from opencrane import OpenCraneConfig
```
````

Avoid the following code block:

````md
```
from opencrane import OpenCraneConfig
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

### Keep explanations outside `<Tabs>` blocks with code

OpenCrane does not split a page inside a `<Tabs>` block, and keeps the block as its own part. When the block contains a code block and has fewer than 50 non-blank lines, or is mostly code, the code chunker handles it. The code chunker keeps only the code blocks, so OpenCrane drops any other text inside the `<Tabs>` block. The text before and after the block stays.

Inside a `<Tabs>` block that contains code, put only the code. Write the explanation before or after the block.

## Embedded specifications

The YAML chunker parses each fenced `yaml` or `yml` block. If the YAML is a known structured type, a tree walker replaces the single-block chunk with detailed chunks, one for each property or element. Other YAML, including a block of flat `key: value` pairs, becomes one `yaml_content` chunk. The following sections describe what each structured type needs.

### Kubernetes CustomResourceDefinitions

For a Kubernetes CustomResourceDefinition (CRD), paste the real specification. Include the following parts:

- `apiVersion: apiextensions.k8s.io/...`
- `kind: CustomResourceDefinition`
- The full `spec.versions[].schema.openAPIV3Schema`

The tree walker replaces the raw YAML chunk completely, so the original code block produces no chunk of its own. Only the properties under `spec` produce chunks. The tree walker skips `status`, which holds runtime state that the user does not configure. Every property chunk keeps the CRD identity in the following metadata fields:

- `crd_kind`, from `spec.names.kind`
- `crd_api_version`, from `spec.group` and the version
- `crd_version`, from the version name
- `crd_property_path`, from the dot-notation path of the property, starting at `spec`

With these fields, the AI agent can filter and group results by kind and API version.

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
                  description: Persistent volume size, for example "10Gi".
```
````

### OpenAPI specifications

For an OpenAPI specification, start the block with the `openapi` version as a string, such as `openapi: 3.0.3`. OpenCrane recognizes the specification only when the version is a string that starts with `3.`. YAML reads an unquoted two-part version such as `3.1` as a number, so quote it as `"3.1"`. OpenCrane also recognizes Swagger 2.0 with a `swagger: "2.0"` field, but chunks only its `info`, `paths`, `security`, and `tags` sections. To get chunks for the definitions, convert the specification to OpenAPI 3.

Include real versions of the following sections:

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
openapi: 3.0.3
paths:
  /users/{id}:
    get:
      summary: ""
      responses: { "200": { description: "" } }
```
````

### JSON Schema

For a JSON Schema, set `$schema` to a `json-schema.org` URL. Fill in `title` and `description` at the root and on each property. A schema with empty or generic descriptions produces low-quality chunks.

The following schema is correct:

````md
```yaml
$schema: https://json-schema.org/draft/2020-12/schema
title: OpenCrane Source
description: A single documentation source definition.
properties:
  type:
    type: string
    description: Source kind, either "github" or "llmstxt".
  repo:
    type: string
    description: GitHub "owner/name", required when type is "github".
```
````

### Split large properties

OpenCrane emits a property of 800 tokens or fewer as one chunk. If a property is over 800 tokens and has nested `properties` or `items.properties`, the tree walker splits it, and each child becomes its own chunk. A large property without nested structure stays one chunk. The 800-token limit is fixed in code, and you cannot configure it.

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
    properties:
      host:
        type: string
        description: Database host name.
```
````

## YAML front matter

Front matter is a `---`-delimited YAML block at the top of a file. The `llms` step strips valid front matter, so it never reaches chunking. The following sections describe how OpenCrane uses it.

### Set the page title in front matter

When the front matter has a `title` field, that title becomes the page title in the `llms.txt` index. OpenCrane also adds it as the `# {TITLE}` heading of the page. A body H1 with different text stays under the added heading, so the page then has two H1 headings. Make the body H1 match `title` exactly, or leave the H1 out. For details, see [Page titles](llms-generation.md#page-titles).

The following block sets the page title:

````md
---
title: Getting started
slug: getting-started
author: Lukasz
date: 2026-04-01
---
````

### Keep searchable content out of front matter

Do not put content that search must retrieve in front matter. OpenCrane discards every front matter field except `title`.

Avoid the following front matter, because search never retrieves the description:

````md
---
title: Getting started
description: >
  OpenCrane is a standalone RAG pipeline that fetches docs from GitHub,
  generates llms-full.txt bundles, chunks and embeds them, and serves
  them through MCP.
---
````

The following page keeps a short title in the front matter and puts the real description in the body:

````md
---
title: Getting started
---

# Getting started

OpenCrane is a standalone RAG pipeline that fetches docs from GitHub,
generates llms-full.txt bundles, chunks and embeds them, and serves
them through MCP.
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
