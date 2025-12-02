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

import os

# Find the directory this file is in
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration: data files live under the repository 'data' directory
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
USEARCH_INDEX_PATH = os.path.join(DATA_DIR, "usearch_index.bin")
METADATA_PATH = os.path.join(DATA_DIR, "metadata.json")
MODEL_NAME = 'all-MiniLM-L6-v2'
DISTANCE_THRESHOLD = 1.1
K_RESULTS = 5

# Docker architecture checking configuration
TARGET_ARCHITECTURES = {'amd64', 'arm64'}
TIMEOUT_SECONDS = 10

# migrate-ease configuration
MIGRATE_EASE_ROOT = "/app/migrate-ease"
# Migrate-Ease scanners supported by this package. Five language wrappers are
# installed: cpp, python, go, js, java.
SUPPORTED_SCANNERS = {"cpp", "python", "go", "js", "java"}
DEFAULT_ARCH = "armv8-a"
WORKSPACE_DIR = "/workspace"
