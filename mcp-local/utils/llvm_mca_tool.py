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

from typing import Dict, Any, List, Optional
from .cli_utils import run_command


def mca_help() -> Dict[str, Any]:
    return run_command(["llvm-mca", "--help"])


def llvm_mca_analyze(input_path: str, triple: Optional[str], cpu: Optional[str], extra_args: Optional[List[str]]) -> Dict[str, Any]:
    cmd = ["llvm-mca", input_path]
    if triple:
        cmd += ["--triple", triple]
    if cpu:
        cmd += ["--mcpu", cpu]
    if extra_args:
        cmd += extra_args
    return run_command(cmd)

