---
# Place this file at: .kiro/steering/migrate-x86-to-arm.md
inclusion: always
---

# Kiro Steering: Migrate x86 to Arm

Goal: Migrate a codebase from x86 to Arm using MCP tools. Replace x86-specific dependencies (build flags, intrinsics, libraries) with Arm equivalents, ensuring compatibility and performance.

Steps:
1. Inspect all Dockerfiles and use check_image and/or skopeo to verify Arm compatibility. Update base images if needed.
2. For each Dockerfile package, call knowledge_base_search and ask: "Is [package] compatible with Arm architecture?" Update incompatible packages.
3. For each line in requirements.txt, call knowledge_base_search with the same Arm compatibility question. Update incompatible packages.
4. Identify the language(s) used in the codebase.
5. Run migrate_ease_scan with the correct language scanner and apply suggested changes.
6. OPTIONAL: If build tools are available and you are on an Arm runner, rebuild and fix compilation errors.
7. OPTIONAL: If benchmarks or integration tests exist, run them and report timing improvements.

Pitfalls:
- Do not confuse software versions with language wrapper package names (e.g., Python package "redis").
- NEON lane indices must be compile-time constants.
- If unsure about Arm equivalents, use knowledge_base_search to find documentation.
- Confirm the target machine and use the appropriate intrinsics (SME/SME2 for Neoverse targets).
- If you have good versions for Dockerfiles, requirements.txt, or other files, update them immediately without asking.

Provide a summary of the changes and how they improve the project.
