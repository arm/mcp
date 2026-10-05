"""Cover PR smoke checks, benchmark reports, and contributor selection."""

import json
import subprocess
from types import SimpleNamespace

import pytest

import evaluate_retrieval as runner


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    rows = [
        {
            "id": key,
            "question": f"question {key}",
            "topic": "cloud",
            "intent": intent,
            "expected_urls": [f"https://example.com/{key}"],
        }
        for key, intent in [("Q1", "setup"), ("Q2", "reference")]
    ]
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(rows))
    monkeypatch.setattr(
        runner,
        "load_search_resources",
        lambda **kw: SimpleNamespace(metadata=[{}], usearch_index=[0]),
    )
    # Q1 passes and Q2 misses; scoring, reporting, and CLI behavior stay real.
    monkeypatch.setattr(
        runner, "search", lambda *a, **kw: [{"url": "https://example.com/Q1"}]
    )
    return rows, path, ["--eval-path", str(path), "--model-path", str(tmp_path)]


@pytest.mark.parametrize("selected,exit_code", [([], 1), (["--id", "Q1"], 0)])
def test_smoke_gate_and_id_selection(inputs, tmp_path, selected, exit_code):
    output = tmp_path / "smoke.json"
    assert (
        runner.main(
            [*inputs[2], "--suite", "smoke", *selected, "--output", str(output)]
        )
        == exit_code
    )
    report = json.loads(output.read_text())
    expected_ids = ["Q1"] if selected else ["Q1", "Q2"]
    assert [case["question_id"] for case in report["cases"]] == expected_ids
    assert report["summary"]["misses"] == exit_code


def test_benchmark_misses_produce_json_and_clean_tables(
    inputs, tmp_path, monkeypatch, capsys
):
    output, summary = tmp_path / "benchmark.json", tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert (
        runner.main([*inputs[2], "--suite", "benchmark", "--output", str(output)]) == 0
    )
    report = json.loads(output.read_text())
    assert report["summary"]["hit_at_5"] == report["summary"]["mrr"] == 0.5
    assert len(report["cases"]) == 2
    printed = capsys.readouterr().out
    for row in (
        "| Benchmark | 2 | 1 | 50.00% |",
        "| setup | 1 | 1 | 100.00% |",
        "| reference | 1 | 0 | 0.00% |",
        "| cloud | 2 | 1 | 50.00% |",
    ):
        assert row in printed and row in summary.read_text()
    assert "MISS" not in printed and "https://" not in printed


@pytest.mark.parametrize("suite", ["smoke", "benchmark"])
@pytest.mark.parametrize("operation", ["load_search_resources", "search"])
def test_setup_and_query_errors_fail_both_suites(
    inputs, tmp_path, monkeypatch, suite, operation
):
    def fail(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(runner, operation, fail)
    output = tmp_path / "error.json"
    assert runner.main([*inputs[2], "--suite", suite, "--output", str(output)]) == 2
    assert json.loads(output.read_text())["status"] == "error"


def test_empty_corpus_cannot_pass_benchmark(inputs, monkeypatch):
    monkeypatch.setattr(
        runner,
        "load_search_resources",
        lambda **kw: SimpleNamespace(metadata=[], usearch_index=[]),
    )
    assert runner.main([*inputs[2], "--suite", "benchmark"]) == 2


def test_baseline_reports_regression_and_recovery(inputs, monkeypatch, tmp_path):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    assert runner.main([*inputs[2], "--output", str(before)]) == 0
    monkeypatch.setattr(
        runner, "search", lambda *a, **kw: [{"url": "https://example.com/Q2"}]
    )
    assert (
        runner.main([*inputs[2], "--baseline", str(before), "--output", str(after)])
        == 0
    )
    comparison = json.loads(after.read_text())["comparison"]
    assert comparison["regressions"] == ["Q1"]
    assert comparison["recoveries"] == ["Q2"]
    assert comparison["delta"]["hit_at_5"] == 0


def test_changed_since_selects_only_new_and_edited_questions(
    inputs, tmp_path, monkeypatch
):
    rows, path, args = inputs

    def git(*args):
        subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True
        )

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    git("add", "suite.json")
    git("commit", "-m", "base")
    git("checkout", "-b", "feature")
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    unchanged = tmp_path / "unchanged.json"
    assert (
        runner.main([*args, "--changed-since", "main", "--output", str(unchanged)]) == 0
    )
    assert json.loads(unchanged.read_text())["status"] == "no_changed_questions"
    rows[0]["question"] = "edited question"
    path.write_text(json.dumps([*rows, {**rows[1], "id": "Q3"}]))
    output = tmp_path / "changed.json"
    assert runner.main([*args, "--changed-since", "main", "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert [case["question_id"] for case in report["cases"]] == ["Q1", "Q3"]
