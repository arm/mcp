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


def bolt_help() -> Dict[str, Any]:
    return run_command(["llvm-bolt", "--help"])


def bolt_optimize(binary: Optional[str], fdata: Optional[str], output_binary: Optional[str], extra_args: Optional[List[str]]) -> Dict[str, Any]:
    if not binary or not fdata or not output_binary:
        return {"status": "error", "message": "binary, fdata, and output_binary are required for optimize mode"}
    cmd = ["llvm-bolt", binary, "-o", output_binary, f"-data={fdata}"]
    if extra_args:
        cmd += extra_args
    return run_command(cmd)

