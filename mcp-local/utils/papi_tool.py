from typing import Dict, Any
from .cli_utils import run_command


def papi_help() -> Dict[str, Any]:
    return run_command(["papi_avail", "-h"])


def papi_list() -> Dict[str, Any]:
    return run_command(["papi_avail"]) 

