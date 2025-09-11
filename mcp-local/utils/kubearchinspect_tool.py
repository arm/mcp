from typing import Dict, Any, Optional, List
from .cli_utils import run_command


def kubearchinspect_help() -> Dict[str, Any]:
    return run_command(["kubearchinspect", "--help"], use_venv=True)


def kubearchinspect_scan(kubeconfig: Optional[str], namespace: Optional[str], output_format: str, extra_args: Optional[List[str]]) -> Dict[str, Any]:
    cmd = ["kubearchinspect"]
    if kubeconfig:
        cmd += ["--kubeconfig", kubeconfig]
    if namespace:
        cmd += ["--namespace", namespace]
    if output_format:
        cmd += ["--output", output_format]
    if extra_args:
        cmd += extra_args
    return run_command(cmd, use_venv=True)

