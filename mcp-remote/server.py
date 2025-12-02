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
from typing import List, Dict, Any
import faiss
import json
import numpy as np
from sentence_transformers import SentenceTransformer
import os
from fastapi import APIRouter
import requests
from typing import Tuple

# Find the directory this file is in
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration (use files in this script's own directory)
FAISS_INDEX_PATH = os.path.join(BASE_DIR, "faiss_index.bin")
FAISS_METADATA_PATH = os.path.join(BASE_DIR, "metadata.json")
MODEL_NAME = 'all-MiniLM-L6-v2'
DISTANCE_THRESHOLD = 1.1
K_RESULTS = 5

# Initialize the MCP server
mcp = FastMCP("arm_server")

#router = APIRouter()
#
#@router.get("/health", tags=["internal"])
#def health():
#    return {"status": "ok"}
#
#mcp.app.include_router(router)

# Load FAISS index and metadata at module load time
def load_faiss_index(index_path: str):
    index = faiss.read_index(index_path)
    return index

def load_metadata(metadata_path: str):
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)
    return metadata

FAISS_INDEX = load_faiss_index(FAISS_INDEX_PATH)
FAISS_METADATA = load_metadata(FAISS_METADATA_PATH)
EMBEDDING_MODEL = SentenceTransformer(MODEL_NAME)

def embedding_search(query: str, k: int = K_RESULTS) -> List[Dict[str, Any]]:
    """Search the FAISS index with a text query."""
    query_embedding = EMBEDDING_MODEL.encode([query])[0]
    distances, indices = FAISS_INDEX.search(query_embedding[None], k)
    results = []
    for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
        if idx != -1 and float(dist) < DISTANCE_THRESHOLD:
            result = {
                "rank": i + 1,
                "distance": float(dist),
                "metadata": FAISS_METADATA[idx]
            }
            results.append(result)
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

if __name__ == "__main__":
    # Bind to all interfaces so the ALB’s target group can reach the app
    mcp.run(host="0.0.0.0", port=5000)