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

Filters restrict candidates before ranking and deduplication. Filtered vector
retrieval uses exact search; unfiltered retrieval uses ANN.

See [CONTRIBUTING.md](../CONTRIBUTING.md#versioning-arm-kb-search) for package
versioning guidance.
