# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.

"""Report HTTP availability and weekly missing history; never edit source data."""

import argparse
import csv
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
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


def check_url(url):
    code, final_url, detail = 0, url, ""
    # Four workers, each pausing before requests. Confirm missing responses once.
    for attempt in range(2):
        time.sleep(1 if attempt == 0 else 2)
        try:
            if urlsplit(url).scheme not in {"http", "https"}:
                raise ValueError("Expected an HTTP(S) URL")
            request = Request(
                url, headers={"User-Agent": "arm-mcp-source-url-audit/1.0"}
            )
            with urlopen(request, timeout=20) as response:
                code, final_url, detail = response.status, response.geturl(), ""
        except HTTPError as error:
            with error:
                code, final_url, detail = error.code, error.geturl(), str(error)
        except (URLError, OSError, ValueError, HTTPException) as error:
            code, final_url, detail = 0, url, str(error)
        if code not in MISSING:
            break
    status = "uncertain"
    if code in MISSING:
        status = "missing"
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
            action="investigate" if status == "uncertain" else "keep",
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


def run_audit(sources, output, previous=None, now=None):
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
    with ThreadPoolExecutor(max_workers=4) as pool:
        for check in pool.map(check_url, urls):
            check.update(
                checked_at=now.isoformat(),
                **missing_history(check["status"], history.get(check["url"], {}), now),
            )
            results.append(check)
            if len(results) % 100 == 0:
                print(
                    f"Checked {len(results)}/{len(urls)} URLs",
                    file=sys.stderr,
                    flush=True,
                )
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
    print(f"Checked {len(results)} URLs. Report only; sources unchanged.\n")
    for action, count in sorted(Counter(row["action"] for row in results).items()):
        print(f"- {action}: {count}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-report", type=Path)
    args = parser.parse_args()
    if sys.version_info < (3, 13):
        parser.error("Use Python 3.13 or later for HTTP 308 redirect support")
    run_audit(args.sources, args.output, args.previous_report)
