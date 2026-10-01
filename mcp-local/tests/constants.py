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

MCP_DOCKER_IMAGE = "arm-mcp:latest"

DEFAULT_PLATFORM = "linux/arm64"

INIT_REQUEST = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0.1"},
            },
        }

CHECK_NGINX_REQUEST = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "knowledge_base_search",
                "arguments": {
                    "query": "nginx performance tweaks",
                },
            },
        }

EXPECTED_CHECK_NGINX_RESPONSE = [
    "https://amperecomputing.com/tuning-guides/nginx-tuning-guide",
    "https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx_tune",
    ]
