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

Review the printed `[NEW SOURCE]` lines and draft coverage questions in a separate evaluation JSON file, then commit the updated CSV. Keep the checked-in evaluation suites fixed during retrieval improvements; suite additions follow the [review process](../CONTRIBUTING.md#adding-questions-and-accepted-urls). The production build chunks the new rows automatically — `generate-chunks.py` already handles developer.arm.com documentation and community blog URLs found in the CSV.

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
Keep these suites fixed during retrieval improvements. Separate question sets,
including holdouts, use the same runner with `--eval-path FILE`. Dataset changes
or verified stale-label corrections require separate review and a fresh baseline.

To rebuild the local corpus and run the benchmark:

```sh
uv run --locked ./run-question-eval.sh
uv run --locked ./run-question-eval.sh --id B001 --id B002 --output reports/selected.json
```

The wrapper copies intrinsic chunks if needed, regenerates chunks, acquires the
locked model, rebuilds the index, and invokes the same evaluator. It accepts
`--suite`, repeatable `--id`, `--output`, and `--baseline`.
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
uv run --locked python evaluate_retrieval.py --suite benchmark \
  --model-path .cache/embedding-model --baseline reports/benchmark.json \
  --output reports/benchmark-next.json
```

Repeat `--id` to select questions for a focused investigation; unknown IDs fail.
Omit `--id` to run the full suite. Changes to sources, the embedding model, or
the ranking algorithm need the full benchmark to check for broader regressions.

Default depth is five. Smoke requires every selected question to retrieve an
accepted source within that depth (exit 1 for a miss). Benchmark misses are
report-only (exit 0). Invalid data, model/index failures, and query errors fail
both modes (exit 2). PR checks always use the whole smoke suite at depth five;
a local subset run does not certify the full suite. Hit@3/5 is unavailable when
the requested depth is lower than its cutoff. MRR is truncated at that depth.
The weekly workflow treats all benchmark steps as report-only: a benchmark
failure is shown as unavailable and does not block image publication. Corpus
build failures and security checks still block publication.

Matching preserves the existing suite policies:

- Smoke accepts the expected page or a child path, ignoring query strings,
  fragments, and trailing slashes. A sibling path or different origin does not
  match. This is a useful-resource coverage check, not exact section coverage.
- Benchmark preserves meaningful query parameters, fragments, platform paths,
  and package/intrinsic selectors. Only tracking `utm_*` parameters, query-pair
  order, host/scheme case, and trailing slashes are normalized.

Smoke and benchmark scores measure different criteria and are not directly
comparable. Promotion to smoke explicitly adopts its page/child matching policy.

Console output and the GitHub Actions Summary show tables with overall pass
percentage and retrieval metrics, followed by intent and topic pass percentages.
The benchmark does not print individual misses. Download the JSON artifact for
per-question ranks/URLs/errors and category metrics. Reports record the Git
revision and `EVAL_TARGET` image reference when available; they do not hash the
model, corpus, or source files.
Runs with execution errors show an unavailable message instead of score tables.
With a compatible baseline, the tables show previous/current results and changes
overall, by topic, and by intent. Rate changes are percentage points; MRR changes
are numeric differences. Individual regressions/recoveries remain in JSON only.
Comparisons require the same question IDs, question text, accepted URLs, matching
rules, and depth, with no execution errors. Metrics are recalculated from stored
ranks, using the current topic/intent labels for both runs. A missing, invalid,
or incompatible baseline leaves current results visible with an explanation
that comparison is unavailable.

PR smoke reports are retained as `retrieval-smoke-*` Actions artifacts. Weekly
reports are retained as `retrieval-benchmark` (90 days requested, subject to
repository retention limits). The weekly job checks the latest 20 successful
runs of the same workflow and branch for the most recent completed benchmark
report, skipping missing artifacts and failed evaluations. It uses that report
automatically as the baseline and links its run in the Actions Summary. The
first run, or an incompatible baseline, shows current results only.
The weekly job evaluates the newly built vectorstore, not the previously
released corpus. It also runs during manual pipeline dry runs.
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
