"""One retrieval evaluator for PR smoke checks and weekly benchmarks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arm_kb_search import load_search_resources, search  # noqa: E402
from arm_kb_search.evaluation import (  # noqa: E402
    EvaluationCaseResult,
    EvaluationResult,
    evaluate_retrieval,
    load_eval_rows,
    suite_url_matches,
)


def valid_url(value):
    return (
        isinstance(value, str)
        and urlparse(value).scheme in ("http", "https")
        and bool(urlparse(value).netloc)
    )


def validate_rows(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Evaluation suite must be a nonempty JSON array")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each evaluation question must be an object")
        if any(
            not isinstance(row.get(key), str) or not row[key].strip()
            for key in ("id", "question")
        ):
            raise ValueError("Each question needs a nonempty ID and question")
        if row["id"] in seen:
            raise ValueError(f"Duplicate question ID: {row['id']}")
        seen.add(row["id"])
        urls = row.get("expected_urls")
        if (
            not isinstance(urls, list)
            or not urls
            or not all(valid_url(url) for url in urls)
        ):
            raise ValueError(
                f"{row['id']}: expected_urls must contain absolute HTTP(S) URLs"
            )
        if len(urls) != len(set(urls)):
            raise ValueError(f"{row['id']}: duplicate expected URL")
        for field in ("area", "topic", "intent"):
            if field in row and (
                not isinstance(row[field], str) or not row[field].strip()
            ):
                raise ValueError(f"{row['id']}: invalid {field}")
    return rows


def git(*args):
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def summarize(cases, top_k):
    return EvaluationResult.from_cases(
        [EvaluationCaseResult(**case) for case in cases]
    ).summary(top_k)


def group_summaries(rows, cases, top_k):
    by_id = {case["question_id"]: case for case in cases}
    return {
        f"by_{field}": {
            group: summarize(
                [by_id[row["id"]] for row in rows if row.get(field) == group], top_k
            )
            for group in sorted({row[field] for row in rows if field in row})
        }
        for field in ("area", "topic", "intent")
    }


def format_summary(report):
    """Render aggregate results for the terminal and GitHub Actions summary."""

    if report["status"] == "error":
        return (
            f"## {report['suite'].title()} unavailable\n\n"
            "The evaluation did not complete successfully. "
            "See the job log or JSON report for details.\n"
        )

    def percent(value):
        return f"{value:.2%}" if value is not None else "—"

    def pass_rate(counts):
        return counts["hits"] / counts["total"] if counts["total"] else None

    def compared(before, current, rate=True):
        display = percent if rate else lambda value: f"{value:.3f}"
        values = [
            display(value) if value is not None else "—" for value in (before, current)
        ]
        change = "—"
        if before is not None and current is not None:
            delta = current - before
            change = f"{delta * 100:+.2f} pp" if rate else f"{delta:+.3f}"
        return " | ".join([*values, change])

    summary = report["summary"]
    previous = (report.get("comparison") or {}).get("previous")
    lines = [
        f"## {report['suite'].title()} results",
        "",
        f"Pass = an accepted source retrieved within the top {report['top_k']} results.",
        "",
    ]
    if previous:
        before = previous["summary"]
        lines += [
            f"Questions: {summary['total']}.",
            "",
            "| Metric | Previous | Current | Change |",
            "| --- | ---: | ---: | ---: |",
            f"| Pass rate | {compared(pass_rate(before), pass_rate(summary))} |",
            *(
                f"| Hit@{k} | {compared(before[f'hit_at_{k}'], summary[f'hit_at_{k}'])} |"
                for k in (1, 3, 5)
            ),
            f"| MRR | {compared(before['mrr'], summary['mrr'], rate=False)} |",
        ]
    else:
        metrics = " | ".join(percent(summary[f"hit_at_{k}"]) for k in (1, 3, 5))
        mrr = f"{summary['mrr']:.3f}" if summary["mrr"] is not None else "—"
        lines += [
            "| Suite | Questions | Passed | Pass rate | Hit@1 | Hit@3 | Hit@5 | MRR |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            f"| {report['suite'].title()} | {summary['total']} | {summary['hits']} | {percent(pass_rate(summary))} | {metrics} | {mrr} |",
        ]
    if report.get("comparison_note") or (
        report["suite"] == "benchmark" and not previous
    ):
        lines += [
            "",
            report.get(
                "comparison_note",
                "Comparison unavailable: no previous report was supplied.",
            ),
        ]
    for field in ("intent", "topic"):
        groups = report.get(f"by_{field}", {})
        if groups:
            columns = (
                "Previous pass % | Current pass % | Change"
                if previous
                else "Passed | Pass rate"
            )
            lines += [
                "",
                f"### By {field}",
                "",
                f"| {field.title()} | Questions | {columns} |",
                "| --- | ---: | ---: | ---: |" + (" ---: |" if previous else ""),
            ]
            for label, counts in sorted(groups.items()):
                values = (
                    compared(
                        pass_rate(previous[f"by_{field}"][label]), pass_rate(counts)
                    )
                    if previous
                    else f"{counts['hits']} | {percent(pass_rate(counts))}"
                )
                label = label.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
                lines.append(f"| {label} | {counts['total']} | {values} |")
    return "\n".join(lines) + "\n"


def load_baseline(path, rows, suite, top_k):
    if not path:
        return None
    previous = json.loads(path.read_text())
    if (
        previous["suite"],
        previous["policy"],
        previous["top_k"],
        previous["status"],
    ) != (suite, f"{suite}-v1", top_k, "complete"):
        raise ValueError(
            "Baseline must be a complete run with the same suite, policy and depth"
        )
    expected = sorted(
        (r["id"], r["question"], sorted(r["expected_urls"])) for r in rows
    )
    actual = sorted(
        (c["question_id"], c["question"], sorted(c["expected_urls"]))
        for c in previous["cases"]
    )
    if actual != expected:
        raise ValueError(
            "Baseline must contain the same questions and accepted sources"
        )
    for case in previous["cases"]:
        rank = case["match_rank"]
        if case["error"] is not None or (
            rank is not None and (type(rank) is not int or not 1 <= rank <= top_k)
        ):
            raise ValueError("Baseline contains a query error or invalid rank")
    # Recompute aggregates instead of validating redundant cached metrics.
    previous["summary"] = summarize(previous["cases"], top_k)
    previous.update(group_summaries(rows, previous["cases"], top_k))
    return previous


def evaluate(args):
    if args.top_k < 1:
        raise ValueError("--top-k must be positive")
    eval_path = REPO_ROOT / "evals" / f"{args.suite}.json"
    rows = validate_rows(load_eval_rows(eval_path))
    print(f"{args.suite}: {len(rows)} questions; top-k={args.top_k}")
    report = {"suite_total": len(rows)}
    try:
        previous = load_baseline(args.baseline, rows, args.suite, args.top_k)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Baseline not used: {exc}", file=sys.stderr)
        previous = None
        report["comparison_note"] = (
            "Comparison unavailable: the previous report is missing, invalid, or incompatible."
        )
    resources = load_search_resources(
        metadata_path=str(args.metadata_path),
        usearch_index_path=str(args.index_path),
        model_path=str(args.model_path),
    )
    if (
        not resources.metadata
        or resources.usearch_index is None
        or len(resources.usearch_index) != len(resources.metadata)
    ):
        raise ValueError(
            "Corpus must have nonempty metadata and a matching vector index"
        )

    def retrieve_urls(question, k):
        results = search(question, resources, k=k)
        if not isinstance(results, list) or any(
            not isinstance(item, dict) or not valid_url(item.get("url"))
            for item in results
        ):
            raise ValueError("Retrieval returned malformed results or missing URLs")
        return [item["url"] for item in results]

    result = evaluate_retrieval(
        rows,
        retrieve_urls,
        args.top_k,
        url_matcher=lambda actual, expected: suite_url_matches(
            actual, expected, args.suite
        ),
    )
    cases = [asdict(case) for case in result.cases]
    report.update(
        status="error" if result.errors else "complete",
        cases=cases,
        summary=result.summary(args.top_k),
    )
    report.update(group_summaries(rows, cases, args.top_k))
    if previous and not result.errors:
        before = {
            c["question_id"] for c in previous["cases"] if c["match_rank"] is not None
        }
        after = {c["question_id"] for c in cases if c["match_rank"] is not None}
        report["comparison"] = {
            "baseline": str(args.baseline),
            "baseline_target": previous.get("target"),
            "previous": {
                key: previous[key] for key in ("summary", "by_topic", "by_intent")
            },
            "regressions": sorted(before - after),
            "recoveries": sorted(after - before),
            "delta": {
                key: report["summary"][key] - previous["summary"][key]
                for key in ("hit_at_1", "hit_at_3", "hit_at_5", "mrr")
                if report["summary"][key] is not None
            },
        }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("smoke", "benchmark"), default="benchmark")
    parser.add_argument("--index-path", type=Path, default=Path("usearch_index.bin"))
    parser.add_argument("--metadata-path", type=Path, default=Path("metadata.json"))
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, help="Write a new JSON report")
    parser.add_argument(
        "--baseline", type=Path, help="Compare with a compatible JSON report"
    )
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        print(
            f"Output already exists; choose a new report path: {args.output}",
            file=sys.stderr,
        )
        return 2
    try:
        report = evaluate(args)
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        report = {"status": "error", "error": str(exc)}
    report.update(
        format_version=1,
        suite=args.suite,
        policy=f"{args.suite}-v1",
        top_k=args.top_k,
        target=os.environ.get("EVAL_TARGET"),
        source_revision=os.environ.get("GITHUB_SHA"),
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    if not report["source_revision"]:
        try:
            report["source_revision"] = git("rev-parse", "HEAD")
        except (OSError, subprocess.CalledProcessError):
            pass
    try:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        if "summary" in report or report["status"] == "error":
            summary_text = format_summary(report)
            print(summary_text)
            if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(summary_path, "a", encoding="utf-8") as summary_file:
                    summary_file.write(summary_text + "\n")
            if args.suite == "smoke":
                for case in report.get("cases", []):
                    if case["match_rank"] is None:
                        print(
                            f"{case['question_id']}: {case['error'] or 'MISS'}; expected={case['expected_urls']}; got={case['ranked_urls']}"
                        )
    except OSError as exc:
        print(f"Could not write report: {exc}", file=sys.stderr)
        return 2
    if report["status"] == "error":
        return 2
    if args.suite == "smoke" and report.get("summary", {}).get("misses"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
