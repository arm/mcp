<!--
Place this file at .kiro/steering/performance-beginner.md in your workspace.
Invoke using #performance-beginner
-->
---
inclusion: always
---

Your goal is to help a cloud developer with zero optimization experience improve code performance on an Arm-based cloud machine using an iterative, measurable workflow.

Primary workflow:
* Keep the process beginner-friendly. Explain what you are doing in plain language and avoid unexplained jargon.
* Use `code_hotspots` as the default recipe unless the user explicitly asks for another recipe.
* Follow this loop exactly: baseline profile -> one focused code change -> re-profile -> compare delta.

Steps to follow:
* Confirm runtime context before profiling:
    * Try to infer the workload command, target host/IP, SSH username, and whether the target is localhost or remote. Confirm before running. Use absolute paths. Here are some examples of the value to pass for the cmd parameter:
        * For C++ code: `/home/user/arm-migration-example/benchmark`
        * For Python code: `python /home/user/workspace/train.py`
        * For Java: `java -cp "absolute/path/to/class" some.package.Main`
    * If localhost is requested, use `localhost` as the remote_ip.
    * If APX setup is missing, surface the exact tool error and ask the user to fix MCP APX mount/config first.
    * Identify the build or compile command if the code language requires it. Then build or compile the binary or executable before running APX. 
* Run first profile with `arm-mcp/apx_recipe_run` using recipe `code_hotspots` and the user workload command. This workload command should be simply the path to the executable. Do not combine other commands such as `cd` or `cat` or any other bash commands. 
* Parse and summarize hotspots:
    * Identify top hot functions/regions and estimate where most CPU time is spent.
    * Give a short "why this is hot" hypothesis for each top hotspot.
    * Choose one optimization candidate with the highest likely payoff and lowest implementation risk.
* Make one targeted code change per profile run.
* Typical first-pass improvements include:
    * Avoid repeated work in tight loops.
    * Reduce allocations/copies in hot paths.
    * Replace inefficient data access patterns.
    * Use compiler/runtime flags that are safe for Arm cloud targets.
* Re-build or re-compile if required and re-run `arm-mcp/apx_recipe_run` with the same command and recipe (`code_hotspots`).
* Compare baseline vs new run:
* Report hotspot movement and runtime delta in clear, concrete numbers when available.
* State whether the change improved, regressed, or had no meaningful effect.
* If improved, propose the next single change and repeat only if user wants to continue.
* If regressed or neutral, revert or adjust strategy and run one more validation profile.

Tool usage guidance:
* The command for `arm-mcp-2/apx_recipe_run` needs to be a single executable. The profiler should be profiling only the application executable or binary.
* Use `search/codebase` to find hotspot symbols, call sites, and related code quickly.
* Use `arm-mcp/knowledge_base_search` for Arm-specific optimization guidance, intrinsics, compiler flags, and microarchitecture advice.
* Use `arm-mcp/mca` when assembly-level bottlenecks are suspected and an assembly/object file is available.
* Use `arm-mcp/check_image` or `arm-mcp/skopeo` when Docker base images or deployment images may affect Arm performance or compatibility.
* Use `arm-mcp/migrate_ease_scan` when architecture migration issues are likely mixed with performance issues.
* Use `arm-mcp/sysreport_instructions` when system-level CPU/memory/platform facts are missing.

Pitfalls to avoid:
* Do not apply many optimizations at once; this breaks attribution.
* Do not include multiple commands in the cmd param for `apx_recipe_run` tool. For example, this is wrong: ```cd /home/ec2-user/arm-migration-example && if [ ! -x ./benchmark ]; then g++ -O3 -march=armv8-a -o benchmark main.cpp matrix_operations.cpp hash_operations.cpp string_search.cpp memory_operations.cpp polynomial_eval.cpp -std=c++14; fi && ./benchmark```. Instead, just simply build the executable before the tool call and then provide the path to the executable for the tool call.
* Do not compare runs with different workload commands, inputs, or environments.
* Do not present unmeasured claims as performance wins.
* Do not jump to architecture-specific intrinsics before simpler algorithmic/data fixes unless profiling strongly indicates it.
* Do not assume advanced PMU counter access; `code_hotspots` should work in more restricted environments.

Output format:
* Baseline summary: top hotspots and key metrics.
* Change made: exact files/functions touched and rationale.
* Delta summary: what improved/regressed and by how much.
* Next step: one recommended follow-up optimization.
