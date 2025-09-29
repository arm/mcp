from typing import Dict, Any, List, Optional
from .cli_utils import run_command


def bolt_help() -> Dict[str, Any]:
    return run_command(["llvm-bolt", "--help"])


def bolt_optimize(binary: Optional[str], fdata: Optional[str], output_binary: Optional[str], extra_args: Optional[List[str]]) -> Dict[str, Any]:
    if not binary or not fdata or not output_binary:
        return {"status": "error", "message": "binary, fdata, and output_binary are required for optimize mode"}
    cmd = ["llvm-bolt", binary, "-o", output_binary, f"-data={fdata}"]
    if extra_args:
        cmd += extra_args
    return run_command(cmd)

