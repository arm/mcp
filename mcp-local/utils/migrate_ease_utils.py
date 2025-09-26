from typing import Dict, Any, List, Optional
import os
import time
import shlex
import subprocess
import json
import tempfile
import shutil
from .config import SUPPORTED_SCANNERS, WORKSPACE_DIR


def _normalize_scanner(scanner: str) -> str:
    """
    Normalize scanner names. Docs sometimes show 'Python' capitalized;
    the package modules are typically lowercase. We'll prefer lowercase.
    """
    s = scanner.strip()
    if s.lower() in SUPPORTED_SCANNERS:
        return s.lower()
    return s  # let the caller see the exact name if it's custom


def _resolve_scan_path(path: Optional[str]) -> str:
    """
    Resolve a user path against the workspace mount if it's not absolute.
    Defaults to WORKSPACE_DIR when path is None.
    """
    if not path:
        return WORKSPACE_DIR
    if os.path.isabs(path):
        return path
    return os.path.join(WORKSPACE_DIR, path)


def _build_output_path(scanner: str, output_format: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = output_format.lower().lstrip(".")
    # Always put results into /tmp to avoid permission issues
    return f"/tmp/migrate_ease_{scanner}_{ts}.{suffix}"


def run_migrate_ease_scan(
    scanner: str,
    arch: str,
    scan_path: Optional[str],
    git_repo: Optional[str],
    output_format: str,
    extra_args: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Execute migrate-ease via unified CLI wrappers installed in /usr/local/bin:
    'migrate-ease-{scanner}' (e.g., migrate-ease-cpp, migrate-ease-python, migrate-ease-go, migrate-ease-js, migrate-ease-java).

    NOTE: Remote repository scans are staged inside a temporary directory under /tmp
    that is removed after execution. The migrate-ease output file is created
    under /tmp and is **deleted** before this function returns. A best-effort
    deletion flag is included in the returned dictionary as 'output_file_deleted'.
    """
    normalized_scanner = _normalize_scanner(scanner)
    fmt = output_format.lower().lstrip(".")
    if fmt not in {"json", "txt", "csv", "html"}:
        return {"status": "error", "message": f"Unsupported output format '{output_format}'."}

    out_path = _build_output_path(normalized_scanner, fmt)

    # Base command uses unified wrapper
    wrapper = f"migrate-ease-{normalized_scanner}"

    cmd: List[str] = [wrapper, "--march", arch, "--output", out_path]

    temporary_clone_dir: Optional[str] = None

    try:
        # Route: git repo vs local path
        if git_repo:
            # Always stage remote scans inside a temporary workspace that is cleaned up later
            temporary_clone_dir = tempfile.mkdtemp(prefix="migrate_ease_clone_", dir="/tmp")
            cmd.extend(["--git-repo", git_repo, temporary_clone_dir])
            resolved_for_echo = temporary_clone_dir
        else:
            target = _resolve_scan_path(scan_path)
            cmd.append(target)
            resolved_for_echo = target

        # Append any raw extra args last
        if extra_args:
            cmd.extend(extra_args)

        # Run (no special cwd required when using wrappers)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60 * 30,  # 30 minutes max
        )
        status = "success" if proc.returncode == 0 else "error"
        result: Dict[str, Any] = {
            "status": status,
            "returncode": proc.returncode,
            "command": " ".join(shlex.quote(c) for c in cmd),
            "ran_from": os.getcwd(),
            "target": resolved_for_echo,
            "stdout": proc.stdout[-50_000:],  # tail to keep payload reasonable
            "stderr": proc.stderr[-50_000:],
            "output_file": out_path,
            "output_format": fmt,
        }

        # Inline JSON results before cleanup so callers still get the data.
        if fmt == "json":
            try:
                with open(out_path, "r") as f:
                    data = json.load(f)
                result["parsed_results"] = data
            except Exception as e:
                result["parsed_results_error"] = f"Failed to parse JSON report: {e}"

        # BEST-EFFORT CLEANUP of the migrate-ease output file
        try:
            os.remove(out_path)
            result["output_file_deleted"] = True
        except FileNotFoundError:
            # It might not have been created (e.g., early failure)
            result["output_file_deleted"] = False
            result["output_file_delete_error"] = "Output file not found during cleanup."
        except Exception as e:
            result["output_file_deleted"] = False
            result["output_file_delete_error"] = f"Failed to delete output file: {e}"

        return result

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": "migrate-ease scan timed out.",
            "command": " ".join(shlex.quote(c) for c in cmd),
        }
    except FileNotFoundError as e:
        return {
            "status": "error",
            "message": f"Failed to execute migrate-ease wrapper '{wrapper}': {e}",
            "hint": "Ensure migrate-ease wrappers are installed on PATH (e.g., /usr/local/bin).",
        }
    finally:
        if temporary_clone_dir:
            shutil.rmtree(temporary_clone_dir, ignore_errors=True)
