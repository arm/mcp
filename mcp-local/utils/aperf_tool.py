from typing import Dict, Any, List
from .cli_utils import run_command


def aperf_help() -> Dict[str, Any]:
    return run_command(["aperf", "--help"], use_venv=True)


def aperf_run(args: List[str]) -> Dict[str, Any]:
    return run_command(["aperf", *args], use_venv=True)

