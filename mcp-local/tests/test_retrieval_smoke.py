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

import os
from pathlib import Path

import constants
from testcontainers.core.container import DockerContainer


def test_retrieval_smoke(platform, tmp_path):
    image = os.getenv("MCP_IMAGE", constants.MCP_DOCKER_IMAGE)
    repo_root = Path(__file__).resolve().parents[2]
    results = Path(os.getenv("RUNNER_TEMP", str(tmp_path))) / "retrieval-smoke"
    results.mkdir(parents=True, exist_ok=True)

    container = (
        DockerContainer(image)
        .with_kwargs(entrypoint="python", network_mode="none", platform=platform)
        .with_volume_mapping(repo_root, "/evaluation", mode="ro")
        .with_volume_mapping(results.resolve(), "/results", mode="rw")
        .with_command([
            "/evaluation/embedding-generation/evaluate_retrieval.py",
            "--suite", "smoke", "--top-k", "5",
            "--metadata-path", "/app/data/metadata.json",
            "--index-path", "/app/data/usearch_index.bin",
            "--model-path", "/app/embedding-model",
            "--output", "/results/smoke.json",
        ])
    )
    image_id = container.get_docker_client().client.images.get(image).id
    container.with_env("EVAL_TARGET", image_id)
    if revision := os.getenv("GITHUB_SHA"):
        container.with_env("GITHUB_SHA", revision)
    if summary_path := os.getenv("GITHUB_STEP_SUMMARY"):
        summary = Path(summary_path).resolve()
        summary.touch(exist_ok=True)
        container.with_volume_mapping(summary, "/evaluation-summary.md", mode="rw")
        container.with_env("GITHUB_STEP_SUMMARY", "/evaluation-summary.md")

    with container:
        try:
            exit_code = container.get_wrapped_container().wait(timeout=15 * 60)["StatusCode"]
        finally:
            stdout, stderr = container.get_logs()
            print(stdout.decode("utf-8", errors="replace"))
            print(stderr.decode("utf-8", errors="replace"))

    assert exit_code == 0, f"Retrieval smoke failed (exit {exit_code}); see evaluator output above."
    assert (results / "smoke.json").is_file(), "Retrieval smoke did not write its JSON report."
