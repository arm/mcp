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

from typing import Annotated, Any, Dict, List, Literal, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
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
from utils.error_handling import format_tool_error
from utils.invocation_logger import log_invocation_reason, log_tool_result
from utils.lean_results import lean_result
from utils.llvm_mca_tool import llvm_mca_analyze, mca_help
from utils.migrate_ease_utils import run_migrate_ease_scan
from utils.skopeo_tool import skopeo_help, skopeo_inspect

import arm_kb_search
from arm_kb_search import SearchFilters
from arm_kb_search.response import ARM_CONTENT_DISCLAIMER, UTM_SOURCE_PRESERVATION_NOTE

INSTRUCTIONS = (
    "Arm knowledge base. Cite URLs exactly as returned (keep utm_source and #fragments).\n\n"
    + UTM_SOURCE_PRESERVATION_NOTE + "\n\n" + ARM_CONTENT_DISCLAIMER
)

# Initialize the MCP server with session-wide citation and legal guidance.
mcp = FastMCP("arm-mcp", instructions=INSTRUCTIONS)


# Load USearch index and metadata at module load time
SEARCH_RESOURCES = arm_kb_search.load_search_resources(
    metadata_path=METADATA_PATH,
    usearch_index_path=USEARCH_INDEX_PATH,
    model_name=MODEL_NAME,
    model_path=MODEL_PATH,
    synonyms_path=NAME_SYNONYMS_PATH,
    utm_source="arm-mcp",
)

# error formatter now lives in utils/error_handling.py


@mcp.tool(
    description=(
        "Search Arm's knowledge base (Learning Paths, install guides, Arm docs, intrinsics, "
        "software compatibility). Returns ranked sections with URLs, titles, headings and snippets. "
        "Filters doc_type, product and platform narrow results before ranking; each accepts a string "
        "or non-empty list. Values within a field use OR; different fields use AND. "
        "Missing or explicitly cleared tags do not match. Use labels present in returned metadata; "
        "older snapshots may use legacy labels. Result fields doc_type, product and platform "
        "always return arrays; missing tags return []. Relax filters if needed evidence is missing. "
        "Start with the default chunks scope. Page scope returns all stored chunks from matched "
        "pages in order and can produce large responses; use only when requested or approved."
    )
)
def knowledge_base_search(
    query: str,
    invocation_reason: Optional[str] = None,
    filters: Optional[SearchFilters] = None,
    k: Annotated[int, Field(strict=True, ge=1, le=20,
        description="Maximum ranked result entries (not tokens or pages); integer from 1 to 20, default 5 when omitted.")] = 5,
    scope: Annotated[Literal["chunks", "page"], Field(description=(
        "chunks (default): ranked matching chunks. page: all stored chunks from every matched "
        "document. Shared documents are returned once, in stored order. k and filters "
        "select initial hits only; expansion is not limited to k chunks. "
        "Requires complete ordering metadata. Expansion can be large; use only when requested."
    ))] = "chunks",
) -> List[Dict[str, Any]]:
    call_args = {
        "query": query,
        "filters": filters.model_dump(mode="json", exclude_none=True) if filters is not None else None,
        "k": k,
        "scope": scope,
    }
    # Log the effective options and retain the ID for the paired search result.
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
        results = arm_kb_search.search(
            query, SEARCH_RESOURCES, filters=filters, k=k, scope=scope
        )
        results = [lean_result(item) for item in results]
        log_tool_result(entry_id, "knowledge_base_search", results)
        return results
    except Exception as e:
        error = format_tool_error(tool="knowledge_base_search", exc=e, args=call_args)
        log_tool_result(entry_id, "knowledge_base_search", error)
        raise ToolError(str(e)) from e


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
