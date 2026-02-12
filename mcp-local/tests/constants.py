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
"https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx_tune/tune_static_file_server",
 "https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx_tune/test_optimizations",
 "https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx_tune/kernel_comp_lib",
 "https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx_tune/before_and_after",
"https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx_tune/tune_revprox_and_apigw"
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
