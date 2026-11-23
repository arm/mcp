# PR 294 versus current KB tool description

Study date: 2026-11-23. Source commit: `3cd00f86b44c631cd0e58861e4d2c9ad8aa1203d`.

## Recommendation

**Prefer the shorter PR 294 description for now, alongside the current lean formatter and heading preservation.** The current wording did not improve answer quality in this selected test: all 16 blinded pair comparisons tied, all 32 answers were adequate, and all applicable source/platform restrictions passed. Current used 4.52% more tokens on real-KB questions and 2.43% more across the full selected suite. Controlled-case usage was effectively similar (0.75% lower, with a wide interval).

On real questions, current requested k=5 for 8 of 9 follow-up calls; PR 294 usually requested k=2–4. The precision case L01 required four calls across two current runs versus three with PR 294. This identifies a candidate for future testing—small follow-ups for a specific missing fact—but does not establish a tested replacement wording.

The real-KB six-cluster interval favors PR 294 in this suite, but the combined interval includes both savings and increases. The selected sample, reused questions, synthetic cases and one model/provider limit generalization. This is a practical recommendation from observed evidence, not proof of universal superiority. No production description was changed by this experiment.

## Comparison

The exact PR 294 description (`baseline`) is compared with the currently committed description (`current`, including the Linux/Windows OR example). Both use the current parameter schema, shared URL/legal instructions, lean formatter with preserved headings, and identical retrieval backend for each question. Only the KB tool-description string changes. The baseline description is 1,810 characters; current is 2,044 characters. Character counts are not token estimates.

Twelve preselected questions: six use the frozen real KB corpus and six use a fictional EvalCache corpus to exercise filter behavior with known evidence. Four questions repeat once (L01, L04, F01, F04), giving 16 runs per description and 32 completed native sessions. Treatment order is seeded and balanced across 16 adjacent pairs. Live and controlled results must be interpreted separately.

## Native provider usage

| Dataset | Runs per version | PR 294 tokens | Current tokens | Current saving | Question-cluster 95% interval |
|---|---:|---:|---:|---:|---|
| Real KB | 8 | 233,623 | 244,186 | -4.52% | -10.76% to -0.24% |
| Controlled filter cases | 8 | 154,156 | 153,000 | +0.75% | -12.51% to +16.48% |
| All selected runs | 16 | 387,779 | 397,186 | -2.43% | -9.02% to +5.35% |
| First designated repetition only | 12 | 289,377 | 300,716 | -3.92% | -16.53% to +6.24% |

Positive saving favors current. Totals are native `turn.completed` input + output counters reported by the configured provider. Cached input is included in input; reasoning is included in output. Intervals use 10,000 paired bootstrap samples by question cluster. Only six clusters per dataset are present; these are exploratory intervals, not evidence of production-wide superiority. The pooled estimate weights the repeated questions twice.

| Metric, all selected runs | PR 294 | Current |
|---|---:|---:|
| Input | 380,390 | 389,160 |
| Cached input (included) | 221,690 | 230,350 |
| Uncached input | 158,700 | 158,810 |
| Cache-write counter (not added again) | 158,571 | 158,678 |
| Output | 7,389 | 8,026 |
| Reasoning output (included) | 1,437 | 1,774 |
| Total | 387,779 | 397,186 |
| KB calls | 27 | 28 |
| Calls using filters | 8 | 9 |
| Returned entries | 121 | 107 |
| Empty calls | 3 | 3 |
| Answers with exact returned or snippet-link citations | 16 | 16 |

## Answer quality

Four fresh model-review sessions graded 16 anonymized answer pairs. A/B labels were randomized per pair; the reviewer saw questions, prewritten rubrics, answers, and each answer’s retrieved evidence, without descriptions, variant names, token counts, or call counts. Grades assess essential completeness, evidence support, and source/platform restrictions. This is model-assisted assessment, not human review, external fact checking, or execution of the suggested commands.

| Dataset / description | Adequate | Partial / inadequate | Material grounding gaps | Restriction failures |
|---|---:|---:|---:|---:|
| Real KB / PR 294 | 8 | 0 / 0 | 0 | 0 |
| Real KB / Current | 8 | 0 / 0 | 0 | 0 |
| Controlled / PR 294 | 8 | 0 / 0 | 0 | 0 |
| Controlled / Current | 8 | 0 / 0 | 0 | 0 |

Pair preferences: `{"tie": 16}`. Missing snippet support does not by itself establish that a real-world claim is false. An honest unknown answer can be correct for the no-evidence case.

## Per-question results

| Case | Question | Pairs | PR 294 tokens | Current tokens | Current saving |
|---|---|---:|---:|---:|---:|
| F01 | For fictional EvalCache, compare how to enable tracing on Linux or Windows only. Exclude other operating systems. | 2 | 31,744 | 31,985 | -0.76% |
| F02 | For fictional EvalCache on Linux with SVE, use only Arm-published reference documentation. Which command validates the SVE backend? | 1 | 15,754 | 15,708 | +0.29% |
| F03 | We run fictional EvalCache on AWS Graviton. Which flag enables deterministic cache snapshots? Use the clearest KB evidence; publisher is unrestricted. | 1 | 15,835 | 15,945 | -0.69% |
| F04 | For fictional EvalCache on Linux only, what command repairs a damaged index? | 2 | 40,773 | 48,413 | -18.74% |
| F05 | Does the knowledge base establish whether fictional EvalCache supports FreeBSD? Give a supported yes/no answer if possible; otherwise explain the evidence limits. | 1 | 34,150 | 24,935 | +26.98% |
| F06 | Using the fictional EvalCache documentation, give the initialization, backup, and restore steps, including the required restore safety check. | 1 | 15,900 | 16,014 | -0.72% |
| L01 | Which C function attributes enable SME streaming mode and give a function its own ZA state? | 2 | 45,993 | 54,039 | -17.49% |
| L02 | Which compiler target should I use when one C++ binary needs to run on Graviton2, Graviton3, and Graviton4? | 1 | 18,811 | 18,266 | +2.90% |
| L03 | How do I check whether an Arm Linux target is ready for Topo deployment and list compatible projects? | 1 | 28,015 | 29,474 | -5.21% |
| L04 | How can I use perf c2c and Arm SPE to find which variables are causing false sharing in a multithreaded C program? | 2 | 60,104 | 60,983 | -1.46% |
| L05 | Use only Arm Learning Paths as sources: how can I use WindowsPerf sampling to find hot functions in a Windows on Arm program? | 1 | 54,478 | 54,517 | -0.07% |
| L06 | Use only AWS-published documentation: on AWS Graviton, how can I check whether my compiled C++ binary contains LSE atomic instructions? | 1 | 26,222 | 26,907 | -2.61% |

## Retrieval choices

- Real KB, baseline: 16 calls; 4 filtered; 2 empty; initial k distribution `{"5": 8}`; follow-up k distribution `{"2": 2, "3": 3, "4": 1, "5": 2}`.
- Real KB, current: 17 calls; 3 filtered; 2 empty; initial k distribution `{"2": 2, "5": 6}`; follow-up k distribution `{"2": 1, "5": 8}`.
- Controlled, baseline: 11 calls; 4 filtered; 1 empty; initial k distribution `{"5": 8}`; follow-up k distribution `{"10": 1, "20": 1, "5": 1}`.
- Controlled, current: 11 calls; 6 filtered; 1 empty; initial k distribution `{"2": 3, "5": 5}`; follow-up k distribution `{"5": 3}`.

## Controls and limitations

- The real corpus has 43,320 chunks and predominantly legacy labels. 41,900 entries have no platform tag; the populated platform values are Linux and Windows. This comparison includes recovery from missing/legacy tags and does not establish how either wording performs on a fully retagged production corpus.
- Controlled cases use a transparent 16-document fictional corpus, deterministic lexical ranking, and the production `SearchFilters` and `MetadataFilterIndex`. They isolate OR/AND restrictions, incidental vendor mentions, missing tags, absence of evidence, and multi-step coverage. Their token totals are not forecasts for live semantic retrieval.
- Several live questions were used in earlier evaluations; this is a selected scenario comparison, not an untouched representative holdout. The controlled OR question intentionally exercises the example in the current description.
- Filter counts and lower k are diagnostic, not success criteria. Restriction-compliant, supported answers take precedence over shorter responses.
- Native Codex codex-cli 0.150.1 uses configured model `gpt-6-astra`, reasoning `high`, through the existing Responses-compatible provider. The CLI uses fallback metadata for this alias. Same frozen code/image and empty client workspace for both treatments. No test skills were deliberately installed; complete absence of skill metadata in the hidden effective prompt is unverified.
- Actual usage includes the native client context and follow-up turns. Provider caches are observed, not forced cold; no dollar-saving claim is made. Elapsed times include model/network, startup and retrieval costs and are not retrieval-speed measurements.
- No new snippet-use instructions were added. Production code and description were not changed during the comparison.

## Attempts, verification, and consumption

Recorded native attempts: 33; completed: 32; complete pairs: 16. Unknown usage: `["L03-baseline-1-attempt1"]`.

The initial L03 baseline attempt failed during MCP initialization: the harness compared an internal schema containing $ref/$defs with the client-expanded representation. The guard was corrected to compare equivalent representations, and setup separately verified the client schemas were identical. The failed attempt and initial setup files are retained. No descriptions, exposed schemas, questions, or result formatting changed. Its usage is unknown, not assumed zero. The retry and paired current run remain adjacent.

Native experiments reported **784,965 tokens**. Blinded reviews reported **108,274 tokens**. Combined reported consumption is **893,239 tokens**, excluding this coordinating chat and the failed attempt’s unknown usage.

Frozen inputs and source/description hashes were verified. Native tool arguments reconcile with server invocation/result logs. All 32 completed runs passed registration checks. No benchmark command execution or unrelated tool use occurred. Named evaluation containers were cleaned up.

## Reproducibility

Image: `sha256:76fc8ee8bbb18905942e4f0c965dc1a1b52feb4b245698db20bf2a7b3f163b21`. Source archive SHA-256: `f8669afb85fe20b86fdbc726ac213bc327f92985cbaf54c8d85a80c6561ded3f`.

Description SHA-256: baseline `556fc1d61cc7ab90d5c7a54e176258559efb5af68c2b11d9e0acd76eb06018ac`; current `0bce8cce6a4ffc42b677661fd9b5556b16d2ee3cac1c2839ed6be23c11a2cdb5`.

Local evidence: `artifacts/kb-description-current-20261123/evidence.tar.gz`, with checksum beside it. Includes frozen code, descriptions, questions/rubrics, schedule, fixture/backend, native events and logs, all answers, failed-startup diagnostics, blinded reviews, scorers and verification. Credentials and raw provider configuration are excluded.

## Audit notes

After 18 completed sessions, the runner paused because docker rm returned nonzero during automatic container removal. The container was verified absent; its answer and usage were retained without rerunning. The runner now checks actual container absence after cleanup. The remaining jobs resumed in their original order.

The initial L05 log comparison flagged raw legacy labels such as Learning Paths and Arm against lowercase validated server labels. The scorer now normalizes arguments using the frozen production SearchFilters model. Original audit records are retained; final native/server logs reconcile for all runs. Run the scorer in the existing evaluation image to use its Pydantic dependency.

The blinded reviewer marked both F05 answers with a minor gap because the snippet-only review bundle did not include empty-search logs. Native/server logs confirm both stated FreeBSD-filtered searches returned zero entries. These are supported search-history claims, not factual errors; raw reviewer grades are retained for transparency, and the tie is unchanged.