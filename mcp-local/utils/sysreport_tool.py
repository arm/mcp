from typing import Dict, Any
from .cli_utils import run_command


def sysreport_help() -> Dict[str, Any]:
    return run_command(["sysreport", "--help"], use_venv=True)

