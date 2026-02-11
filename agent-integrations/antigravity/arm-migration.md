<!--
  Place this file at .agent/workflows/arm-migration.md
  Invoke using /arm-migration
-->
---
description: Scan a project and migrate to Arm architecture
---

Your goal is to migrate a codebase from x86 to Arm. Use the mcp server tools to help you with this. Check for x86-specific dependencies (such as build flags, intrinsics, and libraries) and change them to Arm architecture equivalents, ensuring compatibility and optimizing performance. Look at Dockerfiles, versionfiles, and other dependencies, ensure compatibility, and optimize performance.

# Steps
1. Look in all Dockerfiles and use the check_image and/or skopeo tools to verify Arm compatibility, changing the base image if necessary.
2. Look at the packages installed by the Dockerfile and send each package to the knowledge_base_search tool to check each package for Arm compatibility. If a package isn't compatible, change it to a compatible version. When invoking the tool, explicitly ask "Is [package] compatible with Arm architecture?" where [package] is the name of the package.
3. Look at the contents of any requirements.txt files line-by-line and send each line to the knowledge_base_search tool to check each package for Arm compatibility. If a package isn't compatible, change it to a compatible version. When invoking the tool, explicitly ask "Is [package] compatible with Arm architecture?" where [package] is the name of the package.
4. Look at the codebase that you have access to, and determine what the language used is.
5. // turbo
6. Run the migrate_ease_scan tool on the codebase, using the appropriate language scanner based on what language the codebase uses, and apply the suggested changes. Your current working directory is mapped to /workspace on the MCP server.
7. OPTIONAL: If you have access to build tools, rebuild the project for Arm, if you're running on an Arm-based runner. Fix any compilation errors.
8. OPTIONAL: If you have access to any benchmarks or integration tests for the codebase, run these and report the timing improvements to the user.

# Pitfalls to avoid

* Don't confuse a software version with a language wrapper package version. For example, when checking the Python Redis client, check the Python package name "redis" rather than the Redis server version. Setting the Python Redis package version to the Redis server version in requirements.txt will fail.
* NEON lane indices must be compile-time constants, not variables.
* If you're unsure about Arm equivalents, use knowledge_base_search to find documentation.
* Be sure to find out from the user or system what the target machine is, and use the appropriate intrinsics. For instance, if neoverse (Graviton, Axion, Cobalt) is targeted, use the latest SME/SME2.

If you have good versions to update for the Dockerfile, requirements.txt, and other files, change them immediately without asking for confirmation.

Provide a summary of the changes you made and how they'll improve the project.
