from typing import Dict, Any, List, Optional
from .cli_utils import run_command


def perf_help() -> Dict[str, Any]:
    return run_command(["perf", "--help"])


def perf_record(cmd: List[str], seconds: Optional[int], data_file: str, extra_args: Optional[List[str]]) -> Dict[str, Any]:
    rec = ["perf", "record", "-o", data_file]
    if seconds:
        rec += ["--", "timeout", str(seconds)]
    if extra_args:
        rec += extra_args
    if seconds:
        rec += cmd
    else:
        rec += ["--"] + cmd
    return run_command(rec)


def perf_report(data_file: str, extra_args: Optional[List[str]]) -> Dict[str, Any]:
    cmd = ["perf", "report", "-i", data_file]
    if extra_args:
        cmd += extra_args
    return run_command(cmd)

