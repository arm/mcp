from typing import Dict, Any, List
from .cli_utils import run_command


def processwatch_help() -> Dict[str, Any]:
    return run_command(["processwatch", "-h"], use_venv=True)


def processwatch_run(args: List[str]) -> Dict[str, Any]:
    return run_command(["processwatch", *args], use_venv=True)

