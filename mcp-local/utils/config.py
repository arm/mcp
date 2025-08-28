import os

# Find the directory this file is in
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration (use files in this script's own directory)
USEARCH_INDEX_PATH = os.path.join(os.path.dirname(BASE_DIR), "usearch_index.bin")
METADATA_PATH = os.path.join(os.path.dirname(BASE_DIR), "metadata.json")
MODEL_NAME = 'all-MiniLM-L6-v2'
DISTANCE_THRESHOLD = 1.1
K_RESULTS = 5

# Docker architecture checking configuration
TARGET_ARCHITECTURES = {'amd64', 'arm64'}
TIMEOUT_SECONDS = 10

# migrate-ease configuration
MIGRATE_EASE_ROOT = "/app/migrate-ease"
SUPPORTED_SCANNERS = {"cpp", "docker", "go", "java", "python", "rust"}
DEFAULT_ARCH = "armv8-a"
WORKSPACE_DIR = "/workspace"