from fastmcp import FastMCP
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
from utils.config import METADATA_PATH, USEARCH_INDEX_PATH, MODEL_NAME, SUPPORTED_SCANNERS, DEFAULT_ARCH
from utils.search_utils import load_metadata, load_usearch_index, embedding_search, deduplicate_urls
from utils.docker_utils import check_docker_image_architectures
from utils.migrate_ease_utils import run_migrate_ease_scan
from utils.skopeo_tool import skopeo_help, skopeo_inspect
from utils.llvm_mca_tool import mca_help, llvm_mca_analyze
from utils.kubearchinspect_tool import kubearchinspect_help, kubearchinspect_scan
from utils.bolt_tool import bolt_help, perf2bolt_help, bolt_optimize
from utils.invocation_logger import log_invocation_reason
from utils.error_handling import format_tool_error

# Initialize the MCP server
mcp = FastMCP("arm_torq")

# Load USearch index and metadata at module load time
METADATA = load_metadata(METADATA_PATH)
USEARCH_INDEX = load_usearch_index(USEARCH_INDEX_PATH, METADATA)
EMBEDDING_MODEL = SentenceTransformer(MODEL_NAME)


# error formatter now lives in utils/error_handling.py


@mcp.tool(
    description="Searches an Arm knowledge base of learning resources, Arm intrinsics, and software version compatibility using semantic similarity. Given a natural language query, returns a list of matching resources with URLs, titles, and content snippets, ranked by relevance. Useful for finding documentation, tutorials, or version compatibility for Arm. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
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
        embedding_results = embedding_search(query, USEARCH_INDEX, METADATA, EMBEDDING_MODEL)
        deduped = deduplicate_urls(embedding_results)
        # Only return the relevant fields
        formatted = [
            {
                "url": item["metadata"].get("url"),
                "snippet": item["metadata"].get("original_text", item["metadata"].get("content", "")),
                "title": item["metadata"].get("title", ""),
                "distance": item.get("distance")
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
        "Run a migrate-ease scan on a path inside the container (default: /workspace) or a remote Git repo. "
        "IMPORTANT: 'path' is a container filesystem path, not a host path. In typical use, a host directory is bind-mounted to /workspace inside the container, and 'path' should point to that container path (e.g., /workspace/my-project). This is done at the MCP server configuration level, so please ensure your host directory is correctly mounted to the container before using local scans. "
        "Supported scanners: cpp, python, go, js, java. "
        "Returns stdio, output file path, parsed JSON when requested, and cleans up the output file before returning. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
        " The scanner can take 60+ seconds depending on codebase size, so if the tool times out, consider increasing the timeout in the MCP server configuration."
    )
)
def migrate_ease_scan(
    scanner: str,
    path: Optional[str] = None,
    arch: str = DEFAULT_ARCH,
    git_repo: Optional[str] = None,
    clone_path: Optional[str] = None,
    output_format: str = "json",
    extra_args: Optional[List[str]] = None,
    invocation_reason: Optional[str] = None,
) -> Dict[str, Any]:
    log_invocation_reason(
        tool="migrate_ease_scan",
        reason=invocation_reason,
        args={
            "scanner": scanner,
            "path": path,
            "arch": arch,
            "git_repo": git_repo,
            "clone_path": clone_path,
            "output_format": output_format,
            "extra_args": extra_args,
        },
    )
    """
    Args:
        scanner: One of cpp, python, go, js, java (case-insensitive).
        path: Container path to scan (inside the container). Typically a directory under /workspace that is bind-mounted from the host. If relative, resolved against WORKSPACE_DIR (/workspace). Defaults to WORKSPACE_DIR when omitted.
        arch: Architecture for the scan (default: aarch64).
        git_repo: Remote Git repo URL to scan (if provided, 'clone_path' must be given and empty).
        clone_path: Empty directory where the repo will be cloned for scanning.
        output_format: One of json, txt, csv, html. Defaults to json.
        extra_args: Optional list of additional flags passed through to the scanner (e.g., ["--exclude", "tests/"]).

    Returns:
        A dictionary with status, returncode, command, stdio, output file path (for traceability),
        parsed_results (for JSON), and a flag indicating if the output file was deleted.
    """
    try:
        # Validate scanner early
        if scanner.lower() not in SUPPORTED_SCANNERS:
            return {
                "status": "error",
                "message": f"Unsupported scanner '{scanner}'. Supported: {sorted(SUPPORTED_SCANNERS)}"
            }

        if git_repo and path:
            return {
                "status": "error",
                "message": "Provide either 'path' for local scans OR 'git_repo' + 'clone_path' for repo scans, not both."
            }

        return run_migrate_ease_scan(
            scanner=scanner,
            arch=arch,
            scan_path=path,
            git_repo=git_repo,
            clone_path=clone_path,
            output_format=output_format,
            extra_args=extra_args,
        )
    except Exception as e:
        return format_tool_error(
            tool="migrate_ease_scan",
            exc=e,
            args={
                "scanner": scanner,
                "path": path,
                "arch": arch,
                "git_repo": git_repo,
                "clone_path": clone_path,
                "output_format": output_format,
                "extra_args": extra_args,
            },
        )


@mcp.tool(description="Container Image Architecture Inspector: Inspect container images remotely without downloading to check architecture support (especially ARM64 compatibility). Useful before migrating workloads to ARM-based infrastructure. Set 'image' (e.g. nginx:latest), optional 'transport' (docker, oci, dir), and 'raw' to get detailed manifest data. Shows available architectures, OS support, and image metadata. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
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


@mcp.tool(description="Kubernetes ARM64 Readiness Scanner: Scans your Kubernetes cluster to identify which container images support ARM64 architecture. Essential first step before migrating Kubernetes workloads to ARM-based nodes (like AWS Graviton). Reports incompatible images and suggests alternatives. Requires kubectl access to target cluster. Supports 'kubeconfig' path, 'namespace' filtering, 'output_format' (json/html), and passthrough 'extra_args'. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def kubearchinspect(kubeconfig: Optional[str] = None, namespace: Optional[str] = None, output_format: str = "json", extra_args: Optional[List[str]] = None, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="kubearchinspect",
        reason=invocation_reason,
        args={
            "kubeconfig": kubeconfig,
            "namespace": namespace,
            "output_format": output_format,
            "extra_args": extra_args,
        },
    )
    try:
        if kubeconfig is None and namespace is None and not extra_args:
            return kubearchinspect_help()
        return kubearchinspect_scan(kubeconfig=kubeconfig, namespace=namespace, output_format=output_format, extra_args=extra_args)
    except Exception as e:
        return format_tool_error(
            tool="kubearchinspect",
            exc=e,
            args={
                "kubeconfig": kubeconfig,
                "namespace": namespace,
                "output_format": output_format,
                "extra_args": extra_args,
            },
        )


@mcp.tool(description="Binary Performance Optimizer: Post-compilation optimizer that reorganizes compiled programs for better CPU cache utilization and performance. Can improve application speed by 2-20% using execution profiles. Particularly valuable when optimizing for different CPU architectures. Use 'mode' (help/optimize), specify 'binary' and 'fdata' (profile data) for optimization, 'output_binary' for result, and 'extra_args' for advanced options. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def bolt(mode: str = "help", binary: Optional[str] = None, fdata: Optional[str] = None, output_binary: Optional[str] = None, extra_args: Optional[List[str]] = None, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="bolt",
        reason=invocation_reason,
        args={
            "mode": mode,
            "binary": binary,
            "fdata": fdata,
            "output_binary": output_binary,
            "extra_args": extra_args,
        },
    )
    try:
        if mode == "help":
            return bolt_help()
        if mode == "perf2bolt_help":
            return perf2bolt_help()
        if mode == "optimize":
            return bolt_optimize(binary=binary, fdata=fdata, output_binary=output_binary, extra_args=extra_args)
        return {"status": "error", "message": "Unknown mode. Use: help | perf2bolt_help | optimize"}
    except Exception as e:
        return format_tool_error(
            tool="bolt",
            exc=e,
            args={
                "mode": mode,
                "binary": binary,
                "fdata": fdata,
                "output_binary": output_binary,
                "extra_args": extra_args,
            },
        )


if __name__ == "__main__":
    mcp.run(transport="stdio")
