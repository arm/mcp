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
import os
from sentence_transformers import SentenceTransformer
from utils.config import METADATA_PATH, USEARCH_INDEX_PATH, MODEL_NAME, SUPPORTED_SCANNERS, DEFAULT_ARCH
from utils.search_utils import build_bm25_index, deduplicate_urls, hybrid_search, load_metadata, load_usearch_index
from utils.docker_utils import check_docker_image_architectures
from utils.apx import prepare_target, run_workload, get_results, resolve_apx_ssh_mount_env
from utils.migrate_ease_utils import run_migrate_ease_scan
from utils.skopeo_tool import skopeo_help, skopeo_inspect
from utils.llvm_mca_tool import mca_help, llvm_mca_analyze
from utils.invocation_logger import log_invocation_reason
from utils.error_handling import format_tool_error

# Initialize the MCP server
mcp = FastMCP("arm-mcp")


def sentence_transformer_cache_folder() -> str | None:
    return os.getenv("SENTENCE_TRANSFORMERS_HOME") or None


def load_embedding_model() -> SentenceTransformer:
    try:
        return SentenceTransformer(
            MODEL_NAME,
            cache_folder=sentence_transformer_cache_folder(),
            local_files_only=True,
        )
    except Exception as exc:
        print(f"Local cache miss for embedding model '{MODEL_NAME}', retrying with network access: {exc}")
        return SentenceTransformer(
            MODEL_NAME,
            cache_folder=sentence_transformer_cache_folder(),
            local_files_only=False,
        )


# Load USearch index and metadata at module load time
METADATA = load_metadata(METADATA_PATH)
EMBEDDING_MODEL = load_embedding_model()
USEARCH_INDEX = load_usearch_index(
    USEARCH_INDEX_PATH,
    EMBEDDING_MODEL.get_sentence_embedding_dimension(),
)
BM25_INDEX = build_bm25_index(METADATA)


# error formatter now lives in utils/error_handling.py


@mcp.tool(
    description="IMPORTANT: IF A USER ASKS TO MIGRATE A CODEBASE TO ARM, STRONGLY CONSIDER USING THIS TOOL AS A PART OF YOUR STRATEGY. This tool searches an Arm knowledge base of learning resources, Arm intrinsics, and software version compatibility using semantic similarity. Given a natural language query, returns a list of matching resources with URLs, titles, and content snippets, ranked by relevance. Useful for finding documentation, tutorials, or version compatibility for Arm. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
)
def knowledge_base_search(query: str, invocation_reason: Optional[str] = None) -> List[Dict[str, Any]]:
    # Log invocation reason if provided
    log_invocation_reason(
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
        search_results = hybrid_search(query, USEARCH_INDEX, METADATA, EMBEDDING_MODEL, BM25_INDEX)
        deduped = deduplicate_urls(search_results)
        # Only return the relevant fields
        formatted = [
            {
                "url": item["metadata"].get("url"),
                "snippet": item["metadata"].get("original_text", item["metadata"].get("content", "")),
                "title": item["metadata"].get("title", ""),
                "heading": item["metadata"].get("heading", ""),
                "doc_type": item["metadata"].get("doc_type", ""),
                "product": item["metadata"].get("product", ""),
                "distance": item.get("distance"),
                "score": item.get("rerank_score", item.get("rrf_score")),
            }
            for item in deduped
        ]
        return formatted
    except Exception as e:
        return format_tool_error(
            tool="knowledge_base_search",
            exc=e,
            args={"query": query},
        )


@mcp.tool(
    description="Check Docker image architectures. Provide an image in 'name:tag' format and get a report of supported architectures. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
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
    description="Provides instructions for installing and using sysreport, a tool that obtains system information related to system architecture, CPU, memory, and other hardware details. Since this runs in a container, the tool provides installation instructions for running sysreport directly on the host system."
)
def sysreport_instructions(invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="sysreport_instructions",
        reason=invocation_reason,
        args={},
    )
    try:
        instructions = """
# SysReport Installation and Usage

## Installation
```bash
git clone https://github.com/ArmDeveloperEcosystem/sysreport.git
cd sysreport
```

## Usage
```bash
python3 sysreport.py
```

## What SysReport Does
- Gathers comprehensive system information including architecture, CPU, memory, and hardware details
- Useful for diagnosing system issues or understanding system capabilities
- Provides detailed hardware and software configuration data

## Note
Run these commands directly on your host system (not in a container) to get accurate system information.
"""
        return {
            "instructions": instructions,
            "repository": "https://github.com/ArmDeveloperEcosystem/sysreport.git",
            "usage_command": "python3 sysreport.py",
            "note": "This tool must be run on the host system to provide accurate system information."
        }
    except Exception as e:
        return format_tool_error(
            tool="sysreport_instructions",
            exc=e,
            args={},
        )


@mcp.tool(
    description=(
        "IMPORTANT: IF A USER ASKS TO MIGRATE A CODEBASE TO ARM, STRONGLY CONSIDER USING THIS TOOL AS A PART OF YOUR OVERALL STRATEGY. "
        "Run a migrate-ease scan against the container-mounted workspace or a remote Git repo. "
        "Supported scanners: cpp, python, go, js, java. "
        "Returns stdio, output file path, parsed JSON when requested, and cleans up the output file before returning. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
        " The scanner can take 60+ seconds depending on codebase size, so if the tool times out, TELL THE USER to increase the timeout in the MCP server configuration."
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

@mcp.tool()
def apx_recipe_run(cmd:str, remote_ip_addr:str, remote_usr:str, recipe:str="code_hotspots", invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Run a sample workload on the given target using a Performix recipe, 
    and interpret the results. Some example user requests: 
        - 'Help my analyze my code's performance.'
        - 'Find the code hotspots in my application.'

    If you do not know which recipe to use, use 'code_hotspots'.

    Ask the user if they want to run on localhost or a remote machine. If remote, then ask for the IP address of the remote machine.

    This tool is run within Docker. Do not try to run apx on the local machine.

    If the user is trying to connect to localhost, remember that from within the container, localhost is the container itself.
    Instead, use the host's IP address, which is usually 172.17.0.1.

    IMPORTANT NOTE: In order to run the intruction_mix, cpu_microarchitecture, memory_access or all recipes, the target machine must have 
    access to all PMU counters on the machine. If not, then only code_hotspots can be run.

    Args:
        cmd: absolute path to the executable or the command to run on the remote machine (with absolute paths)
        remote_ip_addr: IP address of the remote machine
        remote_usr: username for SSH access to the remote machine
        recipe: the APX recipe to run (must be one of ["code_hotspots", "instruction_mix", "cpu_microarchitecture", "memory_access"], or "all" if unsure)

    Returns:
        JSON with the results of the workload. 
    """
    log_invocation_reason(
        tool="apx_recipe_run",
        reason=invocation_reason,
        args={
            "cmd": cmd,
            "remote_ip_addr": remote_ip_addr,
            "remote_usr": remote_usr,
            "recipe": recipe,
        },
    )
    apx_dir = os.environ.get("APX_HOME", "/opt/apx")
    ssh_mount_env = resolve_apx_ssh_mount_env()
    key_path = ssh_mount_env["key_path"]
    known_hosts_path = ssh_mount_env["known_hosts_path"]

    if not key_path or not known_hosts_path:
        return {
            "status": "error",
            "recipe": recipe,
            "stage": "config_validation",
            "message": "Missing SSH configuration for APX target access.",
            "suggestion": "Mount both the SSH private key and known_hosts file into /run/keys, then retry.",
            "details": (
                "APX looks for SSH_KEY_PATH and KNOWN_HOSTS_PATH first, then auto-discovers mounted files "
                f"under /run/keys from /proc/self/mounts. Discovered mounts: {ssh_mount_env['mount_targets']}"
            ),
        }

    target_add_res = prepare_target(remote_ip_addr, remote_usr, key_path, apx_dir)
    if "error" in target_add_res:
        return {
            "status": "error",
            "recipe": recipe,
            "stage": "target_prepare",
            "message": target_add_res.get("error", "Failed to prepare target."),
            "suggestion": (
                "Verify SSH reachability, username, key permissions, and host details. "
                "If using localhost from container, try host IP 172.17.0.1."
            ),
            "details": target_add_res.get("details", ""),
            "raw_output": target_add_res.get("raw_output", ""),
        }
    
    run_res = run_workload(cmd, target_add_res["target_id"], recipe, apx_dir)
    if "error" in run_res:
        return {
            "status": "error",
            "recipe": recipe,
            "stage": "workload_run",
            "message": run_res.get("error", "Failed to run APX workload."),
            "suggestion": (
                "Confirm the workload command is valid on the target machine and that the selected recipe "
                "is supported for your PMU permissions."
            ),
            "details": run_res.get("details", ""),
        }
    
    results = get_results(run_res["run_id"], recipe, apx_dir)
    
    return results

@mcp.tool(description="IMPORTANT: IF A USER ASKS TO MIGRATE A CODEBASE TO ARM, STRONGLY CONSIDER USING THIS TOOL AS A PART OF YOUR OVERALL STRATEGY. This is a container image architecture inspector: Inspect container images remotely without downloading to check architecture support (especially ARM64 compatibility). Useful before migrating workloads to ARM-based infrastructure. Set 'image' (e.g. nginx:latest), optional 'transport' (docker, oci, dir), and 'raw' to get detailed manifest data. Shows available architectures, OS support, and image metadata. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
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
