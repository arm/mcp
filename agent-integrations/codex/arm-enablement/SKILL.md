---
name: arm-enablement
description: Assess an open-source codebase for Arm/aarch64 readiness with the Arm MCP Server and produce a professional, evidence-backed Markdown and PDF case-study report. Use when a user asks to scan, assess, validate, enable, or fix Arm support; check multi-architecture containers or dependencies; create an Arm enablement report; or evaluate an OSS project on an Arm runner.
---

# Arm Enablement

Evaluate an OSS repository for end-to-end Arm readiness and create:

- `arm-enablement-report.md` at the target repository root.
- `arm-enablement-report.pdf` exported from that Markdown source.

Write for OSS maintainers, developer-relations teams, and CNCF-style community audiences. Tell a concise case-study story while keeping every technical claim auditable.

## Establish Scope

1. Treat the current repository as the target unless the user supplies a GitHub URL.
2. If a URL is supplied, clone it into an empty workspace or an `arm-enablement-target/` subdirectory.
3. Prefer scanning the local target mounted at MCP `/workspace`. Use the scanner's `git_repo` input only for an initial report-only scan when the current workspace is unrelated to the target and there are no local or uncommitted changes to assess. Never use `git_repo` to validate fixes; mount the changed checkout at `/workspace` and omit `git_repo`.
4. Default to report-only mode. Create only the two report files unless the user explicitly asks to apply fixes.
5. If fixes are requested, make the smallest necessary source changes, update the report, and rerun affected checks. Do not commit unless the user asks.
6. Record the repository URL, current commit, assessment mode, host architecture, and date.

## Verify Arm MCP

Before assessing the project:

1. Confirm that the configured `arm-mcp` server exposes `migrate_ease_scan`, `knowledge_base_search`, `check_image`, `skopeo`, `mca`, `apx_recipe_run`, and `sysreport_instructions` as applicable.
2. Treat these as MCP tools, not command-line programs. Do not search for similarly named executables on `PATH`.
3. Confirm that the target checkout visible to Codex is the same checkout mounted at `/workspace` in the Arm MCP container. Compare a distinctive file or the repository root listing.
4. If the server or workspace mapping is unavailable, stop and report the exact configuration problem. Point to the [Arm MCP installation guide](https://github.com/arm/mcp/blob/main/agent-integrations/agent-install-instructions.md); do not fabricate scan results.

Maintain an audit record for every Arm MCP call: UTC timestamp, tool, relevant arguments, purpose, result summary, and duration when available. If duration is unavailable, state that it was not captured.

## Assess Arm Readiness

1. Inspect manifests and source extensions to identify all primary languages. Supported `migrate_ease_scan` scanners are `cpp`, `python`, `go`, `js`, and `java`; scan each architecture-relevant supported component in a mixed-language repository.
2. If no scanner supports a primary language, do not substitute an unrelated scanner or imply that the scan passed. Record the unsupported-language limitation, inspect architecture-sensitive source/build/container/CI paths manually, and rely on cross-build or native Arm evidence. Scan any supported components separately and label unvalidated areas as deferred.
3. Run `migrate_ease_scan` against the target with `arch=armv8-a` by default. Use `armv8.6-a+sve2` only when that newer target is relevant to the user's request. Capture each file, line, category, finding, and proposed fix. Treat the scanner as the primary compatibility signal for supported languages and use manual searches only to add context.
4. Inspect build and release entry points, including Makefiles, shell scripts, CMake, Dockerfiles, package scripts, and CI workflows. Read branches using `uname -m`, `ARCH`, `TARGETARCH`, `GOARCH`, `CPUTYPE`, hard-coded `amd64` downloads, or architecture-specific flags. Check shell scope and switch fallthrough semantics manually.
5. Inventory images from Dockerfiles, Compose files, Kubernetes manifests, and CI. Call `check_image` for each relevant image tag. For digest pins, call `skopeo` with raw manifest output and determine whether the digest is a manifest list or a single-platform image.
6. Review direct runtime/build dependencies and architecture-sensitive packages. Group related dependencies and use `knowledge_base_search` only where Arm-specific compatibility or version guidance would affect the verdict or remediation plan; do not query every transitive dependency. If no relevant KB result is returned, record `No Arm-specific KB result`, do not infer incompatibility, and use upstream documentation, published artifacts, or native validation as evidence. Mark the item unverified when no stronger evidence is available.
7. If assembly or SIMD intrinsics exist, identify architecture guards. Use `mca` for representative supported assembly and `knowledge_base_search` for appropriate NEON, SVE, or SVE2 guidance. Never invent performance gains.
8. Build and test using the project's documented commands. Cross-compile when supported, then inspect produced binaries with `file` or the platform equivalent.
9. When an authorized native Arm host is available, run a native build and relevant tests there. Record the host CPU/OS and exact commands. Use `sysreport_instructions` or `apx_recipe_run` only when system/performance evidence is relevant and access is configured.
10. If fixes were requested, apply them, rerun tests, and rerun `migrate_ease_scan` against the changed `/workspace` checkout. Do not label a finding resolved without evidence from the repeated check.

Avoid these errors:

- Do not treat raw `grep` matches as confirmed incompatibilities.
- Do not assume a tag or digest is multi-architecture without inspecting its manifest.
- Do not treat a missing knowledge-base result as proof that a dependency is incompatible.
- Do not confuse server versions with language package versions.
- Do not recommend variable NEON lane indices; lane indices must be compile-time constants.
- Do not claim measured improvements without real measurements.
- Do not invent a dramatic defect when the project is already Arm-ready; explain what was proven and what parity work remains.

## Write The Report

Start with YAML metadata suitable for PDF export, followed by this visible title block:

```markdown
# Arm MCP Server in Action: Enabling Arm readiness for [Project]

**Project:** [name and one-line description]
**Repository:** [URL]
**Assessment mode:** Report-only | Fixes applied
**Author:** Arm MCP Server + AI coding agent
**Date:** [current date]
```

Render the report title exactly once in the final PDF. If the exporter automatically renders the YAML `title`, suppress either that generated title block or the repeated body H1 in the PDF input.

Use these sections in order. Keep every section; when no issue exists, explain what was ruled out.

1. Executive Summary: project significance, languages/scope, MCP result, validation result, highest-impact recommendation, and verdict (`Ready`, `Mostly Ready`, `Significant Work`, or `Broken`).
2. Background: The Problem.
3. The Hidden Reality or Current Reality.
4. What is the Arm MCP Server?: a reader-friendly paragraph naming only tools actually used.
5. The Assessment: Step by Step:
   - Automated Codebase Analysis, with an evidence table.
   - Best Practices from Arm's Knowledge Base, with a dependency table.
   - Container Supply Chain Verification, or an explicit no-container finding.
   - Build System and Architecture Switching.
   - Implementation Plan or Implemented Fixes, prioritized and specific.
   - Validation, including build/test status and binary architecture evidence.
6. The Critical Discovery; if none exists, use `The Key Discovery: What Arm MCP Proved`.
7. The Cost of Leaving It Unchecked.
8. Effort Comparison: compare manual investigation, an AI agent without Arm MCP, and an AI agent with Arm MCP. Label time values as estimates unless measured.
9. What Did Not Have to Happen: traditional approach versus MCP-assisted outcome.
10. Audit Trail: one row per MCP invocation and totals without invented timing.
11. Impact: project/community, Arm ecosystem/OSS growth, and Arm developer tooling.
12. What's Next: Roadmap to End-to-End Arm Parity, split into discovery/enablement and execution/distribution phases.
13. Conclusion.
14. References: repository, commit/PR when applicable, scanner, MCP image/version, cited knowledge resources, and the [Arm MCP Server](https://github.com/arm/mcp).

Use case-study language such as "the hidden reality," "the key discovery," "why this matters," and "what did not have to happen," but prefer evidence over drama. Cite file paths and line numbers. Separate confirmed findings from recommendations and deferred validation. Keep dense evidence tables to three columns or fewer so they remain readable in the PDF.

## Export And Verify The PDF

1. Use the Markdown report as the source of truth.
2. Prefer `pandoc` with a table of contents and a PDF engine available locally. Use restrained typography, readable margins, page numbers, syntax highlighting, and link colors. The prescribed section headings already contain numbers, so do not also pass `--number-sections`; use exactly one numbering method. If a TeX engine is unavailable, use plain `pandoc`; if `pandoc` is unavailable, use `npx --yes md-to-pdf` when Node.js is available.
3. If no exporter is available, leave the complete Markdown report and provide an exact installation/export command. Do not create a fake PDF.
4. Verify that the PDF exists, is non-empty, and has the expected page count. When rendering tools are available, render and inspect at least the title page and one evidence-heavy page for clipping, broken tables, blank pages, repeated numbering, duplicate titles, or unreadable text. Regenerate if needed.
5. Remove temporary render images and exporter intermediates before finishing; the target repository should contain only the two report artifacts unless fixes were requested.
6. Finish by reporting both absolute artifact paths, file sizes, the Arm-readiness verdict, fixes made (if any), validation performed, and anything deferred.
