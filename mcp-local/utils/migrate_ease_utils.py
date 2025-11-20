from typing import Dict, Any, List, Optional, Set
import os
import time
import shlex
import subprocess
import json
import tempfile
import shutil
from .config import SUPPORTED_SCANNERS, WORKSPACE_DIR

# Directories and patterns to exclude from migrate-ease scans
EXCLUDE_PATTERNS: Set[str] = {
    # Python virtual environments
    'venv', '.venv', 'env', 'ENV', 'virtualenv',
    # Node.js dependencies
    'node_modules',
    # Python cache and build artifacts
    '__pycache__', '.pytest_cache', '.mypy_cache', '.tox',
    'build', 'dist', '*.egg-info',
    # Version control
    '.git', '.svn', '.hg',
    # IDE and editor directories
    '.vscode', '.idea', '.eclipse',
    # Other common build/cache directories
    'target', 'out', '.cache',
}


def _normalize_scanner(scanner: str) -> str:
    """
    Normalize scanner names. Docs sometimes show 'Python' capitalized;
    the package modules are typically lowercase. We'll prefer lowercase.
    """
    s = scanner.strip()
    if s.lower() in SUPPORTED_SCANNERS:
        return s.lower()
    return s  # let the caller see the exact name if it's custom


def _should_exclude(name: str) -> bool:
    """
    Check if a file or directory should be excluded from the filtered workspace.

    Args:
        name: The file or directory name

    Returns:
        True if the item should be excluded, False otherwise
    """
    # Check exact matches
    if name in EXCLUDE_PATTERNS:
        return True

    # Check pattern matches (e.g., *.egg-info)
    for pattern in EXCLUDE_PATTERNS:
        if '*' in pattern:
            # Simple wildcard matching
            if pattern.startswith('*') and name.endswith(pattern[1:]):
                return True
            if pattern.endswith('*') and name.startswith(pattern[:-1]):
                return True

    return False


def _create_filtered_workspace(source_dir: str) -> tuple[str, List[str]]:
    """
    Create a temporary filtered copy of the workspace, excluding virtual environments
    and dependency directories to avoid scanning irrelevant files.

    Args:
        source_dir: The source directory to filter

    Returns:
        Tuple of (filtered_directory_path, list_of_excluded_items)
    """
    filtered_dir = tempfile.mkdtemp(prefix="migrate_ease_filtered_", dir="/tmp")
    excluded_items: List[str] = []

    def copy_tree(src: str, dst: str, base_src: str = None) -> None:
        """Recursively copy directory tree, excluding filtered items."""
        if base_src is None:
            base_src = src

        try:
            items = os.listdir(src)
        except (PermissionError, FileNotFoundError) as e:
            # Skip directories we can't read
            return

        for item in items:
            src_path = os.path.join(src, item)
            dst_path = os.path.join(dst, item)

            # Check if this item should be excluded
            if _should_exclude(item):
                # Track relative path for reporting
                rel_path = os.path.relpath(src_path, base_src)
                excluded_items.append(rel_path)
                continue

            try:
                # Handle symlinks carefully to avoid the broken symlink issue
                if os.path.islink(src_path):
                    # Check if symlink target exists
                    if not os.path.exists(src_path):
                        # Skip broken symlinks
                        rel_path = os.path.relpath(src_path, base_src)
                        excluded_items.append(f"{rel_path} (broken symlink)")
                        continue
                    # Copy the symlink itself, not its target
                    linkto = os.readlink(src_path)
                    os.symlink(linkto, dst_path)
                elif os.path.isdir(src_path):
                    # Recursively copy directory
                    os.makedirs(dst_path, exist_ok=True)
                    copy_tree(src_path, dst_path, base_src)
                else:
                    # Copy regular file
                    shutil.copy2(src_path, dst_path)
            except (PermissionError, OSError) as e:
                # Skip items we can't copy
                rel_path = os.path.relpath(src_path, base_src)
                excluded_items.append(f"{rel_path} (error: {e})")
                continue

    # Perform the filtered copy
    copy_tree(source_dir, filtered_dir)

    return filtered_dir, excluded_items


def _build_output_path(scanner: str, output_format: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = output_format.lower().lstrip(".")
    # Always put results into /tmp to avoid permission issues
    return f"/tmp/migrate_ease_{scanner}_{ts}.{suffix}"


def run_migrate_ease_scan(
    scanner: str,
    arch: str,
    git_repo: Optional[str],
    output_format: str,
    extra_args: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Execute migrate-ease via unified CLI wrappers installed in /usr/local/bin:
    'migrate-ease-{scanner}' (e.g., migrate-ease-cpp, migrate-ease-python, migrate-ease-go, migrate-ease-js, migrate-ease-java).

    NOTE: Local scans now use a filtered copy of WORKSPACE_DIR (/workspace) that excludes
    virtual environments, dependency directories, and build artifacts to improve scan
    performance and avoid errors from broken symlinks. Remote repository scans are staged
    inside a temporary directory under /tmp that is removed after execution. The migrate-ease
    output file is created under /tmp and is **deleted** before this function returns.
    A best-effort deletion flag is included in the returned dictionary as 'output_file_deleted'.
    For local scans, a listing of excluded items is included in the result.
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
    filtered_workspace_dir: Optional[str] = None
    workspace_listing: Optional[List[str]] = None
    workspace_listing_error: Optional[str] = None
    excluded_items: Optional[List[str]] = None

    try:
        # Route: git repo vs workspace scan
        if git_repo:
            # Always stage remote scans inside a temporary workspace that is cleaned up later
            temporary_clone_dir = tempfile.mkdtemp(prefix="migrate_ease_clone_", dir="/tmp")
            cmd.extend(["--git-repo", git_repo, temporary_clone_dir])
            resolved_for_echo = temporary_clone_dir
        else:
            # Create a filtered copy of the workspace to exclude venvs, node_modules, etc.
            try:
                filtered_workspace_dir, excluded_items = _create_filtered_workspace(WORKSPACE_DIR)
                cmd.append(filtered_workspace_dir)
                resolved_for_echo = f"{WORKSPACE_DIR} (filtered)"

                # Get listing of what's in the filtered workspace
                try:
                    workspace_listing = sorted(os.listdir(filtered_workspace_dir))
                except Exception as e:
                    workspace_listing_error = f"Failed to list filtered workspace contents: {e}"
            except Exception as e:
                # If filtering fails, fall back to scanning the original workspace
                # but note the error
                cmd.append(WORKSPACE_DIR)
                resolved_for_echo = WORKSPACE_DIR
                workspace_listing_error = f"Failed to create filtered workspace (scanning original): {e}"
                try:
                    workspace_listing = sorted(os.listdir(WORKSPACE_DIR))
                except Exception as e2:
                    workspace_listing_error = f"{workspace_listing_error}; Failed to list workspace: {e2}"

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

        if workspace_listing is not None:
            result["workspace_listing"] = workspace_listing
        if workspace_listing_error:
            result["workspace_listing_error"] = workspace_listing_error
        if excluded_items is not None:
            result["excluded_items"] = excluded_items
            result["excluded_count"] = len(excluded_items)

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
        # Clean up temporary directories
        if temporary_clone_dir:
            shutil.rmtree(temporary_clone_dir, ignore_errors=True)
        if filtered_workspace_dir:
            shutil.rmtree(filtered_workspace_dir, ignore_errors=True)
