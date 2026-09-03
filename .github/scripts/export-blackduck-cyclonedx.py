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

#!/usr/bin/env python3
"""Export a completed Black Duck project version as CycloneDX 1.6 JSON."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import BadZipFile, ZipFile


REPORT_MEDIA_TYPE = "application/vnd.blackducksoftware.report-4+json"
SCAN_MEDIA_TYPE = "application/vnd.blackducksoftware.scan-4+json"
CYCLONEDX_REPORT = {
    "reportFormat": "JSON",
    "reportType": "SBOM",
    "sbomType": "CYCLONEDX_16",
    "specification": "CycloneDX-1.6",
}


class BlackDuckExportError(RuntimeError):
    """Raised when Black Duck cannot produce a valid SBOM export."""


class SameOriginRedirectHandler(HTTPRedirectHandler):
    """Prevent credentials from following redirects to another origin."""

    def __init__(self, origin: tuple[str, str]):
        super().__init__()
        self.origin = origin

    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        resolved = urljoin(request.full_url, new_url)
        parsed = urlsplit(resolved)
        if (parsed.scheme, parsed.netloc) != self.origin:
            raise BlackDuckExportError(
                "Black Duck redirected an authenticated request outside the "
                "configured server."
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            resolved,
        )


class BlackDuckClient:
    def __init__(self, base_url: str, api_token: str, request_timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise BlackDuckExportError(
                "The Black Duck URL must be an absolute HTTPS URL."
            )
        self.origin = (parsed.scheme, parsed.netloc)
        self.api_token = api_token
        self.bearer_token = ""
        self.request_timeout = request_timeout
        self.opener = build_opener(SameOriginRedirectHandler(self.origin))

    def _trusted_url(self, url: str) -> str:
        resolved = urljoin(f"{self.base_url}/", url)
        parsed = urlsplit(resolved)
        if (parsed.scheme, parsed.netloc) != self.origin:
            raise BlackDuckExportError(
                "Black Duck returned an API URL outside the configured server."
            )
        return resolved

    def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        content_type: str | None = None,
        accept: str = "application/json",
        use_api_token: bool = False,
    ) -> tuple[bytes, dict[str, str]]:
        trusted_url = self._trusted_url(url)
        headers = {
            "Accept": accept,
            "User-Agent": "arm-mcp-blackduck-sbom-export/1.0",
        }
        if content_type:
            headers["Content-Type"] = content_type
        if use_api_token:
            headers["Authorization"] = f"token {self.api_token}"
        else:
            if not self.bearer_token:
                raise BlackDuckExportError("Black Duck authentication is missing.")
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        request = Request(
            trusted_url,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=self.request_timeout) as response:
                return response.read(), dict(response.headers.items())
        except HTTPError as error:
            raise BlackDuckExportError(
                f"Black Duck API request failed with HTTP {error.code}."
            ) from error
        except URLError as error:
            raise BlackDuckExportError(
                "Black Duck API request could not be completed."
            ) from error

    def _json_request(self, url: str, **kwargs: Any) -> dict[str, Any]:
        response, _ = self._request(url, **kwargs)
        try:
            parsed = json.loads(response)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise BlackDuckExportError(
                "Black Duck returned an invalid JSON response."
            ) from error
        if not isinstance(parsed, dict):
            raise BlackDuckExportError(
                "Black Duck returned an unexpected JSON response."
            )
        return parsed

    def authenticate(self) -> None:
        response = self._json_request(
            f"{self.base_url}/api/tokens/authenticate",
            method="POST",
            body=b"",
            use_api_token=True,
        )
        bearer_token = response.get("bearerToken")
        if not isinstance(bearer_token, str) or not bearer_token:
            raise BlackDuckExportError(
                "Black Duck authentication returned no bearer token."
            )
        self.bearer_token = bearer_token

    def _find_exact_resource(
        self,
        url: str,
        *,
        field: str,
        expected: str,
        resource_name: str,
    ) -> str:
        response = self._json_request(url)
        items = response.get("items", [])
        if not isinstance(items, list):
            raise BlackDuckExportError(
                f"Black Duck returned invalid {resource_name} results."
            )
        matches = [
            item
            for item in items
            if isinstance(item, dict) and item.get(field) == expected
        ]
        if len(matches) != 1:
            raise BlackDuckExportError(
                f"Expected one exact Black Duck {resource_name} named {expected!r}; "
                f"found {len(matches)}."
            )
        metadata = matches[0].get("_meta", {})
        href = metadata.get("href") if isinstance(metadata, dict) else None
        if not isinstance(href, str) or not href:
            raise BlackDuckExportError(
                f"Black Duck {resource_name} response has no API URL."
            )
        return self._trusted_url(href)

    def project_version_url(self, project_name: str, version_name: str) -> str:
        project_query = urlencode({"q": f"name:{project_name}"})
        project_url = self._find_exact_resource(
            f"{self.base_url}/api/projects?{project_query}",
            field="name",
            expected=project_name,
            resource_name="project",
        )
        version_query = urlencode({"q": f"versionName:{version_name}"})
        return self._find_exact_resource(
            f"{project_url}/versions?{version_query}",
            field="versionName",
            expected=version_name,
            resource_name="project version",
        )

    def wait_for_server_scan(
        self, version_url: str, *, timeout: int, poll_interval: int
    ) -> None:
        deadline = time.monotonic() + timeout
        while True:
            response = self._json_request(
                f"{version_url}/codelocations", accept=SCAN_MEDIA_TYPE
            )
            pending = False
            items = response.get("items", [])
            if not isinstance(items, list):
                raise BlackDuckExportError(
                    "Black Duck returned invalid code-location results."
                )
            for item in items:
                if not isinstance(item, dict):
                    continue
                statuses = item.get("status", [])
                if not isinstance(statuses, list):
                    continue
                for status in statuses:
                    if not isinstance(status, dict):
                        continue
                    if status.get("operationNameCode") != "ServerScanning":
                        continue
                    state = status.get("status")
                    if state in {"FAILED", "ERROR"}:
                        raise BlackDuckExportError(
                            "Black Duck server-side container processing failed."
                        )
                    if state != "COMPLETED":
                        pending = True
            if not pending:
                return
            if time.monotonic() >= deadline:
                raise BlackDuckExportError(
                    "Timed out waiting for Black Duck server-side processing."
                )
            time.sleep(poll_interval)

    def _reports(self, version_url: str) -> list[dict[str, Any]]:
        response = self._json_request(
            f"{version_url}/reports", accept=REPORT_MEDIA_TYPE
        )
        items = response.get("items", [])
        if not isinstance(items, list):
            raise BlackDuckExportError("Black Duck returned invalid report results.")
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _report_href(report: dict[str, Any]) -> str | None:
        metadata = report.get("_meta", {})
        href = metadata.get("href") if isinstance(metadata, dict) else None
        return href if isinstance(href, str) and href else None

    def create_cyclonedx_report(
        self, version_url: str, *, timeout: int, poll_interval: int
    ) -> str:
        existing_reports = {
            href
            for report in self._reports(version_url)
            if (href := self._report_href(report)) is not None
        }
        report_body = json.dumps(CYCLONEDX_REPORT).encode("utf-8")
        _, headers = self._request(
            f"{version_url}/sbom-reports",
            method="POST",
            body=report_body,
            content_type=REPORT_MEDIA_TYPE,
            accept=REPORT_MEDIA_TYPE,
        )
        location = headers.get("Location") or headers.get("location")
        requested_report = self._trusted_url(location) if location else None

        deadline = time.monotonic() + timeout
        while True:
            candidates = []
            for report in self._reports(version_url):
                href = self._report_href(report)
                if href is None:
                    continue
                trusted_href = self._trusted_url(href)
                if requested_report:
                    if trusted_href == requested_report:
                        candidates.append((trusted_href, report))
                elif (
                    href not in existing_reports
                    and trusted_href not in existing_reports
                ):
                    candidates.append((trusted_href, report))

            if candidates:
                report_url, report = max(
                    candidates,
                    key=lambda candidate: str(
                        candidate[1].get("createdAt")
                        or candidate[1].get("updatedAt")
                        or candidate[0]
                    ),
                )
                status = report.get("status")
                if status == "COMPLETED":
                    return report_url
                if status in {"FAILED", "ERROR", "CANCELLED"}:
                    raise BlackDuckExportError(
                        f"Black Duck CycloneDX report generation ended with {status}."
                    )

            if time.monotonic() >= deadline:
                raise BlackDuckExportError(
                    "Timed out waiting for the Black Duck CycloneDX report."
                )
            time.sleep(poll_interval)

    def download_report(self, report_url: str) -> bytes:
        report, _ = self._request(
            f"{report_url}/download.zip", accept="application/zip"
        )
        if not report:
            raise BlackDuckExportError("Black Duck returned an empty report archive.")
        return report


def extract_cyclonedx_json(report_archive: bytes) -> bytes:
    try:
        with ZipFile(BytesIO(report_archive)) as archive:
            valid_reports: list[bytes] = []
            for member in archive.infolist():
                if member.is_dir() or not member.filename.lower().endswith(".json"):
                    continue
                content = archive.read(member)
                try:
                    report = json.loads(content)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if (
                    isinstance(report, dict)
                    and report.get("bomFormat") == "CycloneDX"
                    and report.get("specVersion") == "1.6"
                ):
                    valid_reports.append(content)
    except BadZipFile as error:
        raise BlackDuckExportError(
            "Black Duck returned an invalid report archive."
        ) from error

    if len(valid_reports) != 1:
        raise BlackDuckExportError(
            "Expected one CycloneDX 1.6 JSON document in the Black Duck report "
            f"archive; found {len(valid_reports)}."
        )
    return valid_reports[0]


def write_report(output: Path, content: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_bytes(content)
    temporary.replace(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blackduck-url", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--poll-interval", type=int, default=15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_token = os.environ.get("BLACKDUCK_TOKEN", "")
    if not api_token:
        print("Black Duck API token is missing.", file=sys.stderr)
        return 1
    if args.timeout <= 0 or args.poll_interval <= 0:
        print("Timeout and poll interval must be positive.", file=sys.stderr)
        return 1

    try:
        client = BlackDuckClient(args.blackduck_url, api_token)
        client.authenticate()
        version_url = client.project_version_url(args.project, args.version)
        client.wait_for_server_scan(
            version_url,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
        )
        report_url = client.create_cyclonedx_report(
            version_url,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
        )
        report = extract_cyclonedx_json(client.download_report(report_url))
        write_report(args.output, report)
    except (BlackDuckExportError, OSError) as error:
        print(f"Black Duck CycloneDX export failed: {error}", file=sys.stderr)
        return 1

    print(f"Exported Black Duck CycloneDX 1.6 SBOM to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
