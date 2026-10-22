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

## Report format

Use `json` as the default report format unless the user requests another
supported format. If the user requests `txt`, `csv`, or `html`, set the output
filename extension and scanner format option accordingly, and report that format
instead of forcing `json`. Confirm format support in the selected scanner's
`--help` when uncertain.

Use `json` when consolidation, partial issue summaries, or later HTML rendering
from the scan result is required. Non-`json` formats should still include
provenance, metrics, commands, exit status, stdout/stderr, and report paths in
the final response, but do not invent structured issue counts that are not
available from the generated report.

## Excluded paths and patterns

Scan relevant source directories, excluding dependency caches, virtual environments, generated output, and vendored code, including those described below, when outside the assessment.

- `venv`
- `.venv`
- `env`
- `ENV`
- `virtualenv`
- `node_modules`
- `__pycache__`
- `.pytest_cache`
- `.mypy_cache`
- `.tox`
- `build`
- `dist`
- `*.egg-info`
- `.git`
- `.svn`
- `.hg`
- `.vscode`
- `.idea`
- `.eclipse`
- `mcp-traffic.jsonl`
- `error_logging.yaml`
- `target`
- `.cache`

Direct CLI invocation does not make the filtered workspace copy that the
old MCP wrapper made. If staging a copy is necessary, preserve uncommitted edits
and record exclusions. Do not use a clean remote clone to validate local fixes.
For a remote URL, clone it into a new local directory first, record the commit,
then scan that directory. Cloning requires network access; local scanning does not.

## Keep scan artifacts out of Git/GitHub tracking

Run remote-repository scans, temporary clones, generated reports, rendered HTML,
stdout/stderr logs, and consolidation files outside the current project
worktree, such as under `/tmp`, unless the user explicitly asks to save them in
the repository. Do not add generated migration-scan artifacts to Git, GitHub
change tracking, commits, pull requests, or review diffs. Avoid broad `git
status`, `git diff`, or GitHub change-inspection commands over generated scan
artifacts; they can consume unnecessary context and tokens. If scanning a local
checkout is required, write outputs to an ignored or external report directory
and clearly report that path.

## Warning levels

The C/C++ scanner defaults to `--warning-level L1`. Use `L1` when the user wants
the default, higher-certainty report. Use `--warning-level L2` for broader
migration triage or when the user wants to compare against a report that includes
less-certain warnings. Record the warning level used in the scan result.

## Parallel directory scans

For large repositories (size greater than 1 GB ), split the assessment by directory and run one migrate-ease command
per directory. Use the same scanner, architecture, target OS, warning level, and
issue-type options for every split unless the user requests otherwise. Write each
scan to a unique report file using `json` by default, or `txt`, `csv`, or `html`
when requested by the user. Wait for every command to finish, and treat any
failed command, missing report, or invalid report for the requested format as a
failed overall scan.

Example:

```sh
source_dir="$PWD"
report_dir="$(mktemp -d)"
for scan_dir in src include tools; do
  safe_name="$(printf '%s' "$scan_dir" | tr '/ ' '__')"
  docker run --rm --network none \
    --mount "type=bind,src=$source_dir,dst=/workspace,readonly" \
    --mount "type=bind,src=$report_dir,dst=/results" \
    --entrypoint migrate-ease-cpp "${ARM_MCP_IMAGE:-armlimited/arm-mcp:latest}" \
    --march armv8-a --output "/results/${safe_name}.json" \
    "/workspace/${scan_dir}" \
    >"${report_dir}/${safe_name}.stdout" \
    2>"${report_dir}/${safe_name}.stderr" &
done
wait
```

For `json` output, consolidate the per-directory reports into one `json` result by summing
`total_issue_count`, merging `issue_summary` counts by issue type, concatenating
`issues`, and recording the source reports. Do not discard per-directory stdout,
stderr, commands, warning levels, or report paths; include them in the final
response when they help reproduce or troubleshoot the scan.

## Partial results during parallel scans

When multiple scans run in parallel, report completed scan results as soon as
they are available instead of waiting silently for the slowest scan. For each
completed scan, validate that its report exists and matches the requested format.
For `json` reports, show a partial `json` result with:

- repository and commit/ref;
- completed directory or component;
- scanner, scanner version when available, target architecture, and warning
  level;
- scan start and finish timestamps for that completed command;
- elapsed seconds for that completed command;
- exit status and report path;
- total issue count, nonzero issue summary, and any important stdout/stderr
  notes;
- remaining scans still in progress.

Label these updates as partial results and do not present them as the final
assessment. If a completed scan failed, report the failure as a partial failed
result with its exit status and stderr instead of inventing issue counts. Keep
waiting for other in-scope scans unless the user asks to stop.

For `txt`, `csv`, or scanner-native `html` reports, show the completed report
path, metrics, exit status, stdout/stderr notes, and any safe summary that can be
derived directly from the report. Do not claim consolidated issue counts unless
they can be computed from generated data.

After every in-scope scan has finished, print the consolidated `json` result
using the same aggregation rules as above when the requested output is `json`.
For non-`json` output, print the set of generated reports and provenance instead
of a fabricated consolidated `json` issue summary. Ask about optional HTML
rendering only after the final result has been shown, unless the user explicitly
asks to render a partial result.

## Optional HTML rendering

For default `json` scans, the `json` scan result is the primary result. Always
print or summarize the `json` result first. After the `json` result has been
shown to the user, ask whether they want the result rendered as an HTML web
page. Do not create, open, or serve the HTML view until the user confirms.

If the user requested scanner-native `html` output, provide the generated HTML
report path after the scan completes and ask before opening it in a browser.

When the user confirms, render the existing `json` result into a standalone local
HTML file in the report directory. Do not rerun the scan just to make HTML unless
the user specifically requests the scanner's native HTML output. The rendered
page should work without network access or external assets, escape report
content before embedding it in HTML, and include:

- the scanned repository, commit, directories, architecture, scanner, and
  warning level;
- scan metrics, including elapsed time and token-usage availability;
- total issue count and issue summary by type;
- an issue table with file path, line number, issue type, description, snippet,
  and recommendation when present;
- source report paths and command/stdout/stderr locations needed to reproduce or
  troubleshoot the scan.

After the HTML file has been created, provide the local HTML path and ask the
user whether they want it opened in a browser. Do not open the browser until the
user confirms. If the user confirms, open the local HTML file in the default
browser. Request any environment-required approval before using GUI commands
such as `open`, `xdg-open`, or `start`. If a browser cannot be opened, provide
the local HTML file path so the user can open it manually.

## Guardrails against fabricated results

Base the scan result only on executed commands, generated report files, and
explicit user-provided context. Do not invent issue counts, file paths, line
numbers, snippets, recommendations, scanner versions, commits, timings, or token
usage. If a command did not run, a report file is missing, or the report is
invalid for the requested format, report the scan as failed or incomplete
instead of filling gaps from memory or from a previous run.

When consolidating `json` reports, derive counts from the `json` fields in the
report files and preserve the source report paths. For non-`json` reports, derive
only what can be read directly from the generated files and clearly state any
structured fields that are unavailable. If a directory, language, scanner, or
warning level was not assessed, mark it as unassessed rather than implying a
clean result. Keep scanner findings separate from interpretation:
recommendations may be repeated from the report, but any extra analysis must be
clearly labeled as interpretation and tied to the specific finding.

Record enough provenance for the user to reproduce the result, including the
repository URL or local path, commit or ref when available, scanned directories,
scanner executable and version when available, target architecture, warning
level, command line, image or tool installation used, report paths, exit status,
and relevant stdout/stderr. Scanner output is advisory; do not claim that a
project is fully Arm-compatible without a successful native Arm build and test.

## Required metrics

Capture metrics for every scan and include them in the final result. Start
timing immediately before the first migrate-ease command starts. Stop timing
after scanning completes. Do not include the time for final report parsing or
building the consolidated result or rendering the `html` output. For parallel scans, also capture
per-directory timing when practical.

For `json` output, use this shape:

```json
{
  "metrics": {
    "scan_started_at": "ISO-8601 timestamp",
    "scan_finished_at": "ISO-8601 timestamp",
    "elapsed_seconds": 0.0,
    "per_directory_elapsed_seconds": {
      "src": 0.0
    },
    "token_usage": {
      "available": false,
      "input_tokens": null,
      "output_tokens": null,
      "total_tokens": null,
      "source": "client-provided if available; otherwise unavailable"
    }
  }
}
```

Populate token usage from the client or agent runtime if it is exposed. If token
usage is not available, set `available` to `false` and leave token counts as
`null`; do not estimate token usage.

Scans can take minutes. Use a shell timeout suited to project size and retain
exit status, stderr, and the report; an empty or missing report after a failed
command is not a clean scan. Report file paths, line numbers, issue categories,
and relevant recommendations. Scanner findings require review and a native Arm
build/test where available; they do not prove runtime compatibility. Apply fixes
only within the user's requested scope and rerun the same scan on the edited
checkout. Use `knowledge_base_search` for Arm-specific dependency guidance.
