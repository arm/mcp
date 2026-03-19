# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
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

"""Pytest configuration for embedding-generation tests.

This module sets up the Python path and provides the generate_chunks module
as a fixture (required because the filename has a hyphen).
"""

import importlib.util
import os
import sys

import pytest

# Add parent directory to path for imports
_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


def _load_generate_chunks():
    """Load generate-chunks.py module (hyphen in filename requires importlib)."""
    spec = importlib.util.spec_from_file_location(
        "generate_chunks",
        os.path.join(_PARENT_DIR, "generate-chunks.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Load module once at conftest import time
_generate_chunks_module = _load_generate_chunks()


@pytest.fixture
def gc():
    """Provide the generate_chunks module with reset global state."""
    # Reset global state before each test
    _generate_chunks_module.known_source_urls = set()
    _generate_chunks_module.all_sources = []
    yield _generate_chunks_module
    # Clean up after test
    _generate_chunks_module.known_source_urls = set()
    _generate_chunks_module.all_sources = []
