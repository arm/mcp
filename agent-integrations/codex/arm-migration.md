<!-- Place this prompt file at ~/.codex/prompts/arm-migration.md to enable it.
     Invoke using /prompts:arm-migration in the codex chat.
-->
---
description: Scan a project and migrate to Arm architecture
---

Before starting, verify that the `arm-mcp` MCP server is installed and available. If you don't have access to the arm-mcp knowledge_base_search tool and CLI skill resources/prompts, refer to the [MCP Server Installation Guide](https://github.com/arm/mcp/blob/main/agent-integrations/agent-install-instructions.md) to install it on codex.

Your goal is to migrate a codebase from x86 to Arm. Use knowledge_base_search for documentation, and load the arm-container-inspect, arm-migration-scan, and arm-assembly-analyze skills from MCP resources or same-named prompts. If the client cannot load either, install the bundled skills as described in the installation guide. Execute their commands through your shell. Check for x86-specific dependencies (such as build flags, intrinsics, and libraries) and change them to Arm architecture equivalents, ensuring compatibility and optimizing performance. Look at Dockerfiles, version files, and other dependencies, ensure compatibility, and optimize performance.

Steps to follow:
* Look in all Dockerfiles and follow arm-container-inspect to run Skopeo or Docker Buildx from the shell to verify Arm compatibility, changing the base image if necessary.
* Look at the packages installed by the Dockerfile and send each package to the knowledge_base_search tool to check each package for Arm compatibility. If a package isn't compatible, change it to a compatible version. When invoking the tool, explicitly ask "Is [package] compatible with Arm architecture?" where [package] is the name of the package.
* Look at the contents of any requirements.txt files line-by-line and send each line to the knowledge_base_search tool to check each package for Arm compatibility. If a package isn't compatible, change it to a compatible version. When invoking the tool, explicitly ask "Is [package] compatible with Arm architecture?" where [package] is the name of the package.
* Look at the codebase that you have access to, and determine what the language used is.
* Follow arm-migration-scan to run the appropriate migrate-ease language CLI against the actual local checkout and review its findings before applying changes. Mount that checkout read-only for a Docker CLI scan and retain reports in a separate output directory.
* OPTIONAL: If you have access to build tools, rebuild the project for Arm, if you're running on an Arm-based runner. Fix any compilation errors.
* OPTIONAL: If you have access to any benchmarks or integration tests for the codebase, run these and report the timing improvements to the user.

Pitfalls to avoid:

* Don't confuse a software version with a language wrapper package version. For example, when checking the Python Redis client, check the Python package name "redis" rather than the Redis server version. Setting the Python Redis package version to the Redis server version in requirements.txt will fail.
* NEON lane indices must be compile-time constants, not variables.
* If you're unsure about Arm equivalents, use knowledge_base_search to find documentation.
* Be sure to find out from the user or system what the target machine is, and use the appropriate intrinsics. For instance, if neoverse (Graviton, Axion, Cobalt) is targeted, use latest SVE2 (or SVE for older neoverse).

If you have good versions to update for the Dockerfile, requirements.txt, and other files, change them immediately without asking for confirmation.

Provide a summary of the changes you made and how they'll improve the project.
