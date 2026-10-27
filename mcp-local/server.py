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

import sys
from pathlib import Path

# Also support running this file directly from a source checkout. In the image,
# arm_mcp_definitions is copied next to server.py and is already on the import path.
sys.path.append(str(Path(__file__).resolve().parents[1] / "arm-mcp-definitions"))

from arm_mcp_definitions import SERVER_INSTRUCTIONS, register_capabilities
from fastmcp import FastMCP
from utils.config import (
    METADATA_PATH,
    MODEL_NAME,
    MODEL_PATH,
    USEARCH_INDEX_PATH,
)
from utils.error_handling import format_tool_error
from utils.invocation_logger import log_invocation_reason, log_tool_result

import arm_kb_search

mcp = FastMCP("arm-mcp", instructions=SERVER_INSTRUCTIONS)


# Load USearch index and metadata at module load time
SEARCH_RESOURCES = arm_kb_search.load_search_resources(
    metadata_path=METADATA_PATH,
    usearch_index_path=USEARCH_INDEX_PATH,
    model_name=MODEL_NAME,
    model_path=MODEL_PATH,
    utm_source="arm-mcp",
)


def search_knowledge_base(query, invocation_reason=None):
    # Log the call and retain its ID for the paired search result.
    entry_id = log_invocation_reason(
        tool="knowledge_base_search",
        reason=invocation_reason,
        args={"query": query},
    )
    try:
        results = arm_kb_search.search(query, SEARCH_RESOURCES)
        log_tool_result(entry_id, "knowledge_base_search", results)
        return results
    except Exception as e:
        return format_tool_error(
            tool="knowledge_base_search",
            exc=e,
            args={"query": query},
        )


register_capabilities(mcp, search_knowledge_base)


if __name__ == "__main__":
    mcp.run(transport="stdio")
