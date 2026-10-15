# Changelog

## [0.34.0](https://github.com/derberg/OpenCrane/compare/v0.33.1...v0.34.0) (2026-10-15)


### Features

* make embedding and reranker encoder settings configurable ([#94](https://github.com/derberg/OpenCrane/issues/94)) ([5ce2ead](https://github.com/derberg/OpenCrane/commit/5ce2eadcb2228011402c554334c6bd10367a975b))
* record the embedding model and prompts in the index and serve with them ([#96](https://github.com/derberg/OpenCrane/issues/96)) ([ff3d873](https://github.com/derberg/OpenCrane/commit/ff3d873f4a63bbe6ddaaef713b802d148a843fd9))
* take the container image's embedding model from embeddings.json ([#97](https://github.com/derberg/OpenCrane/issues/97)) ([2662284](https://github.com/derberg/OpenCrane/commit/26622845933c6e18648493240440fb9670072b55))
* use the embedding model's own prompts when none are configured ([#95](https://github.com/derberg/OpenCrane/issues/95)) ([0ab5d0e](https://github.com/derberg/OpenCrane/commit/0ab5d0e25d58842748a0aa86877f8727c1b8673e))

## [0.33.1](https://github.com/derberg/OpenCrane/compare/v0.33.0...v0.33.1) (2026-10-14)


### Bug Fixes

* keep stdio search working when config.yaml cannot be parsed ([#90](https://github.com/derberg/OpenCrane/issues/90)) ([2b579eb](https://github.com/derberg/OpenCrane/commit/2b579eb782f7dc710b116de840145e9333f3d4db))
* leave OpenCrane output and tool dirs out of the ignored-file fingerprint ([#91](https://github.com/derberg/OpenCrane/issues/91)) ([44abf8f](https://github.com/derberg/OpenCrane/commit/44abf8f916478396ebae6b3b254f6c0e174bff00))

## [0.33.0](https://github.com/derberg/OpenCrane/compare/v0.32.0...v0.33.0) (2026-10-13)


### Features

* add a LOG_LEVEL variable for all commands ([#82](https://github.com/derberg/OpenCrane/issues/82)) ([c884e4d](https://github.com/derberg/OpenCrane/commit/c884e4db7babf5e4139bea690d1d2349d13a189b))
* configurable hybrid candidate pool and optional reciprocal rank fusion ([#53](https://github.com/derberg/OpenCrane/issues/53)) ([7365b21](https://github.com/derberg/OpenCrane/commit/7365b2103373cec2b0fed6f57803301dcd08ad67))
* configurable prose heading depth, chunk size cap and heading-only sections ([#56](https://github.com/derberg/OpenCrane/issues/56)) ([47ec9ab](https://github.com/derberg/OpenCrane/commit/47ec9ab961642c424b20e50cd785321676e4480f))
* configurable query and document prompts for embedding models ([#54](https://github.com/derberg/OpenCrane/issues/54)) ([b06a9e3](https://github.com/derberg/OpenCrane/commit/b06a9e331630eb46605d2d57852913ab1f36ce9f))
* extra_tools extension point for registering custom MCP tools ([#55](https://github.com/derberg/OpenCrane/issues/55)) ([7df8729](https://github.com/derberg/OpenCrane/commit/7df8729e4d19fba722510ffbb60f5e1c3656f9f6))
* heading path, clause id and neighbour links for prose chunks, plus get_section tool ([#59](https://github.com/derberg/OpenCrane/issues/59)) ([0b627a0](https://github.com/derberg/OpenCrane/commit/0b627a0274c1c094a5d22aeaf34339118e2230f4))
* let custom strategies and walkers emit their own chunk_type ([#83](https://github.com/derberg/OpenCrane/issues/83)) ([3496354](https://github.com/derberg/OpenCrane/commit/34963549791b402d0fa8a928619b0e75ad03c1c4))
* optional identifier-aware BM25 tokenizer ([#52](https://github.com/derberg/OpenCrane/issues/52)) ([e47cd8b](https://github.com/derberg/OpenCrane/commit/e47cd8b1ab173eb05721852866e0bd77eedbedd9))
* optional reranker stage with a cross-encoder reference implementation ([#58](https://github.com/derberg/OpenCrane/issues/58)) ([6ef5dac](https://github.com/derberg/OpenCrane/commit/6ef5dacfd29faf8fc26371c4d6adc6d8a86a9c46))


### Bug Fixes

* apply the source policy to get_yaml_definition and the member tools ([#76](https://github.com/derberg/OpenCrane/issues/76)) ([be8fa05](https://github.com/derberg/OpenCrane/commit/be8fa058c126e962ef17e345ef9b62cb3fd83842))
* build the BM25 index once instead of on every query ([#51](https://github.com/derberg/OpenCrane/issues/51)) ([e9fd740](https://github.com/derberg/OpenCrane/commit/e9fd7408a6a10e8fcf76a210560d18244dde37c1))
* chunk prose around lists as prose and keep continuation lines of list items ([#73](https://github.com/derberg/OpenCrane/issues/73)) ([f855ed6](https://github.com/derberg/OpenCrane/commit/f855ed6d9b26fe16d7155bc5df95bc0594af77ef))
* claim fenced blocks in the YAML strategy by their fence language ([#77](https://github.com/derberg/OpenCrane/issues/77)) ([a42965d](https://github.com/derberg/OpenCrane/commit/a42965d90805c31ea4702916f403ae03131f04a8))
* correct init, compose and CLI help errors ([#66](https://github.com/derberg/OpenCrane/issues/66)) ([55aaa68](https://github.com/derberg/OpenCrane/commit/55aaa68d963f16caf3395cdea070a970380bf88d))
* fail closed on auth misconfiguration ([#85](https://github.com/derberg/OpenCrane/issues/85)) ([a80b52b](https://github.com/derberg/OpenCrane/commit/a80b52b2a6cb6f369bbe7d8daa8ea8b0294e5f44))
* include llmstxt sources in the combined bundle with one sources dir ([#67](https://github.com/derberg/OpenCrane/issues/67)) ([b9114d4](https://github.com/derberg/OpenCrane/commit/b9114d4bd31ab26b0c8c6e522459cb284f6b0bb0))
* keep breadcrumbs after code fences and code blocks inside list items ([#80](https://github.com/derberg/OpenCrane/issues/80)) ([110ec97](https://github.com/derberg/OpenCrane/commit/110ec97bd4b6915eb17edce8f5b5dc6a29c40e7d))
* keep page URLs and detect ignored-file changes in llms --sources-dir ([#86](https://github.com/derberg/OpenCrane/issues/86)) ([df999a2](https://github.com/derberg/OpenCrane/commit/df999a20cdec2ca9b0247a6b8c9131efded4b81f))
* keep prose next to &lt;Tabs&gt; blocks ([#69](https://github.com/derberg/OpenCrane/issues/69)) ([c3e575a](https://github.com/derberg/OpenCrane/commit/c3e575a341d8bd2af6df2f65bae3b1c82533d26c))
* keep the text inside &lt;Tabs&gt; blocks with code ([#78](https://github.com/derberg/OpenCrane/issues/78)) ([97be2c3](https://github.com/derberg/OpenCrane/commit/97be2c3699968537e4b5a1ee2fb5c10427bdb233))
* keep user-set keys of manual sources when fetch rewrites config.yaml ([#64](https://github.com/derberg/OpenCrane/issues/64)) ([f690a94](https://github.com/derberg/OpenCrane/commit/f690a94411543bc172fc51da5272cbae2a928896))
* let embed skip when the chunks file is unchanged ([#63](https://github.com/derberg/OpenCrane/issues/63)) ([ca69b82](https://github.com/derberg/OpenCrane/commit/ca69b82dbe149fd0cdc4b1bc79f4e76a461ba6ec))
* link page URLs to the Git ref the fetch read ([#84](https://github.com/derberg/OpenCrane/issues/84)) ([1d0a16f](https://github.com/derberg/OpenCrane/commit/1d0a16f3a3b603cd648fd69b439ec6548234398a))
* make list_id unique per page ([#72](https://github.com/derberg/OpenCrane/issues/72)) ([f9cbd21](https://github.com/derberg/OpenCrane/commit/f9cbd2134fb47b4e10dd7d18bafc431151084315))
* make pytest read pytest.ini ([#71](https://github.com/derberg/OpenCrane/issues/71)) ([ef27470](https://github.com/derberg/OpenCrane/commit/ef274704ec3390f61cf2d2b0b01e4a01dcf6e1b3))
* pass build file paths to index and select Milvus server mode from MILVUS_HOST ([#74](https://github.com/derberg/OpenCrane/issues/74)) ([6a7ab9c](https://github.com/derberg/OpenCrane/commit/6a7ab9c71a539a2ecd17beda61b3a65358a58cb6))
* podman build command, init --extensions, schema tool duplicates, and undocumented metadata ([#79](https://github.com/derberg/OpenCrane/issues/79)) ([d1df4c4](https://github.com/derberg/OpenCrane/commit/d1df4c4ec91151f2873b60a1c6a6701e03520a70))
* reserve the get_section tool name for extra tools ([#61](https://github.com/derberg/OpenCrane/issues/61)) ([d84e2eb](https://github.com/derberg/OpenCrane/commit/d84e2eb3bb84ff0543c67bb5992ad9ffa9297405))
* stop filter injection through search_docs parameters ([#87](https://github.com/derberg/OpenCrane/issues/87)) ([8708f75](https://github.com/derberg/OpenCrane/commit/8708f7518461785b66151857b7a628cfc0c70173))
* table cell pipes and per-version CRD paths ([#70](https://github.com/derberg/OpenCrane/issues/70)) ([a90a587](https://github.com/derberg/OpenCrane/commit/a90a587b9a5397a4fd4cdb19aa1275ce5d70cabf))
* take the vector dimension from the embedding model instead of hard-coding 768 ([#57](https://github.com/derberg/OpenCrane/issues/57)) ([1708fe5](https://github.com/derberg/OpenCrane/commit/1708fe5fc5446d9317be0f50eea41c69b1b53b0c))
* truncate Milvus VARCHAR fields by UTF-8 bytes within schema limits ([#65](https://github.com/derberg/OpenCrane/issues/65)) ([616eae0](https://github.com/derberg/OpenCrane/commit/616eae0c88fb3e626533a820280b8df53fdf4ece))


### Documentation

* apply the writing guidelines to the documentation ([#50](https://github.com/derberg/OpenCrane/issues/50)) ([e2ae8f5](https://github.com/derberg/OpenCrane/commit/e2ae8f505696c5fcdb60d88883d922e4f1a796c4))
* correct every doc against the code and cut repetition ([#62](https://github.com/derberg/OpenCrane/issues/62)) ([d3def04](https://github.com/derberg/OpenCrane/commit/d3def04c3b22205e255b54f5f2b572860ca743ea))
* describe the fixed embed skip, fetch field handling and reserved tool names ([#88](https://github.com/derberg/OpenCrane/issues/88)) ([0b53e76](https://github.com/derberg/OpenCrane/commit/0b53e76fd522a30052891a629dc47af0c0ea2c93))
* make the packaged metadata schema the single source ([#81](https://github.com/derberg/OpenCrane/issues/81)) ([7b4df6b](https://github.com/derberg/OpenCrane/commit/7b4df6b600eb900e78d54d4fe7ce06720ae6b79e))

## [0.32.0](https://github.com/derberg/OpenCrane/compare/v0.31.0...v0.32.0) (2026-09-15)


### Features

* advertise scopes in protected-resource metadata ([#47](https://github.com/derberg/OpenCrane/issues/47)) ([4b18ae7](https://github.com/derberg/OpenCrane/commit/4b18ae7b42cf525047042e4e6a614512a1cb5944))

## [0.31.0](https://github.com/derberg/OpenCrane/compare/v0.30.3...v0.31.0) (2026-09-14)


### Features

* automate releases with release-please ([#45](https://github.com/derberg/OpenCrane/issues/45)) ([418ae55](https://github.com/derberg/OpenCrane/commit/418ae55d912e49c3216e4e711cac419b02c3356b))
