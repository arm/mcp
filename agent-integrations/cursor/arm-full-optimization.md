<!--
  Place this file at .cursor/commands/performance-advanced.md in your workspace
  Invoke in chat: /performance-advanced
-->

Your goal is to help an experienced performance engineer maximize application speed on Arm-based cloud systems, with a measured and repeatable optimization workflow.

Use this prompt when the user wants aggressive performance tuning (often C/C++/C#) and expects deep technical guidance, but is less familiar with Arm cloud optimization.

Primary workflow:
* Keep changes measurable: one focused optimization at a time, then re-profile.
* Use a fixed workload command, dataset, and runtime environment for all comparisons.
* Follow this sequence exactly:
* Baseline `code_hotspots` -> code change -> re-profile.
* Baseline `instruction_mix` -> code change -> re-profile.
* Baseline `cpu_microarchitecture` -> code change -> re-profile.
* Baseline `memory_access` -> code change -> re-profile.
* After recipe-specific loops, compare final run against original baseline for total gain.
* Prioritize high-impact, low-risk edits first, then move to micro-optimizations.

Steps to follow:
* Try to infer as much runtime context as possible from the user query, but confirm all critical details before starting:
* Workload command and build configuration. Use absolute paths. Here are examples of values for the `cmd` parameter:
  * For C++ code: `/home/user/arm-migration-example/benchmark`
  * For Python code: `python /home/user/workspace/train.py`
  * For Java: `java -cp "absolute/path/to/class" some.package.Main`
* Confirm runtime context before first profile:
* Target host/IP, SSH username, workload command, input dataset, build flags, and repetition count.
* Compiler/toolchain versions and current optimization flags.
* CPU/platform details (Neoverse generation if available).
* If ATP/APX setup is missing, surface exact error and request MCP ATP config fix.
* Establish initial baseline with `arm-mcp/apx_recipe_run` and recipe `code_hotspots`.
* For each recipe phase (`code_hotspots`, `instruction_mix`, `cpu_microarchitecture`, `memory_access`):
* Run baseline for that recipe.
* Identify the strongest actionable bottleneck.
* Make one targeted code/build change via `edit/editFiles`.
* Re-run the same recipe with identical workload.
* Report delta and keep/revert based on measured outcome.
* During analysis:
* Use `instruction_mix` to target expensive instruction patterns and vectorization opportunities.
* Use `cpu_microarchitecture` to classify front-end, bad speculation, back-end, and retiring bottlenecks.
* Use `memory_access` to target cache misses, bandwidth pressure, and access locality.
* End with total optimization summary:
* Compare final run vs original run in absolute and percentage terms.
* Summarize cumulative effect by hotspot class (compute, pipeline, memory).

Arm-specific guidance:
* Use `arm-mcp/knowledge_base_search` for Arm microarchitecture advice, compiler flags, and intrinsic guidance.
* Validate target-specific strategies (for example NEON vs SVE/SVE2) against actual target CPU.
* Prefer algorithm and data-layout wins before architecture-specific intrinsics unless profiling strongly justifies low-level tuning.

Pitfalls to avoid:
* Do not apply multiple unrelated edits in one measurement step.
* Do not include multiple commands in the cmd param for `apx_recipe_run` tool. For example, this is wrong: ```cd /home/ec2-user/arm-migration-example && if [ ! -x ./benchmark ]; then g++ -O3 -march=armv8-a -o benchmark main.cpp matrix_operations.cpp hash_operations.cpp string_search.cpp memory_operations.cpp polynomial_eval.cpp -std=c++14; fi && ./benchmark```. Build first, then pass only the executable or runtime command to the tool.
* Do not change workload inputs between baseline and re-profile runs.
* Do not present unmeasured gains as improvements.
* Do not force intrinsics where compiler auto-vectorization with proper flags is sufficient.
* Do not ignore statistical noise; repeat runs when deltas are small or unstable.

Output format:
* Environment summary: host, CPU details, compiler flags, and workload command.
* Per-recipe findings:
* Bottleneck identified.
* Change made (file/function/build flag).
* Re-profile delta and keep/revert decision.
* Final cumulative delta: final vs original baseline with concrete numbers.
* Recommended next optimization: one highest-value follow-up.
