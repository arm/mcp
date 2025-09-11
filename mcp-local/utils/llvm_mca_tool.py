from typing import Dict, Any, List, Optional
from .cli_utils import run_command


def mca_help() -> Dict[str, Any]:
    return run_command(["llvm-mca", "--help"])


def llvm_mca_analyze(input_path: str, triple: Optional[str], cpu: Optional[str], extra_args: Optional[List[str]]) -> Dict[str, Any]:
    cmd = ["llvm-mca", input_path]
    if triple:
        cmd += ["--triple", triple]
    if cpu:
        cmd += ["--mcpu", cpu]
    if extra_args:
        cmd += extra_args
    return run_command(cmd)

