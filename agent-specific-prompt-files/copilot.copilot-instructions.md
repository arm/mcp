<!-- Place this file at: .github/copilot-instructions.md -->
# copilot-instructions

Your goal is to migrate a codebase from x86 to Arm. Use MCP server tools to help you with this. Check for x86-specific dependencies (build flags, intrinsics, libraries, etc) and change them to Arm architecture equivalents, ensuring compatibility and optimizing performance. Look at Dockerfiles, version files, and other dependencies, ensure compatibility, and optimize performance.

Steps to follow:
1. Look in all Dockerfiles and use the check_image and/or skopeo tools to verify Arm compatibility, changing the base image if necessary.
2. Look at the packages installed by the Dockerfile and send each package to the knowledge_base_search tool to check each package for Arm compatibility. If a package is not compatible, change it to a compatible version. When invoking the tool, explicitly ask "Is [package] compatible with Arm architecture?" where [package] is the name of the package.
3. Look at the contents of any requirements.txt files line-by-line and send each line to the knowledge_base_search tool to check each package for Arm compatibility. If a package is not compatible, change it to a compatible version.
4. Look at the codebase that you have access to, and determine what language is used.
5. Run the migrate_ease_scan tool on the codebase, using the appropriate language scanner based on what language the codebase uses, and apply the suggested changes.
6. OPTIONAL: If you have access to build tools, rebuild the project for Arm, if you are running on an Arm-based runner. Fix any compilation errors.
7. OPTIONAL: If you have access to any benchmarks or integration tests for the codebase, run these and report the timing improvements to the user.

Pitfalls to avoid:
- Do not confuse a software version with a language wrapper package version. For example, when checking the Python Redis client, check the Python package name "redis" rather than the Redis server version.
- NEON lane indices must be compile-time constants, not variables.
- If you are unsure about Arm equivalents, use knowledge_base_search to find documentation.
- Find out from the user or system what the target machine is, and use the appropriate intrinsics. For instance, if neoverse (Graviton, Axion, Cobalt) is targeted, use the latest SME/SME2.
- If you have good versions to update for the Dockerfile, requirements.txt, and other files, change them immediately without asking for confirmation.

Provide a summary of the changes you made and how they improve the project.
