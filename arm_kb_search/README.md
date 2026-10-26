# arm-kb-search

Shared Python retrieval library used by the Arm MCP server and other
applications. Search combines keyword and vector retrieval and returns ranked
results with URLs, snippets, and document metadata.

## Usage

Install with `pip install .` from the repository root. Load the metadata,
vector index, and embedding model from the same knowledge-base bundle:

```python
from arm_kb_search import SearchFilters, load_search_resources, search

resources = load_search_resources(
    metadata_path="data/metadata.json",
    usearch_index_path="data/usearch_index.bin",
    model_path="data/embedding-model",
)
results = search(
    "deploy containers",
    resources,
    k=5,
    filters=SearchFilters(doc_type="Learning Paths", product="AWS Graviton"),
)
```

Reuse the loaded resources across requests. Create new resources when replacing
the corpus; metadata and indexes are treated as a fixed snapshot.

## Filters

`filters` accepts a `SearchFilters` instance or a dictionary with optional
`doc_type`, `product`, `platform`, and `edition` fields.

- Values match complete metadata strings after trimming whitespace and case
  folding. Multiple fields combine with AND; use values present in your corpus.
- Omitted filters, `None`, and `{}` leave search unrestricted. A field set to
  `None` is ignored. Missing or blank metadata cannot match an active filter.
- Invalid dictionary keys, blank strings, and non-string filter values raise
  `ValueError`. No matching chunks returns an empty list.

Filters restrict candidates before ranking and deduplication. Vector retrieval
uses exact search over the full corpus, or only eligible vectors when filtered.

## Retrieval behavior

Keyword search uses tokens from document search text; vector search embeds the
original query. Keyword matching and field scoring recognize Arm64/AArch64 equivalents.
Short execution requests prioritize the named tool over generic action words.

Installation intent includes "set up". When a short installation subject precedes
platform context, scoring emphasizes that subject while retaining explicit
operating-system and architecture terms. Installation queries consider at least
200 dense candidates to reduce candidate-cutoff misses; metadata filters still
restrict both retrieval channels before scoring.

The extra installation-guide bonus requires matching product evidence.
Learning-path overview bonuses depend on query intent and title/URL overlap.
Contribution footers and structurally identified chapter menus are removed,
preserving substantive introductions and next steps. One bounded candidate refill
is available if filtering leaves too few results; it repeats vector search.

Results retain distinct heading sections, intrinsic identifiers, and meaningful
URL parameters. Tracking aliases collapse. Markdown dashboard records use their
public package URL and edition as identity, so duplicate acquisition files
collapse while commercial and open-source editions remain separate.

The final ranking combines reciprocal hybrid resource rank (80%) with semantic
resource rank (20%) before the candidate cutoff. The returned passage comes from
the hybrid-selected piece, expanded to its complete original chunk when available.
Metadata filters apply to both channels and to any refill before ranking.

Intrinsic retrieval matches catalog and expanded function names, and uses the
requested ISA and signature types to improve ranking.

See [CONTRIBUTING.md](../CONTRIBUTING.md#versioning-arm-kb-search) for package
versioning guidance.


## Technical names and reviewed aliases

Whole-name matching recognizes corpus-backed technical names across spaces,
hyphens, underscores, internal dots and joined forms. Complete names count once
in field scoring, and lookup adds at most 100 candidates after metadata filtering.
Ordinary BM25 statistics, embedding queries, snippets and source content remain
unchanged. Matching never bridges independent fields or intervening words.

Prepare the artifact offline after metadata and chunk IDs are finalized:

```bash
python -m arm_kb_search.build_names \
  --metadata data/metadata.json \
  --aliases mcp-local/name-aliases.json \
  --output data/names.json \
  --report data/name-coverage.json
```

Omit `--aliases` for formatting-only matching and `--report` if a separate coverage
report is not needed. Each reviewed alias group supplies a canonical name, exact
corpus labels, accepted aliases and provenance, for example:

```json
{
  "canonical": "Maple Studio Editor",
  "labels": ["Maple Studio Editor (MSE)"],
  "aliases": ["MSE"],
  "provenance": "Reviewed abbreviation in the source catalog"
}
```

The alias input is a JSON array of such groups. Aliases are never inferred from
parentheses, imports or prose. Review ordinary-language ambiguity before adding
a group; `MAX` is excluded because it also means a maximum. Rejected groups print
their reason and corrective action to stderr even without `--report`, and the JSON
build summary includes `rejected_aliases`. Missing optional corpus labels and
conflicting relationships are skipped; malformed definitions fail the build.

Load the artifact with the exact metadata snapshot used to prepare it:

```python
resources = load_search_resources(
    metadata_path="data/metadata.json",
    usearch_index_path="data/usearch_index.bin",
    model_path="data/embedding-model",
    name_index_path="data/names.json",
)
```

Omitting `name_index_path` explicitly selects ordinary retrieval. A configured
missing, damaged, stale or mismatched artifact fails loading; it is never silently
disabled or rebuilt at startup. **Rebuild all older artifacts for schema 5**, and
rebuild whenever metadata content/order, aliases or matching policies change.
Deploy the matching metadata/artifact pair together; existing vectors can be reused.

The MCP Dockerfiles build `/app/data/names.json` offline using the final bundled
metadata and `mcp-local/name-aliases.json`. Server startup loads the saved artifact;
`NAME_INDEX_PATH` can select another prepared file. Saved document spans and token
adjustments avoid a runtime corpus scan or another full-corpus token cache.

Short installation requests use their product subject and explicit platform
constraints for field overlap, retaining original intent and the existing
short/long-query decision. Title and heading evidence distinguish product-focused
documents from body-only prerequisites. For an already reviewed parenthetical
label, URL scoring recognizes the complete slug, such as
`maple-studio-editor-mse`, without authorizing new query aliases or partial names.
Numeric versions, unsupported editions and conflicting product identities remain
excluded. Protected C/C++/C#, leading-dot names, API/intrinsic identifiers, ISA
and signed/unsigned type distinctions retain their existing handling.

The standard evaluator and MCP smoke test can exercise the prepared index:

```bash
python embedding-generation/evaluate_retrieval.py \
  --suite smoke --metadata-path data/metadata.json \
  --index-path data/usearch_index.bin --model-path data/embedding-model \
  --name-index-path data/names.json --output /tmp/name-smoke.json
```

Use a new output path for each run. Omit `--name-index-path` for a baseline, using
identical metadata, vectors, model and suite settings.
