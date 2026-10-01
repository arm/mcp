---
name: arm-migration-scan
description: Scan a local or cloned codebase for Arm portability issues with migrate-ease from the command line. Supports C/C++, Python, Go, JavaScript, and Java migration assessments and validation of fixes.
---

# Scan a codebase for Arm migration

Run commands through the agent's shell. This replaces the former
`migrate_ease_scan` MCP tool. Identify relevant languages and scan each supported
component: `cpp`, `python`, `go`, `js`, or `java`. Report unsupported languages as
unassessed instead of choosing an unrelated scanner.

The Arm MCP image includes `migrate-ease-{language}` executables. Set
`ARM_MCP_IMAGE` to the project's configured image version/digest or local build;
the example defaults to `armlimited/arm-mcp:latest`. Inspect the selected scanner's
`--help` for version-specific flags. The equivalent native command is
`migrate-ease-cpp --march armv8-a --output /absolute/results/report.json /absolute/source`.
For a source installation, follow the upstream
[migrate-ease setup](https://github.com/migrate-ease/migrate-ease) and run the
corresponding Python module from its installation directory.

From the target checkout, use a separate output directory so reports persist
after the CLI container exits:

```sh
source_dir="$PWD"
report_dir="$(mktemp -d)"
docker run --rm --network none \
  --mount "type=bind,src=$source_dir,dst=/workspace,readonly" \
  --mount "type=bind,src=$report_dir,dst=/results" \
  --entrypoint migrate-ease-cpp "${ARM_MCP_IMAGE:-armlimited/arm-mcp:latest}" \
  --march armv8-a --output /results/cpp.json /workspace
```

Change both the executable and report name for each language. On Linux, pass
`--user "$(id -u):$(id -g)"` before the image if host-owned output is needed.
Use `armv8-a` for a baseline assessment unless a different deployment target was
requested. Match optional features such as SVE2 to the actual target CPU.
The output filename extension selects the report format (`json`, `txt`, `csv`,
or `html`); confirm support in the selected scanner's help.

Scan relevant source directories, excluding dependency caches, virtual
environments, generated output, and vendored code when outside the assessment
scope. Direct CLI invocation does not make the filtered workspace copy that the
old MCP wrapper made. If staging a copy is necessary, preserve uncommitted edits
and record exclusions. Do not use a clean remote clone to validate local fixes.
For a remote URL, clone it into a new local directory first, record the commit,
then scan that directory. Cloning requires network access; local scanning does not.

Scans can take minutes. Use a shell timeout suited to project size and retain
exit status, stderr, and the report; an empty or missing report after a failed
command is not a clean scan. Report file paths, line numbers, issue categories,
and relevant recommendations. Scanner findings require review and a native Arm
build/test where available; they do not prove runtime compatibility. Apply fixes
only within the user's requested scope and rerun the same scan on the edited
checkout. Use `knowledge_base_search` for Arm-specific dependency guidance.
