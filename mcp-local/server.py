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
from fastmcp.exceptions import ToolError
from typing import Annotated, List, Dict, Any, Optional, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
import arm_kb_search
from arm_kb_search.filters import normalize_filter_value
from utils.config import (
    DEFAULT_ARCH,
    METADATA_PATH,
    MODEL_NAME,
    MODEL_PATH,
    NAME_SYNONYMS_PATH,
    SUPPORTED_SCANNERS,
    USEARCH_INDEX_PATH,
)
from utils.docker_utils import check_docker_image_architectures
from utils.migrate_ease_utils import run_migrate_ease_scan
from utils.skopeo_tool import skopeo_help, skopeo_inspect
from utils.llvm_mca_tool import mca_help, llvm_mca_analyze
from utils.invocation_logger import log_invocation_reason, log_tool_result
from utils.error_handling import format_tool_error

# Initialize the MCP server
mcp = FastMCP("arm-mcp")


# Load USearch index and metadata at module load time
SEARCH_RESOURCES = arm_kb_search.load_search_resources(
    metadata_path=METADATA_PATH,
    usearch_index_path=USEARCH_INDEX_PATH,
    model_name=MODEL_NAME,
    model_path=MODEL_PATH,
    synonyms_path=NAME_SYNONYMS_PATH,
    utm_source="arm-mcp",
)


FilterValue = str | Annotated[list[str], Field(min_length=1)] | None


class KnowledgeBaseFilters(BaseModel):
    """Exact labels or lists of alternatives; fields combine with AND."""

    model_config = ConfigDict(extra="forbid", strict=True)

    doc_type: FilterValue = Field(default=None, description=(
        "Exact document category, for example Learning Paths, Install Guides, Intrinsic, "
        "or Ecosystem Dashboard. Use labels present in returned metadata."))
    product: FilterValue = Field(default=None, description=(
        "Exact corpus product label, for example Arm, AWS Graviton, Neon, SVE, or SVE2. "
        "This is not generally the software name: Jenkins documentation may have product Arm."))
    platform: FilterValue = Field(default=None, description=(
        "Exact platform label, for example linux or windows. Mainly populated for ecosystem "
        "compatibility records; filtering on it excludes tutorials with missing platform metadata."))
    edition: FilterValue = Field(default=None, description=(
        "Exact edition label, for example commercial or open-source. Mainly populated for "
        "ecosystem compatibility records; missing metadata cannot match."))

    @field_validator("doc_type", "product", "platform", "edition")
    @classmethod
    def normalize_value(cls, value: FilterValue) -> str | list[str] | None:
        normalized = normalize_filter_value(value)
        return list(normalized) if isinstance(normalized, tuple) else normalized


# error formatter now lives in utils/error_handling.py


@mcp.tool(
    description="If a user asks to migrate a codebase to Arm, strongly consider using this tool as a part of your strategy. Use this tool for Arm-related questions about collecting system architecture, CPU, memory, and other host hardware details. Use this tool for Arm-related runtime-performance, profiling, hotspot, benchmarking, and regression questions. Searches an Arm knowledge base of learning resources, Arm intrinsics, and software version compatibility using semantic similarity. Given a natural language query, returns a list of matching resources with URLs, titles, and content snippets, ranked by relevance. Useful for finding documentation, tutorials, or version compatibility for Arm migrations. Returned URLs may include tracking query parameters such as utm_source=arm-mcp and URL fragments. When sharing or citing returned URLs, preserve each URL exactly as returned, including query parameters and fragments; do not remove, normalize, shorten, or rewrite them. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context. Optional filters restrict eligible records before ranking: each field accepts a string or non-empty list of strings. Values match complete metadata strings ignoring case and surrounding whitespace. Alternatives within a field combine with OR; different fields combine with AND. Duplicate alternatives are ignored. Omitted/null fields and empty filters leave search unrestricted. Use filters only when their metadata labels fit the question; do not guess product names or apply platform/edition to general tutorials. Unknown labels match nothing; other alternatives can still match. If filtering removes needed evidence, relax the filter; do not conclude the KB has no information. Optional k limits final ranked result entries, not tokens, pages, or embedding pieces: positive integer, default 5 when omitted/null. Fewer than k results may be available. Agents should use at most 20 results. Start with the default unless the task calls for fewer or more sources; additional searches should address a specific evidence gap. Invalid option types, empty lists, blank or non-string list items, unknown filter fields, and non-positive k are rejected. Optional scope selects matching chunks (default), every matched source page (page), or all stored pages in each matched parent resource (parent_resource). Expanded scopes cover all initial hits and deduplicate shared documents; k and filters limit initial matches only. Sources without a known parent use page scope. Expansion uses stored content only, requires complete ordering metadata, and can be large. Returned source links do not load their contents. Use expanded scope only when the user requests wider context; otherwise ask first. Clients must enforce this user-choice boundary."
)
def knowledge_base_search(
    query: str,
    invocation_reason: Optional[str] = None,
    filters: Optional[KnowledgeBaseFilters] = None,
    k: Annotated[Optional[int], Field(strict=True, ge=1,
        description="Maximum ranked result entries (not tokens or pages); positive integer, default 5 when omitted/null. Agents should use at most 20.")] = None,
    scope: Annotated[Literal["chunks", "page", "parent_resource"], Field(description=(
        "chunks (default): ranked matching chunks. page: all stored chunks from every matched "
        "document. parent_resource: all stored pages in each matched parent resource. Sources "
        "without a known parent use page scope. Shared documents are returned once, in stored order. k and filters "
        "select initial hits only; expansion is not limited to k chunks or filtered sibling pages. "
        "Requires complete ordering metadata. Expansion can be large; use only when requested."
    ))] = "chunks",
) -> List[Dict[str, Any]]:
    options = {}
    if filters is not None:
        values = filters.model_dump(exclude_none=True)
        if values:
            options["filters"] = values
    if k is not None:
        options["k"] = k
    if scope != "chunks":
        options["scope"] = scope
    call_args = {"query": query, **options}
    # Preserve the existing query-only log and search call when options are omitted.
    entry_id = log_invocation_reason(
        tool="knowledge_base_search",
        reason=invocation_reason,
        args=call_args,
    )
    """
    Search for learning resources relevant to the given query using embedding similarity.

    Args:
        query: The search string

    Returns:
        List of dictionaries with metadata including url and text snippets.
    """
    try:
        results = arm_kb_search.search(query, SEARCH_RESOURCES, **options)
        log_tool_result(entry_id, "knowledge_base_search", results)
        return results
    except Exception as e:
        if scope != "chunks":
            error = format_tool_error(tool="knowledge_base_search", exc=e, args=call_args)
            log_tool_result(entry_id, "knowledge_base_search", error)
            raise ToolError(str(e)) from e
        return format_tool_error(
            tool="knowledge_base_search",
            exc=e,
            args=call_args,
        )


@mcp.tool(
    description="Check Docker image architectures. Provide a Docker image reference such as nginx:latest and get a report of supported architectures. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
)
def check_image(image: str, invocation_reason: Optional[str] = None) -> dict:
    log_invocation_reason(
        tool="check_image",
        reason=invocation_reason,
        args={"image": image},
    )
    """Check Docker image architectures
    
    Args:
        image: Docker image name (format: name:tag)
        
    Returns:
        Dictionary with architecture information
    """
    try:
        return check_docker_image_architectures(image)
    except Exception as e:
        return format_tool_error(
            tool="check_image",
            exc=e,
            args={"image": image},
        )


@mcp.tool(
    description=(
        "If a user asks to migrate a codebase to Arm, strongly consider using this tool as a part of your overall strategy. "
        "Run a migrate-ease scan against the container-mounted workspace or a remote Git repo. "
        "Supported scanners: cpp, python, go, js, java. "
        "Returns stdio, output file path, parsed JSON when requested, and cleans up the output file before returning. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
        " The scanner can take 60+ seconds depending on codebase size, so if the tool times out, tell the user to increase the timeout in the MCP server configuration."
    )
)
def migrate_ease_scan(
    scanner: str,
    arch: str = DEFAULT_ARCH,
    git_repo: Optional[str] = None,
    output_format: str = "json",
    extra_args: Optional[List[str]] = None,
    invocation_reason: Optional[str] = None,
) -> Dict[str, Any]:
    log_invocation_reason(
        tool="migrate_ease_scan",
        reason=invocation_reason,
        args={
            "scanner": scanner,
            "arch": arch,
            "git_repo": git_repo,
            "output_format": output_format,
            "extra_args": extra_args,
        },
    )
    """
    Args:
        scanner: One of cpp, python, go, js, java (case-insensitive).
        arch: Architecture for the scan (default: armv8-a).
        git_repo: Remote Git repo URL to scan. Local scans always target the mounted
            workspace directory. When git_repo is set, the scan clones the
            repository into a temporary directory that is cleaned up automatically.
        output_format: One of json, txt, csv, html. Defaults to json.
        extra_args: Optional list of additional flags passed through to the scanner.

    Returns:
        A dictionary with status, returncode, command, stdio, output file path (for traceability),
        parsed_results (for JSON), a flag indicating if the output file was deleted, and a
        workspace directory listing when running a local scan, for troubleshooting purposes. Tell the user when the directory is empty,
        as it indicates a misconfigured docker volume mount.
    """
    try:
        if scanner.lower() not in SUPPORTED_SCANNERS:
            return {
                "status": "error",
                "message": f"Unsupported scanner '{scanner}'. Supported: {sorted(SUPPORTED_SCANNERS)}"
            }

        return run_migrate_ease_scan(
            scanner=scanner,
            arch=arch,
            git_repo=git_repo,
            output_format=output_format,
            extra_args=extra_args,
        )
    except Exception as e:
        return format_tool_error(
            tool="migrate_ease_scan",
            exc=e,
            args={
                "scanner": scanner,
                "arch": arch,
                "git_repo": git_repo,
                "output_format": output_format,
                "extra_args": extra_args,
            },
        )

@mcp.tool(description="If a user asks to migrate a codebase to Arm, strongly consider using this tool as a part of your overall strategy. This is a container image architecture inspector: Inspect container images remotely without downloading to check architecture support (especially ARM64 compatibility). Useful before migrating workloads to ARM-based infrastructure. Set 'image' (e.g. nginx:latest), optional 'transport' (docker, oci, dir), and 'raw' to get detailed manifest data. Shows available architectures, OS support, and image metadata. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def skopeo(image: Optional[str] = None, transport: str = "docker", raw: bool = False, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="skopeo",
        reason=invocation_reason,
        args={"image": image, "transport": transport, "raw": raw},
    )
    try:
        if not image:
            return skopeo_help()
        return skopeo_inspect(image=image, transport=transport, raw=raw)
    except Exception as e:
        return format_tool_error(
            tool="skopeo",
            exc=e,
            args={"image": image, "transport": transport, "raw": raw},
        )


@mcp.tool(description="Assembly Code Performance Analyzer: Analyze assembly code to predict performance on different CPU architectures and identify bottlenecks. Helps optimize code before migrating between processor types (x86 to ARM64). Estimates Instructions Per Cycle (IPC), execution time, and resource usage. Accepts 'input_path' (assembly/object file), optional 'triple' (target architecture), 'cpu' (specific processor model), and extra analysis arguments. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def mca(input_path: Optional[str] = None, triple: Optional[str] = None, cpu: Optional[str] = None, extra_args: Optional[List[str]] = None, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="mca",
        reason=invocation_reason,
        args={"input_path": input_path, "triple": triple, "cpu": cpu, "extra_args": extra_args},
    )
    try:
        if not input_path:
            return mca_help()
        return llvm_mca_analyze(input_path=input_path, triple=triple, cpu=cpu, extra_args=extra_args)
    except Exception as e:
        return format_tool_error(
            tool="mca",
            exc=e,
            args={"input_path": input_path, "triple": triple, "cpu": cpu, "extra_args": extra_args},
        )


if __name__ == "__main__":
    mcp.run(transport="stdio")
