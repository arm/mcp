"""Exercise the offline benchmark boundary and workflow permission graph."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/run-retrieval-benchmark.sh"
IMAGE_ID = "sha256:" + "a" * 64
GENERATOR = "ghcr.io/arm/mcp-embedding-generator@sha256:" + "b" * 64
CANDIDATE = "ghcr.io/arm/mcp-embedding-vectorstore@sha256:" + "c" * 64


@pytest.fixture
def benchmark(tmp_path):
    binary = tmp_path / "docker"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['DOCKER_LOG'], 'a') as log:\n"
        "    log.write(json.dumps(args) + '\\n')\n"
        "if args[:2] == ['image', 'inspect']:\n"
        "    print(os.environ['ACTUAL_IMAGE_ID'])\n"
        "elif args[0] == 'create':\n"
        "    print('corpus-container')\n"
        "elif args[0] == 'run':\n"
        "    reports = pathlib.Path(os.environ['RUNNER_TEMP']) / 'retrieval-benchmark'\n"
        "    (reports / 'summary.md').write_text('Benchmark summary\\n')\n"
        "    sys.exit(int(os.environ.get('EVAL_EXIT', '0')))\n"
    )
    binary.chmod(0o755)
    log = tmp_path / "docker.jsonl"
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        DOCKER_LOG=str(log),
        RUNNER_TEMP=str(tmp_path / "runner temp"),
        GITHUB_WORKSPACE=str(ROOT),
        GITHUB_SHA="d" * 40,
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        GH_TOKEN="must-not-reach-evaluation",
    )

    def run(candidate=CANDIDATE, generator=GENERATOR, actual_id=IMAGE_ID, exit_code=0):
        result = subprocess.run(
            ["bash", str(SCRIPT), generator, candidate, IMAGE_ID],
            env=dict(env, ACTUAL_IMAGE_ID=actual_id, EVAL_EXIT=str(exit_code)),
            capture_output=True,
            text=True,
        )
        calls = (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        return result, calls

    return run


@pytest.mark.parametrize("candidate,exit_code", [(CANDIDATE, 0), (IMAGE_ID, 2)])
def test_benchmark_runs_exact_candidate_offline(
    benchmark, tmp_path, candidate, exit_code
):
    result, calls = benchmark(candidate=candidate, exit_code=exit_code)
    assert result.returncode == exit_code, result.stderr
    create = next(call for call in calls if call[0] == "create")
    assert create[-2:] == [candidate, "/unused"]
    run = next(call for call in calls if call[0] == "run")
    for flag in ("--network=none", "--read-only", "--pull=never", "--cap-drop=ALL"):
        assert flag in run
    assert run[run.index(GENERATOR) + 1 :][:2] == [
        "python",
        "/workspace/embedding-generation/evaluate_retrieval.py",
    ]
    assert f"EVAL_TARGET={candidate}" in run
    assert run[run.index("--model-path") + 1] == "/corpus/embedding-model"
    assert run[run.index("--index-path") + 1] == "/corpus/usearch_index.bin"
    assert run[run.index("--metadata-path") + 1] == "/corpus/metadata.json"
    mounts = [run[i + 1] for i, arg in enumerate(run) if arg == "--mount"]
    for target in ("/workspace", "/corpus", "/baseline"):
        assert any(f"dst={target},readonly" in mount for mount in mounts)
    assert not any("GH_TOKEN" in arg or "docker.sock" in arg for arg in run)
    assert (tmp_path / "summary.md").read_text() == "Benchmark summary\n"
    assert calls[-1] == ["rm", "-f", "corpus-container"]


@pytest.mark.parametrize(
    "override",
    [
        {"generator": "ghcr.io/arm/mcp-embedding-generator:latest"},
        {"candidate": "ghcr.io/arm/mcp-embedding-vectorstore:latest"},
        {"actual_id": "sha256:" + "e" * 64},
    ],
)
def test_benchmark_rejects_mutable_or_wrong_images(benchmark, override):
    result, calls = benchmark(**override)
    assert result.returncode != 0
    assert "::error::" in result.stderr
    assert not any(call[0] in ("create", "run") for call in calls)


def test_benchmark_has_no_publication_privileges_or_dependents():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/build-embeddings.yml").read_text()
    )
    jobs = workflow["jobs"]
    benchmark = jobs["retrieval-benchmark"]
    assert benchmark["permissions"] == {
        "actions": "read",
        "contents": "read",
        "packages": "read",
    }
    assert benchmark["continue-on-error"] is True
    # Report even if scanning or attestation fails after producing the candidate.
    assert benchmark["if"] == "${{ !cancelled() }}"
    checkout = next(
        step
        for step in benchmark["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False
    for name, job in jobs.items():
        if name != "retrieval-benchmark":
            assert "retrieval-benchmark" not in job.get("needs", [])
    publisher_steps = jobs["generate-and-publish-vectorstore"]["steps"]
    assert not any(
        step.get("uses", "").startswith(
            ("actions/setup-python@", "astral-sh/setup-uv@")
        )
        or "evaluate_retrieval.py" in step.get("run", "")
        for step in publisher_steps
    )

    warning = next(
        step
        for step in benchmark["steps"]
        if step["name"] == "Report unavailable benchmark"
    )
    assert warning["if"] == "${{ !cancelled() && failure() }}"
