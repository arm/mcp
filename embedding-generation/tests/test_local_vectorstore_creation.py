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

import pytest

from local_vectorstore_creation import load_local_yaml_files


def test_load_local_yaml_files_requires_intrinsic_chunks(tmp_path, monkeypatch):
    intrinsic_dir = tmp_path / "intrinsic_chunks"
    intrinsic_dir.mkdir()
    monkeypatch.setenv("INTRINSIC_CHUNKS_DIR", str(intrinsic_dir))
    monkeypatch.setenv("YAML_DATA_DIR", str(tmp_path / "yaml_data"))

    with pytest.raises(FileNotFoundError, match="No intrinsic chunk YAML files found"):
        load_local_yaml_files()
