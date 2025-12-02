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

import yaml
import numpy as np
import math
from typing import List, Dict, Tuple
import json
import os
import glob
import sys
import datetime
from sentence_transformers import SentenceTransformer
from usearch.index import Index

def load_local_yaml_files() -> List[Dict]:
    """Load locally stored YAML files and return their contents as a list of dictionaries."""
    print("Loading local YAML files")
    yaml_contents = []

    intrinsic_files = glob.glob(os.path.join("intrinsic_chunks", "*.yaml"))
    print(f"Found {len(intrinsic_files)} YAML files in intrinsic_chunks directory")

    yaml_data_files = glob.glob(os.path.join("yaml_data", "*.yaml"))
    print(f"Found {len(yaml_data_files)} YAML files in yaml_data directory")

    # Combine all files
    all_files = intrinsic_files + yaml_data_files
    total_files = len(all_files)
    print(f"Total files to process: {total_files}")

    for i, file_path in enumerate(all_files, 1):
        print(f"Loading file {i}/{total_files}: {file_path}")

        # Extract chunk identifier based on file location
        if file_path.startswith("intrinsic_chunks"):
            chunk_uuid = f"intrinsic_{os.path.basename(file_path).replace('.yaml', '')}"
        elif file_path.startswith("yaml_data"):
            chunk_uuid = f"yaml_data_{os.path.basename(file_path).replace('.yaml', '')}"
        else:
            chunk_uuid = file_path.replace('chunk_', '').replace('.yaml', '')

        try:
            with open(file_path, 'r') as f:
                yaml_content = yaml.safe_load(f)
                yaml_content['chunk_uuid'] = chunk_uuid
                yaml_contents.append(yaml_content)
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            continue

    print(f"Successfully loaded {len(yaml_contents)} YAML files")
    return yaml_contents

def create_embeddings(contents: List[str], model_name: str = 'all-MiniLM-L6-v2') -> np.ndarray:
    """Create embeddings for the given contents using SentenceTransformers."""
    print(f"Creating embeddings using model: {model_name}")
    model = SentenceTransformer(model_name)
    embeddings = model.encode(contents, show_progress_bar=True, convert_to_numpy=True)
    print(f"Created embeddings with shape: {embeddings.shape}")
    return embeddings

def create_usearch_index(embeddings: np.ndarray, metadata: List[Dict]) -> Tuple[Index, List[Dict]]:
    """Create a USearch index with the given embeddings and metadata."""
    print("Creating USearch index")
    print(f"Embeddings shape: {embeddings.shape}")
    
    dimension = embeddings.shape[1]
    num_vectors = embeddings.shape[0]
    
    # Create USearch index
    index = Index(
        ndim=dimension,
        metric='l2sq',
        dtype='f32',
        connectivity=16,
        expansion_add=128,
        expansion_search=64
    )
    
    # Add vectors to the index
    print(f"Adding {num_vectors} vectors to the index")
    for i, embedding in enumerate(embeddings):
        index.add(i, embedding)

    for item, vec in zip(metadata, embeddings):
        item['vector'] = vec.tolist()
    
    print(f"Added {len(index)} vectors to the index")
    return index, metadata

def main():
    print("Starting the USearch datastore creation process")

    # Load local YAML files
    yaml_contents = load_local_yaml_files()

    # Extract content, uuid, url, and original text from YAML files
    print("Extracting content and metadata from YAML files")
    contents = []
    metadata = []
    for i, yaml_content in enumerate(yaml_contents, 1):
        print(f"Processing YAML content {i}/{len(yaml_contents)}")
        contents.append(yaml_content['content'])
        metadata.append({
            'uuid': yaml_content['uuid'],
            'url': yaml_content['url'],
            'original_text': yaml_content['content'],
            'title': yaml_content['title'],
            'keywords': yaml_content['keywords'],
            'chunk_uuid': yaml_content['chunk_uuid']
        })

    # Create embeddings
    embeddings = create_embeddings(contents)

    print("Saving embeddings to file")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"embeddings_{timestamp}.txt"
    np.savetxt(filename, embeddings)

    # Create USearch index
    print("Creating USearch index")
    index, metadata = create_usearch_index(embeddings, metadata)

    # Save the USearch index
    index_filename = 'usearch_index.bin'
    print(f"Saving USearch index to {index_filename}")
    index.save(index_filename)

    # Save metadata
    metadata_filename = 'metadata.json'
    print(f"Saving metadata to {metadata_filename}")
    with open(metadata_filename, 'w') as f:
        json.dump(metadata, f, indent=2)

    print("USearch index and metadata have been created and saved.")
    print(f"Total documents processed: {len(contents)}")
    print(f"USearch index saved to: {os.path.abspath(index_filename)}")
    print(f"Metadata saved to: {os.path.abspath(metadata_filename)}")

if __name__ == "__main__":
    main()