from typing import Dict, Any
import subprocess


def run_sysreport() -> Dict[str, Any]:
    """
    Run sysreport and return the system information.
    """
    result = subprocess.run(["python3", "/app/sysreport/src/sysreport.py"], capture_output=True, text=True)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    }