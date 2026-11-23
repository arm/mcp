# Expanded native KB description evaluation

Study dates: 2026-11-21–22 America/Chicago (runs started 2026-11-22 UTC; resumed after interruption on 2026-11-23 UTC).

## Result

**The larger test does not establish a token-saving improvement from the plain adaptive description.** Across 24 distinct questions it used 790,088 tokens versus 747,227 for baseline: **42,861 more (+5.74%)**. Including six preselected repeats, it used 1,006,474 versus 997,014: **9,460 more (+0.95%)**. Both bootstrap intervals span savings and increases. Excluding retries or restricting to pre-interruption data changes the small point estimate but not the inconclusive result.

This comparison tests the original PR 294 tool description against the exact plain `adaptive` wording stored in the evidence. Both use the same lean result payloads. It does not measure lean payloads against the old payloads, or validate the currently committed `adaptive_or` wording, which additionally contains a Linux/Windows OR example.

Adaptive made slightly fewer KB calls (71 vs 74 pooled) but requested more entries (286 vs 268). Its k choices were exclusively 2 or 5, with k=5 on 48/71 calls; baseline used k=5 on 26/74. This is consistent with oversized follow-up retrieval offsetting fewer calls, but it does not isolate a causal sentence. Neither version used filters, so this study does not demonstrate improved filter behavior.

Recommendation: retain the separately validated lean result formatting, but do not promote this wording as a proven token optimization. The next narrow candidate should distinguish initial search depth from small follow-up searches; test explicit filter restrictions separately. These are next-test hypotheses, not changes validated by this experiment.

## Matched token results

Positive savings favor adaptive; negative savings mean adaptive used more. Totals are reported native input + output, including cached input.

| Set | Pairs / questions | Baseline tokens | Adaptive tokens | Savings | 95% bootstrap interval | KB calls, baseline / adaptive |
|---|---:|---:|---:|---:|---|---:|
| Designated repetition 1 | 24 / 24 | 747,227 | 790,088 | -5.74% | -17.1% to +4.4% | 55 / 54 |
| Six-question repeat subset | 6 / 6 | 249,787 | 216,386 | +13.37% | +0.1% to +23.7% | 19 / 17 |
| Pooled sessions | 30 / 24 | 997,014 | 1,006,474 | -0.95% | -11.8% to +7.6% | 74 / 71 |
| Complete original pairs only | 26 / 22 | 881,448 | 864,408 | +1.93% | -7.9% to +10.4% | 65 / 60 |
| Before network interruption, repetition 1 | 20 / 20 | 631,661 | 648,022 | -2.59% | -13.4% to +7.4% | 46 / 43 |
| Before network interruption, pooled | 25 / 22 | 826,043 | 820,565 | +0.66% | -8.3% to +9.0% | 61 / 56 |

Intervals use 10,000 paired bootstrap samples of question clusters. Pooled estimates weight sessions, so the six repeated questions count twice. These selected smoke questions are not a random production sample; the interval does not establish generalization or quality noninferiority. “Repetition 1” is a designated label: randomization sometimes ran repetition 2 earlier.

Order sensitivity: adaptive used 7.98% more tokens in the 12 baseline-first pairs and 4.12% fewer in the 18 adaptive-first pairs. These groups contain different questions and include the disclosed non-adjacent retry pairs, so this is not proof of a cache or order effect; it reinforces the limits of the pooled point estimate.

## Usage and retrieval detail

| Metric, designated repetition 1 | Baseline | Adaptive |
|---|---:|---:|
| Input tokens | 726,430 | 770,410 |
| Cached input, included above | 455,580 | 488,780 |
| Uncached input = input minus cached | 270,850 | 281,630 |
| Reported cache-write tokens, not added again | 270,625 | 281,399 |
| Output tokens | 20,797 | 19,678 |
| Reported reasoning output, not added again | 7,463 | 6,222 |
| Total input + output | 747,227 | 790,088 |
| KB calls | 55 | 54 |
| Calls using filters | 0 | 0 |
| Sum of requested k | 196 | 219 |
| Returned entries | 196 | 219 |
| Empty calls | 0 | 0 |
| Answers with an expected source returned | 22 | 22 |
| Answers whose Markdown citations are all exact primary returned URLs | 24 | 23 |
| Answers whose links are exact primary URLs or verbatim links in snippets | 24 | 24 |
| Mean session seconds | 36.8 | 40.0 |
| Median session seconds | 34.6 | 40.5 |

Requested-k distributions: baseline `{'2': 12, '3': 21, '4': 2, '5': 19, '6': 1}`; adaptive `{'2': 17, '5': 37}`.

Wall time includes container startup, retrieval, provider latency and reasoning. Ephemeral sessions do not guarantee a cold provider cache. Native usage is accepted as reported by the configured Responses-compatible provider; no dollar saving is inferred.

Expected-source misses are q15 and q16: both versions retrieved other relevant Arm SVE insights/intrinsic pages instead of the prelisted learning-path URLs. The frozen benchmark lists were not changed after seeing this. All source links were preserved exactly; adaptive q20 additionally links the upstream sse2neon repository verbatim from its snippet. The citation parser was corrected to recognize CommonMark angle-bracket destinations used by baseline q18.

## Blinded answer review

Model-assisted review covered 24 first-designated answer pairs. The reviewer read randomized A/B answers and each answer’s retrieved snippets without description labels or token metrics. This checks support and essential completeness; it is not human review, external fact checking or runtime validation.

| Quality category | Baseline | Adaptive |
|---|---:|---:|
| completion: adequate | 24 | 24 |
| completion: partial | 0 | 0 |
| completion: inadequate | 0 | 0 |
| grounding: supported | 12 | 10 |
| grounding: minor_gap | 10 | 12 |
| grounding: material_gap | 2 | 2 |

Pair preferences: `{'uncertain': 1, 'tie': 20, 'adaptive': 3}`. Unsupported additions are not automatically false; the archived reviews identify the exact claims and evidence limits.

Across all 24 pairs, the blinded reviewer found 20 ties, three modest evidence/completeness preferences for adaptive, and one uncertain comparison. Both versions were rated adequate on all questions, but both had material evidence gaps on Ray Serve (q07) and Unity/Burst (q21). Those gaps mean central implementation details lacked snippet support, not that runtime failure was established.

The q26 review was calibrated against its exact wording: architecture-specific tags separate architectures, while commit-SHA tags alone do not isolate reruns. An initially overbroad material finding was reduced to a minor caveat; the original rating and rationale are retained. This illustrates why these model-assisted grades are judgments rather than ground truth.

## Per-question results

| Question | Baseline tokens / calls | Adaptive tokens / calls | Savings | Grounding, baseline / adaptive |
|---|---:|---:|---:|---|
| q02 — How do I package and deploy a Node.js AWS Lambda function on Graviton using Terraform? | 39,956 / 3 | 29,398 / 2 | +26.4% | minor_gap / minor_gap |
| q03 — How can I measure MinIO upload and download throughput on an Azure Cobalt 100 VM? | 27,345 / 2 | 26,977 / 2 | +1.3% | minor_gap / minor_gap |
| q07 — How do I deploy a Python HTTP endpoint with Ray Serve on a Google Axion VM? | 39,839 / 4 | 39,653 / 3 | +0.5% | material_gap / material_gap |
| q10 — How can I build and run SME2 examples if my machine has no SME2 hardware? | 45,940 / 3 | 61,588 / 4 | -34.1% | supported / minor_gap |
| q11 — Which C function attributes enable SME streaming mode and give a function its own ZA state? | 17,817 / 1 | 17,613 / 1 | +1.1% | supported / supported |
| q14 — How does SME2 LUTI2 use ZT0 to expand packed 2-bit weights into 8-bit values? | 28,267 / 2 | 27,696 / 2 | +2.0% | supported / supported |
| q15 — How do SVE predicates handle the final partial vector of an array without a scalar cleanup loop? | 16,756 / 1 | 16,501 / 1 | +1.5% | supported / supported |
| q16 — How can I check the SVE vector length at runtime in a C program? | 17,483 / 1 | 16,473 / 1 | +5.8% | minor_gap / supported |
| q18 — How can I use SVE2 MATCH to search a byte array for any of several key values? | 31,800 / 2 | 19,680 / 1 | +38.1% | supported / supported |
| q20 — How do I port C++ code that uses SSE2 intrinsics to Arm64 with sse2neon? | 28,169 / 2 | 31,788 / 2 | -12.8% | minor_gap / minor_gap |
| q21 — How do I enable and use Arm Neon intrinsics in Unity C# code for an Android ARM64 build? | 41,077 / 4 | 42,535 / 4 | -3.5% | material_gap / material_gap |
| q24 — How do I request camera permission and receive frames using OpenCV JavaCameraView in an Android app? | 18,768 / 1 | 18,951 / 1 | -1.0% | minor_gap / minor_gap |
| q25 — How do I configure Cyclone DDS communication between OpenAD Kit ROS 2 containers running on two Arm instances? | 18,906 / 1 | 30,650 / 2 | -62.1% | supported / supported |
| q26 — How can I build amd64 and arm64 Docker images with native GitHub Actions runners and publish them under one multi-architecture tag? | 28,837 / 2 | 51,270 / 4 | -77.8% | supported / minor_gap |
| q27 — How can I use WindowsPerf sampling to find hot functions in a Windows on Arm program? | 31,104 / 2 | 32,745 / 2 | -5.3% | supported / minor_gap |
| q28 — How do I compile and run a PyTorch model with ExecuTorch on the Corstone-320 FVP? | 46,341 / 3 | 48,272 / 3 | -4.2% | supported / supported |
| q30 — How do I trigger PAC/BTI tests on Arm devices through AWS IoT Greengrass and read the per-device results? | 18,016 / 1 | 17,916 / 1 | +0.6% | supported / supported |
| q32 — How do I capture and inspect an Android app frame using RenderDoc for Arm GPUs? | 41,218 / 3 | 44,042 / 3 | -6.9% | supported / supported |
| q33 — When is it safe to add restrict to C pointer parameters, and how can it help optimization on Arm? | 26,105 / 2 | 30,290 / 2 | -16.0% | minor_gap / minor_gap |
| q36 — How do I enable MTE in an Android app and use Android Studio to locate a use-after-free bug on a Pixel 8? | 58,532 / 5 | 43,436 / 3 | +25.8% | minor_gap / minor_gap |
| q37 — How do I rebuild a C++ DLL as Arm64EC in Visual Studio while keeping existing x64 dependencies? | 39,215 / 4 | 40,123 / 3 | -2.3% | minor_gap / minor_gap |
| q40 — How do I use KubeArchInspect to check whether images running in my Kubernetes cluster support arm64? | 30,149 / 2 | 44,770 / 3 | -48.5% | supported / supported |
| q42 — Why can publishing a pointer with relaxed C++ atomics fail on Arm, and how do acquire/release operations fix it? | 28,177 / 2 | 29,033 / 2 | -3.0% | minor_gap / minor_gap |
| q46 — How do I use fio job files to compare storage throughput and latency on Arm Linux? | 27,410 / 2 | 28,688 / 2 | -4.7% | minor_gap / minor_gap |

## Design and limitations

- 24 fresh questions selected from the repository smoke suite, covering cloud, SIMD, intrinsics, embedded, Android, Windows, CI/containers, security, compilers, porting and storage. Six preselected questions repeat once: 30 pairs / 60 planned sessions.
- Frozen wording; seeded pair order and within-pair variant order; 12 pairs baseline-first and 18 adaptive-first. Same empty client workspace. One retrieval container at a time.
- Native Codex CLI 0.150.1, configured `gpt-6-astra`, high reasoning, existing Responses-compatible provider. The CLI warns that this alias uses fallback model metadata; the same warning applies to both variants.
- No skill deliberately installed or read. Plugins and skill search disabled. Complete absence of global skill metadata in the hidden effective prompt is unverified.
- Actual KB retrieval against the frozen 43,320-row corpus. Other MCP tool schemas are present with unavailable stubs; external browsing and commands disabled by the test prompt/configuration. Answers requested under 180 words. No question approves page expansion.
- Expected-source coverage means any listed benchmark alternative returned, matching host/path or a child path and ignoring query/fragment. It is a retrieval signal, not answer correctness. Citation preservation and evidence grounding are scored separately.
- Corpus has legacy labels and many missing platform tags. Mostly positive in-corpus questions provide limited evidence about explicit restrictions, no-match behavior, negative compatibility claims, page expansion, or arbitrary production tasks.
- This is one model/provider/configuration and a bundled description change. It cannot isolate the effect of an individual sentence or establish universal token savings.

## Failure and cost accounting

Recorded attempts: 66. Attempts with final usage: 60. Reported experiment tokens: **2,003,488**. Missing usage: `['q16-adaptive-1', 'q16-baseline-1', 'q20-baseline-1', 'q21-adaptive-1', 'q21-baseline-1', 'q26-adaptive-1']`. This excludes orchestration/reviewer chat usage, earlier experiments and any unreported provider work.

Six original attempts failed for infrastructure reasons: q26 adaptive during required MCP startup, and q16 adaptive/baseline, q21 baseline/adaptive and q20 baseline during a network interruption (all designated repetition 1). The five timeout logs report connection failures and lack final usage. A large wall-clock gap occurred; its host-level cause is not established. The original runner records timeout duration as a fixed 240 seconds and did not preserve timeout stderr, so that field is not a complete elapsed-time measure. An earlier Docker event inspection identified OOM on the q26 evaluation container; the observation and the later absence of that event from Docker history are documented in infra-note.md. All six originals remain in the evidence with unknown usage. Infrastructure-only retries have separate immutable IDs and named-container cleanup checks; failed/model-behavior answers are not selected away. q16 and q21 are retried as adjacent pairs; q26 and q20 retain their original successful counterpart, so those selected pairs are non-adjacent. A later Docker inventory found no surviving timed-out evaluation containers; cleanup was not verified separately at each original timeout. Model/provider settings were unchanged in the config file, whose modification time predates the study. Sensitivity rows exclude retries and the interruption.

## Reproducibility

Source commit: `80bb3684591935bbebdfbe9fdbb3bb08d2867dc0`. Image: `sha256:76fc8ee8bbb18905942e4f0c965dc1a1b52feb4b245698db20bf2a7b3f163b21`.

Description SHA-256: baseline `556fc1d61cc7ab90d5c7a54e176258559efb5af68c2b11d9e0acd76eb06018ac`; adaptive `af8c01b9a5b7736016886f3dd059a552a9365d071b3168b680e04214f1595d18`.

Evidence: `artifacts/kb-native-expanded-20261121/evidence.tar.gz` contains frozen descriptions, questions/schedule/provenance, source snapshot, runners and scorers, every native event/answer/status/log, retry history, blinded evidence/reviews and summary data. Credentials and raw provider configuration are excluded. Archive checksum is stored alongside it.
