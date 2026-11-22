# Lean MCP fix and token measurements — 2026-11-21

The routing and citation guidance is restored to the exact PR #294 tool description. Search responses retain one complete Arm content disclaimer, explicitly scoped to Arm sources, on the first applicable result. Repeated notices, distance scores, tracking-instruction fields, and leading duplicate title/heading labels remain removed. Learning Path retrieval and the optional execution workflow remain excluded.

## Overall model usage

Six real smoke questions, two repetitions each, with 12 runs per version. Each fresh Codex CLI session answered one question with replayed five-result KB responses. All model calls, repeated searches, inputs, and outputs are included. These are provider-reported usage counters from `turn.completed`, not tokenizer estimates.

| Metric | PR #294 behavior | Fixed lean behavior | Change |
|---|---:|---:|---:|
| Input tokens | 320,601 | 311,473 | 9,128 fewer (2.85%) |
| Cached input tokens, included above | 180,803 | 184,532 | 3,729 more (2.06%) |
| Uncached input tokens | 139,798 | 126,941 | 12,857 fewer (9.20%) |
| Cache-write input tokens, provider counter | 139,696 | 126,836 | 12,860 fewer (9.21%) |
| Output tokens | 5,914 | 6,425 | 511 more (8.64%) |
| Reasoning output tokens, included in output | 1,442 | 1,933 | 491 more (34.05%) |
| **Total input + output** | **326,515** | **317,898** | **8,617 fewer (2.64%)** |
| Mean total tokens per answer | 27,209.58 | 26,491.50 | 718.08 fewer |
| KB calls across 12 runs | 22 | 23 | 1 more |
| Mean elapsed seconds per answer | 17.815 | 18.920 | 1.105 slower (6.20%) |
| Answers citing an exact returned URL | 12/12 | 12/12 | Equal |

Uncached input is input minus cached input. Do not add cache-write tokens to input, or reasoning tokens to output: these are breakdown counters. Provider pricing was not available, so no dollar savings are claimed. Cache state was not controlled. Total includes cache hits and is not equivalent to billed cost.

The total saving is an observed point estimate in a small experiment, not an established production saving. Input savings were partly offset by more output and one extra search. The host measures startup, network, and model time together; these timings do not measure retrieval speed.

### Variation by question

Totals below include both repetitions and all calls. The selected indices were 0, 9, 19, 29, 39, and 49 of the original 50-question smoke corpus.

| Question | Original total | Fixed total | Total saving | KB calls original/fixed |
|---|---:|---:|---:|---:|
| LSE instruction detection | 35,686 | 34,284 | 3.93% | 2 / 2 |
| Graviton compiler target | 60,153 | 58,170 | 3.30% | 4 / 4 |
| Libamath identical results | 57,818 | 53,704 | 7.12% | 4 / 4 |
| Topo deployment readiness | 58,647 | 54,077 | 7.79% | 4 / 4 |
| perf c2c and Arm SPE false sharing | 57,623 | 65,252 | -13.24% | 4 / 5 |
| KleidiCV on Apple M4 | 56,588 | 52,411 | 7.38% | 4 / 4 |

## Search payload tokens

All 490 saved PR #294 retrieval responses were replayed through the real in-process FastMCP server. The input results are identical for both variants. Counts cover actual returned MCP text content using tiktoken 0.14.0, `o200k_base`; these are estimates, not the configured model's billing tokenizer. They exclude the surrounding session prompt, tool schemas, and model output. Each response preserves the ordered URLs; the fixed response contains at most one disclaimer.

| Corpus | Responses | Original tokens | Fixed tokens | Tokens saved | Reduction | Mean original → fixed |
|---|---:|---:|---:|---:|---:|---:|
| Smoke | 50 | 125,621 | 89,315 | 36,306 | 28.90% | 2,512.42 → 1,786.30 |
| Benchmark | 440 | 1,249,431 | 944,507 | 304,924 | 24.41% | 2,839.62 → 2,146.61 |
| Combined | 490 | 1,375,052 | 1,033,822 | 341,230 | 24.82% | 2,806.23 → 2,109.84 |

The fixed server instructions add an estimated 150 tokens. Both variants use the same original 1,810-character search description and unchanged input schema. Therefore payload savings must not be presented as overall model-token savings. Client serialization can differ; the measured Codex usage above captures the tested client's actual behavior.

## Behavioral checks and tests

| Check | Original | Fixed |
|---|---:|---:|
| KB selected for Arm prompts | 12/14 | 12/14 |
| KB selected for arithmetic negative controls | 0/2 | 0/2 |
| Exact citation URL, including query and fragment | 4/4 | 4/4 |
| Exact final disclaimer sentence recoverable on request | 2/2 | 2/2 |

Both versions skipped KB on the two migration trials. The description is restored exactly, but routing is still model-dependent. Disclaimer tests establish availability when requested, not legal compliance or automatic inclusion in every answer. Exact source citations also passed on all 24 token-answer runs; answer quality itself was not scored.

The initial fix tests produced six expected failures before implementation. Final offline suite: **728 tests and 2 subtests passed**. Ruff checks passed for the changed helper and focused unit/interface tests; E4/E7/E9/F checks passed for server and Docker integration test sources. `git diff --check` passed. One pre-existing anyio/pytest deprecation warning remains. Independent review found no actionable defects. Full Docker rebuild and unrelated external tool transport integration were not run.

## Method and reproducibility

- Base: PR #294 commit `0c249c8cea1f79de56ea0a9b9541b052176ebe05`, containing main `10ac34d853b85d089d936bda2efd9d6041fa2f6c`. Shared `arm_kb_search` retrieval is unchanged.
- Client: installed Codex CLI 0.150.1, configured `gpt-6-astra` with high reasoning through the user's configured proxy. The CLI emitted a fallback-metadata warning for the model alias. This is not a test of the desktop, Claude, or VS Code clients.
- Each original fixture uses the exact original description, no server instructions, and unmodified saved results. Each fixed fixture uses current registration, instructions, and result formatting. Other tools expose their actual schemas but execute harmless stubs. The fixture runs in Docker without network access; only the Codex client reaches its configured model provider.
- 68 sessions completed with no timeouts, client failures, or tool errors: 32 routing, 8 citation, 4 disclaimer, and 24 token-answer sessions. Cases were interleaved using seed 295, with up to four sessions running concurrently.
- The token-answer fixture returns the same saved payload for any repeated query within a question. It exercises formatting and client/model behavior, not fresh retrieval, interactive corpus exploration, or answer quality. Repeated searches were allowed and counted.
- Payload analysis uses `lean-mcp-token-tests:20261121`; functional/client fixtures use `lean-mcp-tests:20261121`, Python 3.12 and FastMCP 3.4.10. These derive from the existing Arm MCP image recorded in the baseline provenance.
- All 68 experimental sessions together reported 1,215,648 input and 28,613 output tokens: **1,244,261 total**. This is the test-run consumption, separate from the 12-versus-12 answer comparison; it excludes the agent's development conversation and earlier diagnostic experiments.

Local evidence: `artifacts/lean-fixed-measurement-20261121/`. `summary.json` contains aggregate model usage; `results.json` contains per-run prompts, answers, and counters; `payload-tokens.json` contains replay totals. `evidence.tar.gz` retains scripts, raw events, protocol inspection, baseline replay inputs, test/lint logs, and source hashes. No user configuration or credentials are copied. Scripts contain local paths and require the configured provider and Docker images to rerun.
