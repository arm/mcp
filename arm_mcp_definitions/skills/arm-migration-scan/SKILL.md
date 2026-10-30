---
name: arm-migration-scan
description: Download and run migrate-ease compatibility scanners to assess Arm portability (C/C++, Python, Go, Rust, Java, JavaScript, Dockerfile). Triggers on requests to scan local checkouts or remote repos for aarch64 migration.
---

# Arm Migration Assessment Workflow

## Trigger Conditions
* **Supported Scanners:** Activate for `cpp`, `python`, `go`, `rust`, `java`, `js`, or `docker` components. Return unsupported targets as unassessed.
* **Boundaries:** Do not use for general static analysis, application compilation, or native cloud build execution. Do not assume that a scan for a specific language is sufficient to assess the entire repository. Scan for all supported languages present.

## Execution Workflow

1. **Target Setup: & Parameter Mapping**
* Map target `--march` from user input (defaults to `armv8-a`). 
* If the user specifies cloud hosting, map via `--vendor` (e.g., AWS, GCP) and `--instance-type` (e.g., c7g) instead of `--march`.

2. **Isolate Environment:** 
Run all tool setup tasks outside the current workspace tree (inside `/tmp`) to protect local Git change tracking from context bloat and trailing artifacts.

3. **Install Migrate Ease from GitHub**
Download Migrate Ease from its canonical GitHub repository into the isolated temporary area, install its Python requirements in a dedicated virtual environment, and record the resolved Git commit. Do not install into the system Python environment or use `sudo`.

```sh
source_dir="/tmp/target-checkout"
tool_root="$(mktemp -d)"
report_dir="$(mktemp -d)"


# Clone and setup tool environment
git clone --depth 1 https://github.com/migrate-ease/migrate-ease.git "$tool_root/migrate-ease"
python3 -m venv "$tool_root/venv"
"$tool_root/venv/bin/python" -m pip install -r "$tool_root/migrate-ease/requirements.txt"

# Log version control state for reproducibility
git -C "$tool_root/migrate-ease" rev-parse HEAD
export PYTHONPATH="$tool_root/migrate-ease"
```

4. **Execute Scanner Environment**
Invoke the module using its specific language-scanner designation. 

* **For Local Directories:**
  ```sh
  "$tool_root/venv/bin/python" -m {scanner_name} --march armv8-a --output "$report_dir/{scanner_name}.json" "/path/to/local-code"
  ```
* **For Remote Git Repositories (Native Execution):**
  ```sh
  "$tool_root/venv/bin/python" -m {scanner_name} --march armv8-a --git-repo {repo_url} --output "$report_dir/{scanner_name}.json" "$source_dir"
  ```
* **Using Vendor Flags (If applicable):**
  ```sh
  "$tool_root/venv/bin/python" -m {scanner_name} --vendor {vendor} --instance-type {instance} --output "$report_dir/{scanner_name}.json" "$source_dir"
  ```
5. **Scale Control (Repositories > 1 GB):** Split scopes by independent sub-directories. Execute scanner processes in parallel and surface completed partial chunks dynamically.

6. **Report Consolidation:**
For multi-directory or multi-language split scans, consolidate individual JSON results using `jq` into a unified report array before rendering:
```sh
jq -s '.' "$report_dir"/*.json > "$report_dir/consolidated_report.json"
```

7. **Interactive HTML View:** After presenting the scan summary, explicitly ask the user whether they want the report opened in a web browser, then end the turn and wait for their response. Only after the user explicitly confirms may the agent start a report server and open the consolidated profile.
   * Convert `consolidated_report.json` into `consolidated_report.html`. The HTML must present the scan summary, coverage, findings, scanner errors, and source-file details; it may load the JSON as a companion file from the same directory. Preserve the original JSON as the source of truth.
   * Serve the report directory with a loopback-only localhost server and open the HTML URL with the platform's browser opener. Choose an unused port if the example port is occupied. Confirm that the server returns the HTML successfully; if the browser does not appear, give the user the localhost URL.
   ```sh
     # First generate $report_dir/consolidated_report.html from the JSON.
     python3 -m http.server 8765 --bind 127.0.0.1 --directory "$report_dir" &
     open "http://127.0.0.1:8765/consolidated_report.html"
   ```
## Operational Rules
* **Mandatory Post-Scan Prompt:** Every scan that produces a consolidated report must end with an explicit question such as, "Would you like me to open the report in your browser?"
* **Strict Confirmation Gate:** Do not start the native web server or attempt to launch a local browser window until the user gives an explicit affirmative response.
* **Localhost HTML Report:** When the user has confirmed, generate the HTML report, bind its server to `127.0.0.1` rather than all interfaces, and open `consolidated_report.html` through the localhost URL instead of relying on a local-file association.
* **Strict Fail-Fast:** If downloading or installing Migrate Ease fails, a scanner command fails, a report is missing, or formatting breaks, mark the segment as failed/incomplete. Never synthesize arbitrary metrics or metrics counts.
* **Exclusion Targets:** Automatically exclude standard dependency targets (`.venv`, `node_modules`), caches (`__pycache__`), and version control metadata (`.git`) via scanner arguments or directory skipping.
* **Arm-Specific Guidance:** Use `knowledge_base_search` for Arm-specific dependency guidance.