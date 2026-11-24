"""HTTP checks, weekly grace period and report-only guarantees."""

import csv
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
import yaml

import audit_source_urls as audit

NOW = datetime(2026, 11, 23, tzinfo=UTC)
URL = "https://example.com/guide"


@pytest.mark.parametrize(
    "codes,status",
    [
        ([404, 404], "missing"),
        ([410, 410], "missing"),
        ([404, 200], "redirected"),
        ([404, 503], "uncertain"),
        ([404, 0], "uncertain"),
        ([401], "uncertain"),
        ([403], "uncertain"),
        ([429], "uncertain"),
        ([500], "uncertain"),
        ([0], "uncertain"),
        ([200], "redirected"),
    ],
)
def test_http_outcomes(monkeypatch, codes, status):
    remaining = iter(codes)

    @contextmanager
    def open_url(request, timeout):
        assert request.get_method() == "GET"
        code = next(remaining)
        if not code:
            raise URLError("offline")
        if code >= 400:
            raise HTTPError(URL, code, "error", {}, None)
        yield SimpleNamespace(status=code, geturl=lambda: URL + "-new")

    monkeypatch.setattr(audit, "urlopen", open_url)
    monkeypatch.setattr(audit.time, "sleep", lambda _: None)
    result = audit.check_url(URL)
    assert result["status"] == status
    assert next(remaining, None) is None
    if status == "redirected":
        assert result["final_url"] == URL + "-new"


@pytest.mark.parametrize(
    "day,expected", [(0, "watch"), (6, "watch"), (7, "review_removal"), (15, "watch")]
)
def test_grace_period_and_stale_history(day, expected):
    first = audit.missing_history("missing", {}, NOW)
    previous = dict(first, status="missing", checked_at=NOW.isoformat())
    assert (
        audit.missing_history("missing", previous, NOW + timedelta(days=day))["action"]
        == expected
    )


@pytest.mark.parametrize("status", ["reachable", "redirected", "uncertain"])
def test_recovery_or_uncertainty_resets_history(status):
    previous = dict(
        status="missing", checked_at=NOW.isoformat(), first_missing_at=NOW.isoformat()
    )
    reset = audit.missing_history(status, previous, NOW + timedelta(days=7))
    assert reset["first_missing_at"] == ""
    assert (
        audit.missing_history(
            "missing", dict(reset, status=status), NOW + timedelta(days=14)
        )["action"]
        == "watch"
    )


@pytest.mark.parametrize(
    "timestamp", ["bad", "2026-11-23", "2026-12-23T00:00:00+00:00"]
)
def test_invalid_or_future_history_cannot_qualify(timestamp):
    previous = dict(status="missing", checked_at=timestamp, first_missing_at=timestamp)
    assert (
        audit.missing_history("missing", previous, NOW + timedelta(days=7))["action"]
        == "watch"
    )


def test_reports_check_both_columns_deduplicate_and_preserve_inputs(
    tmp_path, monkeypatch
):
    source, first, second = (
        tmp_path / name for name in ("sources.csv", "first.csv", "second.csv")
    )
    contents = f"URL,Transcript Source URL\n{URL},{URL}/transcript\n{URL},\n"
    source.write_text(contents)
    seen = []
    transcript_checked = Event()

    def check(url, deadline=None):
        if url == URL:
            assert transcript_checked.wait(5)
        seen.append(url)
        if url.endswith("/transcript"):
            transcript_checked.set()
        return dict(
            url=url, status="missing", http_status=404, final_url=url, detail=""
        )

    monkeypatch.setattr(audit, "check_url", check)
    audit.run_audit(source, first, now=NOW)
    assert sorted(seen) == [URL, URL + "/transcript"]
    assert [row["url"] for row in csv.DictReader(first.open())] == [
        URL,
        URL + "/transcript",
    ]
    original = first.read_bytes()
    assert all(row["action"] == "watch" for row in csv.DictReader(first.open()))
    audit.run_audit(source, second, previous=first, now=NOW + timedelta(days=7))
    assert all(
        row["action"] == "review_removal" for row in csv.DictReader(second.open())
    )
    assert source.read_text() == contents and first.read_bytes() == original
    with pytest.raises(ValueError, match="source CSV"):
        audit.run_audit(source, source)
    with pytest.raises(ValueError, match="previous report"):
        audit.run_audit(source, second, previous=source)

    def fail(url, deadline=None):
        raise RuntimeError("failure")

    monkeypatch.setattr(audit, "check_url", fail)
    with pytest.raises(RuntimeError):
        audit.run_audit(source, first)
    assert source.read_text() == contents and first.read_bytes() == original


def test_frequent_runs_do_not_shorten_grace_period():
    previous = {}
    for day in range(8):
        now = NOW + timedelta(days=day)
        result = audit.missing_history("missing", previous, now)
        assert result["action"] == ("review_removal" if day == 7 else "watch")
        previous = dict(result, status="missing", checked_at=now.isoformat())


@pytest.mark.parametrize("exit_code", [0, 1])
def test_workflow_distinguishes_no_history_from_lookup_failure(
    tmp_path, monkeypatch, exit_code
):
    root = Path(__file__).resolve().parents[2]
    assert not (root / ".github/workflows/source-url-audit.yml").exists()
    workflow = yaml.safe_load(
        (root / ".github/workflows/build-embeddings.yml").read_text()
    )
    script = next(
        step["run"]
        for step in workflow["jobs"]["source-url-audit"]["steps"]
        if step["name"] == "Download previous report"
    )
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        f'  *"--branch codex/test-url-audit"*) exit {exit_code};;\n'
        "  *) exit 99;;\nesac\n"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("GH_REPO", "arm/mcp")
    monkeypatch.setenv("GITHUB_RUN_ID", "100")
    monkeypatch.setenv("GITHUB_REF_NAME", "codex/test-url-audit")
    result = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == exit_code
    assert ("No previous report available" in result.stdout) == (exit_code == 0)


def test_budget_publishes_all_rows_without_waiting_for_stalled_requests(
    tmp_path, monkeypatch
):
    sources, previous, report = (
        tmp_path / name for name in ("sources.csv", "previous.csv", "report.csv")
    )
    urls = [f"{URL}/{i}" for i in range(10)]
    contents = "URL\n" + "\n".join(urls) + "\n"
    sources.write_text(contents)
    old = (NOW - timedelta(days=7)).isoformat()
    with previous.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=audit.FIELDS)
        writer.writeheader()
        writer.writerows(
            dict(url=url, status="missing", checked_at=old, first_missing_at=old)
            for url in urls
        )
    release, finished = Event(), Event()
    seen = []

    def check(url, deadline):
        seen.append(url)
        if url != urls[0]:
            release.wait(5)  # Deliberately ignore the request timeout/deadline.
            finished.set()
        return dict(
            url=url, status="reachable", http_status=200, final_url=url, detail=""
        )

    monkeypatch.setattr(audit, "check_url", check)
    try:
        rows = audit.run_audit(
            sources, report, previous=previous, now=NOW, budget_seconds=1
        )
        assert not finished.is_set(), "Report waited for a stalled request"
        assert [row["url"] for row in rows] == urls
        assert rows[0]["action"] == "keep"
        assert all(
            row["action"] == "investigate" and not row["first_missing_at"]
            for row in rows[1:]
        )
        assert all("budget" in row["detail"].lower() for row in rows[1:])
        assert len(seen) < len(urls), "Queued checks started after the budget expired"
        assert len(list(csv.DictReader(report.open()))) == len(urls)
        assert sources.read_text() == contents
    finally:
        release.set()


def test_budget_expiry_before_confirmation_is_not_missing(monkeypatch):
    clock = [0]
    calls = []

    def open_url(request, timeout):
        calls.append(request.full_url)
        clock[0] = 4
        raise HTTPError(URL, 404, "missing", {}, None)

    monkeypatch.setattr(audit.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(audit.time, "sleep", lambda _: None)
    monkeypatch.setattr(audit, "urlopen", open_url)
    assert audit.check_url(URL, deadline=3)["status"] == "uncertain"
    assert calls == [URL]


def test_stalled_workers_do_not_prevent_process_exit(tmp_path):
    source, report = tmp_path / "sources.csv", tmp_path / "report.csv"
    source.write_text(f"URL\n{URL}\n")
    script = """
import sys
from threading import Event
import audit_source_urls as audit

def stalled_check(url, deadline):
    Event().wait()

audit.check_url = stalled_check
audit.run_audit(sys.argv[1], sys.argv[2], budget_seconds=0.1)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(source), str(report)],
        cwd=Path(audit.__file__).parent,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    rows = list(csv.DictReader(report.open()))
    assert len(rows) == 1 and rows[0]["action"] == "investigate"
