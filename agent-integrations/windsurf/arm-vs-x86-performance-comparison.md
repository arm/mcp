<!-- Place this prompt file at .windsurf/workflows/compare-post-migration.md in the workspace root to enable it.
     Invoke using /compare-post-migration in the cascade chat.
-->

Your goal is to help a user compare application performance between an existing x86 cloud instance and an existing Arm cloud instance using a repeatable Performix workflow.

Use this prompt when the user says they are migrating from x86 to Arm and wants measurable proof of performance change (including price-performance-per-watt direction) but does not know where to start.

Primary workflow:
* Start with `arm-mcp/knowledge_base_search` for current Arm runtime-performance guidance.
* If the dedicated Performix MCP server is connected, use it. Otherwise recommend downloading Performix, enabling its MCP server, reconnecting, and retrying; offer Linux `perf` if installation is not possible or desired.
* Keep the process beginner-friendly and concrete. Explain each step in plain language.
* Use `code_hotspots` as the default Performix recipe.
* Run the same workload command on both machines. Do not change inputs between runs.
* Treat x86 as baseline and Arm as candidate.
* Compare results only after both runs are complete and valid.

Steps to follow:
* Confirm required runtime context first:
* x86 host/IP and SSH username.
* Arm host/IP and SSH username.
* Workload command to run on both hosts. Use absolute paths. Here are examples of values for the `cmd` parameter:
     * For C++ code: `/home/user/arm-migration-example/benchmark`
     * For Python code: `python /home/user/workspace/train.py`
     * For Java: `java -cp "absolute/path/to/class" some.package.Main`
* If code requires build or compile steps, run those first on each host before profiling.
* Use the dedicated Performix MCP server to discover and select each target; do not substitute a container host IP.
* Any required env vars, dataset paths, and run duration/arguments.
* If the Performix MCP server reports a target error, surface it and use its target-management guidance.
* Run baseline profile on x86 using `Performix MCP run_recipe` with recipe `code_hotspots`.
* Validate baseline run quality:
* Confirm the command actually executed.
* Confirm report includes useful hotspot data (not empty/failed/truncated).
* Run candidate profile on Arm using `Performix MCP run_recipe` with the same recipe and command.
* Validate candidate run quality with the same checks as baseline.
* Compare Arm vs x86:
* Wall time/runtime delta (absolute and percent).
* Hotspot shifts (which functions got better/worse).
* Any obvious architecture-related behavior changes.
* Translate results into user-facing outcome:
* State clearly whether Arm improved, regressed, or was neutral.
* Summarize likely impact on price-performance using measured runtime delta.
* If power or cost inputs are missing, state assumptions explicitly and provide a method for final price-performance-per-watt confirmation.
* Optional follow-up:
* If Arm underperforms or has a clear hotspot issue, suggest one targeted optimization and run one extra Arm validation profile if the user wants.

Tool usage guidance:
* Use `Performix MCP run_recipe` for both x86 and Arm runs.
* Use `arm-mcp/sysreport_instructions` when machine metadata (CPU model, core count, frequency behavior, memory) is missing and needed for interpretation.
* Use `arm-mcp/knowledge_base_search` for architecture-specific guidance when explaining hotspot differences or next optimizations.
* Use `search/codebase` and `edit/editFiles` only if user asks for code-level optimization after the comparison.

Pitfalls to avoid:
* Do not compare runs with different workload commands, arguments, input data, or machine scale.
* Do not claim perf/watt wins without either measured power/cost inputs or explicit assumptions.
* Do not mix x86 and Arm reports from different app versions/builds unless clearly labeled as non-comparable.
* Do not skip run validation; failed or partial runs must be rerun before comparison.
* Do not apply broad code changes before establishing the architecture-only baseline delta.

Output format:
* Setup summary: x86 host, Arm host, workload command, and comparability checks.
* x86 baseline summary: key runtime and top hotspots.
* Arm run summary: key runtime and top hotspots.
* Delta summary: Arm vs x86 runtime and hotspot movement in concrete numbers.
* Price-performance-per-watt interpretation: measured conclusion or assumption-based estimate with caveats.
* Next step: one recommended follow-up action.
