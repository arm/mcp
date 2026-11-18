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

## Intrinsic Catalog Snapshot

Builds reuse the snapshot pinned by `intrinsic_chunks_image` in `pipeline-inputs.lock.json`.
To refresh it, prepare new and updated catalog records with `prepare_intrinsic_chunk`,
preserve their existing IDs and URLs, and publish the full snapshot at
`/embedding-data/intrinsic_chunks/` in a new image.
Update the pin to its published digest; builds use the previous snapshot until then.

## Add Documents

Add one row to `vector-db-sources.csv` for each document:

```csv
Site Name,License Type,Display Name,URL,Keywords,Transcript Source URL,Doc Type,Product,Platform
Learning Paths,CC4.0,Example Arm Guide,https://example.com/arm-guide,arm; migration; linux,,learning,arm,linux
```

Use clear keywords that users might include in questions. The `URL` is also what retrieval eval uses for expected matches.

### Learn content from public sources

All Learn acquisition uses public sources and requires no GitHub credentials.

| Content | Acquisition source |
| --- | --- |
| Learning Paths, Install Guides, migration and other Learn pages | Public `ArmDeveloperEcosystem/arm-learning-paths` repository |
| Courses | Published `https://learn.arm.com/courses/` pages and their lesson navigation |
| Insights | Published `https://learn.arm.com/insights/` pages and answer panels |

The Learning Paths repository's `production` branch is resolved once, then a
commit-pinned archive is streamed and only source files are retained. Override
`LEARN_LEARNING_PATHS_REF` with a branch, tag or commit SHA to choose its revision.
The parser uses Hugo frontmatter URLs, slugs and aliases, lowercases generated
page paths, and preserves the original case in repository source links. Drafts
(including cascaded drafts), future and expired pages are excluded. Retired or
unpublished repository-backed CSV rows are reported and omitted during reconciliation.

Courses and Insights are fetched from the public website, never their private
repositories. Course rows include lessons linked in the published curriculum;
a single lesson row includes just that lesson. Insights answers are parsed
separately, retaining each question in the heading path and its public answer
anchor even when answers reuse inner headings. Published quiz questions retain
correct/incorrect labels and explanatory feedback; completion and survey controls
are omitted. Discovery reads the public course and Insights listing cards.

Public page URLs stay in `url`. For repository content, `resolved_url` records
the public repository commit and source file; for courses and Insights it records
the public page URL. Web pages are reused within an acquisition run but can change
between runs, even when the Learning Paths repository revision is pinned.
`SKIP_DISCOVERY=1` prevents adding rows while still validating and acquiring the
specified public sources. Public website rows are not removed based on repository
contents. Learn fetch and parsing errors stop acquisition before the CSV or existing
chunks are replaced. Overlapping parent/child rows emit identical Learn chunks once.

Repository Markdown is rendered locally and passed through the shared content
parser. Code, tables, callouts, code-tab labels, prerequisites, learning objectives,
generated FAQs and further-reading links are retained. Heading IDs follow Hugo's
raw-heading sanitization and duplicate handling. Learning Path frontmatter sections
use the published `about-marker` and `generated-summary-faq` anchors. Unknown Hugo
shortcodes fail explicitly so new content formats cannot silently lose text.

Changes to this parsing code require rebuilding the toolchain and merging its
`automation/pin-embedding-generator` PR before rebuilding the corpus. The pinned
toolchain, not the current checkout, supplies the acquisition Python modules.
Acquisition first runs the pinned generator's CSV load/save roundtrip offline.
It fails if tags or rows are lost. Acquisition and promotion also verify that
retained sources preserve their overrides before replacing the CSV. Merge order:
generator changes and guard, then the reviewed toolchain image pin, then rebuilt
KB artifacts and their runtime pin. Never substitute an unverified image digest.

### Filter tags during ingestion

The optional `Doc Type`, `Product` and `Platform` CSV columns provide public
search tags. `Site Name` still selects the ingestion path; `Keywords` help text
retrieval and are not filter tags. Add only tags verified by the source.

| CSV column | Search filter | Values |
|---|---|---|
| `Doc Type` | `doc_type` | `learning`, `guide`, `reference`, `article`, `compatibility` |
| `Product` | `product` | Document publisher: currently `arm`, `aws`, `google`, `ampere` |
| `Platform` | `platform` | Verified execution environment, ISA, architecture, hardware family or hosted runtime; see below |

Choose Doc Type by the document's primary purpose:

| Tag | Use for |
|---|---|
| `learning` | Tutorials, courses, lessons and worked exercises |
| `guide` | Installation, operation, migration, tuning and troubleshooting instructions |
| `reference` | Intrinsic/instruction definitions, technical manuals, specifications and Insights FAQs |
| `article` | Explanations, overviews, white papers and benchmark analysis |
| `compatibility` | Supported software, operating-system and version catalogs |

Product identifies the **document publisher**, not the software discussed or the
hosting service. An Arm-published Docker tutorial or ArmEducationX course uses
`arm`; an AWS-published Graviton guide uses `aws`. Verify ownership before adding
a publisher. All three fields have fixed vocabularies. Add a new publisher to
`PRODUCTS` in `source_metadata.py` only after verifying ownership.

| Cell value | Meaning |
|---|---|
| `linux` | One explicit tag |
| `["linux","windows","macos"]` | Multiple tags in one cell |
| blank / omitted column | Inherit source metadata when available |
| `[]` | Explicitly clear this field, suppressing inherited tags |

Case and surrounding whitespace are normalized; duplicate labels are removed.
Unknown or inapplicable fields stay untagged. Do not enter placeholder labels
such as `unknown`, `all` or `n/a`. Invalid values fail with the field and source URL.
Use JSON arrays for multiple values, not comma- or semicolon-separated labels.
Use the exact column names above; misspellings such as `platform` or `Platforms`
fail validation instead of silently losing tags on save.

In a spreadsheet, enter the JSON array in one cell and let CSV export quote it.
When editing raw CSV, quote the cell and double its internal quotes:

```csv
Site Name,License Type,Display Name,URL,Keywords,Transcript Source URL,Doc Type,Product,Platform
Learning Paths,CC4.0,Example Arm Docker tutorial,https://example.com/arm-docker,docker; installation,,learning,arm,"[""linux"",""windows"",""macos""]"
Graviton Getting Started Guide,CC4.0,Example AWS Graviton guide,https://example.com/aws-graviton,graviton; migration,,guide,aws,linux
```

#### Platform values

| Scope | Accepted tags |
|---|---|
| Execution environment | `linux`, `windows`, `macos`, `android`, `baremetal`, `rtos`, `chromeos`, `freebsd` |
| ISA family | `neon`, `sve`, `sve2`, `sme`, `sme2`, `helium` |
| Architecture / hardware family | `cme`, `mali`, `cortex-m` |
| Hosted runtime | `google-colab` |

- Tag the environments or architectures the source substantively covers, including
  verified host/target environments and explicitly required setup. Incidental
  mentions, optional links and general software portability are insufficient.
- `baremetal` means software running without an OS. Physical cloud servers running
  Linux use `linux`. `Bare metal` and `Bare-metal` normalize to `baremetal`.
- Intrinsic cards derive ISA tags from their catalog families: `MVE` maps to
  `helium`, and combined groups receive each listed family. Unknown families remain
  blank. SVE2 does not imply SVE; streaming SVE mode alone does not imply `sve`.
- `cme` covers CME architecture, programming and performance monitoring. `mali`
  covers Mali GPU guidance, including Neural Accelerator (NX) guidance. `cortex-m`
  covers material explicitly targeting Cortex-M. These tags imply neither an OS,
  support for every hardware variant, nor additional ISA tags.
- `google-colab` requires a documented Colab execution environment. It implies no
  OS, CPU architecture or GPU model and does not change the publisher tag.
- Dashboard entries use their catalog platform (`linux` or `windows`), not every
  OS supported by the package. Keep verified OS tags when adding hardware/ISA tags.

#### Preservation and filtering

CSV loading, saving and discovery preserve explicit overrides, including blank
versus `[]`. Newly discovered sources have no override. Existing CSVs without tag
columns keep their layout; files with a subset keep that subset. Conflicting
explicit overrides for duplicate dashboard URLs fail validation.

Blank cells inherit verified adapter defaults: Learning Paths use `learning` /
`arm`, Install Guides use `guide` / `arm`, and dashboard records use
`compatibility` / `arm` plus their catalog OS. Mixed-purpose adapters still need
an explicit Doc Type. Learn Platform defaults come from the pinned repository's
`operatingsystems`, exact Cortex-M/Mali `armips`, and exact ISA values in
`tools_software_languages`. Lessons inherit their path's taxonomy unless the
lesson overrides that field. Body text and general keywords do not infer tags.
Install guides without structured platform metadata need a reviewed CSV tag.

An explicit Platform cell replaces the entire derived list; include the verified
OS and ISA/hardware tags together. Leave redundant overrides blank so future
frontmatter changes can flow through. `[]` suppresses every inherited tag for
that field. Builds print `[METADATA GAP]` with source URLs, unmapped OS warnings,
and source-chunk coverage; unknown or inapplicable values remain untagged.

For overlapping Learn sources, an explicitly configured child page or smaller
resource takes precedence field by field. Blank child fields inherit the parent;
`[]` clears them. Canonical membership, including aliases, determines precedence
independently of CSV row order. Same-scope conflicts fail before replacing outputs.

The dispatcher applies tags to every parsed chunk, including transcripts, child
pages and API topics. YAML and vector JSON preserve them in `filter_metadata`;
scalar metadata retains source identity for intrinsic ranking, dashboard variants
and document context. Explicit intrinsic overrides take precedence over defaults.

Search uses OR within a field and AND across fields; missing requested tags are
excluded. `["linux","sve"]` means Linux **or** SVE, not their intersection.
Older artifacts with a missing curated field fall back to legacy metadata;
`[]` suppresses fallback. All three result fields are arrays, including legacy
values; unknown values return `[]`. Legacy
Doc Type names remain query aliases when the public type is nonempty. Legacy
Product ISA labels are not aliases for publisher tags. Existing published
artifacts retain their old tags until the generator and corpus are rebuilt and
promoted. See the [search API](../arm_kb_search/README.md#filters) for client usage.

Edition is removed from contributor tags and public filters/results. Remove the
`Edition` column from older CSVs; ingestion rejects it with a migration message.
Raw dashboard edition remains internal so catalog variants stay distinct.

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


### Chunk versions

Use the source's explicit version, such as the Arm API's `versionLabel`, or an
empty string. Do not guess from titles, URLs, or content. Schemas stay unchanged.

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

PR smoke, the weekly benchmark, and `run-question-eval.sh` use the reviewed alias map.
For direct evaluator commands, add `--synonyms-path ../mcp-local/name-synonyms.json`.
Keep corpus, model, and questions fixed when comparing runs.

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

The recurring embedding workflow runs all 423 benchmark questions in a separate
job with read-only permissions. It evaluates the published candidate by digest,
or the same saved image in a dry run, after verifying its original image ID.
Evaluation runs without networking in the digest-pinned generator image, using
the candidate's model, metadata, and index. Code and corpus mounts are read-only;
only reports and temporary files are writable. No dependencies are installed in
the benchmark job. Benchmark scores and failures are reported without blocking
publication. Corpus build failures and security failures still block it.

The pinned generator image must include all locked evaluation dependencies;
the benchmark does not install packages at runtime.

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
uv run --locked python acquire-model.py --output .cache/embedding-model
uv run --locked pytest
```



## Arm AGI CPU product brief ingestion

`agi_product_brief.py` handles the public Arm AGI CPU product brief PDF. It
extracts the specification table using PDF layout information and emits a
self-contained chunk per CPU variant/SKU. Specification values come from the
downloaded PDF, including multiline cells; they are not maintained in code.
Introduction, benefits, individual highlights, rack-level overview, and reference
platforms receive descriptive headings. Performance-estimate and configurable-TDP
qualifications remain attached to the relevant content.

The adapter validates the expected headings, table rows, nonempty cells, and
unique variant/SKU identities. An unfamiliar or incomplete structure raises an
error rather than falling back to ambiguous flattened specifications. It is
selected only for the brief's Arm-hosted URL. Other PDFs retain generic parsing.
Acquisition and validation happen before rewriting the sources CSV or deleting
existing chunks; the validated chunks are reused without a second download.
All parsed PDF pages now cite `#page=N`, while `resolved_url` retains the fetched
document URL. Rebuild the toolchain and regenerate chunks/vector artifacts to
publish these changes.

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

Raw dashboard metadata for internal source identity:

- `doc_type`: `Ecosystem Dashboard` for both platforms.
- `platform`: `linux` or `windows`, from the source directory.
- `edition`: `open-source` or `commercial` for the corresponding Linux catalog.
  Windows `all_packages` does not establish an edition, so its value is empty.
- `product` and `version`: explicitly empty. Package identity is separate from
  product taxonomy, and minimum/recommended versions remain distinct content facts.

The shared chunker, YAML serialization and vector metadata retain the raw
`platform` and `edition` values for source identity. Public search results expose
only Doc Type, Product and Platform; Edition is not accepted as a filter or
returned as a result field. Same-name catalog records can still disagree on
support or minimum versions, so their facts and identities remain separate.

The dashboard consumer's historical [proposed contract in PR #1092](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/1092)
requested an Edition result field. That proposal must be revised for this
three-filter contract before enabling a consumer that depends on it.

## Intrinsic embedding records

Acquisition prepares clean intrinsic metadata and one `embedding_text` containing
the operation, signature, and type descriptions. The builder embeds it once in
the shared index, preserves the full source for responses, and excludes
`embedding_text` from saved metadata.

Public Platform tags come from the stored catalog family, independently of the
embedding text. Adding support for a family label does not acquire that family's
records; refreshing the intrinsic snapshot is a separate operation.

Rebuild and pin the updated toolchain, then regenerate chunks before rebuilding
the vector store. Intrinsic chunks require prepared metadata and `embedding_text`;
missing preparation or descriptions over 500 tokens fail the build. Publish the
model, metadata, and index together.
