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

Review the printed `[NEW SOURCE]` lines, add a question with the new URL in `expected_urls` to `../evals/benchmark.json` for each one, then commit the updated CSV. The production build chunks the new rows automatically — `generate-chunks.py` already handles developer.arm.com documentation and community blog URLs found in the CSV.

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
the existing Sunday embedding refresh. The suites are `../evals/smoke.json` and
`../evals/benchmark.json`; the old `eval_questions.json` is historical input.

To rebuild the local corpus and run the benchmark:

```sh
uv run --locked ./run-question-eval.sh
uv run --locked ./run-question-eval.sh --changed-since upstream/main --output reports/changed.json
```

The wrapper copies intrinsic chunks if needed, regenerates chunks, acquires the
locked model, rebuilds the index, and invokes the same evaluator. It accepts
`--suite`, repeatable `--id`, `--changed-since`, `--output`, and `--baseline`.
`--eval FILE` remains available for a custom question file. A relative report
path is relative to this directory. Use a new output filename for each run.

To evaluate an existing local corpus without rebuilding it:

```sh
uv run --locked python evaluate_retrieval.py --suite smoke \
  --model-path .cache/embedding-model --output reports/smoke.json
uv run --locked python evaluate_retrieval.py --suite benchmark \
  --model-path .cache/embedding-model --output reports/benchmark.json
uv run --locked python evaluate_retrieval.py --suite benchmark --id B001 --id B002 \
  --model-path .cache/embedding-model
uv run --locked python evaluate_retrieval.py --suite benchmark --changed-since upstream/main \
  --model-path .cache/embedding-model
uv run --locked python evaluate_retrieval.py --suite benchmark \
  --model-path .cache/embedding-model --baseline reports/benchmark.json \
  --output reports/benchmark-next.json
```

`--changed-since` compares parsed records by ID against the branch merge base,
including uncommitted additions/edits. Removed IDs are reported. Formatting and
record ordering do not select questions. Invalid refs and unknown IDs fail;
no changed questions is an explicit no-op. Fetch the base branch/history first.
This filter selects changed questions, not every question affected by a changed
source, embedding model, or ranking algorithm. Run the full benchmark for those
changes. ID selection and changed-since selection are mutually exclusive.

Default depth is five. Smoke requires every selected question to retrieve an
accepted source within that depth (exit 1 for a miss). Benchmark misses are
report-only (exit 0). Invalid data, model/index failures, and query errors fail
both modes (exit 2). PR checks always use the whole smoke suite at depth five;
a local subset run does not certify the full suite. Hit@3/5 is unavailable when
the requested depth is lower than its cutoff. MRR is truncated at that depth.

Matching preserves the existing suite policies:

- Smoke accepts the expected page or a child path, ignoring query strings,
  fragments, and trailing slashes. A sibling path or different origin does not
  match. This is a useful-resource coverage check, not exact section coverage.
- Benchmark preserves meaningful query parameters, fragments, platform paths,
  and package/intrinsic selectors. Only tracking `utm_*` parameters, query-pair
  order, host/scheme case, and trailing slashes are normalized.

Console output and the GitHub Actions Summary show tables with overall pass
percentage and retrieval metrics, followed by intent and topic pass percentages.
The benchmark does not print individual misses. Download the JSON artifact for
per-question ranks/URLs/errors and category metrics. Reports record the Git
revision and `EVAL_TARGET` image reference when available; they do not hash the
model, corpus, or source files.
Errors are separate from misses and contribute zero to headline rates.
Benchmark comparisons show metric deltas and regressed/recovered IDs for the
same question IDs, question text, accepted URLs, matching rules, and depth, with
no execution errors. Metrics are recalculated from the stored ranks, so older
reports remain usable without relying on cached metrics or fingerprints.
Changed questions or accepted URLs need a fresh baseline. No supplied baseline
means no regression claim.

PR smoke reports are retained as `retrieval-smoke-*` Actions artifacts. Weekly
reports are retained for 90 days as `retrieval-benchmark`; download two reports
for an explicit comparison. The weekly job evaluates the newly built vectorstore,
not the previously released corpus. It also runs during manual pipeline dry runs.
The published scratch vectorstore is copied from a stopped container and
searched using the locked evaluation environment; no second runner is involved.

New sources need a rebuilt local corpus: building the MCP image alone uses its
pinned embedding artifact. See [contribution guidance](../CONTRIBUTING.md#retrieval-evaluations)
for source-label rules, miss investigation, and smoke promotion.

Run lint and tests with:

```sh
uv run --locked ruff check .
uv run --locked pytest
```
