<!-- Place this file at: AGENTS.md (repository root or nearest directory). -->
# AGENTS.md - Codex

## Goal
Migrate the codebase from x86 to Arm using MCP server tools. Identify x86-specific dependencies (build flags, intrinsics, libraries) and replace them with Arm architecture equivalents, ensuring compatibility and performance.

## Steps
1. Review all Dockerfiles and use MCP tools (check_image and/or skopeo) to verify Arm compatibility. Update base images if required.
2. For every package installed by Dockerfiles, call knowledge_base_search and explicitly ask: "Is [package] compatible with Arm architecture?" If not compatible, switch to a compatible version.
3. For each line in every requirements.txt, call knowledge_base_search and ask the same Arm compatibility question. Update incompatible packages.
4. Identify the primary language(s) used in the codebase.
5. Run migrate_ease_scan with the correct language scanner and apply suggested changes.
6. OPTIONAL: If build tools are available and you are on an Arm runner, rebuild and fix compilation errors.
7. OPTIONAL: If benchmarks or integration tests exist, run them and report timing improvements.

## Pitfalls
- Do not confuse software version numbers with language wrapper package names (e.g., use Python package "redis").
- NEON lane indices must be compile-time constants.
- If unsure about Arm equivalents, use knowledge_base_search to find documentation.
- Confirm the target machine (e.g., Neoverse/Graviton/Axion/Cobalt) and use appropriate intrinsics (SME/SME2 if applicable).
- If you have good versions for Dockerfiles, requirements.txt, or other files, update them immediately without asking.

## Output
Provide a summary of the changes made and how they improve the project.
