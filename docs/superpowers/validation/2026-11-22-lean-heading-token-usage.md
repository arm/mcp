# Lean results with heading context: actual token usage

Study date: 2026-11-22 America/Chicago.

**Observed total usage fell from 405,448 to 379,162 tokens: 26,286 fewer (6.48%).** The corrected formatter preserves full heading context; no new snippet-use instructions were added. Both versions made 25 KB calls and preserved cited source URLs in all 12 answers per version. All 24 sessions completed without missing usage or retries.

## What was compared

Both versions use the same current tool description (including its Linux/Windows OR example), parameter schemas, shared server instructions, frozen source/corpus, configured model and reasoning effort. The full-result control bypasses only `lean_results`; the other arm uses the existing formatter. This isolates result formatting under the current configuration. The control is not the complete old PR 294 server configuration.

The heading-path correction is implemented: parent-section context is retained once in heading_path where it adds information beyond heading. The proposed snippet-use instructions remain excluded. Token usage alone does not establish equal answer quality.

Six earlier study questions were each repeated twice: 12 matched pairs / 24 native Codex sessions. This recheck uses live KB retrieval, while the earlier 2.64% result used fixed replay responses. Therefore the two point estimates are not direct replications of the same retrieval conditions.

## Measured provider usage

All input/output counters below come from native `turn.completed` usage. No tokenizer estimates are used. Cached input is included in input; reasoning output is a subset, not an additional charge. Cache was observed, not forced cold. No dollar-cost claim.

| Metric | Full results | Lean results | Lean change |
|---|---:|---:|---:|
| Input tokens | 394,851 | 368,683 | -6.63% |
| Cached input (included above) | 241,405 | 227,876 | -5.60% |
| Uncached input | 153,446 | 140,807 | -8.24% |
| Provider cache-write counter (not added again) | 153,335 | 140,696 | -8.24% |
| Output tokens | 10,597 | 10,479 | -1.11% |
| Reasoning output (included above) | 3,685 | 3,552 | -3.61% |
| Total input + output | 405,448 | 379,162 | -6.48% |
| Matched sessions per version | 12 | 12 | — |
| KB calls | 25 | 25 | — |
| Returned result entries | 110 | 104 | — |
| Calls with filters | 0 | 0 | — |
| Answers whose citations match returned URLs or verbatim snippet links | 12 | 12 | — |
| Mean total tokens per answer | 33,787.33 | 31,596.83 | -6.48% |
| Mean session seconds | 37.30 | 35.44 | -4.99% |

Observed saving: **26,286 tokens (6.48%)**. Exploratory 95% question-cluster bootstrap interval: -6.74% to +21.52%. Only six question clusters are present; this does not establish a production saving.

## Per-question totals

Both repetitions and all model/search calls are included.

| Question | Pairs | Full tokens | Lean tokens | Saving |
|---|---:|---:|---:|---:|
| On AWS Graviton, how can I check whether my compiled C++ binary contains LSE atomic instructions? | 2 | 38,267 | 37,134 | +2.96% |
| Which compiler target should I use when one C++ binary needs to run on Graviton2, Graviton3, and Graviton4? | 2 | 37,755 | 37,872 | -0.31% |
| How do I enable and verify bitwise-identical Libamath results across scalar, Neon, and SVE code? | 2 | 107,347 | 113,443 | -5.68% |
| How do I check whether an Arm Linux target is ready for Topo deployment and list compatible projects? | 2 | 63,161 | 59,002 | +6.58% |
| How can I use perf c2c and Arm SPE to find which variables are causing false sharing in a multithreaded C program? | 2 | 51,450 | 59,127 | -14.92% |
| How do I build KleidiCV on an Apple M4 Mac and run its API tests? | 2 | 107,468 | 72,584 | +32.46% |

Three of six question totals decreased and three increased. The largest improvement was KleidiCV on Apple M4 (32.46% fewer tokens). Excluding that question, the remaining five used 297,980 full-result tokens versus 306,578 lean tokens (2.89% more). This post-hoc sensitivity check is not a replacement score; it shows that the aggregate gain is concentrated in one workload. The exploratory six-cluster interval spans both savings and increases.

## Verification and limitations

- The heading regression was reproduced with three failing cases before the fix. All 16 focused formatter tests then passed; Ruff and git diff --check passed. The test run retains one pre-existing anyio/pytest deprecation warning.
- A real in-process MCP setup check established identity formatting for the full-result control and exact current formatting for the lean arm on the same saved inputs. The source fixture and ordered URLs were preserved.
- Every native session verifies an identical hash of the registered KB description, input schema and shared server instructions. Native calls and parameters are reconciled against server invocation/result logs.
- Pair order is seeded, with six full-first and six lean-first pairs. Sessions use the same empty client workspace and run serially. Other MCP tool schemas are present with harmless unavailable stubs. Browsing is disabled; the prompt prohibits command execution and asks for answers under 180 words.
- Fresh ephemeral sessions do not guarantee a cold provider cache. The CLI uses fallback metadata for the configured model alias. The complete hidden client prompt is not independently captured; no test skills are deliberately installed.
- Live queries, follow-up counts and returned content can differ in response to the payload. Thus this is an end-to-end behavioral measurement, not the token count of an identical serialized result alone.
- Citation and log checks are not an answer-accuracy benchmark. No full blinded quality evaluation or execution of answer code was performed in this recheck.
- The formatter preserves a full heading breadcrumb from the original snippet where the separate heading does not contain it. Flat headings are not duplicated. Existing structured heading_path fields remain unchanged.
- Wall time includes container startup, model/network time and cleanup. It does not measure retrieval speed.

## Attempts and experiment consumption

Planned sessions: 24. Recorded attempts: 24. Completed attempts: 24. Complete matched pairs: 12. Missing final usage: `[]`.

All recorded attempts with reported usage consumed **784,610 tokens**. This excludes orchestration/reviewer conversation usage, earlier experiments and any unreported provider work. Missing usage is unknown, not zero.

The superseded preliminary batch completed 7 sessions and reported 231,747 tokens before it was stopped following the user’s heading-preservation choice. Those sessions are excluded from every corrected-version comparison above. Total reported consumption for this request, including preliminary sessions: 1,016,357 tokens.

## Reproducibility

Base commit: `80bb3684591935bbebdfbe9fdbb3bb08d2867dc0` plus recorded heading-fix.patch (SHA-256 `b239d601f3ce93cadf4d1cdb5bf5824f65ccf41a0e66658f5a9a18855c8b75b2`). Corrected source archive SHA-256: `db1a88a06c4c5e1a74f4e4f8e4718d96e8452526d785f307ef219afd6e863c2b`.

Image: `sha256:76fc8ee8bbb18905942e4f0c965dc1a1b52feb4b245698db20bf2a7b3f163b21`. Client: `codex-cli 0.150.1`. Configured model: `gpt-6-astra`; reasoning: `high`; provider API: `responses`.

Local evidence: `artifacts/lean-heading-usage-20261122/`. The archive retains the frozen source, exact registration, schedule, runners/scorers, raw native/server logs, answers, attempt records and verification. Model configuration and credentials are not included. The Docker image/corpus is identified by hash rather than copied.

## Post-measurement consolidation

The formatter was subsequently moved into the existing `arm_kb_search/response.py` module, the separate `mcp-local/utils/lean_results.py` file was removed, and an unused prefix-stripping wrapper was deleted. The local MCP server continues to opt into lean formatting; the shared search behavior is unchanged. Serialized output matched the measured formatter across 490 saved responses (2,450 result entries), with input objects preserved. The formatter, local MCP integration, and shared-response regression suites passed all 79 tests. This consolidation did not require another model experiment; the usage figures above remain the measurements of the frozen source identified in Reproducibility.
