# Arm MCP server: knowledge-base search

## Search response

`knowledge_base_search(query, invocation_reason=None, filters=None, k=5,
scope="chunks")` retains the search library's ranking and filters. `k` accepts
integers from 1 to 20. Filters `doc_type`, `product`, and `platform` accept a label
or non-empty list; labels within a field use OR, and fields use AND. `scope="page"`
expands the initially matched pages using stored ordering metadata and should be
used when the user requests or approves wider context.

The tool description guides agents to choose `k=2` for a precise fact, command,
or API; `k=5` for a procedure, comparison, or uncertain question; and `k=8–10`
when distinct sources or missing coverage justify a broader search. The API
still defaults to `k=5`. Approved page expansion starts from `k=1–2` hits.

Use filters for explicit source, content-type, or environment restrictions,
or to narrow noisy results using observed tags. For Linux or Windows only,
use `platform=["linux", "windows"]`; for Arm-published guidance about Graviton,
use `product="arm"`. A list cannot express Linux **and** SVE: filter one and
verify the other in the retrieved evidence. Missing or legacy tags can hide
relevant results, so relax inferred restrictions while preserving the user's
requirements when choosing sources. Increasing `k` cannot repair an empty
filtered set. Follow-up searches should name the missing fact in
`invocation_reason` and stop when the answer is supported or further searches
add no useful evidence. This guidance is self-contained; no skill is required.

Each response entry retains its citation `url`, `title`, `heading`, `snippet`,
array-valued `doc_type`, `product`, and `platform`, and `score`. Existing extra
fields, including `context`, `page_url`, and `parent_page_url`, remain available.
`edition` is no longer a filter or response field. The MCP presentation omits
`distance` and `url_tracking_instruction`, and removes duplicate
`Document Title:` / `Heading Path:` prefixes only at the top of snippets.
When the search library supplies Arm content disclaimers, one `disclaimer` is
retained on the first applicable Arm-domain result. It explicitly covers all
Arm-domain results in that response, preserves the original legal wording, and
is omitted from the other entries. External-only and empty responses receive no
Arm notice. The list shape and result order stay unchanged.

The tool description retains the hardware/performance/migration routing hints
and exact-URL citation rule. Session instructions also carry scoped legal and
citation guidance, but clients need not rely solely on initialization metadata.
The shared `arm_kb_search` Python API retains its existing response contract.

Preserve citation URLs exactly as returned, including query parameters and
fragments. Learning Paths remain searchable through the existing search tool;
no dedicated Learning Path retrieval tool or derived root field is added.

Search calls and results are logged as paired entries in
`/workspace/mcp-traffic.jsonl`, including the optional invocation reason.
