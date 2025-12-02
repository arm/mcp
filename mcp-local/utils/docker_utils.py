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

from typing import Dict, List, Tuple
import requests
from .config import TARGET_ARCHITECTURES, TIMEOUT_SECONDS


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


def check_docker_image_architectures(image: str) -> dict:
    """Check Docker image architectures and return status information."""
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