from fastmcp import FastMCP
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer

# Import helper modules
from utils.config import METADATA_PATH, USEARCH_INDEX_PATH, MODEL_NAME, SUPPORTED_SCANNERS, DEFAULT_ARCH
from utils.search_utils import load_metadata, load_usearch_index, embedding_search, deduplicate_urls
from utils.docker_utils import check_docker_image_architectures
from utils.migrate_ease_utils import run_migrate_ease_scan
from utils.sys_utils import run_sysreport

# Initialize the MCP server
mcp = FastMCP("arm_torq")

# Load USearch index and metadata at module load time
METADATA = load_metadata(METADATA_PATH)
USEARCH_INDEX = load_usearch_index(USEARCH_INDEX_PATH, METADATA)
EMBEDDING_MODEL = SentenceTransformer(MODEL_NAME)


@mcp.tool(
    description="Searches an Arm knowledge base of learning resources, Arm intrinsics, and software version compatibility using semantic similarity. Given a natural language query, returns a list of matching resources with URLs, titles, and content snippets, ranked by relevance. Useful for finding documentation, tutorials, or version compatibility for Arm."
)
def knowledge_base_search(query: str) -> List[Dict[str, Any]]:
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


@mcp.tool()
def check_image(image: str) -> dict:
    """Check Docker image architectures
    
    Args:
        image: Docker image name (format: name:tag)
        
    Returns:
        Dictionary with architecture information
    """
    return check_docker_image_architectures(image)


@mcp.tool(
    description="Runs sysreport, a tool that obtains system information related to system architecture, CPU, memory, and other hardware details. Useful for diagnosing system issues or gathering information about the system's capabilities."
)
def sysreport() -> Dict[str, Any]:
    """
    Run sysreport and return the system information.
    """
    return run_sysreport()


@mcp.tool(
    description=(
        "Run a migrate-ease scan on a local path (default: mounted WORKSPACE_DIR) or a remote Git repo. "
        "Wraps the CLI usage: 'python3 -m {scanner_name} --march {arch} [--git-repo REPO CLONE_PATH]|[SCAN_PATH] "
        "--output /tmp/….{json|txt|csv|html}'. Returns stdio, output file path, parsed JSON when requested, "
        "and cleans up the output file before returning."
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
) -> Dict[str, Any]:
    """
    Args:
        scanner: One of cpp, docker, go, java, python, rust (case-insensitive).
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


if __name__ == "__main__":
    mcp.run()