from fastmcp import FastMCP
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
import os
from utils.atp import prepare_target, run_workload, get_results

# Import helper modules
from utils.config import METADATA_PATH, USEARCH_INDEX_PATH, MODEL_NAME, SUPPORTED_SCANNERS, DEFAULT_ARCH
from utils.search_utils import load_metadata, load_usearch_index, embedding_search, deduplicate_urls
from utils.docker_utils import check_docker_image_architectures
from utils.migrate_ease_utils import run_migrate_ease_scan
from utils.sys_utils import run_sysreport
from utils.atp import prepare_target, run_workload, get_results
from utils.skopeo_tool import skopeo_help, skopeo_inspect
from utils.llvm_mca_tool import mca_help, llvm_mca_analyze
from utils.topdown_tool import topdown_help, topdown_run
from utils.kubearchinspect_tool import kubearchinspect_help, kubearchinspect_scan
from utils.aperf_tool import aperf_help, aperf_run
from utils.bolt_tool import bolt_help, perf2bolt_help, bolt_optimize
from utils.papi_tool import papi_help, papi_list
from utils.perf_tool import perf_help, perf_record, perf_report
from utils.processwatch_tool import processwatch_help, processwatch_run
from utils.invocation_logger import log_invocation_reason

# Initialize the MCP server
mcp = FastMCP("arm_torq")

# Load USearch index and metadata at module load time
METADATA = load_metadata(METADATA_PATH)
USEARCH_INDEX = load_usearch_index(USEARCH_INDEX_PATH, METADATA)
EMBEDDING_MODEL = SentenceTransformer(MODEL_NAME)


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
    return check_docker_image_architectures(image)


@mcp.tool(
    description="Runs sysreport, a tool that obtains system information related to system architecture, CPU, memory, and other hardware details. Useful for diagnosing system issues or gathering information about the system's capabilities. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
)
def sysreport(invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="sysreport",
        reason=invocation_reason,
        args={},
    )
    """
    Run sysreport and return the system information.
    """
    return run_sysreport()


@mcp.tool(
    description=(
        "Run a migrate-ease scan on a local path (default: mounted WORKSPACE_DIR) or a remote Git repo. "
        "Uses unified wrappers installed in /usr/local/bin (migrate-ease-cpp, migrate-ease-python, migrate-ease-go, migrate-ease-js, migrate-ease-java). "
        "CLI shape: 'migrate-ease-{scanner} --march {arch} [--git-repo REPO CLONE_PATH]|[SCAN_PATH] --output /tmp/….{json|txt|csv|html}'. "
        "Returns stdio, output file path, parsed JSON when requested, and cleans up the output file before returning. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context."
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
        path: Local path to scan. If relative, resolved against WORKSPACE_DIR. Defaults to WORKSPACE_DIR when omitted.
        arch: Architecture for the scan (default: aarch64).
        git_repo: Remote Git repo URL to scan (if provided, 'clone_path' must be given and empty).
        clone_path: Empty directory where the repo will be cloned for scanning.
        output_format: One of json, txt, csv, html. Defaults to json.
        extra_args: Optional list of additional flags passed through to the scanner (e.g., ["--exclude", "tests/"]).

    Returns:
        A dictionary with status, returncode, command, stdio, output file path (for traceability),
        parsed_results (for JSON), and a flag indicating if the output file was deleted.
    """
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

@mcp.tool()
def atp_recipe_run(cmd:str, remote_ip_addr:str, remote_usr:str, recipe:str) -> str:
    """
    Run a sample workload on the given target using an Arm Total Performance recipe, 
    and interpret the results. Example user prompt: "Help me analyze my code's performance"

    This tool is run within Docker, so the ATP CLI is installed at /opt/Arm Total Performance/assets/atperf
    If you hit an error when running atperf commands, log the error to the user and back out. Do not try to run atperf on the local machine.

    Args:
        cmd: command to run on the remote machine
        remote_ip_addr: IP address of the remote machine
        remote_usr: username for SSH access to the remote machine
        recipe: the ATP recipe to run (must be one of ["cpu_hotspots", "instruction_mix", "topdown", "memory_access"], or "all" if unsure)

    Returns:
        JSON with the results of the workload. 
    """
    key_path = os.getenv("SSH_KEY_PATH")
    known_hosts_path = os.getenv("KNOWN_HOSTS_PATH")

    if not key_path or not known_hosts_path:
        raise RuntimeError("SSH_KEY_PATH and KNOWN_HOSTS_PATH environment variables must be set in the docker run command in the mcp config file to use ATP.")

    atp_cli_dir = "/opt/Arm Total Performance/assets/atperf"
    target_id = prepare_target(remote_ip_addr, remote_usr, key_path, atp_cli_dir)
    #target_id = "aws_10.252.211.230" #Hardcoding the target for now
    print(f"Prepared target: {target_id}")
    run_id = run_workload(cmd, target_id, recipe, atp_cli_dir)
    print(f"Workload run ID: {run_id}")
    results = get_results(run_id, "drilldown", atp_cli_dir)
    
    return results

@mcp.tool(description="Container Image Architecture Inspector: Inspect container images remotely without downloading to check architecture support (especially ARM64 compatibility). Useful before migrating workloads to ARM-based infrastructure. Set 'image' (e.g. nginx:latest), optional 'transport' (docker, oci, dir), and 'raw' to get detailed manifest data. Shows available architectures, OS support, and image metadata. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def skopeo(image: Optional[str] = None, transport: str = "docker", raw: bool = False, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="skopeo",
        reason=invocation_reason,
        args={"image": image, "transport": transport, "raw": raw},
    )
    if not image:
        return skopeo_help()
    return skopeo_inspect(image=image, transport=transport, raw=raw)


@mcp.tool(description="Assembly Code Performance Analyzer: Analyze assembly code to predict performance on different CPU architectures and identify bottlenecks. Helps optimize code before migrating between processor types (x86 to ARM64). Estimates Instructions Per Cycle (IPC), execution time, and resource usage. Accepts 'input_path' (assembly/object file), optional 'triple' (target architecture), 'cpu' (specific processor model), and extra analysis arguments. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def mca(input_path: Optional[str] = None, triple: Optional[str] = None, cpu: Optional[str] = None, extra_args: Optional[List[str]] = None, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="mca",
        reason=invocation_reason,
        args={"input_path": input_path, "triple": triple, "cpu": cpu, "extra_args": extra_args},
    )
    if not input_path:
        return mca_help()
    return llvm_mca_analyze(input_path=input_path, triple=triple, cpu=cpu, extra_args=extra_args)


@mcp.tool(description="CPU Performance Bottleneck Analyzer: Systematically identifies what's limiting your application performance using Intel's Top-Down methodology. Categorizes issues into CPU frontend problems (instruction fetch), backend problems (execution units), bad speculation (branch misprediction), or retirement issues. Essential for performance tuning when migrating between architectures. Requires no arguments to show help, or provide custom analysis arguments. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def topdown(args: Optional[List[str]] = None, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="topdown",
        reason=invocation_reason,
        args={"args": args},
    )
    if not args:
        return topdown_help()
    return topdown_run(args=args)


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
    if kubeconfig is None and namespace is None and not extra_args:
        return kubearchinspect_help()
    return kubearchinspect_scan(kubeconfig=kubeconfig, namespace=namespace, output_format=output_format, extra_args=extra_args)


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
    if mode == "help":
        return bolt_help()
    if mode == "perf2bolt_help":
        return perf2bolt_help()
    if mode == "optimize":
        return bolt_optimize(binary=binary, fdata=fdata, output_binary=output_binary, extra_args=extra_args)
    return {"status": "error", "message": "Unknown mode. Use: help | perf2bolt_help | optimize"}


@mcp.tool(description="Hardware Performance Counter Interface: Portable interface for accessing CPU performance metrics (cache misses, instruction counts, cycles) across different processor architectures. Essential for comparing performance between x86 and ARM systems during migration. Use 'help' to see available counters or 'list' to show supported performance events for your hardware. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def papi(mode: str = "help", invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="papi",
        reason=invocation_reason,
        args={"mode": mode},
    )
    if mode == "help":
        return papi_help()
    if mode == "list":
        return papi_list()
    return {"status": "error", "message": "Unknown mode. Use: help | list"}


@mcp.tool(description="Linux System Performance Profiler: Record and analyze CPU performance, identify hotspots, and trace system events. Critical for performance comparison when migrating applications between architectures. Use 'record' mode with 'record_cmd' (command to profile), optional 'record_seconds' duration, and 'extra_args'. Use 'report' mode with 'data_file' to analyze previously recorded data. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def perf(mode: str = "help", record_cmd: Optional[List[str]] = None, record_seconds: Optional[int] = None, data_file: str = "/tmp/perf.data", extra_args: Optional[List[str]] = None, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="perf",
        reason=invocation_reason,
        args={
            "mode": mode,
            "record_cmd": record_cmd,
            "record_seconds": record_seconds,
            "data_file": data_file,
            "extra_args": extra_args,
        },
    )
    if mode == "help":
        return perf_help()
    if mode == "record":
        return perf_record(cmd=record_cmd or ["sleep", "1"], seconds=record_seconds, data_file=data_file, extra_args=extra_args)
    if mode == "report":
        return perf_report(data_file=data_file, extra_args=extra_args)
    return {"status": "error", "message": "Unknown mode. Use: help | record | report"}


@mcp.tool(description="ARM Instruction Usage Monitor: Real-time monitoring tool that tracks which ARM-specific instruction sets (NEON, SVE, SVE2) your running processes are actually using. Valuable for validating that migrated applications are taking advantage of ARM architectural features and for identifying optimization opportunities. Provide monitoring 'args' or no arguments for usage help. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def process_watch(args: Optional[List[str]] = None, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="process_watch",
        reason=invocation_reason,
        args={"args": args},
    )
    if not args:
        return processwatch_help()
    return processwatch_run(args=args)


@mcp.tool(description="AWS Performance Data Collector: Comprehensive performance monitoring tool that collects system metrics, CPU counters, and generates comparative HTML reports. Designed for troubleshooting performance issues and comparing workload behavior across different instance types (especially when migrating to ARM-based AWS Graviton instances). Records performance data for analysis and visualization. Provide 'args' for recording/monitoring options or no arguments for help. Includes 'invocation_reason' parameter so the model can briefly explain why it is calling this tool to provide additional context.")
def aperf(args: Optional[List[str]] = None, invocation_reason: Optional[str] = None) -> Dict[str, Any]:
    log_invocation_reason(
        tool="aperf",
        reason=invocation_reason,
        args={"args": args},
    )
    if not args:
        return aperf_help()
    return aperf_run(args=args)


if __name__ == "__main__":
    mcp.run(transport="stdio")
