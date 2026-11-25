"""Backend content verification must not confuse source data with public page status."""

import csv
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import audit_source_urls as audit

URL = "https://developer.arm.com/ecosystem-dashboard/linux?package=example"
BACKEND = (
    "https://raw.githubusercontent.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/"
    + "a" * 40
    + "/content/linux/opensource_packages/example.md"
)


def test_backend_records_skip_http_and_reset_missing_history(tmp_path, monkeypatch):
    source, report, previous = (
        tmp_path / name for name in ["sources.csv", "report.csv", "previous.csv"]
    )
    other = "https://example.com/guide"
    source.write_text(f"URL\n{URL}\n{other}\n")
    now = datetime(2026, 11, 25, tzinfo=UTC)
    old = (now - timedelta(days=7)).isoformat()
    with previous.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=audit.FIELDS)
        writer.writeheader()
        writer.writerow(
            dict(url=URL, status="missing", checked_at=old, first_missing_at=old)
        )
    catalog = {URL: [SimpleNamespace(document=SimpleNamespace(resolved_url=BACKEND))]}
    monkeypatch.setattr(audit, "fetch_backend_catalog", lambda: catalog)
    seen = []

    def check(url, deadline):
        seen.append(url)
        return dict(
            url=url, status="reachable", http_status=200, final_url=url, detail=""
        )

    monkeypatch.setattr(audit, "check_url", check)
    rows = audit.run_audit(
        source, report, previous=previous, now=now, backend_content=True
    )
    assert seen == [other]
    assert rows[0]["status"] == "content_available" and rows[0]["action"] == "keep"
    assert rows[0]["http_status"] == "" and rows[0]["final_url"] == BACKEND
    assert not rows[0]["first_missing_at"]
    assert rows[1]["status"] == "reachable"
    assert len(list(csv.DictReader(report.open()))) == 2


def test_absent_record_and_failed_backend_are_never_good_or_missing(monkeypatch):
    monkeypatch.setattr(audit, "fetch_backend_catalog", lambda: {})
    rows = audit.verify_backend_content([URL], budget_seconds=1)
    assert rows[URL]["status"] == "uncertain"
    assert "No matching content" in rows[URL]["detail"]

    def fail():
        raise OSError("backend unavailable")

    monkeypatch.setattr(audit, "fetch_backend_catalog", fail)
    rows = audit.verify_backend_content([URL], budget_seconds=1)
    assert rows[URL]["status"] == "uncertain"
    assert "backend unavailable" in rows[URL]["detail"]


def test_stalled_backend_obeys_budget(monkeypatch):
    def stall():
        time.sleep(5)
        return {}

    monkeypatch.setattr(audit, "fetch_backend_catalog", stall)
    started = time.monotonic()
    rows = audit.verify_backend_content([URL], budget_seconds=0.1)
    assert time.monotonic() - started < 2
    assert rows[URL]["status"] == "uncertain"
    assert "budget" in rows[URL]["detail"]


@pytest.mark.parametrize(
    "url",
    ["https://example.com/guide", "https://[invalid", URL.replace("https:", "ftp:")],
)
def test_no_dashboard_urls_never_fetch_catalog(monkeypatch, url):
    def unexpected():
        raise AssertionError("Unexpected backend request")

    monkeypatch.setattr(audit, "fetch_backend_catalog", unexpected)
    assert audit.verify_backend_content([url], budget_seconds=10) == {}
