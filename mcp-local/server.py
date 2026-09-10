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
from typing import List, Dict, Any, Optional
import arm_kb_search
from utils.config import (
    DEFAULT_ARCH,
    METADATA_PATH,
    MODEL_NAME,
    MODEL_PATH,
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
