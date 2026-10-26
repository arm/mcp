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
   jq -s 'reduce .[] as \$item ({}; . * \$item)' \$report_dir/*.json > \$report_dir/consolidated_report.json
   ```
6. **Interactive HTML View:** If the user confirms they want to open the report visually in a web browser, start the native Web UI app component to host the consolidated JSON profile:
   ```sh
   python3 web/server.py --port 8080 &
   echo "Interactive view serving at: http://localhost:8080"
   ```

## Operational Rules
* **Strict Confirmation Gate:** Never open a web browser, start the local `web/server.py` utility, or convert files to HTML automatically. The agent must present the text-based summary of `consolidated_report.json` first, explicitly ask for permission, and wait for confirmation.
* **Strict Fail-Fast:** If a container command fails, a report is missing, or formatting breaks, mark the segment as failed/incomplete. Never synthesize arbitrary metrics or metrics counts.
* **Exclusion Targets:** Automatically exclude standard dependency targets (`.venv`, `node_modules`), caches (`__pycache__`), and version control metadata (`.git`) via scanner arguments or directory skipping.