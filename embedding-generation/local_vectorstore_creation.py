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

    yaml_files = glob.glob("chunk_*.yaml")
    total_files = len(yaml_files)
    print(f"Found {total_files} YAML files")

    for i, file_path in enumerate(yaml_files, 1):
        print(f"Loading file {i}/{total_files}: {file_path}")
        chunk_uuid = file_path.replace('chunk_', '').replace('.yaml', '')
        
        with open(file_path, 'r') as f:
            yaml_content = yaml.safe_load(f)
            yaml_content['chunk_uuid'] = chunk_uuid
            yaml_contents.append(yaml_content)

    print(f"Loaded {len(yaml_contents)} YAML files")
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

    # Initialize USearch index (using cosine similarity by default)
    index = Index(dimension=dimension, metric='cos', dtype='f32')

    # USearch needs integer keys for vectors. We'll use their index in the metadata list.
    for idx, (item, vec) in enumerate(zip(metadata, embeddings)):
        # Index add: key must be int, vector must be numpy array
        index.add(idx, vec.astype(np.float32))
        item['vector'] = vec.tolist()  # Optionally save for debugging/inspection

    print(f"Added {len(embeddings)} vectors to the index")
    return index, metadata

def main():
    print("Starting the USearch datastore creation process")

    # Load local YAML files
    yaml_contents = load_local_yaml_files()

    # Extract content and metadata from YAML files
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
        json.dump(metadata, f, indent=2)  # Added indent for better readability

    print("USearch index and metadata have been created and saved.")
    print(f"Total documents processed: {len(contents)}")
    print(f"USearch index saved to: {os.path.abspath(index_filename)}")
    print(f"Metadata saved to: {os.path.abspath(metadata_filename)}")

if __name__ == "__main__":
    main()