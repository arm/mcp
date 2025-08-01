from fastmcp import FastMCP
from typing import List, Dict, Any
from usearch.index import Index
import json
import numpy as np
from sentence_transformers import SentenceTransformer
import os
import requests
from typing import Tuple
import subprocess

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
def load_usearch_index(index_path: str, metadata: List[Dict]) -> Index:
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
USEARCH_INDEX = load_usearch_index(USEARCH_INDEX_PATH, METADATA)
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
    if result.returncode == 0:
        return json.loads(result.stdout)
    else:
        return {"error": result.stderr}


if __name__ == "__main__":
    mcp.run()