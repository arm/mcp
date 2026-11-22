# Arm MCP server: knowledge-base search

## Search response

`knowledge_base_search(query, invocation_reason=None, filters=None, k=5,
scope="chunks")` retains the search library's ranking and filters. `k` accepts
integers from 1 to 20. Filters `doc_type`, `product`, and `platform` accept a label
or non-empty list; labels within a field use OR, and fields use AND. `scope="page"`
expands the initially matched pages using stored ordering metadata and should be
used when the user requests or approves wider context.

Each response entry retains its citation `url`, `title`, `heading`, `snippet`,
array-valued `doc_type`, `product`, and `platform`, and `score`. Existing extra
fields, including `context`, `page_url`, and `parent_page_url`, remain available.
`edition` is no longer a filter or response field. The MCP presentation omits
`distance`, `disclaimer`, and `url_tracking_instruction`, and removes duplicate
`Document Title:` / `Heading Path:` prefixes only at the top of snippets.
Session instructions carry the original legal and URL-preservation guidance.
The shared `arm_kb_search` Python API retains its existing response contract.

Preserve citation URLs exactly as returned, including query parameters and
fragments. Learning Paths remain searchable through the existing search tool;
no dedicated Learning Path retrieval tool or derived root field is added.

Search calls and results are logged as paired entries in
`/workspace/mcp-traffic.jsonl`, including the optional invocation reason.
