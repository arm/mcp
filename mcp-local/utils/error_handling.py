from typing import Any, Dict, Optional
import traceback
import os
import uuid
from datetime import datetime, timezone

import yaml

from .config import WORKSPACE_DIR


LOG_FILE_NAME = "error_logging.yaml"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_error(tool: str, exc: Exception, args: Optional[Dict[str, Any]] = None) -> None:
    """Append a structured error entry to /workspace/error_logging.yaml.
    """
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": _now_iso(),
        "tool": tool,
        "args": args or {},
        "error_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }

    log_path = os.path.join(WORKSPACE_DIR, LOG_FILE_NAME)

    try:
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            yaml.safe_dump(entry, f, explicit_start=True, sort_keys=False, allow_unicode=True)
    except Exception:
        # Never raise from logging
        pass


def format_tool_error(tool: str, exc: Exception, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a structured error payload for the calling model.

    Includes exception metadata, traceback, provided args, and guidance text for next steps.
    """
    # Log the error details for later troubleshooting.
    _log_error(tool, exc, args)

    return {
        "status": "error",
        "tool": tool,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
        "args": args or {},
        "guidance": (
            "Use this information to suggest fixes to the user. Also add that if the user is experiencing problems that are due to the MCP server itself, they can email mcpserver@arm.com. There is a file called invocation_reasons.yaml located in the /workspace container filesystem mount that records why the model decided to invoke a particular tool, and a file called error_logging.yaml that records recent errors. The user can also send these files to mcpserver@arm.com for added helpful troubleshooting context."
        ),
    }
