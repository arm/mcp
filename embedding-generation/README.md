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

Review the printed `[NEW SOURCE]` lines and commit the updated CSV. Propose benchmark coverage in a separate reviewed dataset change, following the [review process](../CONTRIBUTING.md#adding-questions-and-accepted-urls). Keep the checked-in evaluation suites fixed during retrieval improvements. The production build chunks the new rows automatically — `generate-chunks.py` already handles developer.arm.com documentation and community blog URLs found in the CSV.

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

One evaluator runs the stable smoke suite on every PR and the full benchmark in
the existing recurring embedding refresh. The suites are `../evals/smoke.json` and
`../evals/benchmark.json`. Select either checked-in suite with `--suite`.
Keep these suites fixed during retrieval improvements. Each question
requires a unique, nonempty `id`, a `question`, and a nonempty `expected_urls` list.
Smoke questions also require `area`; benchmark questions require `topic` and `intent`.
Dataset changes or verified stale-label corrections require separate review and
a fresh baseline.

To rebuild the local corpus and run the benchmark:

```sh
uv run --locked ./run-question-eval.sh
```

The wrapper copies intrinsic chunks if needed, regenerates chunks, acquires the
locked model, rebuilds the index, and invokes the same evaluator. It accepts
`--suite`, `--eval-path`, `--output`, and `--baseline`.
Relative paths passed to the wrapper are relative to this directory. Use a new
output filename for each run.

To evaluate an existing local corpus without rebuilding it:

```sh
uv run --locked python evaluate_retrieval.py --suite smoke \
  --model-path .cache/embedding-model --output reports/smoke.json
uv run --locked python evaluate_retrieval.py --suite benchmark \
  --model-path .cache/embedding-model --output reports/benchmark.json
uv run --locked python evaluate_retrieval.py --suite benchmark \
  --model-path .cache/embedding-model --baseline reports/benchmark.json \
  --output reports/benchmark-next.json
```

For local experiments, pass `--eval-path` to use a custom question file without
editing the checked-in datasets. It must meet the selected suite's validation
requirements; `--suite` still controls URL matching and pass/fail behavior:

```sh
uv run --locked python evaluate_retrieval.py --suite benchmark \
  --eval-path /path/to/questions.json --model-path .cache/embedding-model \
  --output reports/local.json
```

Every run evaluates all questions in the selected file. PR smoke runs all 50
questions alongside the MCP integration tests against the candidate image. Every question
must retrieve an accepted source in the top five results; a miss or execution
error fails the required integration check and blocks merging.

The recurring embedding workflow runs all 408 benchmark questions against the
newly built corpus. Benchmark scores and evaluation failures are reported without
blocking publication. Corpus build failures and security failures still block it.

Smoke accepts the expected page or a child path on the same origin, ignoring
query strings and fragments. Benchmark uses stricter matching that preserves
meaningful query parameters, fragments, and resource paths while ignoring
`utm_*` tracking parameters. The two suites' scores are not directly comparable.

View aggregate results in the terminal or GitHub Actions Summary. Download
`retrieval-smoke-*` or `retrieval-benchmark` Actions artifacts for individual
question results. The recurring job compares against a compatible benchmark
report from the latest successful run of the same workflow and branch. If that
report is unavailable or incompatible, it shows current results only. Comparisons
require unchanged category labels. Older reports without saved category labels
cannot be used as baselines; the next completed report establishes a new baseline.

New sources need a rebuilt local corpus: building the MCP image alone uses its
pinned embedding artifact. See [contribution guidance](../CONTRIBUTING.md#retrieval-evaluations)
for source-label rules and miss investigation.

Run lint and tests with:

```sh
uv run --locked ruff check .
uv run --locked pytest
```



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
