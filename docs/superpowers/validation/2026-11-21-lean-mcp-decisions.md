# SDD ledger — plan: docs/superpowers/plans/2026-11-21-lean-mcp.md

> Historical record: the user subsequently deferred the Learning Path feature. Current scope is search-result slimming and shared citation/legal instructions only; see `docs/superpowers/validation/2026-11-21-lean-mcp.md`.

| Task | Contract check | Result |
|---|---|---|
| 1 | Server formatting, index, interface tests share metadata and helpers; kept together | consistent |

Ruling: Preserve PR #294 arrays and removed edition over the older example shape — requested base takes precedence — cost if wrong: response schema adjustment.
Ruling: Slim only MCP presentation, retaining shared library contract — request targets server and retrieval must remain unchanged — cost if wrong: standalone search consumers retain verbose responses.
Ruling: Omit optional Change 4 pending user preference — specification makes it conditional on arm-run — cost if wrong: extra compiler implementation.
Task 1: in progress; base 0c249c8cea1f79de56ea0a9b9541b052176ebe05.

Task 1: complete (commits 0c249c8..4fe741d, review clean).
Acceptance complete: 753 tests + 2 subtests, all490 ranked URL lists identical, smoke -33.77%, benchmark -29.50%; real paths and page-scope assertions passed.
Final review: spec PASS, quality PASS; 514 paths / 2713 pages / 18624 retained chunks checked; no actionable findings.
