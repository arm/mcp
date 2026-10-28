# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
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

"""One MCP contract with a server-supplied knowledge-search implementation."""

from collections.abc import Awaitable, Callable
from typing import Any, Optional

from fastmcp import FastMCP

from .skill_catalog import register_skills

SERVER_INSTRUCTIONS = (
    'Use knowledge_base_search for Arm documentation and compatibility guidance. For CLI '
    'workflows, read skill://arm-container-inspect/SKILL.md, '
    'skill://arm-migration-scan/SKILL.md, or skill://arm-assembly-analyze/SKILL.md using '
    'resources/read, or select the same-named MCP prompt. Run the commands through the '
    "client's shell in the target workspace. The server exposes no image inspection, "
    'migration scanning, or assembly analysis tools.'
)

KNOWLEDGE_SEARCH_DESCRIPTION = (
    'If a user asks to migrate a codebase to Arm, strongly consider using this tool as a '
    'part of your strategy. Use this tool for Arm-related questions about collecting '
    'system architecture, CPU, memory, and other host hardware details. Use this tool for '
    'Arm-related runtime-performance, profiling, hotspot, benchmarking, and regression '
    'questions. Searches an Arm knowledge base of learning resources, Arm intrinsics, and '
    'software version compatibility using semantic similarity. Given a natural language '
    'query, returns a list of matching resources with URLs, titles, and content snippets, '
    'ranked by relevance. Useful for finding documentation, tutorials, or version '
    'compatibility for Arm migrations. Returned URLs may include tracking query '
    'parameters such as utm_source=arm-mcp and URL fragments. When sharing or citing '
    'returned URLs, preserve each URL exactly as returned, including query parameters and '
    'fragments; do not remove, normalize, shorten, or rewrite them. Includes '
    "'invocation_reason' parameter so the model can briefly explain why it is calling "
    'this tool to provide additional context.'
)

SearchResults = list[dict[str, Any]]
SearchHandler = Callable[[str, Optional[str]], SearchResults | Awaitable[SearchResults]]


def register_capabilities(mcp: FastMCP, search_handler: SearchHandler) -> None:
    """Add shared tools, resources and prompts without invoking the backend.

    The handler receives (query, invocation_reason). It owns retrieval, logging,
    and error policy, and may be synchronous or asynchronous. Further server-only
    capabilities can be registered on the same FastMCP instance independently.
    """
    @mcp.tool(description=KNOWLEDGE_SEARCH_DESCRIPTION)
    def knowledge_base_search(
        query: str, invocation_reason: Optional[str] = None
    ) -> SearchResults:
        # FastMCP runs sync tools in its worker pool and awaits any returned
        # coroutine. Preserve that execution policy for both backend styles.
        return search_handler(query, invocation_reason)

    register_skills(mcp)
