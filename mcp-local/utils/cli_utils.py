from __future__ import annotations

from typing import Dict, Any, List, Optional
import subprocess
import shlex
import os


def run_command(cmd: List[str], use_venv: bool = False, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run a CLI command and return a structured result.

    Args:
        cmd: Command and args to run.
        use_venv: If true, ensure the command runs with this project's venv bin on PATH.
        cwd: Optional working directory.
        env: Optional extra environment variables.

    Returns:
        Dict with keys: status (ok/error), code, stdout, stderr, cmd.
    """
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    if use_venv:
        venv_bin = os.path.join(os.getcwd(), ".venv", "bin")
        # Prepend venv bin to PATH if it exists
        if os.path.isdir(venv_bin):
            full_env["PATH"] = f"{venv_bin}:{full_env.get('PATH','')}"

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=full_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "cmd": cmd,
        }
    except FileNotFoundError as e:
        return {"status": "error", "code": 127, "stdout": "", "stderr": str(e), "cmd": cmd}
    except Exception as e:
        return {"status": "error", "code": -1, "stdout": "", "stderr": str(e), "cmd": cmd}

