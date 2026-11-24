"""Browser fallback must verify rendered content before upgrading blocked URLs."""

import subprocess
import sys

import pytest

import audit_source_urls as audit
from audit_source_urls_browser import usable_page

URL = "https://developer.arm.com/documentation/101897/latest/"
BODY = "Arm GPU Best Practices Developer Guide. " * 10


@pytest.mark.parametrize(
    "title,body,final_url,expected",
    [
        (
            "Arm GPU Best Practices Developer Guide",
            BODY,
            "https://support.arm.com/documentation/101897/latest/",
            True,
        ),
        ("Documentation – Arm Developer", BODY, URL, False),
        ("Access Denied", BODY, URL, False),
        ("Just a moment...", BODY, URL, False),
        ("Sign in", BODY, URL, False),
        ("404 Page not found", BODY, URL, False),
        ("Arm GPU Best Practices Developer Guide", "", URL, False),
        (
            "Arm GPU Best Practices Developer Guide",
            BODY,
            "https://login.arm.com/login",
            False,
        ),
    ],
)
def test_rendered_document_validation(title, body, final_url, expected):
    assert usable_page(URL, final_url, title, body) is expected


def test_dashboard_requires_a_selected_package():
    url = "https://developer.arm.com/ecosystem-dashboard/linux?package=anaconda"
    assert usable_page(url, url, "Anaconda - Ecosystem Dashboard for Arm", BODY)
    assert not usable_page(url, url, "Software Ecosystem Dashboard for Arm", BODY)


def test_partial_browser_results_survive_a_stalled_browser(monkeypatch):
    checks = [
        dict(
            url=url,
            status="blocked",
            http_status=403,
            final_url=url,
            detail="Forbidden",
        )
        for url in [URL, URL + "other"]
    ]
    popen = subprocess.Popen
    started = []

    def browser_process(command, **kwargs):
        script = r"""
import json, sys, time
from pathlib import Path
url = json.loads(Path(sys.argv[1]).read_text())[0]
with Path(sys.argv[2]).open('w') as output:
    output.write(json.dumps(dict(url=url, final_url=url, http_status=200, title='Working guide')) + '\n')
    output.flush()
time.sleep(60)
"""
        process = popen(
            [sys.executable, "-c", script, command[2], command[3]], **kwargs
        )
        started.append(process)
        return process

    monkeypatch.setattr(audit.subprocess, "Popen", browser_process)
    audit.verify_in_browser(checks, budget_seconds=1)
    assert started[0].poll() is not None
    assert checks[0]["status"] == "reachable"
    assert checks[0]["http_status"] == 200
    assert checks[0]["detail"].startswith("Browser verified after HTTP 403")
    assert checks[1]["status"] == "blocked"


def test_browser_failure_does_not_make_blocked_urls_healthy(monkeypatch):
    checks = [
        dict(
            url=URL,
            status="blocked",
            http_status=403,
            final_url=URL,
            detail="Forbidden",
        )
    ]
    popen = subprocess.Popen

    def failed_browser(command, **kwargs):
        return popen([sys.executable, "-c", "raise SystemExit(1)"], **kwargs)

    monkeypatch.setattr(audit.subprocess, "Popen", failed_browser)
    audit.verify_in_browser(checks, budget_seconds=5)
    assert checks[0]["status"] == "blocked"


def test_browser_verification_resets_missing_history(tmp_path, monkeypatch):
    import csv
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 11, 24, tzinfo=UTC)
    source, report, previous = (
        tmp_path / name for name in ["sources.csv", "report.csv", "previous.csv"]
    )
    source.write_text(f"URL\n{URL}\n")
    old = (now - timedelta(days=7)).isoformat()
    with previous.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=audit.FIELDS)
        writer.writeheader()
        writer.writerow(
            dict(url=URL, status="missing", checked_at=old, first_missing_at=old)
        )
    monkeypatch.setattr(
        audit,
        "check_url",
        lambda url, deadline: dict(
            url=url,
            status="blocked",
            http_status=403,
            final_url=url,
            detail="Forbidden",
        ),
    )
    calls = []

    def verify(checks, budget_seconds, channel):
        calls.append(budget_seconds)
        checks[0].update(
            status="redirected",
            http_status=200,
            final_url="https://support.arm.com/documentation/101897/latest/",
            detail="Browser verified after HTTP 403",
        )

    monkeypatch.setattr(audit, "verify_in_browser", verify)
    rows = audit.run_audit(
        source, report, previous=previous, now=now, browser_fallback=True
    )
    assert len(calls) == 1 and 0 < calls[0] <= audit.AUDIT_BUDGET_SECONDS
    assert rows[0]["action"] == "keep" and not rows[0]["first_missing_at"]


@pytest.mark.parametrize(
    "code,status,budget",
    [(200, "reachable", 5), (429, "blocked", 5), (403, "blocked", 0)],
)
def test_browser_only_rechecks_forbidden_urls_with_remaining_budget(
    monkeypatch, code, status, budget
):
    def unexpected(*args, **kwargs):
        raise AssertionError("Browser should not have started")

    monkeypatch.setattr(audit.subprocess, "Popen", unexpected)
    checks = [dict(url=URL, status=status, http_status=code, final_url=URL, detail="")]
    audit.verify_in_browser(checks, budget_seconds=budget)
    assert checks[0]["status"] == status
