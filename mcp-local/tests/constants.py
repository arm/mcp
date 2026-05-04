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

CHECK_IMAGE_REQUEST = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "check_image",
                "arguments": {
                    "image": "ubuntu:24.04",
                    "invocation_reason": (
                        "Checking ARM architecture compatibility for ubuntu:24.04 "
                        "container image as requested by the user"
                    ),
                },
            },
        }

EXPECTED_CHECK_IMAGE_RESPONSE = {
            "status": "success",
            "message": "Image ubuntu:24.04 supports all required architectures",
            "architectures": [
                "amd64",
                "unknown",
                "arm",
                "unknown",
                "arm64",
                "unknown",
                "ppc64le",
                "unknown",
                "riscv64",
                "unknown",
                "s390x",
                "unknown",
            ],
        }

CHECK_SKOPEO_REQUEST = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "skopeo",
                "arguments": {
                    "image": "armswdev/arm-mcp",
                    "invocation_reason": (
                        "Checking the architecture support of the armswdev/arm-mcp container image to verify ARM compatibility as requested by the user."
                    ),
                },
            },
        }
# Fields Architecture, Os and Status are asserted in test to avoid mismatches due to dynamic fields
EXPECTED_CHECK_SKOPEO_RESPONSE = {
  "status": "ok",
  "code": 0,
  "stdout": "{\n    \"Name\": \"docker.io/armswdev/arm-mcp\",\n    \"Digest\": \"\",\n    \"RepoTags\": [\n        \"latest\"\n    ],\n    \"Created\": \"\",\n    \"DockerVersion\": \"\",\n    \"Labels\": {\n        \"org.opencontainers.image.ref.name\": \"ubuntu\",\n        \"org.opencontainers.image.version\": \"24.04\"\n    },\n    \"Architecture\": \"arm64\",\n    \"Os\": \"linux\",\n    \"Layers\": [\n        \"\",\n        \"\",\n        \"\",\n        \"\",\n        \"\",\n        \"\",\n        \"\"\n    ],\n    \"LayersData\": [\n        {\n            \"MIMEType\": \"application/vnd.oci.image.layer.v1.tar+gzip\",\n            \"Digest\": \"\",\n            \"Size\": 28861712,\n            \"Annotations\": null\n        },\n        {\n            \"MIMEType\": \"application/vnd.oci.image.layer.v1.tar+gzip\",\n            \"Digest\": \"\",\n            \"Size\": 142025708,\n            \"Annotations\": null\n        },\n        {\n            \"MIMEType\": \"application/vnd.oci.image.layer.v1.tar+gzip\",\n            \"Digest\": \"\",\n            \"Size\": 107240731,\n            \"Annotations\": null\n        },\n        {\n            \"MIMEType\": \"application/vnd.oci.image.layer.v1.tar+gzip\",\n            \"Digest\": \"\",\n            \"Size\": 1180,\n            \"Annotations\": null\n        },\n        {\n            \"MIMEType\": \"application/vnd.oci.image.layer.v1.tar+gzip\",\n            \"Digest\": \"\",\n            \"Size\": 7105736,\n            \"Annotations\": null\n        },\n        {\n            \"MIMEType\": \"application/vnd.oci.image.layer.v1.tar+gzip\",\n            \"Digest\": \"\",\n            \"Size\": 392970938,\n            \"Annotations\": null\n        },\n        {\n            \"MIMEType\": \"application/vnd.oci.image.layer.v1.tar+gzip\",\n            \"Digest\": \"\",\n            \"Size\": 32,\n            \"Annotations\": null\n        }\n    ],\n    \"Env\": [\n        \"PATH=/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\",\n        \"DEBIAN_FRONTEND=noninteractive\",\n        \"PYTHONUNBUFFERED=1\",\n        \"PIP_NO_CACHE_DIR=1\",\n        \"WORKSPACE_DIR=/workspace\",\n        \"VIRTUAL_ENV=/app/.venv\"\n    ]\n}\n",
  "stderr": "",
  "cmd": [
    "skopeo",
    "inspect",
    "docker://armswdev/arm-mcp"
  ]
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
    "https://amperecomputing.com/tuning-guides/nginx-tuning-guide"
    ]

CHECK_MIGRATE_EASE_TOOL_REQUEST = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "migrate_ease_scan",
                "arguments": {
                    "scanner": "java",
                },
            },
        }
'''TODO: Need to use a user-controlled repo with static example for testing to check more detailed response params. 
For now, only status field is asserted in test to avoid mismatches due to dynamic fields.
Sample response below for reference -
EXPECTED_CHECK_MIGRATE_EASE_TOOL_RESPONSE = {
  "status": "success",
  "returncode": 0,
  "command": "migrate-ease-java --march armv8-a --output /tmp/migrate_ease_java_20260126-215207.json /tmp/migrate_ease_filtered_s45ojwm1",
  "ran_from": "/app",
  "target": "/workspace (filtered)",
  "stdout": "[Java] Loading of check_points.yaml took 0.002821 seconds.\n[Java] Initialization of checkpoints took 0.000328 seconds.\nNo issue found.\n",
  "stderr": "",
  "output_file": "/tmp/migrate_ease_java_20260126-215207.json",
  "output_format": "json",
  "workspace_listing": [
    "invocation_reasons.yaml"
  ],
  "excluded_items": [],
  "excluded_count": 0,
  "parsed_results": {
    "branch": None,
    "commit": None,
    "errors": [],
    "file_summary": {
      "jar": {
        "count": 0,
        "fileName": "Jar",
        "loc": 0
      },
      "java": {
        "count": 0,
        "fileName": "java",
        "loc": 0
      },
      "pom": {
        "count": 0,
        "fileName": "POM",
        "loc": 0
      }
    },
    "git_repo": None,
    "issue_summary": {
      "Error": {
        "count": 0,
        "des": "Exception encountered by the code scanning tool during the scanning process, not an issue with the code logic itself. User can ignore it."
      },
      "JarIssue": {
        "count": 0,
        "des": "JAR package does not support target arch. Need to rebuild or upgrade."
      },
      "JavaSourceIssue": {
        "count": 0,
        "des": "Java source file contains native call that may need modify/rebuild for target arch."
      },
      "OtherIssue": {
        "count": 0,
        "des": "Issues exceeding the limit will be categorized as OtherIssue. when the issue count limit option is enabled"
      },
      "PomIssue": {
        "count": 0,
        "des": "Pom imports java artifact that does not support target arch."
      }
    },
    "issue_type_config": None,
    "issues": [],
    "language_type": "java",
    "march": "armv8-a",
    "output": None,
    "progress": True,
    "quiet": False,
    "remarks": [],
    "root_directory": "/tmp/migrate_ease_filtered_s45ojwm1",
    "source_dirs": [],
    "source_files": [],
    "target_os": "OpenAnolis",
    "total_issue_count": 0
  },
  "output_file_deleted": True
}'''

EXPECTED_CHECK_MIGRATE_EASE_TOOL_RESPONSE_STATUS = "success"

CHECK_SYSREPORT_TOOL_REQUEST = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "sysreport_instructions",
                "arguments": {
                    "invocation_reason": "Providing instructions for using the sysreport tool as requested by the user.",
                },
            },
        }
EXPECTED_CHECK_SYSREPORT_TOOL_RESPONSE = {
  "instructions": "\n# SysReport Installation and Usage\n\n## Installation\n```bash\ngit clone https://github.com/ArmDeveloperEcosystem/sysreport.git\ncd sysreport\n```\n\n## Usage\n```bash\npython3 sysreport.py\n```\n\n## What SysReport Does\n- Gathers comprehensive system information including architecture, CPU, memory, and hardware details\n- Useful for diagnosing system issues or understanding system capabilities\n- Provides detailed hardware and software configuration data\n\n## Note\nRun these commands directly on your host system (not in a container) to get accurate system information.\n",
  "repository": "https://github.com/ArmDeveloperEcosystem/sysreport.git",
  "usage_command": "python3 sysreport.py",
  "note": "This tool must be run on the host system to provide accurate system information."
}

CHECK_MCA_TOOL_REQUEST = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "mca",
                "arguments": {
                    "input_path": "/workspace/tests/sum_test.s",
                    "invocation_reason": "User requested to run the MCA tool on the ARM assembly file sum_test.s to analyze its performance characteristics, using the correct workspace path"
                },
            },
        }

'''TODO: Need to use a user-controlled repo with static example for testing to check more detailed response params. 
For now, only status field is asserted in test to avoid mismatches due to dynamic fields.
Sample response below for reference -
EXPECTED_CHECK_MCA_TOOL_RESPONSE = {
              "status": "ok",
              "code": 0,
              "stdout": "Iterations:        100\nInstructions:      500\nTotal Cycles:      501\nTotal uOps:        500\n\nDispatch Width:    3\nuOps Per Cycle:    1.00\nIPC:               1.00\nBlock RThroughput: 1.7\n\n\nInstruction Info:\n[1]: #uOps\n[2]: Latency\n[3]: RThroughput\n[4]: MayLoad\n[5]: MayStore\n[6]: HasSideEffects (U)\n\n[1]    [2]    [3]    [4]    [5]    [6]    Instructions:\n 1      1     0.33                        add\tx1, x1, x2\n 1      1     0.33                        add\tx1, x1, x3\n 1      1     0.33                        add\tx1, x1, x4\n 1      1     0.33                        add\tx1, x1, x5\n 1      1     0.33                        add\tx1, x1, x6\n\n\nResources:\n[0]   - CortexA510UnitALU0\n[1.0] - CortexA510UnitALU12\n[1.1] - CortexA510UnitALU12\n[2]   - CortexA510UnitB\n[3]   - CortexA510UnitDiv\n[4]   - CortexA510UnitLd1\n[5]   - CortexA510UnitLdSt\n[6]   - CortexA510UnitMAC\n[7]   - CortexA510UnitPAC\n[8]   - CortexA510UnitVALU0\n[9]   - CortexA510UnitVALU1\n[10.0] - CortexA510UnitVMAC\n[10.1] - CortexA510UnitVMAC\n[11]  - CortexA510UnitVMC\n\n\nResource pressure per iteration:\n[0]    [1.0]  [1.1]  [2]    [3]    [4]    [5]    [6]    [7]    [8]    [9]    [10.0] [10.1] [11]   \n -     2.50   2.50    -      -      -      -      -      -      -      -      -      -      -     \n\nResource pressure by instruction:\n[0]    [1.0]  [1.1]  [2]    [3]    [4]    [5]    [6]    [7]    [8]    [9]    [10.0] [10.1] [11]   Instructions:\n -     0.50   0.50    -      -      -      -      -      -      -      -      -      -      -     add\tx1, x1, x2\n -     0.50   0.50    -      -      -      -      -      -      -      -      -      -      -     add\tx1, x1, x3\n -     0.50   0.50    -      -      -      -      -      -      -      -      -      -      -     add\tx1, x1, x4\n -     0.50   0.50    -      -      -      -      -      -      -      -      -      -      -     add\tx1, x1, x5\n -     0.50   0.50    -      -      -      -      -      -      -      -      -      -      -     add\tx1, x1, x6\n",
              "stderr": "",
              "cmd": [
                "llvm-mca",
                "/workspace/tests/sum_test.s"
              ]
      }'''

EXPECTED_CHECK_MCA_TOOL_RESPONSE_STATUS = "ok"     

CHECK_APX_CPU_HOTSPOTS_JAVA_REQUEST = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "apx_recipe_run",
                "arguments": {
                    "cmd": (
                        "D=\"$HOME/cpuburner\"; "
                        "mkdir -p \"$D\"; "
                        "printf '%s' 'Ly8gQ3B1QnVybmVyLmphdmEKLy8gT3JpZ25hbCB1bi1vcHRpbWlzZWQgdmVyc2lvbiB3b3JrQyBmdW5jdGlvbiBpcyBkZWxpYmVyYXRlbHkgc2xvdwovLyBVc2FnZTogIGphdmEgQ3B1QnVybmVyIDxzZWNvbmRzPgovLyBFeGFtcGxlOiBqYXZhIENwdUJ1cm5lciAxMAovLwovLyBSdW5zIGZvciAoYXBwcm94aW1hdGVseSkgdGhlIGdpdmVuIGR1cmF0aW9uLCBjYWxsaW5nIEEvQi9DIHRoZSBzYW1lIG51bWJlciBvZiB0aW1lcy4KLy8gQTogZXhwZW5zaXZlIHN0cmluZyBtYW5pcHVsYXRpb24KLy8gQjogY29tcHV0YXRpb25hbGx5IGV4cGVuc2l2ZSBtZW1jcHkgKFN5c3RlbS5hcnJheWNvcHkgb3ZlciBsYXJnZSBidWZmZXJzKQovLyBDOiBmbG9hdGluZyBwb2ludCAvIG1hdHJpeCBtdWx0aXBsaWNhdGlvbnMgKElOVEVOVElPTkFMTFkgU0xPV0VEIERPV04pCgppbXBvcnQgamF2YS5uaW8uY2hhcnNldC5TdGFuZGFyZENoYXJzZXRzOwppbXBvcnQgamF2YS51dGlsLkxvY2FsZTsKCnB1YmxpYyBmaW5hbCBjbGFzcyBDcHVCdXJuZXIgewoKICAgIC8vIFByZXZlbnQgZGVhZC1jb2RlIGVsaW1pbmF0aW9uCiAgICBwcml2YXRlIHN0YXRpYyB2b2xhdGlsZSBsb25nIFNJTktfTE9ORyA9IDA7CiAgICBwcml2YXRlIHN0YXRpYyB2b2xhdGlsZSBkb3VibGUgU0lOS19EQkwgPSAwLjA7CgogICAgLy8gRXh0cmEgc2luayB1c2VkIG9ubHkgdG8ga2VlcCAid2FzdGVkIiBtYXRoIGZyb20gYmVpbmcgb3B0aW1pemVkIGF3YXkKICAgIHByaXZhdGUgc3RhdGljIHZvbGF0aWxlIGRvdWJsZSBXQVNURV9EQkwgPSAwLjA7CgogICAgLy8gLS0tLSBXb3JrbG9hZCBCIGJ1ZmZlcnMgLS0tLQogICAgcHJpdmF0ZSBzdGF0aWMgZmluYWwgaW50IE1FTV9TSVpFID0gOCAqIDEwMjQgKiAxMDI0OyAvLyA4IE1pQgogICAgcHJpdmF0ZSBzdGF0aWMgZmluYWwgYnl0ZVtdIFNSQyA9IG5ldyBieXRlW01FTV9TSVpFXTsKICAgIHByaXZhdGUgc3RhdGljIGZpbmFsIGJ5dGVbXSBEU1QgPSBuZXcgYnl0ZVtNRU1fU0laRV07CgogICAgLy8gLS0tLSBXb3JrbG9hZCBDIG1hdHJpY2VzIC0tLS0KICAgIHByaXZhdGUgc3RhdGljIGZpbmFsIGludCBOID0gNjQ7CiAgICBwcml2YXRlIHN0YXRpYyBmaW5hbCBkb3VibGVbXVtdIE0xID0gbmV3IGRvdWJsZVtOXVtOXTsKICAgIHByaXZhdGUgc3RhdGljIGZpbmFsIGRvdWJsZVtdW10gTTIgPSBuZXcgZG91YmxlW05dW05dOwogICAgcHJpdmF0ZSBzdGF0aWMgZmluYWwgZG91YmxlW11bXSBPVVQgPSBuZXcgZG91YmxlW05dW05dOwoKICAgIHN0YXRpYyB7CiAgICAgICAgLy8gRGV0ZXJtaW5pc3RpYyBpbml0IGZvciByZXBlYXRhYmxlIHByb2ZpbGluZwogICAgICAgIGxvbmcgeCA9IDB4OUUzNzc5Qjk3RjRBN0MxNUw7CiAgICAgICAgZm9yIChpbnQgaSA9IDA7IGkgPCBNRU1fU0laRTsgaSsrKSB7CiAgICAgICAgICAgIHggXj0gKHggPDwgMTMpOyB4IF49ICh4ID4+PiA3KTsgeCBePSAoeCA8PCAxNyk7CiAgICAgICAgICAgIFNSQ1tpXSA9IChieXRlKSB4OwogICAgICAgIH0KCiAgICAgICAgbG9uZyB5ID0gMHhEMUI1NEEzMkQxOTJFRDAzTDsKICAgICAgICBmb3IgKGludCBpID0gMDsgaSA8IE47IGkrKykgewogICAgICAgICAgICBmb3IgKGludCBqID0gMDsgaiA8IE47IGorKykgewogICAgICAgICAgICAgICAgeSBePSAoeSA8PCAxMyk7IHkgXj0gKHkgPj4+IDcpOyB5IF49ICh5IDw8IDE3KTsKICAgICAgICAgICAgICAgIE0xW2ldW2pdID0gKCh5ICYgMHhGRkZGKSAtIDMyNzY4KSAvIDEwMjQuMDsKICAgICAgICAgICAgICAgIHkgXj0gKHkgPDwgMTMpOyB5IF49ICh5ID4+PiA3KTsgeSBePSAoeSA8PCAxNyk7CiAgICAgICAgICAgICAgICBNMltpXVtqXSA9ICgoeSAmIDB4RkZGRikgLSAzMjc2OCkgLyAxMDI0LjA7CiAgICAgICAgICAgIH0KICAgICAgICB9CiAgICB9CgogICAgcHVibGljIHN0YXRpYyB2b2lkIG1haW4oU3RyaW5nW10gYXJncykgewogICAgICAgIGlmIChhcmdzLmxlbmd0aCAhPSAxKSB7CiAgICAgICAgICAgIFN5c3RlbS5lcnIucHJpbnRsbigiVXNhZ2U6IGphdmEgQ3B1QnVybmVyIDxzZWNvbmRzPiIpOwogICAgICAgICAgICBTeXN0ZW0uZXJyLnByaW50bG4oIkV4YW1wbGU6IGphdmEgQ3B1QnVybmVyIDEwIik7CiAgICAgICAgICAgIFN5c3RlbS5leGl0KDIpOwogICAgICAgIH0KCiAgICAgICAgZmluYWwgZG91YmxlIHNlY29uZHM7CiAgICAgICAgdHJ5IHsKICAgICAgICAgICAgc2Vjb25kcyA9IERvdWJsZS5wYXJzZURvdWJsZShhcmdzWzBdKTsKICAgICAgICB9IGNhdGNoIChOdW1iZXJGb3JtYXRFeGNlcHRpb24gZSkgewogICAgICAgICAgICBTeXN0ZW0uZXJyLnByaW50bG4oIkludmFsaWQgbnVtYmVyOiAiICsgYXJnc1swXSk7CiAgICAgICAgICAgIFN5c3RlbS5leGl0KDIpOwogICAgICAgICAgICByZXR1cm47CiAgICAgICAgfQoKICAgICAgICBpZiAoc2Vjb25kcyA8PSAwLjApIHsKICAgICAgICAgICAgU3lzdGVtLmVyci5wcmludGxuKCJEdXJhdGlvbiBtdXN0IGJlID4gMCIpOwogICAgICAgICAgICBTeXN0ZW0uZXhpdCgyKTsKICAgICAgICB9CgogICAgICAgIGZpbmFsIGxvbmcgZHVyYXRpb25OYW5vcyA9IChsb25nKSAoc2Vjb25kcyAqIDFfMDAwXzAwMF8wMDBMKTsKICAgICAgICBmaW5hbCBsb25nIHN0YXJ0ID0gU3lzdGVtLm5hbm9UaW1lKCk7CiAgICAgICAgZmluYWwgbG9uZyBkZWFkbGluZSA9IHN0YXJ0ICsgZHVyYXRpb25OYW5vczsKCiAgICAgICAgbG9uZyBjYWxsc0EgPSAwLCBjYWxsc0IgPSAwLCBjYWxsc0MgPSAwOwoKICAgICAgICAvLyBSb3VuZC1yb2JpbiBBLT5CLT5DOyBvbmx5IGNvbXBsZXRlIGZ1bGwgY3ljbGVzIHNvIGNvdW50cyByZW1haW4gZXF1YWwKICAgICAgICB3aGlsZSAodHJ1ZSkgewogICAgICAgICAgICBpZiAoU3lzdGVtLm5hbm9UaW1lKCkgPj0gZGVhZGxpbmUpIGJyZWFrOwoKICAgICAgICAgICAgLy8gQQogICAgICAgICAgICBTSU5LX0xPTkcgXj0gd29ya0EoY2FsbHNBKTsKICAgICAgICAgICAgY2FsbHNBKys7CgogICAgICAgICAgICAvLyBDaGVjayBiZXR3ZWVuIGZ1bmN0aW9ucyB0byBhdm9pZCBvdmVyc2hvb3RpbmcgdG9vIG11Y2gKICAgICAgICAgICAgaWYgKFN5c3RlbS5uYW5vVGltZSgpID49IGRlYWRsaW5lKSB7IGNhbGxzQS0tOyBicmVhazsgfQoKICAgICAgICAgICAgLy8gQgogICAgICAgICAgICBTSU5LX0xPTkcgXj0gd29ya0IoY2FsbHNCKTsKICAgICAgICAgICAgY2FsbHNCKys7CgogICAgICAgICAgICBpZiAoU3lzdGVtLm5hbm9UaW1lKCkgPj0gZGVhZGxpbmUpIHsgY2FsbHNBLS07IGNhbGxzQi0tOyBicmVhazsgfQoKICAgICAgICAgICAgLy8gQwogICAgICAgICAgICBTSU5LX0RCTCArPSB3b3JrQyhjYWxsc0MpOwogICAgICAgICAgICBjYWxsc0MrKzsKCiAgICAgICAgICAgIGlmIChTeXN0ZW0ubmFub1RpbWUoKSA+PSBkZWFkbGluZSkgeyBjYWxsc0EtLTsgY2FsbHNCLS07IGNhbGxzQy0tOyBicmVhazsgfQogICAgICAgIH0KCiAgICAgICAgLy8gRW5zdXJlIGV4YWN0bHkgZXF1YWwgY291bnRzIChkcm9wIGFueSBwYXJ0aWFsIGN5Y2xlIGlmIHRpbWluZyBjdXQgaXQgc2hvcnQpCiAgICAgICAgbG9uZyBtaW4gPSBNYXRoLm1pbihjYWxsc0EsIE1hdGgubWluKGNhbGxzQiwgY2FsbHNDKSk7CiAgICAgICAgY2FsbHNBID0gY2FsbHNCID0gY2FsbHNDID0gbWluOwoKICAgICAgICBsb25nIGVsYXBzZWROYW5vcyA9IFN5c3RlbS5uYW5vVGltZSgpIC0gc3RhcnQ7CiAgICAgICAgU3lzdGVtLm91dC5wcmludGxuKCJFbGFwc2VkOiAiICsgKGVsYXBzZWROYW5vcyAvIDFfMDAwXzAwMCkgKyAiIG1zIik7CiAgICAgICAgU3lzdGVtLm91dC5wcmludGxuKCJDYWxsczogQT0iICsgY2FsbHNBICsgIiBCPSIgKyBjYWxsc0IgKyAiIEM9IiArIGNhbGxzQyArICIgKGVxdWFsKSIpOwogICAgICAgIFN5c3RlbS5vdXQucHJpbnRsbigiU2lua3M6IGxvbmc9IiArIFNJTktfTE9ORyArICIgZG91YmxlPSIgKyBTdHJpbmcuZm9ybWF0KExvY2FsZS5ST09ULCAiJS42ZiIsIFNJTktfREJMKSk7CiAgICAgICAgLy8gV0FTVEVfREJMIGludGVudGlvbmFsbHkgbm90IHByaW50ZWQ7IGl0J3Mgb25seSB0byBwcmV2ZW50IG9wdGltaXphdGlvbi4KICAgIH0KCiAgICAvLyBBOiBleHBlbnNpdmUgc3RyaW5nIG1hbmlwdWxhdGlvbgogICAgcHJpdmF0ZSBzdGF0aWMgbG9uZyB3b3JrQShsb25nIGl0ZXIpIHsKICAgICAgICAvLyBNaXggaXRlcmF0aW9uIHRvIGF2b2lkIGlkZW50aWNhbCBzdHJpbmdzIGVhY2ggdGltZQogICAgICAgIFN0cmluZyBiYXNlID0gIlRoZV9xdWlja19icm93bl9mb3hfanVtcHNfb3Zlcl90aGVfbGF6eV9kb2dfIiArIGl0ZXI7CgogICAgICAgIGxvbmcgaCA9IDE0Njk1OTgxMDM5MzQ2NjU2MDNMOyAvLyBGTlYtMWEtaXNoIG1peAogICAgICAgIGZvciAoaW50IHJvdW5kID0gMDsgcm91bmQgPCA1MDA7IHJvdW5kKyspIHsKICAgICAgICAgICAgU3RyaW5nIHMxID0gbmV3IFN0cmluZ0J1aWxkZXIoYmFzZSkucmV2ZXJzZSgpLmFwcGVuZCgnXycpLmFwcGVuZChyb3VuZCkudG9TdHJpbmcoKTsKICAgICAgICAgICAgU3RyaW5nIHMyID0gczEudG9VcHBlckNhc2UoTG9jYWxlLlJPT1QpLnJlcGxhY2UoJ18nLCAnLScpOwogICAgICAgICAgICBTdHJpbmcgczMgPSBzMiArICI6OiIgKyBJbnRlZ2VyLnRvSGV4U3RyaW5nKHMyLmhhc2hDb2RlKCkpOwoKICAgICAgICAgICAgLy8gQnl0ZS1sZXZlbCBjaHVybgogICAgICAgICAgICBieXRlW10gYnl0ZXMgPSBzMy5nZXRCeXRlcyhTdGFuZGFyZENoYXJzZXRzLlVURl84KTsKICAgICAgICAgICAgZm9yIChieXRlIGIgOiBieXRlcykgewogICAgICAgICAgICAgICAgaCBePSAoYiAmIDB4RkYpOwogICAgICAgICAgICAgICAgaCAqPSAxMDk5NTExNjI4MjExTDsKICAgICAgICAgICAgfQoKICAgICAgICAgICAgLy8gTW9yZSBzdHJpbmcgY2h1cm4KICAgICAgICAgICAgU3RyaW5nW10gcGFydHMgPSBzMy5zcGxpdCgiOjoiKTsKICAgICAgICAgICAgYmFzZSA9IHBhcnRzWzBdICsgIl8iICsgcGFydHNbMV0gKyAiXyIgKyAoaCAmIDB4RkZGRik7CiAgICAgICAgfQogICAgICAgIHJldHVybiBoOwogICAgfQoKICAgIC8vIEI6IGNvbXB1dGF0aW9uYWxseSBleHBlbnNpdmUgbWVtY3B5IChsYXJnZSBhcnJheWNvcHkgKyBsaWdodCBjaGVja3N1bSkKICAgIHByaXZhdGUgc3RhdGljIGxvbmcgd29ya0IobG9uZyBpdGVyKSB7CiAgICAgICAgaW50IGNodW5rID0gMjU2ICogMTAyNDsgLy8gMjU2IEtpQgogICAgICAgIGludCBjb3BpZXMgPSAzMjsgICAgICAgIC8vIDMyICogMjU2S2lCIH49IDhNaUIgY29waWVkIHBlciBjYWxsCgogICAgICAgIC8vIE9mZnNldCBzaGlmdHMgdG8gYXZvaWQgY29weWluZyBpZGVudGljYWwgcmVnaW9ucyBlYWNoIGNhbGwKICAgICAgICBpbnQgb2ZmID0gKGludCkgKChpdGVyICogMTMxNTQyMzkxMUwpICYgKE1FTV9TSVpFIC0gMSkpOwogICAgICAgIG9mZiA9IG9mZiAmIH4oY2h1bmsgLSAxKTsgLy8gYWxpZ24gdG8gY2h1bmsKCiAgICAgICAgZm9yIChpbnQgaSA9IDA7IGkgPCBjb3BpZXM7IGkrKykgewogICAgICAgICAgICBpbnQgc3JjT2ZmID0gKG9mZiArIGkgKiBjaHVuaykgJSAoTUVNX1NJWkUgLSBjaHVuayk7CiAgICAgICAgICAgIGludCBkc3RPZmYgPSAoc3JjT2ZmIF4gMHg1QTVBNUEpICUgKE1FTV9TSVpFIC0gY2h1bmspOwogICAgICAgICAgICBTeXN0ZW0uYXJyYXljb3B5KFNSQywgc3JjT2ZmLCBEU1QsIGRzdE9mZiwgY2h1bmspOwogICAgICAgIH0KCiAgICAgICAgLy8gVG91Y2ggYSBmZXcgYnl0ZXMgc28gaXQgaXNuJ3Qgb3B0aW1pemVkIGF3YXkKICAgICAgICBsb25nIHN1bSA9IDA7CiAgICAgICAgZm9yIChpbnQgaSA9IDA7IGkgPCA0MDk2OyBpICs9IDY0KSB7CiAgICAgICAgICAgIHN1bSA9IChzdW0gKiAxMzE1NDIzOTExTCkgKyAoRFNUWyhvZmYgKyBpKSAlIE1FTV9TSVpFXSAmIDB4RkYpOwogICAgICAgIH0KICAgICAgICByZXR1cm4gc3VtOwogICAgfQoKICAgIC8vIEM6IGZsb2F0aW5nIHBvaW50IC8gbWF0cml4IG11bHRpcGxpY2F0aW9ucyAoSU5URU5USU9OQUxMWSBTTE9XKQogICAgcHJpdmF0ZSBzdGF0aWMgZG91YmxlIHdvcmtDKGxvbmcgaXRlcikgewogICAgICAgIC8vIE5haXZlIE54TiBtdWx0aXBseSByZXBlYXRlZCBhIGZldyB0aW1lcwogICAgICAgIGRvdWJsZSB0b3RhbCA9IDAuMDsKICAgICAgICBpbnQgcmVwcyA9IDY7CgogICAgICAgIGZvciAoaW50IHIgPSAwOyByIDwgcmVwczsgcisrKSB7CiAgICAgICAgICAgIC8vIE9VVCA9IE0xICogTTIKICAgICAgICAgICAgZm9yIChpbnQgaSA9IDA7IGkgPCBOOyBpKyspIHsKICAgICAgICAgICAgICAgIC8vIChkZWxpYmVyYXRlbHkgYXZvaWQgY2FjaGluZyByb3cgcmVmZXJlbmNlcyB0byBtYWtlIGFjY2VzcyBhIGJpdCB3b3JzZSkKICAgICAgICAgICAgICAgIGZvciAoaW50IGogPSAwOyBqIDwgTjsgaisrKSB7CiAgICAgICAgICAgICAgICAgICAgZG91YmxlIGFjYyA9IDAuMDsKICAgICAgICAgICAgICAgICAgICBmb3IgKGludCBrID0gMDsgayA8IE47IGsrKykgewogICAgICAgICAgICAgICAgICAgICAgICBkb3VibGUgcHJvZCA9IE0xW2ldW2tdICogTTJba11bal07CiAgICAgICAgICAgICAgICAgICAgICAgIGFjYyArPSBwcm9kOwoKICAgICAgICAgICAgICAgICAgICAgICAgLy8gSW50ZW50aW9uYWwgaW5lZmZpY2llbmN5OiBleHRyYSB0cmFuc2NlbmRlbnRhbHMgaW4gdGhlIGlubmVyIGxvb3AuCiAgICAgICAgICAgICAgICAgICAgICAgIC8vIFdBU1RFX0RCTCBpcyB2b2xhdGlsZSBzbyB0aGUgSklUIGNhbid0IGRpc2NhcmQgdGhpcyB3b3JrLgogICAgICAgICAgICAgICAgICAgICAgICBXQVNURV9EQkwgKz0gKE1hdGguc2luKHByb2QpICsgTWF0aC5jb3MocHJvZCkpICogMWUtMTI7CiAgICAgICAgICAgICAgICAgICAgfQogICAgICAgICAgICAgICAgICAgIE9VVFtpXVtqXSA9IGFjYzsKICAgICAgICAgICAgICAgIH0KICAgICAgICAgICAgfQoKICAgICAgICAgICAgLy8gRm9sZCBzb21lIHJlc3VsdHMgaW50byB0b3RhbCwgYW5kIHNsaWdodGx5IHBlcnR1cmIgaW5wdXRzIHNvIHJlcGVhdHMgZGlmZmVyCiAgICAgICAgICAgIGludCB0ID0gKGludCkgKGl0ZXIgKyByKTsKICAgICAgICAgICAgaW50IGlpID0gKHQgKiAxNykgJiAoTiAtIDEpOwogICAgICAgICAgICBpbnQgamogPSAodCAqIDMxKSAmIChOIC0gMSk7CiAgICAgICAgICAgIHRvdGFsICs9IE9VVFtpaV1bampdOwoKICAgICAgICAgICAgZG91YmxlIHR3ZWFrID0gKHRvdGFsICogMWUtOSkgKyAxZS0xMjsKICAgICAgICAgICAgTTFbaWldW2pqXSArPSB0d2VhazsKICAgICAgICAgICAgTTJbampdW2lpXSAtPSB0d2VhazsKICAgICAgICB9CiAgICAgICAgcmV0dXJuIHRvdGFsOwogICAgfQp9Cg==' | base64 -d > \"$D/CpuBurner.java\"; "
                        "cd \"$D\" && javac CpuBurner.java && "
                        "java -XX:+PreserveFramePointer -cp \"$D\" CpuBurner 30"
                    ),
                    "remote_ip_addr": "localhost",
                    "remote_usr": "base",
                    "recipe": "code_hotspots",
                    "invocation_reason": "Run APX code hotspots recipe against the CpuBurner Java workload to identify CPU hotspots.",
                },
            },
        }

CHECK_APX_RECIPE_RUN_REQUEST = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "apx_recipe_run",
                "arguments": {
                    "cmd": "python3 -c \"print('Hello, world!')\"",
                    "remote_ip_addr": "localhost",
                    "remote_usr": "base",
                    "recipe": "code_hotspots",
                    "invocation_reason": "Run APX code hotspots recipe against the local test workload requested by the user.",
                },
            },
        }
