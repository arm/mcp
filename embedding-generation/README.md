# Embedding Generation

This directory produces and packages the vector-store assets used by the MCP server:

- Generated `metadata.json`
- Generated `usearch_index.bin`
- A pinned, locally saved Sentence Transformers model in `embedding-model/`

These assets are published together in the final vector-store image and used as
inputs to the MCP image build.

## Build the Toolchain Image

From this directory:

```sh
docker build -f Dockerfile.toolchain -t arm-mcp-embedding-generator .
```

The toolchain image:

1. Installs the exact Python dependencies recorded in `uv.lock`.
2. Acquires the sentence-transformer revision recorded in `embedding-model.lock.json`.
3. Confirms that the saved model loads with networking disabled.
4. Copies the locked environment, local model, and generation scripts into the
   final image without `uv`, `pip`, or `ensurepip` and its bundled pip wheel.

When a file baked into the toolchain changes on `main`, including its
Dockerfile, Python or model locks, acquisition code, or generation scripts,
GitHub Actions rebuilds this image and opens or updates
`automation/pin-embedding-generator`. That PR updates
`pipeline-inputs.lock.json` to the new immutable digest. The workflow also
supports manual branch runs, which publish an image without opening a PR.

`Dockerfile.acquire` uses this toolchain for network-enabled discovery and
content acquisition, then publishes only the acquired chunk snapshot from a
scratch stage. `Dockerfile.vectorstore` uses the same toolchain and that
immutable chunk snapshot to build `metadata.json` and `usearch_index.bin`
without network access. The scratch output also includes the exact local model
used to generate the index, keeping the model, metadata, and index together as
one immutable artifact. It is published privately as
`ghcr.io/arm/mcp-embedding-vectorstore`.

## Promote an Embedding Build into MCP

The embedding pipeline publishes candidates; it does not cause the MCP image
to consume the newest registry artifact automatically. To promote a candidate:

1. Let **Build Offline Embedding Pipeline** run from `main` every Sunday at
   09:00 UTC, or start it manually for an out-of-band update.
2. After publishing the vector store, the workflow opens or updates the
   `automation/pin-embedding-vectorstore` PR with the immutable digest in both
   `mcp-local/build-inputs.lock.json` and `mcp-local/Dockerfile`, along with the
   next minor version in `mcp-local/server.json`.
   The same PR updates `vector-db-sources.csv` from that run's immutable chunk artifact.
3. Review the source revision, image digest, and proposed version.
4. Merge the approved PR to publish the MCP release using that exact embedding
   digest and version.

The workflow does not merge the promotion PR. A candidate can therefore be
generated, evaluated, and rejected without changing the released MCP image.
For a major or hotfix release, run **Build MCP Image** manually with the
corresponding release action; it opens a separate reviewed version PR.

## Add Documents

Add one row to `vector-db-sources.csv` for each document:

```csv
Site Name,License Type,Display Name,URL,Keywords,Transcript Source URL
Example Docs,CC4.0,Example Arm Guide,https://example.com/arm-guide,arm; migration; linux,
```

Use clear keywords that users might include in questions. The `URL` is also what retrieval eval uses for expected matches.

## Discover developer.arm.com Sources

`discover-developer-arm-com-sources.py` searches developer.arm.com and appends any new relevant pages (currently SME-related guides, programmer's guides, and blog posts) to `vector-db-sources.csv`. Existing rows are never modified, so it is safe to re-run occasionally to pick up new content.

It is intentionally not part of the production Docker build: it needs Playwright and Chromium (heavy dependencies we don't want in the build image), and each run should be reviewed by a human rather than ingested sight unseen.

Run it manually from this directory:

```sh
pip install playwright && playwright install chromium
python discover-developer-arm-com-sources.py vector-db-sources.csv
```

Review the printed `[NEW SOURCE]` lines, add a question with the new URL in `expected_urls` to `eval_questions.json` for each one, then commit the updated CSV. The production build chunks the new rows automatically — `generate-chunks.py` already handles developer.arm.com documentation and community blog URLs found in the CSV.

### Transcript-backed sources

Some sources (for example edX course videos) do not have directly chunkable text
at their primary `URL`. For these, populate the optional `Transcript Source URL`
column with a link to a plain-text, markdown, PowerPoint (`.pptx`), or Jupyter
notebook transcript (such as a GitHub `.../blob/...` file). When
`Transcript Source URL` is set,
`generate-chunks.py` fetches and chunks the transcript instead of the primary
`URL`, but keeps the primary `URL` as the user-facing link returned by retrieval:

```csv
Site Name,License Type,Display Name,URL,Keywords,Transcript Source URL
Educational Course,All rights reserved,Example Video,https://courses.edx.org/videos/...arm, ai; inference,https://github.com/arm-education/.../M1KV1.txt
```

Leave the column empty for sources that are chunked from their primary `URL`.


## Test Locally

Install dependencies once:

```sh
uv sync --locked
```

Python 3.13 is required.

Run the full local question eval:

```sh
uv run --locked ./run-question-eval.sh
```

That command copies intrinsic chunks from the embedding base image if needed,
regenerates chunks, acquires the revision in `embedding-model.lock.json`, rebuilds
the local USearch index from that local model, and runs `evaluate_retrieval.py`
without model network access.

Useful options:

```sh
uv run --locked ./run-question-eval.sh --refresh-intrinsic-chunks
uv run --locked ./run-question-eval.sh --eval eval_questions.json --top-k 5
SKIP_DISCOVERY=1 uv run --locked ./run-question-eval.sh
```

Run lint and tests with:

```sh
uv run --locked ruff check .
uv run --locked pytest
```

To check a new document, add or update a question in `eval_questions.json` with the document URL in `expected_urls`, then run the wrapper. Review `Hit@1`, `Hit@3`, `Hit@5`, `MRR`, and any printed misses before committing the CSV change.

## Ecosystem Dashboard ingestion

`ecosystem_dashboard.py` resolves the dashboard repository's `main` branch once
per run and downloads a commit-pinned archive. Discovery and chunk generation
share this snapshot. Set `ECOSYSTEM_DASHBOARD_REVISION` to a full 40-character
commit SHA to reproduce a run. Every chunk's `resolved_url` records the exact
Markdown source revision; its `url` points to the public Linux or Windows package
page. Acquisition reads archive members in memory without extracting files.

The same module converts package frontmatter into shared chunker documents.
It includes descriptions, categories, vendor information, support status,
minimum/recommended versions and dates, recommendation rationale, caveats,
alternatives, and labeled resource links. Markdown bodies use the shared parser.
Test-run output and maintenance fields are excluded. Missing support is unknown,
not unsupported; version spelling is preserved (`3.10` stays `3.10`).

Invalid individual records produce a warning with their source URL and reason and
are skipped. Misplaced guidance fields are invalid rather than silently omitted.
There are no package-specific fixes or HTML fallbacks. A failed download, invalid
archive/revision, or snapshot with no usable packages for either platform fails
acquisition before the existing source CSV or chunk snapshot is overwritten.
Review skipped-record warnings, omitted-source notices, and package counts before
promotion. Fixed upstream records return on the next discovery run.

The CSV keeps one row per dashboard package URL, using
`https://developer.arm.com/ecosystem-dashboard/{platform}?package={slug}`.
Source matching uses these URLs exactly; custom CSVs must use this format too.
Reconciliation preserves curated keywords for retained sources and reports removed
or invalid sources. `SKIP_DISCOVERY=1` retains only existing dashboard rows and
does not add new packages. Normal discovery also adds new Linux and Windows packages. Source records sharing a URL remain distinct in
chunking through their pinned Markdown `resolved_url`. Retrieval keeps the
highest-ranked hit per public URL and edition, so duplicate source files in the
same edition do not consume additional result slots.

Metadata for downstream dashboard search:

- `doc_type`: `Ecosystem Dashboard` for both platforms.
- `platform`: `linux` or `windows`, from the source directory.
- `edition`: `open-source` or `commercial` for the corresponding Linux catalog.
  Windows `all_packages` does not establish an edition, so its value is empty.
- `product` and `version`: explicitly empty. Package identity is separate from
  product taxonomy, and minimum/recommended versions remain distinct content facts.

The shared chunker, YAML serialization, vector-store metadata, and shared search
response preserve `platform` and `edition`. Other sources and older artifacts
return empty values unless supplied. The shared search package version changes
with this response extension; REST deployments must update their package pin to
receive the fields. No request filters are added here.

The dashboard consumer's [proposed contract in PR #1092](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/1092)
requires `doc_type`, `platform`, and `edition` on Linux hits, plus filtering before
top-k selection. STESOL-625 must coordinate these scope filters as well as its
planned `product` filter. The consumer's live integration remains disabled until
that contract is implemented and verified. Same-name source records may disagree
on support or minimum versions; ingestion preserves their facts and reports shared
URLs rather than selecting an authoritative record.
