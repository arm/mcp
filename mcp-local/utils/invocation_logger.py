# Copyright © 2025, Arm Limited and Contributors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from .config import WORKSPACE_DIR


LOG_FILE_NAME = "mcp-traffic.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_invocation_reason(
    tool: str,
    reason: Optional[str],
    args: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Append a JSONL call entry to the workspace traffic log.

    Returns the entry ID so the caller can pair the tool result with this invocation.
    Errors are swallowed to avoid impacting tool execution.
    """
    entry_id = str(uuid.uuid4())
    timestamp = _now_iso()

    traffic_entry = {
        "id": entry_id,
        "timestamp": timestamp,
        "tool": tool,
        "args": args or {},
        "invocation_reason": reason,
    }
    log_path = os.path.join(WORKSPACE_DIR, LOG_FILE_NAME)
    try:
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(traffic_entry) + "\n")
    except Exception:
        pass

    return entry_id


def log_tool_result(entry_id: str, tool: str, result: Any) -> None:
    """Append a JSONL result entry paired with a tool invocation."""
    log_path = os.path.join(WORKSPACE_DIR, LOG_FILE_NAME)
    result_entry = {
        "id": entry_id,
        "type": "result",
        "tool": tool,
        "result": result,
    }
    try:
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(result_entry, default=str) + "\n")
    except Exception:
        pass
