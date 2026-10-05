"""Cover full-suite smoke checks, benchmark reports, and comparisons."""

import json
from types import SimpleNamespace

import pytest
from arm_kb_search.evaluation import evaluate_retrieval

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
    suites = tmp_path / "evals"
    suites.mkdir()
    for suite in ("smoke", "benchmark"):
        (suites / f"{suite}.json").write_text(json.dumps(rows))
    path = suites / "benchmark.json"
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "load_search_resources",
        lambda **kw: SimpleNamespace(metadata=[{}], usearch_index=[0]),
    )
    # Q1 passes and Q2 misses; scoring, reporting, and CLI behavior stay real.
    monkeypatch.setattr(
        runner, "search", lambda *a, **kw: [{"url": "https://example.com/Q1"}]
    )
    return rows, path, ["--model-path", str(tmp_path)]


@pytest.mark.parametrize("all_match,exit_code", [(False, 1), (True, 0)])
def test_smoke_gate_requires_all_questions(
    inputs, tmp_path, monkeypatch, all_match, exit_code
):
    if all_match:
        answers = {row["question"]: row["expected_urls"][0] for row in inputs[0]}
        monkeypatch.setattr(
            runner, "search", lambda question, *a, **kw: [{"url": answers[question]}]
        )
    output = tmp_path / "smoke.json"
    assert (
        runner.main([*inputs[2], "--suite", "smoke", "--output", str(output)])
        == exit_code
    )
    report = json.loads(output.read_text())
    assert [case["question_id"] for case in report["cases"]] == ["Q1", "Q2"]
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
    inputs, tmp_path, monkeypatch, capsys, suite, operation
):
    def fail(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(runner, operation, fail)
    output = tmp_path / "error.json"
    assert runner.main([*inputs[2], "--suite", suite, "--output", str(output)]) == 2
    assert json.loads(output.read_text())["status"] == "error"
    if suite == "benchmark":
        printed = capsys.readouterr().out
        assert "Benchmark unavailable" in printed
        assert "| Benchmark |" not in printed


def test_empty_corpus_cannot_pass_benchmark(inputs, monkeypatch):
    monkeypatch.setattr(
        runner,
        "load_search_resources",
        lambda **kw: SimpleNamespace(metadata=[], usearch_index=[]),
    )
    assert runner.main([*inputs[2], "--suite", "benchmark"]) == 2


@pytest.mark.parametrize("depth", [1, 5])
def test_shared_metrics_count_ranks_misses_and_errors(depth):
    rows = [
        {"question": str(rank), "expected_urls": ["https://example.com/hit"]}
        for rank in (1, 3, 5, 0, -1)
    ]

    def retrieve(question, k):
        rank = int(question)
        if rank == -1:
            raise RuntimeError("query failed")
        return ["https://example.com/miss"] * (rank - 1) + (
            ["https://example.com/hit"] if rank else []
        )

    result = evaluate_retrieval(rows, retrieve, depth)
    summary = result.summary(depth)
    assert (
        summary["total"],
        summary["hits"],
        summary["misses"],
        summary["errors"],
    ) == (5, 1 if depth == 1 else 3, 3 if depth == 1 else 1, 1)
    assert summary["hit_at_1"] == result.hit_at_1 == 0.2
    assert summary["mrr"] == pytest.approx(0.2 if depth == 1 else 0.3066666667)
    assert summary["mrr"] == result.mrr
    assert summary["hit_at_3"] == (None if depth == 1 else 0.4)
    assert summary["hit_at_5"] == (None if depth == 1 else 0.6)


def test_baseline_reports_regression_and_recovery(
    inputs, monkeypatch, tmp_path, capsys
):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    assert runner.main([*inputs[2], "--output", str(before)]) == 0
    saved = json.loads(before.read_text())
    for case in saved["cases"]:
        case["reciprocal_rank"] = 999  # Baseline metrics must come from ranks.
    before.write_text(json.dumps(saved))
    capsys.readouterr()
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
    printed = capsys.readouterr().out
    assert "| Metric | Previous | Current | Change |" in printed
    assert "| Pass rate | 50.00% | 50.00% | +0.00 pp |" in printed
    assert "| MRR | 0.500 | 0.500 | +0.000 |" in printed
    assert "| setup | 1 | 100.00% | 0.00% | -100.00 pp |" in printed
    assert "| reference | 1 | 0.00% | 100.00% | +100.00 pp |" in printed
    assert "| cloud | 2 | 50.00% | 50.00% | +0.00 pp |" in printed
    assert all(value not in printed for value in ("Q1", "Q2", "https://", "MISS"))


@pytest.mark.parametrize("baseline", ["missing", "changed", "invalid"])
def test_unavailable_baseline_still_reports_current_results(
    inputs, tmp_path, capsys, baseline
):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    if baseline != "missing":
        assert runner.main([*inputs[2], "--output", str(before)]) == 0
        if baseline == "changed":
            inputs[0][0]["question"] = "edited question"
            inputs[1].write_text(json.dumps(inputs[0]))
        else:
            before.write_text("{}")
    capsys.readouterr()
    assert (
        runner.main([*inputs[2], "--baseline", str(before), "--output", str(after)])
        == 0
    )
    report = json.loads(after.read_text())
    assert report["summary"]["total"] == 2
    assert "comparison" not in report
    assert "Comparison unavailable" in capsys.readouterr().out
