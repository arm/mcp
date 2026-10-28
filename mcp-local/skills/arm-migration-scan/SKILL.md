---
name: arm-migration-scan
description: Run migrate-ease compatibility scans via Docker CLI to assess Arm portability (C/C++, Python, Go, Rust, Java, Dockerfile). Triggers on requests to scan local checkouts or remote repos for aarch64 migration.
---

# Arm Migration Assessment Workflow

## Trigger Conditions
* **Supported Scanners:** Activate for `cpp`, `python`, `go`, `rust`, `java`, or `docker` components. Return unsupported targets as unassessed.
* **Boundaries:** Do not use for general static analysis, application compilation, or native cloud build execution.

## Execution Workflow
1. **Target Setup:** Map target `--march` from user input (defaults to `armv8-a`). Alternatively, derive via `--vendor` and `--instance-type`.
2. **Isolate Environment:** Run scans outside the current workspace tree (e.g., inside `/tmp`) to protect Git change tracking from context bloat and trailing artifacts.
3. **Container CLI Invocation:** Mount the target code to `/workspace` as read-only and pass `--user "$(id -u):$(id -g)"` to ensure correct file ownership:
   ```sh
   docker run --rm --network none \
     --user "(id -u):(id -g)" \
     --mount "type=bind,src=\$source_dir,dst=/workspace,readonly" \
     --mount "type=bind,src=\$report_dir,dst=/results" \
     --entrypoint migrate-ease-{language} "\${ARM_MCP_IMAGE:-armlimited/arm-mcp:latest}" \
     --march armv8-a --output /results/{language}.json /workspace
   ```
4. **Scale Control (Repositories > 1 GB):** Split scopes by independent sub-directories. Execute parallel containers and surface completed partial chunks dynamically.
5. **Report Consolidation:** For multi-directory or multi-language split scans, consolidate individual JSON results using `jq` into a unified report array before rendering:
   ```sh
   jq -s '.' \$report_dir/*.json > \$report_dir/consolidated_report.json
   ```
6. **Interactive HTML View:** After presenting the scan summary, explicitly ask the user whether they want the report opened in a web browser, then end the turn and wait for their response. Only after the user explicitly confirms may the agent start a report server and open the consolidated profile.
   * If `web/server.py` exists, use the native Web UI app component.
   * If `web/server.py` is absent, convert `consolidated_report.json` into `consolidated_report.html`. The HTML must present the scan summary, coverage, findings, scanner errors, and source-file details; it may load the JSON as a companion file from the same directory. Preserve the original JSON as the source of truth.
   * Serve the report directory with a loopback-only localhost server and open the HTML URL with the platform's browser opener. Choose an unused port if the example port is occupied. Confirm that the server returns the HTML successfully; if the browser does not appear, give the user the localhost URL.
   ```sh
   if [ -f web/server.py ]; then
     python3 web/server.py --port 8080 &
     echo "Interactive view serving at: http://localhost:8080"
   else
     # First generate \$report_dir/consolidated_report.html from the JSON.
     python3 -m http.server 8765 --bind 127.0.0.1 --directory "\$report_dir" &
     open "http://127.0.0.1:8765/consolidated_report.html"
   fi
   ```

## Operational Rules
* **Mandatory Post-Scan Prompt:** Every scan that produces a consolidated report must end with an explicit question such as, "Would you like me to open the report in your browser?"
* **Strict Confirmation Gate:** A request to run a scan is not permission to open its report. Do not convert the JSON to HTML, start `web/server.py` or another localhost server, launch a browser, or otherwise present the interactive view until the user gives an explicit affirmative response to the post-scan prompt.
* **Localhost HTML Fallback:** When `web/server.py` is unavailable and the user has confirmed, generate the HTML fallback, bind its server to `127.0.0.1` rather than all interfaces, and open `consolidated_report.html` through the localhost URL instead of relying on a local-file association.
* **Strict Fail-Fast:** If a container command fails, a report is missing, or formatting breaks, mark the segment as failed/incomplete. Never synthesize arbitrary metrics or metrics counts.
* **Exclusion Targets:** Automatically exclude standard dependency targets (`.venv`, `node_modules`), caches (`__pycache__`), and version control metadata (`.git`) via scanner arguments or directory skipping.
* **Arm-Specific Guidance:** Use `knowledge_base_search` for Arm-specific dependency guidance.
