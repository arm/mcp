# Embedding Generation

This directory builds the vector database artifacts used by the MCP server:

- `metadata.json`
- `usearch_index.bin`

## Build the Docker Image

From this directory:

```sh
docker build -t arm-mcp-embeddings .
```

The Dockerfile:

1. Starts from `armlimited/arm-mcp:mcp-embedding-base` to copy cached intrinsic chunks.
2. Installs the Python dependencies in a build stage.
3. Downloads the sentence-transformer model into the build cache.
4. Runs `generate-chunks.py vector-db-sources.csv`.
5. Runs `local_vectorstore_creation.py`.
6. Copies only `metadata.json` and `usearch_index.bin` into the final image.

## Add Documents

Add one row to `vector-db-sources.csv` for each document:

```csv
Site Name,License Type,Display Name,URL,Keywords
Example Docs,CC4.0,Example Arm Guide,https://example.com/arm-guide,arm; migration; linux
```

Use clear keywords that users might include in questions. The `URL` is also what retrieval eval uses for expected matches.

## Discover developer.arm.com Sources

`discover-developer-arm-com-sources.py` searches developer.arm.com and appends any new relevant pages (currently SME-related guides, programmer's guides, and blog posts) to `vector-db-sources.csv`. Existing rows are never modified, so it is safe to re-run occasionally to pick up new content.

It is intentionally not part of the weekly Docker build: it needs Playwright and Chromium (heavy dependencies we don't want in the build image), and each run should be reviewed by a human rather than ingested sight unseen.

Run it manually from this directory:

```sh
pip install playwright && playwright install chromium
python discover-developer-arm-com-sources.py vector-db-sources.csv
```

Review the printed `[NEW SOURCE]` lines, add a question with the new URL in `expected_urls` to `eval_questions.json` for each one, then commit the updated CSV. The weekly build chunks the new rows automatically — `generate-chunks.py` already handles developer.arm.com documentation and community blog URLs found in the CSV.

## Test Locally

Install dependencies once:

```sh
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

Run the full local question eval:

```sh
./run-question-eval.sh
```

That command copies intrinsic chunks from the embedding base image if needed, regenerates chunks, caches the embedding model if needed, rebuilds the local USearch index, and runs `evaluate_retrieval.py`.

Useful options:

```sh
./run-question-eval.sh --refresh-intrinsic-chunks
./run-question-eval.sh --eval eval_questions.json --top-k 5
SKIP_DISCOVERY=1 ./run-question-eval.sh
```

To check a new document, add or update a question in `eval_questions.json` with the document URL in `expected_urls`, then run the wrapper. Review `Hit@1`, `Hit@3`, `Hit@5`, `MRR`, and any printed misses before committing the CSV change.
