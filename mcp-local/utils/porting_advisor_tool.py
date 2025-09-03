from typing import Dict, Any, List, Optional
from .cli_utils import run_command


def porting_advisor_help() -> Dict[str, Any]:
    return run_command(["porting-advisor", "--help"], use_venv=True)


def porting_advisor_run(path: Optional[str], extra_args: Optional[List[str]]) -> Dict[str, Any]:
    if not path and not extra_args:
        return {"status": "error", "message": "Provide a path or extra_args to run Porting Advisor."}
    cmd = ["porting-advisor"]
    if path:
        cmd.append(path)
    if extra_args:
        cmd += extra_args
    return run_command(cmd, use_venv=True)

