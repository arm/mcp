import yaml
import faiss
import numpy as np
import math
from typing import List, Dict, Tuple
import json
import os
import glob
import sys
import datetime
from sentence_transformers import SentenceTransformer  # <--- NEW

def load_local_yaml_files() -> List[Dict]:
    """Load locally stored YAML files and return their contents as a list of dictionaries."""
    print("Loading local YAML files")
    yaml_contents = []

    yaml_files = glob.glob("chunk_*.yaml")
    total_files = len(yaml_files)
    print(f"Found {total_files} YAML files")

    for i, file_path in enumerate(yaml_files, 1):
        print(f"Loading file {i}/{total_files}: {file_path}")
        # Extract chunk number from filename
        chunk_uuid = file_path.replace('chunk_', '').replace('.yaml', '')
        
        with open(file_path, 'r') as f:
            yaml_content = yaml.safe_load(f)
            # Add chunk number to the yaml content
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

def create_faiss_index(embeddings: np.ndarray, metadata: List[Dict]) -> Tuple[faiss.IndexFlatL2, List[Dict]]:
    """Create a FAISS index with the given embeddings and metadata."""
    print("Creating FAISS index")
    print(f"Embeddings shape: {embeddings.shape}")
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)

    # Store the vector used for each metadata record (for debugging)
    for item, vec in zip(metadata, embeddings):
        item['vector'] = vec.tolist()  # Convert numpy array to list for JSON serialization
    
    print(f"Added {index.ntotal} vectors to the index")
    return index, metadata

def main():
    print("Starting the FAISS datastore creation process")

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

    # Create FAISS index
    print("Creating FAISS index")
    index, metadata = create_faiss_index(embeddings, metadata)

    # Save the FAISS index
    index_filename = 'faiss_index.bin'
    print(f"Saving FAISS index to {index_filename}")
    faiss.write_index(index, index_filename)

    # Save metadata
    metadata_filename = 'metadata.json'
    print(f"Saving metadata to {metadata_filename}")
    with open(metadata_filename, 'w') as f:
        json.dump(metadata, f, indent=2)  # Added indent for better readability

    print("FAISS index and metadata have been created and saved.")
    print(f"Total documents processed: {len(contents)}")
    print(f"FAISS index saved to: {os.path.abspath(index_filename)}")
    print(f"Metadata saved to: {os.path.abspath(metadata_filename)}")

if __name__ == "__main__":
    main()