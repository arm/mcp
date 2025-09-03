from typing import Dict, Any, List
from .cli_utils import run_command


def topdown_help() -> Dict[str, Any]:
    return run_command(["topdown-tool", "--help"], use_venv=True)


def topdown_run(args: List[str]) -> Dict[str, Any]:
    return run_command(["topdown-tool", *args], use_venv=True)

