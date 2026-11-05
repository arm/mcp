---
name: arm-knowledgebase
description: Search the Arm MCP knowledge base for sourced guidance about Arm architecture, migration, software compatibility, intrinsics, system information, and performance. Use when a user asks an Arm-specific technical question or wants relevant Arm documentation; use arm-enablement instead for a whole-repository readiness assessment.
---

# Arm Knowledge Base

Use the configured `arm-mcp` server's `knowledge_base_search` tool as the
primary source for Arm-specific technical lookups.

## Verify Access

1. Confirm that the configured `arm-mcp` server exposes
   `knowledge_base_search`. Treat it as an MCP tool, not a command-line program.
2. If the tool is unavailable, stop and identify the missing MCP configuration.
   Point the user to the [Arm MCP installation guide](https://github.com/arm/mcp/blob/main/agent-integrations/agent-install-instructions.md).
3. Ask a concise clarifying question only when a missing product name, version,
   architecture, or error detail would materially change the search.

## Search and Answer

1. Form a focused natural-language query from the user's problem. Preserve exact
   software names, versions, CPU names, architecture extensions, and error text
   that affect the result.
2. Call `knowledge_base_search` with the query and a brief `invocation_reason`.
3. Review the ranked results. Refine the query when the initial results are
   irrelevant or when a narrower follow-up would resolve a material ambiguity;
   avoid repeated near-duplicate searches.
4. Answer the user's question directly and cite the relevant returned sources by
   title. Preserve every returned URL exactly, including query parameters and
   fragments.
5. Distinguish source-supported facts from inference. Do not turn a general
   tutorial or a result for another software version into a definitive
   compatibility or performance claim.
6. If the search returns nothing relevant, say `No relevant Arm knowledge-base
   result` and identify what remains unverified. Do not infer that a product is
   unsupported or incompatible from an empty result.

## Boundaries

- Use `arm-enablement` for whole-repository readiness assessments and report
  generation when that skill is available.
- Do not call unrelated Arm MCP tools such as `migrate_ease_scan`, `check_image`,
  `skopeo`, or `mca` unless the user's request expands beyond knowledge lookup.
- Use other authoritative sources only when the user requests broader research
  or the knowledge base cannot answer the question, and clearly label evidence
  obtained outside the Arm knowledge base.
