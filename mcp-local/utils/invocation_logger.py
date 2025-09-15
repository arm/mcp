import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import yaml

from .config import WORKSPACE_DIR


LOG_FILE_NAME = "invocation_reasons.yaml"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_invocation_reason(tool: str, reason: Optional[str], args: Optional[Dict[str, Any]] = None) -> None:
    """
    Append a YAML document with the tool invocation reason and metadata to /workspace/invocation_reasons.yaml.

    Each call writes a separate YAML document with fields: id, timestamp, tool, args, reason.
    Errors are swallowed to avoid impacting tool execution.
    """
    if not reason:
        return

    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": _now_iso(),
        "tool": tool,
        "args": args or {},
        "reason": str(reason),
    }

    log_path = os.path.join(WORKSPACE_DIR, LOG_FILE_NAME)

    try:
        # Ensure workspace directory exists (it should in runtime environments)
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            yaml.safe_dump(entry, f, explicit_start=True, sort_keys=False, allow_unicode=True)
    except Exception:
        # Do not break tool execution if logging fails
        pass

