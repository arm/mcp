# Task 1 implementation report

> Historical record: the user subsequently deferred the Learning Path feature. Current scope is search-result slimming and shared citation/legal instructions only; see `docs/superpowers/validation/2026-11-21-lean-mcp.md`.

Status: implemented Changes 1–3, verified locally, ready for independent review.
Base: `0c249c8cea1f79de56ea0a9b9541b052176ebe05` (PR #294 on latest main).
Branch: `codex/lean-mcp`. No push performed. Optional Change 4 excluded.

## Implementation

- Added server-only lean response copying, preserving search order, URLs, array-valued metadata, context, and every extra field. Drops disclaimer/tracking/distance and strips only leading title/heading prefixes. Search Learning Path extraction requires the anchored HTTPS URL pattern and a slash after the slug. Shared `arm_kb_search` remains unchanged.
- Added behavior-first FastMCP instructions and preserved the exact shared legal and URL-preservation constants once per session.
- Added startup `LearningPathIndex` over shipped metadata. Supports scalar and array Learning Paths labels, stored page manifests/page indices and chunk indices, version/heading fallback, navigation exclusions, parent embedding-piece reassembly via `snippet_for`, deduplication, full/commands/outline rendering, page restriction, citation query preservation, normalized lookup, explicit invalid-input errors, and the 80,000-character outline fallback.
- Registered `get_learning_path` with prescribed signature and description plus paired invocation/result/error logging.
- Added offline renderer tests and real FastMCP interface assertions, adapted realistic resource stubs, updated Docker integration expectations, and added new tests to CI.
- Created `mcp-local/README.md` because it did not exist on the base and linked it from the existing root README (approved by controller).
- Removed an obsolete static description assertion in `test_build_inputs.py`, while retaining all assertions that Performix is absent. Real MCP interface tests cover the new description.

## TDD and verification evidence

Tests were written before production changes. Initial renderer collection failed because `utils.learning_paths` did not exist; the isolated server test failed because `mcp.instructions` was None. A later explicit bare-root search regression failed because search extraction incorrectly accepted a missing slash; extraction was then made strict while lookup remains forgiving. One fixture's independent character count was corrected from 33 to 34 after inspecting the full literal.

Tests run offline using controller-provided `lean-mcp-tests:20261121` (Python 3.12, FastMCP 3.4.10), with repo mounted read-only, `PYTHONPATH=/repo:/repo/mcp-local`, and `-p no:cacheprovider`:

```text
python -m pytest mcp-local/tests/test_learning_paths.py mcp-local/tests/test_invocation_logger.py -q -p no:cacheprovider
40 passed, 1 warning in 2.92s

python -m pytest tests mcp-local/tests/test_build_inputs.py mcp-local/tests/test_build_input_fingerprint.py mcp-local/tests/test_invocation_logger.py mcp-local/tests/test_learning_paths.py mcp-local/tests/test_promote_fork_pr.py mcp-local/tests/test_release_withdrawal.py -q -p no:cacheprovider
753 passed, 1 warning, 2 subtests passed in 5.42s

python -m ruff check --no-cache mcp-local/utils/learning_paths.py mcp-local/tests/test_learning_paths.py mcp-local/tests/test_invocation_logger.py
All checks passed!

python -m ruff check --no-cache --select E4,E7,E9,F mcp-local/server.py mcp-local/tests/test_mcp.py
All checks passed!

git diff --check
(no output; success)
```

The full suite covers shared search/filter/context regressions as well as server units. The warning comes from the existing anyio pytest plugin importing pytest's deprecated CallSpec2 alias. An initial full-suite run exposed the obsolete description assertion described above (752 passed, 1 failed); the final fresh run passed all 753. A full Ruff run on legacy server/integration files reports existing typing/exception/style rules outside this task; new helper and interface changes pass their full lint selection. Ruff was rerun with `--no-cache` after its initial default cache could not write to the read-only mount.

Controller-reported independent acceptance at report time: real-corpus nested-virtualization full output has six ordered pages; redis_cache falls back to actionable outline and page fetch works; commands mode and real page-scope preservation pass. Smoke50 comparison has zero ordered URL differences and mean payload 11,124.38 → 7,367.3 characters (33.77% reduction). Full 440-question comparison remains controller-owned and was still running at this report's creation.

## Self-review and limitations

Reviewed presentation transformation and retrieval call boundaries: embedding, ranking, k, filters, scope, and shared library public contracts remain untouched. Source dictionaries are copied and not mutated. Commands output contains only selected fences/shell lines; page citation context is in the note. Distinct stored chunks sharing a URL remain distinct through chunk positions. Index construction and rendering perform no network I/O.

The Docker image build and end-to-end Docker tool integration test (`test_mcp.py`, including external image checks/migration scans) were not run by this implementer; interface tests exercise the real in-process FastMCP server, and the controller performs real-corpus acceptance independently. Very large individual pages can still require an outline under the same specified size guard. Legacy metadata without ordering fields uses the prescribed heuristic, which cannot infer unavailable source order.
