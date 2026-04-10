import json
import subprocess
import os
import re
from textwrap import dedent
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


QUERY_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "sql" / "queries.sql"
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
RUN_KEYS_DIR = Path("/run/keys")
PROC_MOUNTS_PATH = Path("/proc/self/mounts")


def load_recipe_query_map(sql_file_path: Path) -> Dict[str, Dict[str, str]]:
    recipe_query_map: Dict[str, Dict[str, str]] = {}
    if not sql_file_path.exists():
        return recipe_query_map

    content = sql_file_path.read_text(encoding="utf-8")
    current_key: Optional[str] = None
    current_lines: List[str] = []

    def commit_block(block_key: Optional[str], block_lines: List[str]) -> None:
        if not block_key:
            return

        sql_text = "\n".join(block_lines).strip()
        if not sql_text:
            return

        if "." not in block_key:
            raise ValueError(
                f"Invalid SQL block name '{block_key}'. Expected format '<recipe>.<query_name>'."
            )

        recipe, query_name = block_key.split(".", 1)
        recipe = recipe.strip()
        query_name = query_name.strip()
        if not recipe or not query_name:
            raise ValueError(
                f"Invalid SQL block name '{block_key}'. Recipe and query name must be non-empty."
            )

        recipe_query_map.setdefault(recipe, {})[query_name] = sql_text

    for line in content.splitlines():
        name_match = re.match(r"^\s*--\s*name\s*:\s*(.+?)\s*$", line)
        if name_match:
            commit_block(current_key, current_lines)
            current_key = name_match.group(1).strip()
            current_lines = []
            continue

        if current_key:
            current_lines.append(line)

    commit_block(current_key, current_lines)
    return recipe_query_map


RECIPE_QUERY_MAP = load_recipe_query_map(QUERY_REGISTRY_PATH)


def normalize_sql_query(query: str) -> str:
    normalized = dedent(query).strip()
    if not normalized.endswith(";"):
        normalized += ";"
    return normalized


def build_recipe_query(recipe: str, default_table: str, query_name: str = "default") -> str:
    recipe_query_set = RECIPE_QUERY_MAP.get(recipe, {})
    recipe_query = recipe_query_set.get(query_name)
    if recipe_query:
        return normalize_sql_query(recipe_query)

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", default_table):
        raise ValueError(f"Invalid SQL table name for fallback query: {default_table}")

    return f"SELECT * FROM {default_table};"


def _trim_output(text: str, max_chars: int = 50_000) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _sanitize_apx_output(output: str) -> str:
    return ANSI_ESCAPE_RE.sub("", output or "")


def _extract_session_id(render_output: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract session_id from apx render output, trying full JSON then line-by-line JSON."""
    clean_output = (render_output or "").strip()
    if not clean_output:
        return None, "apx render returned empty output."

    parse_attempts: List[str] = [clean_output]
    parse_attempts.extend(
        [line.strip() for line in clean_output.splitlines() if line.strip().startswith("{")]
    )

    parse_errors: List[str] = []
    for candidate in parse_attempts:
        try:
            parsed = json.loads(candidate)
        except Exception as exc:
            parse_errors.append(str(exc))
            continue

        session_id = (
            parsed.get("data", {})
            .get("invocation", {})
            .get("session_id")
        )
        if session_id:
            return session_id, None

    parse_error_text = "; ".join(parse_errors[-3:]) if parse_errors else "Unknown parse failure"
    return None, f"Unable to parse session_id from render output. Parse errors: {parse_error_text}"


def _dedupe_headers(headers: List[str]) -> Tuple[List[str], List[str]]:
    unique_headers: List[str] = []
    warnings: List[str] = []
    seen: Dict[str, int] = {}

    for idx, header in enumerate(headers, start=1):
        base = header.strip() or f"column_{idx}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        if count == 1:
            unique_headers.append(base)
            continue

        deduped = f"{base}_{count}"
        unique_headers.append(deduped)
        warnings.append(
            f"Duplicate header '{base}' detected; renamed occurrence {count} to '{deduped}'."
        )

    return unique_headers, warnings


def _coerce_cell_value(value: str) -> Any:
    text = (value or "").strip()
    if text == "":
        return ""

    numeric_candidate = text.replace(",", "")
    if re.fullmatch(r"[-+]?\d+", numeric_candidate):
        try:
            return int(numeric_candidate)
        except Exception:
            return text
    if re.fullmatch(r"[-+]?\d*\.\d+", numeric_candidate):
        try:
            return float(numeric_candidate)
        except Exception:
            return text
    return text


def parse_apx_query_table(output: str) -> Dict[str, Any]:
    """
    Parse an apx unicode table into structured columns/rows.
    Returns best-effort results and warnings without raising.
    """
    cleaned = _sanitize_apx_output(output)
    lines = cleaned.splitlines()
    table_rows: List[List[str]] = []

    for line in lines:
        stripped = line.strip()
        if not (stripped.startswith("┃") and stripped.endswith("┃")):
            continue

        inner = stripped[1:-1]
        cells = [cell.strip() for cell in inner.split("┃")]
        if len(cells) < 2:
            # Skip single-cell rows from the rendered query preview block.
            continue
        if all(cell == "" for cell in cells):
            continue
        table_rows.append(cells)

    if not table_rows:
        return {
            "columns": [],
            "rows": [],
            "warnings": ["No result table detected in apx query output."],
        }

    raw_headers = table_rows[0]
    columns, header_warnings = _dedupe_headers(raw_headers)
    expected_columns = len(columns)
    warnings: List[str] = list(header_warnings)
    parsed_rows: List[Dict[str, Any]] = []

    for row_idx, cells in enumerate(table_rows[1:], start=1):
        adjusted_cells = list(cells)
        if len(adjusted_cells) != expected_columns:
            warnings.append(
                f"Row {row_idx} has {len(adjusted_cells)} cells; expected {expected_columns}. "
                "Adjusted row length to match headers."
            )
            if len(adjusted_cells) < expected_columns:
                adjusted_cells += [""] * (expected_columns - len(adjusted_cells))
            else:
                adjusted_cells = adjusted_cells[:expected_columns]

        row_obj: Dict[str, Any] = {}
        for col_name, raw_value in zip(columns, adjusted_cells):
            row_obj[col_name] = _coerce_cell_value(raw_value)
        parsed_rows.append(row_obj)

    return {
        "columns": columns,
        "rows": parsed_rows,
        "warnings": warnings,
    }


def _build_atp_error_response(
    recipe: str,
    stage: str,
    message: str,
    suggestion: str,
    details: str = "",
    query: Optional[str] = None,
    raw_output: str = "",
) -> Dict[str, Any]:
    response: Dict[str, Any] = {
        "status": "error",
        "recipe": recipe,
        "stage": stage,
        "message": message,
        "suggestion": suggestion,
        "details": _trim_output(details),
        "warnings": [],
    }
    if query:
        response["query"] = query
    if raw_output:
        response["raw_output"] = _trim_output(raw_output)
    return response


def _decode_mount_field(field: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        field,
    )


def discover_run_keys_mounts(
    mounts_path: Optional[Path] = None,
    run_keys_dir: Optional[Path] = None,
) -> List[str]:
    mounts_path = mounts_path or PROC_MOUNTS_PATH
    run_keys_dir = run_keys_dir or RUN_KEYS_DIR

    if not mounts_path.exists():
        return []

    mount_targets: List[str] = []
    for line in mounts_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        target = _decode_mount_field(parts[1])
        if target == str(run_keys_dir) or target.startswith(f"{run_keys_dir}/"):
            mount_targets.append(target)

    # Preserve input order while removing duplicates.
    return list(dict.fromkeys(mount_targets))


def _select_known_hosts_path(mount_targets: List[str]) -> Optional[str]:
    matches = [
        path for path in mount_targets
        if "known_hosts" in Path(path).name.lower().replace("-", "_")
    ]
    return matches[0] if len(matches) == 1 else None


def _select_ssh_key_path(mount_targets: List[str], known_hosts_path: Optional[str]) -> Optional[str]:
    candidates = [path for path in mount_targets if path != known_hosts_path]
    if len(candidates) == 1:
        return candidates[0]

    key_like = [
        path for path in candidates
        if any(
            token in Path(path).name.lower()
            for token in ("ssh", "key", ".pem", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")
        )
    ]
    return key_like[0] if len(key_like) == 1 else None


def resolve_apx_ssh_mount_env() -> Dict[str, Any]:
    key_path = os.getenv("SSH_KEY_PATH")
    known_hosts_path = os.getenv("KNOWN_HOSTS_PATH")
    mount_targets: List[str] = []

    if key_path and known_hosts_path:
        return {
            "key_path": key_path,
            "known_hosts_path": known_hosts_path,
            "mount_targets": mount_targets,
        }

    mount_targets = discover_run_keys_mounts()

    if not known_hosts_path:
        known_hosts_path = _select_known_hosts_path(mount_targets)
        if known_hosts_path:
            os.environ["KNOWN_HOSTS_PATH"] = known_hosts_path

    if not key_path:
        key_path = _select_ssh_key_path(mount_targets, known_hosts_path)
        if key_path:
            os.environ["SSH_KEY_PATH"] = key_path

    return {
        "key_path": key_path,
        "known_hosts_path": known_hosts_path,
        "mount_targets": mount_targets,
    }

def extract_run_id(output: str) -> str:
    if not output:
        return ""
    try:
        data = json.loads(output.split("\n")[1])
        return data.get("data", {}).get("run_id", {})
    except Exception:
        return ""

def run_command(command: list, cwd: str, parse_output=None) -> tuple:
    """
    Run a shell command as a child process and wait for it to finish.
    Optionally parse the output using a provided function.
    Returns (returncode, parsed_output or stdout).
    """
    try:
        #print(command)
        result = subprocess.run(command, cwd=cwd, timeout=60*60*3, capture_output=True, text=True)
    except subprocess.TimeoutExpired as e:
        print(f"Command timed out: {e}")
        return -1, None
    output = result.stdout
    
    if parse_output:
        output = parse_output(output)
    return result.returncode, output

def read_file_contents(file_path: str) -> str:
    """Read the contents of a file and return as a string."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def prepare_target(remote_ip_addr: str, remote_usr: str, ssh_key_path: str, apx_dir:str) -> dict:
    """Prepare the target machine for running workloads. 
        Returns the target ID."""
    
    #Check if target already exists
    list_command = ["./apx", "target", "list", "--json"]
    status, list_output = run_command(list_command, cwd=apx_dir)
    if status == 0 and list_output:
        try:
            lines = list_output.strip().split("\n")
            json_line = lines[1] if len(lines) > 1 else lines[0]
            data = json.loads(json_line)
            targets = data.get("data", {})
            for target_id, target_info in targets.items():
                value = target_info.get("value", {})
                jumps = value.get("jumps", [])
                if not jumps:
                    continue
                jump = jumps[0]
                t_host = jump.get("host")
                t_user = jump.get("username")
                t_key = jump.get("private_key_filename")
                if t_host == remote_ip_addr and t_user == remote_usr and t_key == ssh_key_path:
                    #print(f"Target already exists: {target_id}")
                    return {
                        "target_id": target_id
                    }
        except Exception as e:
            print(f"Failed to parse target list output: {e}")
    
    generated_name = f"{remote_usr}_{remote_ip_addr.replace('.', '_')}"
    # Add the target if it doesn't exist
    if remote_ip_addr in {"172.17.0.1", "localhost"}:
        add_command = [
            "./apx", "target", "add",
            f"{remote_usr}@172.17.0.1:22:{ssh_key_path}",
            "--name", generated_name, "--host-key-policy=ignore"
        ]
    else:
        add_command = [
            "./apx", "target", "add",
            f"{remote_usr}@{remote_ip_addr}:22:{ssh_key_path}",
            "--name", generated_name
        ]
    add_status, add_output = run_command(add_command, cwd=apx_dir)
    
    # Check for SSH key permission errors
    if add_output and ("engine.ssh.KEY_FILE_NOT_READABLE" in add_output):
        return {
            "error": "Check that the file permissions allow read access to the SSH key file. If ATP still cannot read the file, contact Arm support.",
            "details": f"Please run: chmod 0600 on your SSH key and then restart the mcp server.",
            "raw_output": add_output
        }

    command = [
        "./apx",
        "target", "prepare",
        "--target", f"{generated_name}"
    ]
    status, target_id = run_command(command, cwd=apx_dir)
    if status != 0 or not target_id:
        return {
            "error": "Failed to prepare target. Check the connection details and make sure you have the correct username and ip address. Sometimes when you mean to connect to localhost, you are running from a docker container so the ip address needs to be 172.17.0.1",
            "details": target_id
        }
    return {
        "target_id": generated_name
    }

def run_workload(cmd:str, target: str, recipe:str, apx_dir:str) -> dict:
    """Run a sample workload on the target machine. Some example queries: 
        - 'Help my analyze my code's performance'.
        - 'Find the CPU hotspots in my application'.
        Returns the run ID of the workload execution."""
    
    # Check if the recipe is ready to run on the target
    ready_command = ["./apx", "recipe", "ready", recipe, "--target", target]
    ready_status, ready_output = run_command(ready_command, cwd=apx_dir)

    ready_output_text = (ready_output or "").lower()
    has_deploy_tools_hint = (
        "--deploy-tools" in ready_output_text
        and "to deploy this tool on the target" in ready_output_text
    )
    
    # If readiness failed for reasons other than missing deployed tools, return early.
    # Missing tool deployment is expected because recipe run uses --deploy-tools.
    if (ready_status != 0 or (ready_output and ready_output.strip())) and not has_deploy_tools_hint:
        return {
            "error": "The recipe is not ready to run on the target machine.",
            "details": ready_output if ready_output else "Recipe readiness check failed.",
            "suggestion": "You may need to run 'target prepare' or use '--deploy-tools' flag."
        }
    
    command = [
        "./apx",
        "recipe", "run", recipe,
        f"--workload={cmd}",
        "--json",
        f"--target={target}",
        "--deploy-tools", "--param", "collect_java_stacks=true"
    ]
    status, output = run_command(command, cwd=apx_dir)
    output_text = output or ""
    run_id = extract_run_id(output_text) if status == 0 else ""
    if not run_id or "Error" in output_text:
        return {
            "error": output_text if output_text else "Failed to run workload.",
            "details": output_text
        }
    return {"run_id": run_id}

def get_results(run_id: dict, recipe: str, apx_dir: str, default_table: str = "drilldown") -> Dict[str, Any]:
    """Get results from the target machine after running a workload. 
        Returns a structured response with SQL query, table columns/rows, and warnings/errors."""

    if not run_id or "value" not in run_id:
        return _build_atp_error_response(
            recipe=recipe,
            stage="input_validation",
            message="Missing or invalid run_id payload.",
            suggestion="Re-run the workload and retry this recipe query.",
            details=f"Expected run_id with a 'value' key, received: {run_id}",
        )

    try:
        query = build_recipe_query(recipe, default_table)
    except ValueError as e:
        return _build_atp_error_response(
            recipe=recipe,
            stage="query_build",
            message="Failed to build a query for this recipe.",
            suggestion="Use a supported recipe query name or validate SQL table names in the fallback query.",
            details=str(e),
        )

    # Startup the local db for querying results
    render_cmd = ["./apx", "run", "render", run_id["value"]]
    try:
        render_proc = subprocess.run(
            render_cmd,
            cwd=apx_dir,
            timeout=60 * 5,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return _build_atp_error_response(
            recipe=recipe,
            stage="render",
            message="Timed out while rendering run data.",
            suggestion="Try running a shorter workload or verify the remote target is responsive.",
            query=query,
        )
    except Exception as e:
        return _build_atp_error_response(
            recipe=recipe,
            stage="render",
            message="Failed to render run data.",
            suggestion="Verify ATP is installed and the run ID is valid, then retry.",
            details=str(e),
            query=query,
        )

    render_stdout = render_proc.stdout or ""
    render_stderr = render_proc.stderr or ""
    if render_proc.returncode != 0:
        return _build_atp_error_response(
            recipe=recipe,
            stage="render",
            message="apx run render command failed.",
            suggestion="Check target connectivity and rerun the recipe. If this persists, prepare the target again.",
            details=render_stderr or render_stdout,
            query=query,
            raw_output=render_stdout,
        )

    session_id, session_error = _extract_session_id(render_stdout)
    if not session_id:
        return _build_atp_error_response(
            recipe=recipe,
            stage="render_parse",
            message="Could not extract session ID from render output.",
            suggestion="Rerun the recipe and ensure ATP returns valid JSON render output.",
            details=session_error or "Missing session_id in render output.",
            query=query,
            raw_output=render_stdout,
        )

    query_cmd = ["./apx", "render", "query", session_id, query]
    try:
        query_proc = subprocess.run(
            query_cmd,
            cwd=apx_dir,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return _build_atp_error_response(
            recipe=recipe,
            stage="query",
            message="Timed out while querying rendered ATP data.",
            suggestion="Try a narrower recipe query or rerun with a smaller workload.",
            query=query,
        )
    except Exception as e:
        return _build_atp_error_response(
            recipe=recipe,
            stage="query",
            message="Failed while executing rendered ATP query.",
            suggestion="Verify ATP CLI health and rerun the recipe.",
            details=str(e),
            query=query,
        )

    if query_proc.returncode != 0:
        return _build_atp_error_response(
            recipe=recipe,
            stage="query",
            message="apx render query command failed.",
            suggestion="Check the generated SQL query and session state, then retry.",
            details=(query_proc.stderr or query_proc.stdout),
            query=query,
            raw_output=query_proc.stdout,
        )

    parsed = parse_apx_query_table(query_proc.stdout or "")
    columns = parsed.get("columns", [])
    rows = parsed.get("rows", [])
    warnings = parsed.get("warnings", [])
    status = "success" if columns else "partial"
    if not columns:
        warnings.append(
            "Query command succeeded but table parsing found no structured columns. Raw output is included."
        )

    return {
        "status": status,
        "recipe": recipe,
        "stage": "complete",
        "query": query,
        "session_id": session_id,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "warnings": warnings,
        "raw_output": _trim_output(query_proc.stdout or ""),
        "stderr": _trim_output(query_proc.stderr or ""),
    }
