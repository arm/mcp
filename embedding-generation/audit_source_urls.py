# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.

"""Report source availability and weekly missing history; never edit source data."""

import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from queue import Empty, Queue
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

FIELDS = [
    "url",
    "status",
    "http_status",
    "final_url",
    "detail",
    "checked_at",
    "first_missing_at",
    "action",
]
MISSING = {404, 410}
BLOCKED = {401, 403, 429}
AUDIT_BUDGET_SECONDS = 45 * 60


def budget_exhausted(url):
    return dict(
        url=url,
        status="uncertain",
        http_status="",
        final_url=url,
        detail="Audit time budget exhausted; check incomplete",
    )


def check_url(url, deadline=float("inf")):
    code, final_url, detail = 0, url, ""
    # Eight workers, each pausing before requests. Confirm missing responses once.
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return budget_exhausted(url)
        time.sleep(min(1 if attempt == 0 else 2, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return budget_exhausted(url)
        try:
            if urlsplit(url).scheme not in {"http", "https"}:
                raise ValueError("Expected an HTTP(S) URL")
            request = Request(
                url, headers={"User-Agent": "arm-mcp-source-url-audit/1.0"}
            )
            with urlopen(request, timeout=min(20, remaining)) as response:
                code, final_url, detail = response.status, response.geturl(), ""
        except HTTPError as error:
            with error:
                code, final_url, detail = error.code, error.geturl(), str(error)
        except (URLError, OSError, ValueError, HTTPException) as error:
            code, final_url, detail = 0, url, str(error)
        if time.monotonic() >= deadline:
            return budget_exhausted(url)
        if code not in MISSING:
            break
    status = "uncertain"
    if code in MISSING:
        status = "missing"
    elif code in BLOCKED:
        status = "blocked"
    elif 200 <= code < 300:
        status = "redirected" if final_url != url else "reachable"
    return dict(
        url=url,
        status=status,
        http_status=code or "",
        final_url=final_url,
        detail=detail,
    )


def missing_history(status, previous, now):
    if status != "missing":
        return dict(
            first_missing_at="",
            action={"uncertain": "investigate", "blocked": "retry"}.get(status, "keep"),
        )
    first = now
    if previous.get("status") == "missing":
        try:
            checked = datetime.fromisoformat(previous["checked_at"])
            started = datetime.fromisoformat(previous["first_missing_at"])
            if started <= checked < now and now - checked <= timedelta(days=14):
                first = started
        except (KeyError, ValueError, TypeError):
            pass  # Invalid, naive or missing timestamps cannot establish history.
    action = "review_removal" if now - first >= timedelta(days=7) else "watch"
    return dict(first_missing_at=first.isoformat(), action=action)


def fetch_backend_catalog():
    from ecosystem_dashboard import REPOSITORY, parse_catalog

    headers = {"User-Agent": "arm-mcp-source-url-audit/1.0"}
    url = f"https://api.github.com/repos/{REPOSITORY}/commits/main"
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        revision = json.load(response)["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid dashboard revision")
    url = f"https://codeload.github.com/{REPOSITORY}/tar.gz/{revision}"
    with urlopen(Request(url, headers=headers), timeout=60) as response:
        archive = response.read()
    return parse_catalog(archive, revision, require_content=True)


def verify_backend_content(urls, budget_seconds):
    targets = []
    for url in urls:
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue  # Let the HTTP checker report malformed URLs as uncertain.
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname == "developer.arm.com"
            and parsed.path
            in {"/ecosystem-dashboard/linux", "/ecosystem-dashboard/windows"}
        ):
            targets.append(url)
    if not targets:
        return {}
    started = time.monotonic()
    completed = Queue()

    def worker():
        try:
            completed.put(fetch_backend_catalog())
        except Exception as error:
            completed.put(error)

    if budget_seconds > 0:
        Thread(target=worker, daemon=True).start()
    try:
        catalog = completed.get(timeout=max(0, min(90, budget_seconds)))
    except Empty:
        catalog = TimeoutError("Backend check exceeded its time budget")
    results = {}
    for url in targets:
        result = dict(url=url, status="uncertain", http_status="", final_url=url)
        if isinstance(catalog, Exception):
            result["detail"] = f"Backend content could not be verified: {catalog}"
        elif packages := catalog.get(url):
            result.update(
                status="content_available",
                final_url=packages[0].document.resolved_url,
                detail="Backend description/body verified; public page not checked",
            )
        else:
            result["detail"] = (
                "No matching content record in the dashboard backend snapshot"
            )
        results[url] = result
    verified = sum(row["status"] == "content_available" for row in results.values())
    print(
        f"Backend verified {verified}/{len(targets)} dashboard sources in {time.monotonic() - started:.1f}s",
        file=sys.stderr,
        flush=True,
    )
    return results


def collect_checks(urls, budget_seconds):
    deadline = time.monotonic() + budget_seconds
    pending, completed = Queue(), Queue()
    stopped = Event()
    results = {}
    for url in urls:
        pending.put(url)

    def worker():
        while not stopped.is_set() and time.monotonic() < deadline:
            try:
                url = pending.get_nowait()
            except Empty:
                return
            try:
                result = check_url(url, deadline=deadline)
            except Exception as error:
                completed.put((url, error))
                return
            completed.put((url, result))

    # Daemon workers let report writing and process exit proceed even when DNS
    # or a socket operation ignores its timeout. Workers never write the report.
    for _ in range(min(8, len(urls))):
        Thread(target=worker, daemon=True).start()
    try:
        while len(results) < len(urls):
            try:
                url, result = completed.get(timeout=max(0, deadline - time.monotonic()))
            except Empty:
                break
            if isinstance(result, Exception):
                raise result
            results[url] = result
            if len(results) % 100 == 0:
                print(
                    f"Checked {len(results)}/{len(urls)} URLs",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        stopped.set()
    return [results.get(url, budget_exhausted(url)) for url in urls]


def verify_in_browser(checks, budget_seconds, channel="chromium"):
    blocked = {row["url"]: row for row in checks if row["http_status"] == 403}
    if not blocked or budget_seconds <= 0:
        return
    print(
        f"Browser-verifying {len(blocked)} blocked URLs...", file=sys.stderr, flush=True
    )
    with TemporaryDirectory(prefix="source-url-browser-") as temporary:
        source, output = (
            Path(temporary) / name for name in ("urls.json", "verified.jsonl")
        )
        source.write_text(json.dumps(list(blocked)), encoding="utf-8")
        command = [
            sys.executable,
            str(Path(__file__).with_name("audit_source_urls_browser.py")),
            str(source),
            str(output),
            "--budget-seconds",
            str(budget_seconds),
            "--channel",
            channel,
        ]
        # Keep completed browser results even if Chromium or its driver stalls.
        with subprocess.Popen(
            command, start_new_session=True, stdout=sys.stderr
        ) as process:
            try:
                process.wait(timeout=budget_seconds)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                print(
                    "Browser budget exhausted; keeping completed verifications.",
                    file=sys.stderr,
                )
            if process.returncode:
                print("Incomplete browser checks remain unverified.", file=sys.stderr)
        if output.exists():
            for line in output.read_text(encoding="utf-8").splitlines():
                try:
                    result = json.loads(line)
                except json.JSONDecodeError:
                    continue  # Killing the child may leave its last line partial.
                row = blocked.get(result.get("url"))
                if row is not None and 200 <= result.get("http_status", 0) < 300:
                    row.update(
                        status="redirected"
                        if result["final_url"] != row["url"]
                        else "reachable",
                        http_status=result["http_status"],
                        final_url=result["final_url"],
                        detail="Browser verified after HTTP 403: " + result["title"],
                    )


def print_summary(results):
    counts = Counter(row["action"] for row in results)
    counts["content_available"] = sum(
        row["status"] == "content_available" for row in results
    )
    counts["keep"] -= counts["content_available"]
    print("## Source URL audit\n")
    print(f"Reported {len(results):,} URLs. Report only; sources unchanged.\n")
    verified = sum(
        row.get("detail", "").startswith("Browser verified") for row in results
    )
    if verified:
        print(f"Browser fallback verified {verified:,} previously blocked URLs.\n")
    print("| Result | URLs |\n| --- | ---: |")
    for action, label in (
        ("content_available", "Backend content available"),
        ("keep", "Working pages"),
        ("retry", "Access blocked (automatic retry)"),
        ("watch", "Missing (watch for seven days)"),
        ("review_removal", "Persistent missing (manual removal review)"),
        ("investigate", "Other errors (investigate)"),
    ):
        print(f"| {label} | {counts[action]:,} |")

    def link(url):
        return "<" + quote(url, safe=":/?#[]@!$&'()*+,;=%") + ">"

    blocked = {}
    for row in results:
        if row["status"] == "blocked":
            host = urlsplit(row["final_url"] or row["url"]).hostname or "unknown"
            blocked.setdefault((host, str(row["http_status"])), []).append(row)
    if blocked:
        print("\n### Site access restrictions\n")
        print(
            "These URLs remain unverified and are automatically retried next run. "
            "Review access once per site; no individual URL review is requested. "
            "Access restrictions never qualify URLs for removal.\n"
        )
        print("| Site | HTTP | URLs | Example |\n| --- | --- | ---: | --- |")
        for (host, code), rows in sorted(blocked.items()):
            print(
                f"| {host} | {code} | {len(rows):,} | [Open]({link(rows[0]['url'])}) |"
            )

    followups = [
        row
        for action in ("review_removal", "watch", "investigate")
        for row in results
        if row["action"] == action
    ]
    if followups:
        print("\n### URL follow-up\n")
        print("| Action | HTTP | URL |\n| --- | --- | --- |")
        for row in followups[:20]:
            print(
                f"| {row['action']} | {row['http_status'] or 'No response'} | {link(row['url'])} |"
            )
        if len(followups) > 20:
            print(f"\nShowing 20 of {len(followups):,} follow-ups.")
    print("\nFull results and history: `source-url-audit.csv` in the report artifact.")


def run_audit(
    sources,
    output,
    previous=None,
    now=None,
    budget_seconds=AUDIT_BUDGET_SECONDS,
    browser_fallback=False,
    browser_channel="chromium",
    backend_content=False,
):
    sources, output = Path(sources), Path(output)
    if output.resolve() == sources.resolve() or (
        output.exists() and output.samefile(sources)
    ):
        raise ValueError("Report must not overwrite the source CSV")
    history = {}
    if previous is not None:
        with Path(previous).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if not {"url", "status", "checked_at", "first_missing_at"}.issubset(
                reader.fieldnames or []
            ):
                raise ValueError("Invalid previous report")
            history = {row["url"]: row for row in reader}
    with sources.open(newline="", encoding="utf-8") as handle:
        urls = {}
        reader = csv.DictReader(handle)
        if "URL" not in (reader.fieldnames or []):
            raise ValueError("Source CSV must contain URL")
        for row in reader:
            if not (row.get("URL") or "").strip():
                raise ValueError("Source CSV row has no URL")
            for column in ("URL", "Transcript Source URL"):
                if url := (row.get(column) or "").strip():
                    urls[url] = None
    now = now or datetime.now(timezone.utc)
    results = []
    print(f"Checking {len(urls)} unique URLs...", file=sys.stderr, flush=True)
    started = time.monotonic()
    deadline = started + budget_seconds
    checked = verify_backend_content(urls, budget_seconds) if backend_content else {}
    http_urls = [url for url in urls if url not in checked]
    for check in collect_checks(http_urls, max(0, deadline - time.monotonic())):
        checked[check["url"]] = check
    checks = [checked[url] for url in urls]
    if browser_fallback:
        verify_in_browser(checks, deadline - time.monotonic(), browser_channel)
    for check in checks:
        check.update(
            checked_at=now.isoformat(),
            **missing_history(check["status"], history.get(check["url"], {}), now),
        )
        results.append(check)
    # Publish only a complete report; failures preserve the previous output.
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=output.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(results)
    temporary.replace(output)
    print_summary(results)
    print(f"\nAudit duration: {time.monotonic() - started:.1f} seconds.")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-report", type=Path)
    parser.add_argument(
        "--browser-fallback",
        action="store_true",
        help="Verify HTTP 403 responses with Playwright Chromium",
    )
    parser.add_argument("--browser-channel", default="chromium")
    parser.add_argument(
        "--backend-content",
        action="store_true",
        help="Verify dashboard content from its published source repository",
    )
    args = parser.parse_args()
    if sys.version_info < (3, 13):
        parser.error("Use Python 3.13 or later for HTTP 308 redirect support")
    run_audit(
        args.sources,
        args.output,
        args.previous_report,
        browser_fallback=args.browser_fallback,
        browser_channel=args.browser_channel,
        backend_content=args.backend_content,
    )
