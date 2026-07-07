<!-- Place this prompt file at .github/prompts/arm-enablement.prompt.md in the repo root to enable it.
     Invoke using /arm-enablement in the chat.
-->
---
name: 'arm-enablement'
description: 'Scan an OSS codebase with Arm MCP and generate a CubeFS-style Arm enablement report as Markdown and PDF'
argument-hint: '[local workspace or GitHub repo URL] [--apply-fixes optional]'
agent: 'agent'
tools: ['search/codebase', 'search/fileSearch', 'search/textSearch', 'search/listDirectory', 'edit/editFiles', 'execute/runInTerminal', 'execute/getTerminalOutput', 'read/terminalLastCommand', 'arm-mcp/skopeo', 'arm-mcp/check_image', 'arm-mcp/knowledge_base_search', 'arm-mcp/migrate_ease_scan', 'arm-mcp/mca', 'arm-mcp/apx_recipe_run', 'arm-mcp/sysreport_instructions']
---

Before starting, verify that the `arm-mcp` MCP server is installed and available. If you don't have access to the arm-mcp tools (skopeo, check_image, knowledge_base_search, migrate_ease_scan, mca, sysreport_instructions), refer to the [MCP Server Installation Guide](https://github.com/arm/mcp/blob/main/agent-integrations/agent-install-instructions.md) to install it on vs-code.

Your goal is to evaluate an open-source codebase for Arm (aarch64) readiness and generate a polished **Arm Enablement Report** like the CubeFS case study. The report must be useful to an OSS maintainer, developer-relations team, or CNCF community audience. It must answer: "What is needed to make this project 100% Arm-enabled, and what did the Arm MCP Server discover that ordinary manual review could miss?"

The required local deliverables are:

* `arm-enablement-report.md` at the repo root.
* `arm-enablement-report.pdf` at the repo root, exported from the markdown report.

The report must be reproducible. Every technical claim must be backed by an `arm-mcp` tool call, a file reference, or a command result. Do not present unmeasured performance wins as facts. Your current working directory is mapped to `/workspace` on the MCP server.

Input handling:

* If the user runs `/arm-enablement` from an already-cloned OSS project, analyze the current workspace.
* If the user provides a GitHub repository URL, clone that repository into the current workspace if it is empty, or into a clearly named subdirectory such as `arm-enablement-target/` if the workspace is not empty. Then analyze the cloned repository.
* If the user provides `--apply-fixes` or explicitly asks to fix the project, apply the minimum source changes needed for Arm enablement after writing the initial report, then update the report with the implemented fixes and re-run the relevant MCP checks.
* If the user does not request fixes, stay in report-only mode. Do not modify project source files except for creating `arm-enablement-report.md` and `arm-enablement-report.pdf`.

Steps to follow:

* Detect the project's primary language(s) by inspecting the codebase (`go.mod`, `package.json`, `requirements.txt`, `pom.xml`, `Cargo.toml`, `CMakeLists.txt`, source file extensions). Pick the appropriate `migrate_ease_scan` scanner: `cpp`, `python`, `go`, `js`, or `java`.
* Run `arm-mcp/migrate_ease_scan` against the workspace with the chosen scanner. If the user supplied a GitHub URL and the workspace is not the target checkout, pass the URL as `git_repo` only for the scanner call, then use the local clone for file inspection. Capture every architecture-sensitive finding (file path, line number, category, suggestion). This is the discovery phase and drives the rest of the report.
* For each Dockerfile, Compose file, and Kubernetes manifest in the repo, list every container image referenced. For each image, call `arm-mcp/check_image` to confirm `linux/arm64` is published. For images pinned by `@sha256:` digest, also call `arm-mcp/skopeo` with `raw=true` to confirm whether the digest resolves to a multi-arch manifest list or a single-arch manifest. Flag any image that is amd64-only or pinned to a single-arch digest.
* For each dependency declared in package manifests (Dockerfile `apt-get`/`yum`/`apk` lines, `requirements.txt`, `go.mod`, `package.json`, `pom.xml`), call `arm-mcp/knowledge_base_search` and explicitly ask "Is [package] compatible with Arm architecture?" where [package] is the name of the package. Record the verdict and the recommended version if a change is needed.
* Inspect build entry points (`Makefile`, `build.sh`, `CMakeLists.txt`, `setup.py`, `Dockerfile` build stages, CI workflows) for architecture-switching logic. Manually read shell pipelines and `case`/`switch` blocks that branch on `uname -m`, `$ARCH`, `TARGETARCH`, `GOARCH`, `CPUTYPE`, or similar variables. Subtle shell semantics bugs (subshell variable scope, missing `arm64` cases, hard-coded `amd64` URLs) are common and not catchable by `grep`. Call out anything suspicious as a "Critical Discovery" candidate.
* If the codebase contains assembly (`.s`, `.S`) or architecture-specific intrinsics (SSE/AVX, NEON), use `arm-mcp/mca` to analyze representative hot paths and use `arm-mcp/knowledge_base_search` to find the Arm equivalent (NEON, SVE, or SVE2 depending on target).
* OPTIONAL: If the user is on an Arm host or has access to an Arm runner (AWS Graviton, Azure Cobalt, GCP Axion), validate the final state with native builds, `file <binary>` architecture checks, `sysreport_instructions`, and `arm-mcp/apx_recipe_run` for performance/hotspot evidence when relevant. If no Arm host is available, mark validation as deferred.
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
* Do not generate a generic checklist. The final report must be specific to the scanned repository, cite real files, and distinguish confirmed findings from recommended follow-up work.

Output format:

First produce a single markdown file named `arm-enablement-report.md` at the repo root with the following sections, in order. Every section is required; if a section has no findings, write "No findings" rather than omitting the section.

Use a professional report style similar to the CubeFS Arm MCP case study: concise narrative, evidence tables, maintainer-facing recommendations, and a clear before/after story. Do not make it sound like an internal debug log.

* **Executive Summary** — One paragraph: project name, language(s) and lines of code, total findings count, container audit summary, the single highest-impact recommendation, and overall Arm-readiness verdict (Ready / Mostly Ready / Significant Work / Broken).
* **Background: The Problem** — What the project does, where Arm enablement matters, why a maintainer should care, and any prior Arm-related claims found in CHANGELOGs or READMEs (especially claims contradicted by the scan results).
* **What is the Arm MCP Server?** — Briefly explain that Arm MCP provides tools such as `migrate_ease_scan`, `knowledge_base_search`, `check_image`, `skopeo`, `mca`, `sysreport_instructions`, and `apx_recipe_run`, and that the agent used those tools directly during this assessment.
* **Project Overview** — Repository URL, primary language(s), approximate lines of code, build system, container strategy, CI/release strategy, and existing architecture support signals.
* **Step 1: Automated Codebase Analysis** — `migrate_ease_scan` summary table: column headers `File`, `Line`, `Category`, `Finding`, `Suggested Fix`. Group by category. State the scanner used and the elapsed time.
* **Step 2: Dependency and Knowledge Base Verification** — Table of every package checked via `knowledge_base_search`: column headers `Package`, `Source File`, `Arm Compatible`, `Notes / Recommended Version`. Cite the KB documents used.
* **Step 3: Container Supply Chain Verification** — Table per image: `Image`, `Pinned By` (tag/digest), `arm64 Support`, `Action Needed`. Include `check_image` and `skopeo` verdicts. Call out single-arch digest pins explicitly.
* **Step 4: Build System and Architecture Switching** — Plain-English audit of `build.sh`, `Makefile`, `Dockerfile`, CI workflows, and any other architecture-switching files. Include short code snippets for any logic flagged as suspicious.
* **Critical Discoveries: Bugs Hiding in Plain Sight** — Non-obvious findings that manual review or `grep` would miss (silent shell bugs, missing `arm64` cases, single-arch digest pins, hardcoded amd64 download URLs). For each: the bug, why it survived undetected, impact to users/contributors, and the one-line fix. Write "No critical discoveries" if none.
* **Step 5: Implementation Plan or Implemented Fixes** — If in report-only mode, provide a table of files to change: `#`, `File`, `What to fix`, `Why`, `Priority`. If `--apply-fixes` was requested, instead list each file changed and what was fixed. Order by impact. Include both required fixes (broken on Arm) and recommended fixes (works but suboptimal).
* **Step 6: Validation** — If a build was attempted, report build status and ELF target architecture for produced binaries (`file <binary>` output is sufficient). If no build was attempted, state "Validation deferred — recommend running on an AWS Graviton, Azure Cobalt, or GCP Axion instance after applying the Implementation Plan."
* **Effort Comparison** — Three-row table: `Approach` (Manual investigation / AI agent without Arm MCP / AI agent with Arm MCP), `Risk Level`, `Time to discovery`. Use the actual elapsed time for the Arm MCP row from the audit trail.
* **What Did Not Have to Happen** — A two-column table comparing traditional manual effort with the Arm MCP-assisted workflow, modeled on the CubeFS report. Include rows for grep triage, Docker image guessing, dependency flag trial-and-error, missed build-script logic, and waiting for external guidance when applicable.
* **Audit Trail** — Numbered table of every `arm-mcp` tool invocation: `#`, `Time (UTC)`, `Tool`, `Purpose`. End with total invocation count and total MCP computation time.
* **Impact** — Three subsections: impact for the project maintainers/users, impact for the Arm ecosystem and OSS growth, and impact for Arm developer tooling. Keep claims evidence-based and avoid marketing exaggeration.
* **Roadmap to Arm Parity** — Two phases. Phase 1: Discovery and Enablement (what this report covers, the work the maintainer must merge). Phase 2: Execution and Distribution (multi-arch CI runners, multi-arch image publishing, release workflow updates) — items the Arm MCP server cannot drive but can validate.
* **Conclusion** — A short, maintainer-facing conclusion that says what the project should do next.
* **References** — Repository URL, language scanner used, MCP server version, and links to any KB articles cited. Include attribution to the [Arm MCP Server](https://github.com/arm/mcp).

After the markdown report is complete, export it to a local PDF named `arm-enablement-report.pdf` at the repo root.

PDF export instructions:

* First try `pandoc arm-enablement-report.md -o arm-enablement-report.pdf` if `pandoc` is installed.
* If `pandoc` is not available and Node.js is installed, try `npx --yes md-to-pdf arm-enablement-report.md --output arm-enablement-report.pdf`.
* If both exporters are unavailable, do not invent a PDF. Leave `arm-enablement-report.md` complete and tell the user exactly which command to run after installing `pandoc` or Node.js. The markdown report remains the source of truth.
* After export, verify that `arm-enablement-report.pdf` exists and is non-empty. If possible, report its file size.

If the user has explicitly asked for changes to be applied, after the report is written: apply the fixes from the Implementation Plan via `edit/editFiles`, commit each fix as a separate change for review-ability, and re-run `migrate_ease_scan` to confirm findings are resolved. If the user asked only for analysis, do not modify any source files; the report alone is the deliverable.

Provide the final markdown and PDF paths to the user along with a one-line summary of the Arm-readiness verdict.
