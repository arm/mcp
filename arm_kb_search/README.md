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

MCP images cache keyword tokens in `metadata.keywords.json.gz` beside
`metadata.json`. Startup builds BM25 statistics from these tokens.
Library users can prepare the cache with the same synonym map:

```python
from arm_kb_search.resources import write_keyword_cache
write_keyword_cache("data/metadata.json", synonyms_path="mcp-local/name-synonyms.json")
```

Missing, stale or damaged caches fall back to slower indexing in memory.
Runtime loading writes no files. Keep metadata and synonyms unchanged during loading.

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

Edit `mcp-local/name-synonyms.json` directly, e.g. `{"awscli": ["aws cli", "awscli"]}`.
Names in a group match each other. Spaces, hyphens, underscores and dots are
equivalent separators; joined forms must be listed explicitly.

The MCP server loads this map; override it with `NAME_SYNONYMS_PATH`.
Library users opt in with `synonyms_path`. Missing or invalid configured maps fail loading.

## Retrieval behavior

Keyword analysis keeps fields separate and matches complete names without
splitting Unicode identifiers. It uses `original_text` or legacy `content`
(including empty values), falling back to `search_text` only if neither is available.

Markdown is analyzed as source text: link metadata remains searchable and names
inside or across links may not match. Normalize documents first if needed.

Vector search embeds the original query; keyword scoring recognizes Arm64/AArch64.
Short execution requests prioritize the named tool.

Installation queries (including "set up") prioritize the named product while
retaining platform context. They consider at least 200 dense candidates.

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
