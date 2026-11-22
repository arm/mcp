# KB description and optional-skill experiments — 2026-11-21

## Recommendation

Use a self-contained adaptive tool description with one explicit OR-filter example. Keep essential query, filter, result-count, follow-up, and citation decisions in the tool description. Do not make this tool depend on a separately installed skill. API defaults, parameter validation, retrieval, result formatting, citations, and the deferred Learning Path scope are unchanged.

The selected wording sets `k=2` for a precise fact/command/API, `k=5` for procedures/comparisons/uncertain questions, and 8–10 when breadth is needed. It distinguishes publisher tags from topic names, explicit exclusions from incidental hints, OR lists from AND across fields, empty filtered sets from insufficient `k`, and approved page expansion from ordinary chunk search. These are model-facing recommendations; the API still defaults to `k=5` and accepts 1–20.

No version was cheapest in every test set. Plain adaptive wording was cheaper in repeated direct-model trials, while the stronger filter recipe was cheaper in native validation. The selected one-example version prioritizes self-contained guidance and explicit filter use with a smaller wording change. **Consistent overall token savings were not established.**

## Candidate screening

Eight real-corpus questions and seven controlled scenarios per variant. Each initial variant ran once per scenario. The controlled corpus contains 16 fictional NimbusRT documents; its deterministic ranking is not a production retrieval benchmark. All controlled filters use the repository’s actual `SearchFilters` and `MetadataFilterIndex` semantics. The real-corpus path invokes the unchanged search engine with each model-generated query, filters, k, and scope.

| Description | Runs | KB calls | Reported total tokens | Change vs current |
|---|---:|---:|---:|---:|
| Current description | 15 | 24 | 126,195 | +0.00% |
| Prescriptive rules | 15 | 28 | 143,577 | +13.77% |
| Prescriptive rules + examples | 15 | 25 | 133,052 | +5.43% |
| Adaptive rules | 15 | 22 | 114,976 | -8.89% |

All four initial candidates retrieved the expected source in all 14 source-scored scenarios, preserved an exact returned citation in 15/15, and covered the required facts in all six fact-scored controlled cases. The unknown-support case has no expected positive source and was inspected for calibrated uncertainty. No unapproved page expansion occurred. The initial rules encouraged unnecessary legacy-tag searches; the adaptive wording avoided some of those retries.

## Repeated diagnostic scenarios

Three matched scenarios, five fresh sessions each: KleidiCV build/tests on Apple M4, AWS-only compiler guidance, and Linux-or-Windows installation comparison. The baseline, adaptive, and skill variants were interleaved in one seeded batch. Refined wording was tested in later batches using the same prompts and corpus. All attempts and outputs are retained; results below include all completed runs for the matched scenarios.

| Description | Runs | KB calls | Reported total tokens | Change vs current |
|---|---:|---:|---:|---:|
| Current description | 15 | 26 | 136,604 | +0.00% |
| Adaptive rules | 15 | 25 | 128,075 | -6.24% |
| Adaptive rules + optional skill | 15 | 25 | 178,535 | +30.70% |
| Adaptive rules + stronger filter recipe | 15 | 31 | 178,048 | +30.34% |
| Adaptive rules + one OR example | 15 | 28 | 153,375 | +12.28% |

### Explicit OR-filter selection

An unfiltered search can still answer correctly; this measures adherence to the explicit environment restriction, separately from answer correctness.

| Description | Correct first-call Linux-or-Windows filter |
|---|---:|
| Current description | 3/5 |
| Adaptive rules | 0/5 |
| Adaptive rules + optional skill | 5/5 |
| Adaptive rules + stronger filter recipe | 5/5 |
| Adaptive rules + one OR example | 5/5 |

The skill improved filter selection, but added a retrieval/read step without improving source coverage. The larger filter recipe also improved selection but increased follow-up searches in the repeated real-corpus questions. The final edit retains the adaptive rules and adds only the explicit OR example. This narrows the behavioral change while keeping that demonstrated filter benefit.

## Native Codex/MCP validation

Four validation questions were held out from wording development: repeated Go GC benchmarks with Benchstat, MongoDB/YCSB on Axion, Zephyr hello-world on Corstone-300, and mixed C/assembly Cortex-M debugging in Keil Studio. Each run uses real retrieval over stdio MCP through the installed Codex CLI. These are four observations per version, not a production savings guarantee.

| Description | Runs | KB calls | Reported total tokens | Change vs current |
|---|---:|---:|---:|---:|
| Current description | 4 | 12 | 164,170 | +0.00% |
| Adaptive rules | 4 | 10 | 138,825 | -15.44% |
| Adaptive rules + stronger filter recipe | 4 | 9 | 125,431 | -23.60% |
| Adaptive rules + one OR example | 4 | 12 | 151,941 | -7.45% |

For the selected version versus current description:

| Metric across four native answers | Current | Selected |
|---|---:|---:|
| Input tokens | 160,685 | 148,009 |
| Cached input, included above | 112,298 | 99,579 |
| Output tokens | 3,485 | 3,932 |
| Reasoning output, included above | 805 | 1,335 |
| Total input + output | 164,170 | 151,941 |
| Mean elapsed seconds | 35.10 | 36.21 |
| Expected-source retrieval | 4/4 | 4/4 |
| Answers with an exact returned citation | 4/4 | 4/4 |

The optional skill was also made genuinely discoverable in a temporary project `.agents/skills/arm-kb-search/SKILL.md`, rather than only injecting its contents. In that native comparison it was read successfully, but the client also performed two discovery calls. For the same Linux-or-Windows case, total reported tokens were 31,144 for the current description, 16,054 for adaptive wording, and 40,580 with the skill. This one run demonstrates real loading overhead, not a general percentage estimate; discovery behavior itself varied.

## Quality and verification

A separate citation audit checked every Markdown citation link, not just whether an answer contained one exact link. All citation links in the selected version's 22 citing answers matched returned result URLs exactly; its arithmetic control had no citations. One parent-adaptive native answer also linked an installation-guide URL outside the primary returned URL fields, recorded separately in `citation-audit.json`.

The final description selected the Linux-or-Windows OR filter correctly in the native client and verified Linux plus SVE without treating the OR list as an intersection. Native routing controls selected KB for the Arm hardware question with both current/final descriptions (1/1 each), and neither selected KB for arithmetic (0/1 each). These small controls establish observed behavior, not routing guarantees.

- Final matched scenarios: expected-source coverage 15/15, exact citations 15/15, and required controlled facts 5/5. Filter-use scores are kept separate from answer scores.
- An independent blinded review of six baseline/adaptive answer pairs found no substantive grounding regression. It identified a small baseline word-limit overrun and differences in optional caveat coverage. This review covered the parent adaptive wording; later edits added filter examples without changing retrieval. It is not independent verification that every source statement is current.
- The final production diff received independent review: no actionable semantic issues. The registered description exactly matches the selected tested text; advertised schemas and server instructions are unchanged. Existing registered-tool tests preserve routing phrases, exact-URL guidance, parameter validation/defaults, list results, the single scoped Arm notice, and the absence of the LP tool.
- Final unit/interface suite: 728 tests and 2 subtests passed. E4/E7/E9/F Ruff checks and `git diff --check` passed. One pre-existing anyio/pytest deprecation warning remains. No new production feature or endpoint was added.
- Full Docker rebuild and unrelated external-tool transport integration were not run for this description-only change.

## Measurement limits and reproducibility

- These are empirical comparisons of tested wording, not proof of a globally optimal description. Model choices vary: clearer instructions do not guarantee fewer searches, lower latency, or fewer tokens on every question. Selection considered filter use, evidence coverage, citation fidelity, and cost together.
- Direct screening uses the configured `gpt-6-astra` model at high reasoning through the user’s existing Responses-compatible provider, actual Arm tool schemas, and the same server instructions. It uses a minimal common assistant prompt and function-tool loop to reduce experimental overhead. Those totals must not be confused with native Codex session totals.
- Native validation uses installed Codex CLI 0.150.1 with the same configured model/provider/reasoning, actual MCP schemas and registration, fresh ephemeral read-only sessions, and a network-disabled retrieval container. CLI fallback-metadata warnings for the model alias remain. This does not establish behavior in other clients or models.
- Reported total tokens are input plus output, including cache hits. Reasoning and cached counters are included breakdowns, not extra tokens. Cache state is uncontrolled, timings include startup/provider delays, and provider prices are unknown. No dollar savings are claimed.
- Real retrieval uses the existing 43,320-row corpus from the local Arm MCP image. It has legacy tags (for example `Learning Paths` and `AWS Graviton`) and 41,900 records without a platform tag. Controlled cases exercise modern publisher/type/platform arrays, OR/AND decisions, missing tags, unsupported-version uncertainty, and approved page expansion. No corpus rewrite was used.
- An early harness call used an unavailable FastMCP method and was corrected before model trials. One model attempt was interrupted when a concurrent retrieval container exhausted Docker memory; its 1,908 reported tokens are retained in the experiment total. That exact scenario was rerun successfully. Heavy retrieval workers were serialized thereafter. TLS verification remained enabled using trusted public system certificates.
- All candidate text, prompts, raw model responses, completed MCP calls, skill reads, per-run usage, analysis scripts, source hashes, logs, and reviews are preserved in local evidence. No authentication configuration or credential values are copied. The actual skill candidate is experimental and is not installed globally or made a production dependency.

## Selected tool description

```text
Search Arm documentation, tutorials, intrinsics and compatibility. Use for Arm migration; system architecture, CPU, memory and host hardware; and runtime-performance, profiling, hotspot, benchmarking, and regression questions.
Query with the known software/intrinsic, target and question; avoid building the query around an unverified answer.
Choose k=2 for a precise fact, command or API; k=5 for a procedure, comparison or uncertain question. Use 8-10 when several distinct sources are needed or relevant results leave coverage gaps. k limits ranked entries, not tokens or pages (maximum 20).
Filters are optional exclusions: use them for explicit metadata restrictions or to narrow noisy results using observed tags. A mentioned vendor or OS alone does not require a filter. doc_type selects content type; product means document publisher, not software or CPU; platform means verified environment or ISA. For an explicit "Linux or Windows only" restriction, use platform=["linux","windows"]. Omit uncertain fields. Lists are OR within a field; fields combine with AND. platform=["linux","sve"] means either, not both: filter one, keep the other in the query, and verify both in the evidence.
Older snapshots use legacy labels or lack tags. If filters hide relevant evidence, relax inferred filters while keeping the target in the query; enforce explicit user restrictions when selecting sources. Raising k cannot fix an empty filtered set. No match does not establish incompatibility.
Search again only for a missing fact needed to answer; name that gap in invocation_reason. Rephrase for relevance, increase k for coverage. Use scope="page" for surrounding context only when requested or approved, with k=1-2 initial hits: expansion returns all stored chunks of matched pages and may be large. Stop when the answer is supported; state remaining uncertainty when searches add no useful evidence.
When citing, preserve each URL exactly as returned, including query parameters and fragments; do not remove, normalize, shorten, or rewrite them.
```

## Experiment accounting

Completed direct-model sessions: 145. Completed native sessions: 27. Interrupted model attempts: 1. Reported model tokens for this experiment, including the connection probe and interrupted attempt: **2,172,689**. This excludes the development conversation, reviewer-agent usage, and earlier lean-result experiments.

Local evidence: `artifacts/kb-guidance-eval-20261121/`. The archive retains the experimental skill and all rejected candidates; `final-summary.json` contains machine-readable aggregates. Scripts contain local paths and require the configured provider and existing Docker images to rerun.
