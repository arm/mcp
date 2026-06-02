# AGENTS.md — Arm Enablement Agent

> **For OSS maintainers:** copy this file to the **root of your project's repository** (not the root of `arm/mcp`). It instructs GitHub Copilot Coding Agent (and other AGENTS.md-aware agents) how to evaluate your codebase for Arm (aarch64) readiness using the [Arm MCP Server](https://github.com/arm/mcp).

---

## When this playbook applies

Run this playbook when a user:

* Assigns an issue to `@copilot` whose title or body mentions Arm, aarch64, arm64, multi-arch, or Graviton/Cobalt/Axion enablement.
* Comments `@copilot run arm enablement` on an issue or pull request.
* Asks for a "Arm enablement report" or "Arm readiness assessment".

If the request is unrelated to Arm enablement, ignore this playbook and follow normal repository instructions.

## Required tools (from the `arm-mcp` MCP server)

This playbook depends on the [Arm MCP Server](https://github.com/arm/mcp) being configured for the repository under **Settings → Copilot → Coding agent → MCP configuration**. Confirm the following tools are reachable before starting:

* `arm-mcp/migrate_ease_scan`
* `arm-mcp/check_image`
* `arm-mcp/skopeo`
* `arm-mcp/knowledge_base_search`
* `arm-mcp/mca`
* `arm-mcp/sysreport_instructions`

If the tools are not available, post a comment linking to the [Arm MCP Server Installation Guide](https://github.com/arm/mcp/blob/main/agent-integrations/agent-install-instructions.md) and stop.

## Goal

Produce a structured **Arm Enablement Report** that the maintainer can publish or attach to a tracking issue. The audience is a project maintainer who wants a clear, evidence-based answer to: "What is needed to make this project 100% Arm-enabled?". Every claim must be backed by an `arm-mcp` tool call. Unmeasured improvements must not be presented as wins. The repository checkout is mapped to `/workspace` on the MCP server.

## Steps to follow

* Detect the project's primary language(s) by inspecting the codebase (`go.mod`, `package.json`, `requirements.txt`, `pom.xml`, `Cargo.toml`, `CMakeLists.txt`, source file extensions). Pick the appropriate `migrate_ease_scan` scanner: `cpp`, `python`, `go`, `js`, or `java`.
* Run `arm-mcp/migrate_ease_scan` against the workspace with the chosen scanner. Capture every architecture-sensitive finding (file path, line number, category, suggestion). This drives the rest of the report.
* For each Dockerfile, Compose file, and Kubernetes manifest in the repo, list every container image referenced. For each image, call `arm-mcp/check_image` to confirm `linux/arm64` is published. For images pinned by `@sha256:` digest, also call `arm-mcp/skopeo` with `raw=true` to confirm whether the digest resolves to a multi-arch manifest list or a single-arch manifest. Flag any image that is amd64-only or pinned to a single-arch digest.
* For each dependency declared in package manifests (Dockerfile `apt-get`/`yum`/`apk` lines, `requirements.txt`, `go.mod`, `package.json`, `pom.xml`), call `arm-mcp/knowledge_base_search` and explicitly ask "Is [package] compatible with Arm architecture?" where [package] is the name of the package. Record the verdict and the recommended version if a change is needed.
* Inspect build entry points (`Makefile`, `build.sh`, `CMakeLists.txt`, `setup.py`, `Dockerfile` build stages) for architecture-switching logic. Manually read shell pipelines and `case`/`switch` blocks that branch on `uname -m`, `$ARCH`, `TARGETARCH`, `GOARCH`, or `CPUTYPE`. Subtle shell semantics bugs (subshell variable scope, missing `arm64` cases, hard-coded `amd64` URLs) are common and are not catchable by `grep`. Call out anything suspicious as a "Critical Discovery" candidate.
* If the codebase contains assembly (`.s`, `.S`) or architecture-specific intrinsics (SSE/AVX, NEON), use `arm-mcp/mca` to analyze representative hot paths and use `arm-mcp/knowledge_base_search` to find the Arm equivalent (NEON, SVE, or SVE2 depending on target).
* Maintain an audit trail: for every `arm-mcp` tool call, record `{timestamp, tool, arguments, reason}`. This drives the "Audit Trail" section of the final report.

## Pitfalls to avoid

* Do not equate `grep -r "amd64"` results with actionable findings. `migrate_ease_scan` filters out false positives in vendored dependencies, test fixtures, and assembly files that already carry arm64 build tags. Trust the scanner over manual grep.
* Do not assume an image is multi-arch because the upstream tag has Arm64 manifests. A `@sha256:` digest pin in a Dockerfile resolves to a single platform manifest and will fail with `exec format error` on Arm hosts. Always inspect digests with `skopeo`.
* Do not confuse a software version with a language wrapper package version. For example, when checking the Python Redis client, check the Python package name "redis" rather than the Redis server version.
* NEON lane indices must be compile-time constants, not variables.
* Do not mark a finding as resolved without running `migrate_ease_scan` again to confirm.
* Do not present unmeasured gains as improvements. Any performance numbers must come from a real build and (optionally) `arm-mcp/apx_recipe_run` measurement.
* Do not skip the audit trail. The report's value to maintainers is reproducibility.
* Be sure to find out from the user or system what the target machine is, and use the appropriate intrinsics. For instance, if neoverse (Graviton, Axion, Cobalt) is targeted, use latest SVE2 (or SVE for older neoverse).

## Output: open a pull request

Open a single pull request titled `arm-enablement-report: <project name>` containing:

1. A new file `arm-enablement-report.md` at the repository root with the report sections listed below.
2. (Optional, only if the issue requested fixes) The minimum set of code changes needed to make the project Arm-buildable. Each fix should be a separate commit so reviewers can land them independently.

The PR description should include the report's Executive Summary verbatim and link to the issue.

## Report sections (all required, in this order)

Every section is required; if a section has no findings, write "No findings" rather than omitting the section.

* **Executive Summary** — One paragraph: project name, language(s) and lines of code, total findings count, container audit summary, the single highest-impact recommendation, and overall Arm-readiness verdict (Ready / Mostly Ready / Significant Work / Broken).
* **Project Overview** — Repository, primary language(s), build system, container strategy, and any prior Arm-related claims found in CHANGELOGs or READMEs (especially flag claims that contradict the scan results).
* **Step 1: Automated Codebase Analysis** — `migrate_ease_scan` summary table: column headers `File`, `Line`, `Category`, `Finding`, `Suggested Fix`. Group by category. State the scanner used and the elapsed time.
* **Step 2: Dependency and Knowledge Base Verification** — Table of every package checked via `knowledge_base_search`: column headers `Package`, `Source File`, `Arm Compatible`, `Notes / Recommended Version`. Cite the KB documents used.
* **Step 3: Container Supply Chain Verification** — Table per image: `Image`, `Pinned By` (tag/digest), `arm64 Support`, `Action Needed`. Include `check_image` and `skopeo` verdicts. Call out single-arch digest pins explicitly.
* **Step 4: Build System and Architecture Switching** — Plain-English audit of `build.sh`, `Makefile`, `Dockerfile`, and any other architecture-switching files. Include verbatim quoted code snippets for any logic flagged as suspicious.
* **Critical Discoveries** — Non-obvious findings that manual review or `grep` would miss (silent shell bugs, missing `arm64` cases, single-arch digest pins, hardcoded amd64 download URLs). For each: the bug, why it survived undetected, and the one-line fix. Write "No critical discoveries" if none.
* **Step 5: Implementation Plan** — Table of files to change: `#`, `File`, `What to fix`, `Why`. Order by impact. Include both required fixes (broken on Arm) and recommended fixes (works but suboptimal).
* **Step 6: Validation** — If a build was attempted, report build status and ELF target architecture for produced binaries. If no build was attempted, state "Validation deferred — recommend running on an AWS Graviton, Azure Cobalt, or GCP Axion instance after applying the Implementation Plan."
* **Effort Comparison** — Three-row table: `Approach` (Manual investigation / AI agent without Arm MCP / AI agent with Arm MCP), `Risk Level`, `Time to discovery`. Use the actual elapsed time for the Arm MCP row from the audit trail.
* **Audit Trail** — Numbered table of every `arm-mcp` tool invocation: `#`, `Time (UTC)`, `Tool`, `Purpose`. End with total invocation count and total MCP computation time.
* **Roadmap to Arm Parity** — Two phases. Phase 1: Discovery and Enablement (what this report covers, the work the maintainer must merge). Phase 2: Execution and Distribution (multi-arch CI runners, multi-arch image publishing, release workflow updates).
* **References** — Repository URL, language scanner used, MCP server version, and links to any KB articles cited. Include attribution to the [Arm MCP Server](https://github.com/arm/mcp).

## Default mode is read-only analysis

Unless the issue explicitly requests fixes, do not modify source files. Produce only the report. The maintainer reviews the report and opens a follow-up issue requesting fixes if desired.
