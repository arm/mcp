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
    synonyms_path="mcp-local/name-synonyms.json",  # Optional; enables name aliases.
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

## Startup preparation

MCP images prepare keyword tokens during the image build, alongside the supplied
vector index. At startup the library loads `metadata.keywords.json.gz` next to
`metadata.json` and constructs the in-memory BM25 statistics from those tokens.
A valid cache avoids repeating name analysis across the corpus.

Library users can prepare the same optional artifact before starting a service:

```python
from arm_kb_search.resources import write_keyword_cache

write_keyword_cache("data/metadata.json", synonyms_path="mcp-local/name-synonyms.json")
```

Use the same synonym map when loading resources. `cache_path` on the writer and
`keyword_cache_path` on `load_search_resources()` allow a different artifact
location. The compressed JSON contains vocabulary IDs, not executable objects.
It is validated against metadata order/content, the synonym file, analyzer source,
Python version and the tokenizer version. Missing, stale or damaged artifacts fall
back to normal indexing; startup will be slower until the artifact is rebuilt.
Runtime loading never writes files, so read-only containers remain supported.
Metadata and synonym inputs must remain unchanged while resources are loading.

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

## Name synonyms

Name synonyms connect alternative names and spellings, so a query using one
can match documents using another in the same group. Spaces, hyphens,
underscores and dots can separate the same name parts; joined spellings must
be listed explicitly.

Edit `mcp-local/name-synonyms.json` directly; no generation step is needed.
For example, one group can contain:

```json
{"awscli": ["aws cli", "awscli"]}
```

Keys identify groups; lists contain the accepted names and aliases.
The MCP server loads the map at startup. Set `NAME_SYNONYMS_PATH` to override
its location. For library use, pass `synonyms_path` to `load_search_resources()`;
omitting it disables aliases. Missing or invalid configured files fail loading.

## Retrieval behavior

Keyword search analyzes metadata fields, heading-path elements and the original
body separately, so adjacent fields cannot form a product name. `original_text`
(or legacy `content`) is authoritative even when empty; `search_text` is used as
a fallback only when neither body field is available. Existing snapshots that
retain these fields need no vector regeneration. Name-related keyword and phrase
scores require complete names; Unicode identifier continuations stay literal.

Keyword analysis reads source text, including Markdown link/reference metadata.
It does not render Markdown or reconstruct names in or across links. Normalize
documents before indexing if rendered-text matching is required.

Vector search embeds the original query. Keyword matching and field scoring
recognize Arm64/AArch64 equivalents.
Short execution requests prioritize the named tool over generic action words.

Installation intent includes "set up". Scoring emphasizes a short installation
subject with or without platform context, retaining operating-system and architecture
terms. Complete names are recognized before context separators. Installation queries
consider at least 200 dense candidates to reduce candidate-cutoff misses; metadata
filters still restrict both retrieval channels before scoring.

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
