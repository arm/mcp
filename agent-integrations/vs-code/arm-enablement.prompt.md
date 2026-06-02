<!-- Place this prompt file at .github/prompts/arm-enablement.prompt.md in the repo root to enable it.
     Invoke using /arm-enablement in the chat.
-->
---
name: 'arm-enablement'
description: 'Scan an OSS codebase and produce a maintainer-facing Arm enablement report with actionable findings, container audit, and roadmap'
agent: 'agent'
tools: ['search/codebase', 'edit/editFiles', 'arm-mcp/skopeo', 'arm-mcp/check_image', 'arm-mcp/knowledge_base_search', 'arm-mcp/migrate_ease_scan', 'arm-mcp/mca', 'arm-mcp/sysreport_instructions']
---

Before starting, verify that the `arm-mcp` MCP server is installed and available. If you don't have access to the arm-mcp tools (skopeo, check_image, knowledge_base_search, migrate_ease_scan, mca, sysreport_instructions), refer to the [MCP Server Installation Guide](https://github.com/arm/mcp/blob/main/agent-integrations/agent-install-instructions.md) to install it on vs-code.

Your goal is to evaluate an open-source codebase for Arm (aarch64) readiness and produce a structured **Arm Enablement Report** that an OSS maintainer can publish or attach to a tracking issue. The audience is a project maintainer who wants a clear, evidence-based answer to: "What is needed to make this project 100% Arm-enabled?". The report must be reproducible, every claim must be backed by an `arm-mcp` tool call, and unmeasured improvements must not be presented as wins. Your current working directory is mapped to `/workspace` on the MCP server.

Steps to follow:

* Detect the project's primary language(s) by inspecting the codebase (`go.mod`, `package.json`, `requirements.txt`, `pom.xml`, `Cargo.toml`, `CMakeLists.txt`, source file extensions). Pick the appropriate `migrate_ease_scan` scanner: `cpp`, `python`, `go`, `js`, or `java`.
* Run `arm-mcp/migrate_ease_scan` against the workspace with the chosen scanner. Capture every architecture-sensitive finding (file path, line number, category, suggestion). This is the discovery phase and drives the rest of the report.
* For each Dockerfile, Compose file, and Kubernetes manifest in the repo, list every container image referenced. For each image, call `arm-mcp/check_image` to confirm `linux/arm64` is published. For images pinned by `@sha256:` digest, also call `arm-mcp/skopeo` with `raw=true` to confirm whether the digest resolves to a multi-arch manifest list or a single-arch manifest. Flag any image that is amd64-only or pinned to a single-arch digest.
* For each dependency declared in package manifests (Dockerfile `apt-get`/`yum`/`apk` lines, `requirements.txt`, `go.mod`, `package.json`, `pom.xml`), call `arm-mcp/knowledge_base_search` and explicitly ask "Is [package] compatible with Arm architecture?" where [package] is the name of the package. Record the verdict and the recommended version if a change is needed.
* Inspect build entry points (`Makefile`, `build.sh`, `CMakeLists.txt`, `setup.py`, `Dockerfile` build stages) for architecture-switching logic. Manually read shell pipelines and `case`/`switch` blocks that branch on `uname -m`, `$ARCH`, `TARGETARCH`, `GOARCH`, or `CPUTYPE`. Subtle shell semantics bugs (subshell variable scope, missing `arm64` cases, hard-coded `amd64` URLs) are common and not catchable by `grep`. Call out anything suspicious as a "Critical Discovery" candidate.
* If the codebase contains assembly (`.s`, `.S`) or architecture-specific intrinsics (SSE/AVX, NEON), use `arm-mcp/mca` to analyze representative hot paths and use `arm-mcp/knowledge_base_search` to find the Arm equivalent (NEON, SVE, or SVE2 depending on target).
* OPTIONAL: If the user is on an Arm host or has access to an Arm runner (AWS Graviton, Azure Cobalt, GCP Axion), apply the recommended fixes via `edit/editFiles` and rebuild to validate. Report any compilation errors and resolve them. Do not apply fixes unless the user has confirmed they want changes committed; the default mode is read-only analysis that produces the report.
* Maintain an audit trail: for every `arm-mcp` tool call, record `{timestamp, tool, arguments, reason}`. This drives the "Audit Trail" section of the final report.

Pitfalls to avoid:

* Do not equate `grep -r "amd64"` results with actionable findings. `migrate_ease_scan` filters out false positives in vendored dependencies, test fixtures, and assembly files that already carry arm64 build tags. Trust the scanner over manual grep.
* Do not assume an image is multi-arch because the upstream tag has Arm64 manifests. A `@sha256:` digest pin in a Dockerfile resolves to a single platform manifest and will fail with `exec format error` on Arm hosts. Always inspect digests with `skopeo`.
* Do not confuse a software version with a language wrapper package version. For example, when checking the Python Redis client, check the Python package name "redis" rather than the Redis server version.
* NEON lane indices must be compile-time constants, not variables.
* Do not mark a finding as resolved without running `migrate_ease_scan` again to confirm. Re-scan after every batch of fixes.
* Do not present unmeasured gains as improvements. Performance numbers in the report must come from a real build and (optionally) `arm-mcp/apx_recipe_run` measurement.
* Do not skip the audit trail. The report's value to maintainers is reproducibility; an undocumented run cannot be defended.
* Be sure to find out from the user or system what the target machine is, and use the appropriate intrinsics. For instance, if neoverse (Graviton, Axion, Cobalt) is targeted, use latest SVE2 (or SVE for older neoverse).

Output format:

Produce a single markdown file named `arm-enablement-report.md` at the repo root with the following sections, in order. Every section is required; if a section has no findings, write "No findings" rather than omitting the section.

* **Executive Summary** — One paragraph: project name, language(s) and lines of code, total findings count, container audit summary, the single highest-impact recommendation, and overall Arm-readiness verdict (Ready / Mostly Ready / Significant Work / Broken).
* **Project Overview** — Repository, primary language(s), build system, container strategy, and any prior Arm-related claims found in CHANGELOGs or READMEs (especially flag claims that contradict the scan results).
* **Step 1: Automated Codebase Analysis** — `migrate_ease_scan` summary table: column headers `File`, `Line`, `Category`, `Finding`, `Suggested Fix`. Group by category. State the scanner used and the elapsed time.
* **Step 2: Dependency and Knowledge Base Verification** — Table of every package checked via `knowledge_base_search`: column headers `Package`, `Source File`, `Arm Compatible`, `Notes / Recommended Version`. Cite the KB documents used.
* **Step 3: Container Supply Chain Verification** — Table per image: `Image`, `Pinned By` (tag/digest), `arm64 Support`, `Action Needed`. Include `check_image` and `skopeo` verdicts. Call out single-arch digest pins explicitly.
* **Step 4: Build System and Architecture Switching** — Plain-English audit of `build.sh`, `Makefile`, `Dockerfile`, and any other architecture-switching files. Include verbatim quoted code snippets for any logic flagged as suspicious.
* **Critical Discoveries** — Non-obvious findings that manual review or `grep` would miss (silent shell bugs, missing `arm64` cases, single-arch digest pins, hardcoded amd64 download URLs). For each: the bug, why it survived undetected, and the one-line fix. Write "No critical discoveries" if none.
* **Step 5: Implementation Plan** — Table of files to change: `#`, `File`, `What to fix`, `Why`. Order by impact. Include both required fixes (broken on Arm) and recommended fixes (works but suboptimal).
* **Step 6: Validation** — If a build was attempted, report build status and ELF target architecture for produced binaries (`file <binary>` output is sufficient). If no build was attempted, state "Validation deferred — recommend running on an AWS Graviton, Azure Cobalt, or GCP Axion instance after applying the Implementation Plan."
* **Effort Comparison** — Three-row table: `Approach` (Manual investigation / AI agent without Arm MCP / AI agent with Arm MCP), `Risk Level`, `Time to discovery`. Use the actual elapsed time for the Arm MCP row from the audit trail.
* **Audit Trail** — Numbered table of every `arm-mcp` tool invocation: `#`, `Time (UTC)`, `Tool`, `Purpose`. End with total invocation count and total MCP computation time.
* **Roadmap to Arm Parity** — Two phases. Phase 1: Discovery and Enablement (what this report covers, the work the maintainer must merge). Phase 2: Execution and Distribution (multi-arch CI runners, multi-arch image publishing, release workflow updates) — items the Arm MCP server cannot drive but can validate.
* **References** — Repository URL, language scanner used, MCP server version, and links to any KB articles cited. Include attribution to the [Arm MCP Server](https://github.com/arm/mcp).

If the user has explicitly asked for changes to be applied, after the report is written: apply the fixes from the Implementation Plan via `edit/editFiles`, commit each fix as a separate change for review-ability, and re-run `migrate_ease_scan` to confirm findings are resolved. If the user asked only for analysis, do not modify any source files; the report alone is the deliverable.

Provide the final report path to the user along with a one-line summary of the Arm-readiness verdict.
