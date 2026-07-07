<!-- Place this prompt file at ~/.codex/prompts/arm-enablement.md to enable it.
     Invoke using /prompts:arm-enablement in the codex chat.
-->
---
description: Scan an OSS codebase with Arm MCP and generate a CubeFS-style Arm enablement report as Markdown and PDF
---

Before starting, verify that the `arm-mcp` MCP server is installed and available. If you don't have access to the arm-mcp tools (skopeo, check_image, knowledge_base_search, migrate_ease_scan, mca, apx_recipe_run, sysreport_instructions), refer to the [MCP Server Installation Guide](https://github.com/arm/mcp/blob/main/agent-integrations/agent-install-instructions.md) to install it on codex.

Your goal is to evaluate an open-source codebase for Arm (aarch64) readiness and generate a polished **Arm Enablement Report** in the style of the CubeFS case study, "Arm MCP Server in Action: Enabling multi-arch support for CubeFS." The report must read like a professional external case study for an OSS maintainer, developer-relations team, or CNCF community audience, not like an internal checklist. It must answer: "What is needed to make this project 100% Arm-enabled, and what did the Arm MCP Server discover that ordinary manual review could miss?"

The required local deliverables are:

* `arm-enablement-report.md` at the repo root.
* `arm-enablement-report.pdf` at the repo root, exported from the markdown report.

The report must be reproducible. Every technical claim must be backed by an `arm-mcp` tool call, a file reference, or a command result. Do not present unmeasured performance wins as facts. Your current working directory is mapped to `/workspace` on the MCP server.

Input handling:

* If the user runs `/prompts:arm-enablement` from an already-cloned OSS project, analyze the current workspace.
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
* Do not let the final report collapse into a dry audit table. Tables are evidence, not the story. Write concise narrative around each table explaining why the finding matters, how Arm MCP changed the investigation, and what the maintainer should do next.
* If the project is already mostly or fully Arm-ready, do not invent a dramatic bug. Instead, frame the report as an "Arm readiness validation" case study: explain what MCP proved, what risks it ruled out, and which parity gaps remain. Use a section such as "The Key Discovery: What Arm MCP Proved" rather than ending with only "No critical discoveries."

Professional case-study writing rules:

* Start with a title block, not just a generic heading. Use this pattern:
  * `# Arm MCP Server in Action: Enabling Arm readiness for [Project]`
  * `Project: [name and one-line description]`
  * `Repository: [URL]`
  * `Assessment mode: Report-only` or `Assessment mode: Fixes applied`
  * `Author: Arm MCP Server + AI coding agent`
  * `Date: [current date]`
* The report must have a clear story arc:
  1. Why this project matters.
  2. What the hidden or uncertain Arm-readiness question was.
  3. What Arm MCP checked that manual review would make slow or error-prone.
  4. What was discovered.
  5. What was validated.
  6. What remains to reach true Arm parity.
* Prefer case-study language like "The hidden reality", "The key discovery", "Why this matters", "What did not have to happen", and "Where Arm MCP fits next."
* Keep auditability: every claim still needs a file reference, MCP call, or command result.

Output format:

First produce a single markdown file named `arm-enablement-report.md` at the repo root with the following case-study sections, in order. Every section is required; if a section has no findings, explain what was ruled out rather than dropping the section.

* **Title Block** — Use the title-block pattern above and make the project identity obvious in the first viewport/page.
* **Executive Summary** — One strong paragraph in case-study style: project name, importance, language(s)/size, MCP discovery result, validation result, highest-impact recommendation, and verdict (Ready / Mostly Ready / Significant Work / Broken). Include the "why it matters" in the same paragraph.
* **Background: The Problem** — What the project does, where Arm enablement matters, why a maintainer should care, and any prior Arm-related claims found in CHANGELOGs or READMEs.
* **The Hidden Reality / Current Reality** — For broken projects, explain what was silently broken and why it was hard to notice. For ready projects, explain what was uncertain before the assessment and what parity gaps remained hidden behind "it builds."
* **What is the Arm MCP Server?** — Briefly explain MCP and the Arm tools used. Write this as a reader-friendly paragraph, not a tool list dump.
* **The Assessment: Step by Step** — Use subsections:
  * `Step 1: Automated Codebase Analysis` with `migrate_ease_scan` results and a concise evidence table (`File`, `Line`, `Category`, `Finding`, `Suggested Fix`). If there are zero findings, say what MCP ruled out.
  * `Step 2: Best Practices from Arm's Knowledge Base` with the most useful `knowledge_base_search` guidance and a dependency table.
  * `Step 3: Container Supply Chain Verification` with `check_image`/`skopeo` evidence when applicable; explicitly say when no container surface exists.
  * `Step 4: Build System and Architecture Switching` with plain-English analysis of shell, Makefile, Dockerfile, CI, and release logic. Include short snippets for suspicious logic.
  * `Step 5: Implementation Plan or Implemented Fixes` with a prioritized table. If report-only, describe the exact maintainer PR that should be opened.
  * `Step 6: Validation` with build/test status and `file <binary>` architecture output when available.
* **The Critical Discovery / The Key Discovery** — If a non-obvious bug exists, tell the CubeFS-style story: the bug, why it survived, user impact, and one-line fix. If no critical bug exists, use `The Key Discovery: What Arm MCP Proved` and describe the risks ruled out plus the strongest remaining parity gap.
* **The Cost of Leaving It Unchecked** — Explain likely project/user/ecosystem cost. Keep this evidence-based; do not invent adoption numbers.
* **Effort Comparison** — Three-row table: `Manual Investigation`, `AI agent without Arm MCP`, `AI agent with Arm MCP`; include risk and time-to-discovery.
* **What Did Not Have to Happen** — Two-column table modeled on CubeFS: traditional approach vs Arm MCP-assisted outcome.
* **Audit Trail** — Numbered table of every `arm-mcp` tool invocation: `#`, `Time (UTC)`, `Tool`, `Purpose`. End with total invocation count and total MCP computation time.
* **Impact** — Three subsections: `For the Project and Open-Source Community`, `For the Arm Ecosystem and OSS Growth`, `For Arm Developer Tooling`.
* **What's Next: Roadmap to End-to-End Arm Parity** — Two phases. Phase 1: Discovery and Enablement (where MCP drives). Phase 2: Execution and Distribution (where MCP validates CI, published images/artifacts, and regressions).
* **Conclusion** — Short, maintainer-facing, case-study style conclusion.
* **References** — Repository URL, PR URL if applicable, language scanner used, MCP server version/image, and links to KB articles cited. Include attribution to the [Arm MCP Server](https://github.com/arm/mcp).

After the markdown report is complete, export it to a local PDF named `arm-enablement-report.pdf` at the repo root.

PDF export instructions:

* First try `pandoc arm-enablement-report.md -o arm-enablement-report.pdf` if `pandoc` is installed.
* If `pandoc` is not available and Node.js is installed, try `npx --yes md-to-pdf arm-enablement-report.md --output arm-enablement-report.pdf`.
* If both exporters are unavailable, do not invent a PDF. Leave `arm-enablement-report.md` complete and tell the user exactly which command to run after installing `pandoc` or Node.js. The markdown report remains the source of truth.
* After export, verify that `arm-enablement-report.pdf` exists and is non-empty. If possible, report its file size.

If the user has explicitly asked for changes to be applied, after the report is written: apply the fixes from the Implementation Plan in the workspace, commit each fix as a separate change for review-ability, and re-run `migrate_ease_scan` to confirm findings are resolved. If the user asked only for analysis, do not modify any source files; the report alone is the deliverable.

Provide the final markdown and PDF paths to the user along with a one-line summary of the Arm-readiness verdict.
