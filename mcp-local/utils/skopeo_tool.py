from typing import Dict, Any
from .cli_utils import run_command


def skopeo_help() -> Dict[str, Any]:
    return run_command(["skopeo", "--help"])


def skopeo_inspect(image: str, transport: str = "docker", raw: bool = False) -> Dict[str, Any]:
    cmd = ["skopeo", "inspect"]
    if raw:
        cmd.append("--raw")
    cmd.append(f"{transport}://{image}")
    return run_command(cmd)

