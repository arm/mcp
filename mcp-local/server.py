from fastmcp import FastMCP
from typing import List, Dict, Any, Optional, Tuple
from usearch.index import Index
import json
import numpy as np
from sentence_transformers import SentenceTransformer
import os
import requests
import pathlib
import time
import shlex
import subprocess
from utils.atp import prepare_target, run_workload, get_results


# Find the directory this file is in
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration (use files in this script's own directory)
USEARCH_INDEX_PATH = os.path.join(BASE_DIR, "usearch_index.bin")
METADATA_PATH = os.path.join(BASE_DIR, "metadata.json")
MODEL_NAME = 'all-MiniLM-L6-v2'
DISTANCE_THRESHOLD = 1.1
K_RESULTS = 5

# Initialize the MCP server
mcp = FastMCP("arm_torq")

# Load USearch index and metadata at module load time
def load_usearch_index(index_path: str, metadata: List[Dict]):# -> Index:
    """Load USearch index from file."""
    # Get dimension from the first metadata entry's vector
    dimension = len(metadata[0]['vector'])
    
    # Create index with same parameters as used during creation
    index = Index(
        ndim=dimension,
        metric='l2sq',  # L2 squared distance
        dtype='f32',
        connectivity=16,
        expansion_add=128,
        expansion_search=64
    )
    
    # Load the saved index
    index.load(index_path)
    return index

def load_metadata(metadata_path: str) -> List[Dict]:
    """Load metadata from JSON file."""
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)
    return metadata

# Load metadata first, then index (since index needs dimension from metadata)
METADATA = load_metadata(METADATA_PATH)
#USEARCH_INDEX = load_usearch_index(USEARCH_INDEX_PATH, METADATA)
EMBEDDING_MODEL = SentenceTransformer(MODEL_NAME)

def embedding_search(query: str, k: int = K_RESULTS) -> List[Dict[str, Any]]:
    """Search the USearch index with a text query."""
    # Create query embedding
    query_embedding = EMBEDDING_MODEL.encode([query])[0]
    
    # Search in USearch index
    matches = USEARCH_INDEX.search(query_embedding, k)
    results = []
    # Robust handling of USearch Matches object, as in test_vectorstore.py
    if matches is not None:
        try:
            # USearch Matches object can be accessed with .keys and .distances properties
            if hasattr(matches, 'keys') and hasattr(matches, 'distances'):
                labels = matches.keys
                distances = matches.distances
            # Alternative attribute names
            elif hasattr(matches, 'labels') and hasattr(matches, 'distances'):
                labels = matches.labels
                distances = matches.distances
            # Try converting to numpy arrays
            else:
                labels = np.array(matches.keys) if hasattr(matches, 'keys') else None
                distances = np.array(matches.distances) if hasattr(matches, 'distances') else None
            # If tuple (labels, distances)
            if labels is None or distances is None:
                if isinstance(matches, tuple) and len(matches) == 2:
                    labels, distances = matches
                elif isinstance(matches, dict):
                    labels = matches.get('labels', matches.get('indices'))
                    distances = matches.get('distances')
            if labels is not None and distances is not None:
                labels = np.atleast_1d(labels)
                distances = np.atleast_1d(distances)
                for i, (idx, dist) in enumerate(zip(labels, distances)):
                    if idx != -1 and float(dist) < DISTANCE_THRESHOLD:
                        result = {
                            "rank": i + 1,
                            "distance": float(dist),
                            "metadata": METADATA[int(idx)]
                        }
                        results.append(result)
        except Exception as e:
            print(f"Error processing matches: {e}")
            import traceback
            traceback.print_exc()
    return results

def deduplicate_urls(embedding_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate metadata based on the 'url' field."""
    seen_urls = set()
    deduplicated_results = []
    for item in embedding_results:
        url = item["metadata"].get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduplicated_results.append(item)
    return deduplicated_results

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
    embedding_results = embedding_search(query)
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

# Target architectures to check
TARGET_ARCHITECTURES = {'amd64', 'arm64'}
TIMEOUT_SECONDS = 10

def get_auth_token(repository: str) -> str:
    """Get Docker Hub authentication token."""
    url = "https://auth.docker.io/token"
    params = {
        "service": "registry.docker.io",
        "scope": f"repository:{repository}:pull"
    }
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()['token']
    except requests.exceptions.RequestException as e:
        return f"Failed to get auth token: {e}"

def get_manifest(repository: str, tag: str, token: str) -> Dict:
    """Fetch manifest for specified image."""
    headers = {
        'Accept': 'application/vnd.docker.distribution.manifest.list.v2+json',
        'Authorization': f'Bearer {token}'
    }
    url = f"https://registry-1.docker.io/v2/{repository}/manifests/{tag}"
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to get manifest: {e}"}

def check_architectures(manifest: Dict) -> List[str]:
    """Check available architectures in the manifest."""
    if manifest.get('manifests'):
        archs = [m['platform']['architecture'] for m in manifest['manifests']]
        return archs
    else:
        return []

def parse_image_spec(image: str) -> Tuple[str, str]:
    """Parse image specification into repository and tag."""
    if ':' in image:
        repository, tag = image.split(':', 1)
    else:
        repository, tag = image, 'latest'

    if '/' not in repository:
        repository = f'library/{repository}'
    return repository.lower(), tag

@mcp.tool()
def check_image(image: str) -> dict:
    """Check Docker image architectures
    
    Args:
        image: Docker image name (format: name:tag)
        
    Returns:
        Dictionary with architecture information
    """
    repository, tag = parse_image_spec(image)
    token = get_auth_token(repository)
    
    if isinstance(token, str) and not token.startswith("Failed"):
        manifest = get_manifest(repository, tag, token)
        if isinstance(manifest, dict) and not manifest.get("error"):
            architectures = check_architectures(manifest)
            
            if not architectures:
                return {"status": "error", "message": f"No architectures found for {image}"}
            
            available_targets = TARGET_ARCHITECTURES.intersection(architectures)
            missing_targets = TARGET_ARCHITECTURES - set(architectures)
            
            if not missing_targets:
                return {
                    "status": "success",
                    "message": f"Image {image} supports all required architectures",
                    "architectures": architectures
                }
            else:
                return {
                    "status": "warning",
                    "message": f"Image {image} is missing architectures: {', '.join(missing_targets)}",
                    "available": architectures,
                    "missing": list(missing_targets)
                }
        else:
            return {"status": "error", "message": manifest.get("error", "Unknown error getting manifest")}
    else:
        return {"status": "error", "message": token}


@mcp.tool(
    description="Runs sysreport, a tool that obtains system information related to system architecture, CPU, memory, and other hardware details. Useful for diagnosing system issues or gathering information about the system's capabilities."
)
def sysreport() -> Dict[str, Any]:
    """
    Run sysreport and return the system information.
    """
    result = subprocess.run(["python3", "/app/sysreport/src/sysreport.py"], capture_output=True, text=True)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    }


MIGRATE_EASE_ROOT = "/app/migrate-ease"
SUPPORTED_SCANNERS = {"cpp", "docker", "go", "java", "python", "rust"}  # case-insensitive
DEFAULT_ARCH = "aarch64"

def _normalize_scanner(scanner: str) -> str:
    """
    Normalize scanner names. Docs sometimes show 'Python' capitalized;
    the package modules are typically lowercase. We'll prefer lowercase.
    """
    s = scanner.strip()
    if s.lower() in SUPPORTED_SCANNERS:
        return s.lower()
    return s  # let the caller see the exact name if it's custom

def _ensure_dir_empty(path: str) -> Optional[str]:
    """Ensure directory exists and is empty; return None on success or error string."""
    try:
        p = pathlib.Path(path)
        p.mkdir(parents=True, exist_ok=True)
        # If directory has content, that's an error for migrate-ease git mode
        if any(p.iterdir()):
            return f"clone_path '{path}' must be empty."
        return None
    except Exception as e:
        return f"Failed to prepare clone_path '{path}': {e}"

def _resolve_scan_path(path: Optional[str]) -> str:
    """
    Resolve a user path against the workspace mount if it's not absolute.
    Defaults to WORKSPACE_DIR when path is None.
    """
    if not path:
        return WORKSPACE_DIR
    if os.path.isabs(path):
        return path
    return os.path.join(WORKSPACE_DIR, path)

def _build_output_path(scanner: str, output_format: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = output_format.lower().lstrip(".")
    # Always put results into /tmp to avoid permission issues
    return f"/tmp/migrate_ease_{scanner}_{ts}.{suffix}"

def _run_migrate_ease(
    scanner: str,
    arch: str,
    scan_path: Optional[str],
    git_repo: Optional[str],
    clone_path: Optional[str],
    output_format: str,
    extra_args: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Execute migrate-ease scanner as 'python3 -m {scanner} ...' in MIGRATE_EASE_ROOT.
    """
    normalized_scanner = _normalize_scanner(scanner)
    fmt = output_format.lower().lstrip(".")
    if fmt not in {"json", "txt", "csv", "html"}:
        return {"status": "error", "message": f"Unsupported output format '{output_format}'."}

    out_path = _build_output_path(normalized_scanner, fmt)

    # Base command
    cmd: List[str] = ["python3", "-u", "-m", normalized_scanner, "--arch", arch, "--output", out_path]

    # Route: git repo vs local path
    if git_repo:
        if not clone_path:
            return {"status": "error", "message": "clone_path is required when git_repo is provided."}
        # migrate-ease requires empty directory for clone
        err = _ensure_dir_empty(clone_path)
        if err:
            return {"status": "error", "message": err}
        cmd.extend(["--git-repo", git_repo, clone_path])
        resolved_for_echo = clone_path
    else:
        target = _resolve_scan_path(scan_path)
        cmd.append(target)
        resolved_for_echo = target

    # Append any raw extra args last
    if extra_args:
        cmd.extend(extra_args)

    # Run
    try:
        proc = subprocess.run(
            cmd,
            cwd=MIGRATE_EASE_ROOT,  # run from repo root so module resolution works
            capture_output=True,
            text=True,
            timeout=60 * 30,  # 30 minutes max
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": "migrate-ease scan timed out.",
            "command": " ".join(shlex.quote(c) for c in cmd),
        }
    except FileNotFoundError as e:
        return {
            "status": "error",
            "message": f"Failed to execute migrate-ease: {e}",
            "hint": "Verify MIGRATE_EASE_ROOT and that Python can import the scanner module.",
        }

    result: Dict[str, Any] = {
        "status": "success" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "command": " ".join(shlex.quote(c) for c in cmd),
        "ran_from": MIGRATE_EASE_ROOT,
        "target": resolved_for_echo,
        "stdout": proc.stdout[-50_000:],  # tail to keep payload reasonable
        "stderr": proc.stderr[-50_000:],
        "output_file": out_path,
        "output_format": fmt,
    }

    # If JSON, try to parse and inline a preview
    if fmt == "json":
        try:
            with open(out_path, "r") as f:
                data = json.load(f)
            result["parsed_results"] = data
        except Exception as e:
            result["parsed_results_error"] = f"Failed to parse JSON report: {e}"

    return result

@mcp.tool(
    description=(
        "Run a migrate-ease scan on a local path (default: mounted WORKSPACE_DIR) or a remote Git repo. "
        "Wraps the CLI usage: 'python3 -m {scanner_name} --arch {arch} [--git-repo REPO CLONE_PATH]|[SCAN_PATH] "
        "--output /tmp/….{json|txt|csv|html}'. Returns stdio, output file path, and parsed JSON when requested."
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
        A dictionary with status, returncode, command, stdio, output file path, and parsed_results (for JSON).
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

    return _run_migrate_ease(
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

if __name__ == "__main__":
    mcp.run(transport="stdio")