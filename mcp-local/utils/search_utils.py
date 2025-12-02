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

from typing import List, Dict, Any
from usearch.index import Index
import json
import numpy as np
from sentence_transformers import SentenceTransformer
from .config import USEARCH_INDEX_PATH, METADATA_PATH, MODEL_NAME, DISTANCE_THRESHOLD, K_RESULTS
import os


def load_usearch_index(index_path: str, metadata: List[Dict]) -> Index:
    """Load USearch index from file."""
    if not os.path.exists(index_path):
        print(f"Error: USearch index file '{index_path}' does not exist.")
        return None
    if not metadata:
        print("Error: Knowledge base metadata is missing or invalid.")
        return None
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
    if not os.path.exists(metadata_path):
        print(f"Error: Metadata file '{metadata_path}' does not exist.")
        return []
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)
    return metadata


def embedding_search(
    query: str, 
    usearch_index: Index, 
    metadata: List[Dict], 
    embedding_model: SentenceTransformer,
    k: int = K_RESULTS
) -> List[Dict[str, Any]]:
    """Search the USearch index with a text query."""
    # Create query embedding
    query_embedding = embedding_model.encode([query])[0]
    
    # Search in USearch index
    matches = usearch_index.search(query_embedding, k)
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
                            "metadata": metadata[int(idx)]
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