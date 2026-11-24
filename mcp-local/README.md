# Arm MCP server: knowledge-base search

## Search response

`knowledge_base_search(query, invocation_reason=None, filters=None, k=5,
scope="chunks")` retains the search library's ranking and filters. `k` accepts
integers from 1 to 20. Filters `doc_type`, `product`, and `platform` accept a label
or non-empty list; labels within a field use OR, and fields use AND. `scope="page"`
expands the initially matched pages using stored ordering metadata and should be
used when the user requests or approves wider context.

The `k` parameter help recommends considering `k=2–4` for a targeted follow-up
and increasing it only when needed evidence is missing. The default remains
`k=5`. With approved `scope="page"` expansion, `k` selects the initial hits;
the number of returned page chunks can exceed `k`.

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
`distance` and `url_tracking_instruction`. Snippets are returned unchanged,
including any `Document Title:` / `Heading Path:` prefixes, code indentation,
and trailing whitespace.
When the search library supplies Arm content disclaimers, one `disclaimer` is
retained on the first applicable Arm-domain result. It explicitly covers all
Arm-domain results in that response, preserves the original legal wording, and
is omitted from the other entries. External-only and empty responses receive no
Arm notice. The list shape and result order stay unchanged.

The tool description retains the hardware/performance/migration routing hints
and exact-URL citation rule. Session instructions also carry scoped legal and
citation guidance, but clients need not rely solely on initialization metadata.

The shared `arm_kb_search` Python API also changes its public metadata contract:
`doc_type`, `product`, and `platform` always return arrays, with `[]` for missing
tags. `edition` is no longer accepted as a filter or returned in results. Python
callers must handle tag arrays and remove uses of the public `edition` field.
See the [shared API filter documentation](../arm_kb_search/README.md#filters)
for metadata semantics and migration details.

Lean formatting applies only to MCP responses. The shared Python API retains
`distance` and, when configured, per-result URL tracking instructions and Arm
disclaimers. Disclaimer consolidation is MCP-only.

Preserve citation URLs exactly as returned, including query parameters and
fragments. Learning Paths remain searchable through the existing search tool;
no dedicated Learning Path retrieval tool or derived root field is added.

Search calls and results are logged as paired entries in
`/workspace/mcp-traffic.jsonl`, including the optional invocation reason.
