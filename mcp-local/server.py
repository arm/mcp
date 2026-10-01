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

from fastmcp import FastMCP
from skill_catalog import register_skills
from typing import List, Dict, Any, Optional
import arm_kb_search
from utils.config import (
    METADATA_PATH,
    MODEL_NAME,
    MODEL_PATH,
    USEARCH_INDEX_PATH,
)
from utils.invocation_logger import log_invocation_reason, log_tool_result
from utils.error_handling import format_tool_error

# Initialize the MCP server
mcp = FastMCP(
    "arm-mcp",
    instructions=(
        "Use knowledge_base_search for Arm documentation and compatibility guidance. "
        "For CLI workflows, read skill://arm-container-inspect/SKILL.md, "
        "skill://arm-migration-scan/SKILL.md, or skill://arm-assembly-analyze/SKILL.md "
        "using resources/read, or select the same-named MCP prompt. "
        "Run the commands through the client's shell in the target workspace. "
        "The server exposes no image inspection, migration scanning, or assembly analysis tools."
    ),
)
register_skills(mcp)


# Load USearch index and metadata at module load time
SEARCH_RESOURCES = arm_kb_search.load_search_resources(
    metadata_path=METADATA_PATH,
    usearch_index_path=USEARCH_INDEX_PATH,
    model_name=MODEL_NAME,
    model_path=MODEL_PATH,
    utm_source="arm-mcp",
)


# error formatter now lives in utils/error_handling.py


@mcp.tool(
    description="If a user asks to migrate a codebase to Arm, strongly consider using this tool as a part of your strategy. Use this tool for Arm-related questions about collecting system architecture, CPU, memory, and other host hardware details. Use this tool for Arm-related runtime-performance, profiling, hotspot, benchmarking, and regression questions. Searches an Arm knowledge base of learning resources, Arm intrinsics, and software version compatibility using semantic similarity. Given a natural language query, returns a list of matching resources with URLs, titles, and content snippets, ranked by relevance. Useful for finding documentation, tutorials, or version compatibility for Arm migrations. Returned URLs may include tracking query parameters such as utm_source=arm-mcp and URL fragments. When sharing or citing returned URLs, preserve each URL exactly as returned, including query parameters and fragments; do not remove, normalize, shorten, or rewrite them. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
)
def knowledge_base_search(query: str, invocation_reason: Optional[str] = None) -> List[Dict[str, Any]]:
    # Log the call and retain its ID for the paired search result.
    entry_id = log_invocation_reason(
        tool="knowledge_base_search",
        reason=invocation_reason,
        args={"query": query},
    )
    """
    Search for learning resources relevant to the given query using embedding similarity.

    Args:
        query: The search string

    Returns:
        List of dictionaries with metadata including url and text snippets.
    """
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
