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

from typing import Dict, Any
from .cli_utils import run_command


def skopeo_help() -> Dict[str, Any]:
    return run_command(["skopeo", "--help"])


def skopeo_inspect(image: str, transport: str = "docker", raw: bool = False) -> Dict[str, Any]:
    cmd = ["skopeo", "inspect"]
    if raw:
        cmd.append("--raw")
    cmd.append(f"{transport}://{image}")
    return run_command(cmd)

