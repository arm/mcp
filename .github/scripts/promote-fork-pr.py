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
"""Promote an exact fork pull-request revision to a branch in arm/mcp."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ALLOWED_REPOSITORY = "arm/mcp"
BASE_BRANCH = "main"
TRUSTED_PERMISSIONS = {"write", "maintain", "admin"}
WORKFLOW_DIRECTORY = ".github/workflows/"
SHA_PATTERN = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")
LOGIN_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")


class ApiError(RuntimeError):
    """A GitHub API response outside the expected success range."""

    def __init__(self, status: int, method: str, url: str, detail: str) -> None:
        message = f"GitHub API {method} {url} failed with HTTP {status}: {detail}"
        super().__init__(message)
        self.status = status


class GitHubApi:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, str | int] | None = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                body = response.read()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise ApiError(error.code, method, url, detail) from error
        if not body:
            return None
        return json.loads(body)

    def get(self, path: str, query: dict[str, str | int] | None = None) -> Any:
        return self.request("GET", path, query=query)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request("POST", path, payload=payload)

    def patch(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request("PATCH", path, payload=payload)


def is_trusted_permission(permission: str) -> bool:
    return permission.lower() in TRUSTED_PERMISSIONS


def promotion_branch(
    mode: str, username: str, pull_number: int, expected_sha: str
) -> str:
    if not SHA_PATTERN.fullmatch(expected_sha):
        raise ValueError(
            "expected SHA must be a full 40- or 64-character hexadecimal ID"
        )
    if pull_number < 1:
        raise ValueError("pull request number must be positive")
    sha = expected_sha.lower()
    if mode == "manual":
        return f"external-contributions/pr-{pull_number}-{sha}"
    if mode != "auto":
        raise ValueError(f"unsupported promotion mode: {mode}")
    if not LOGIN_PATTERN.fullmatch(username):
        raise ValueError(f"unsafe GitHub username for branch name: {username!r}")
    return f"trusted-fork-{username}/pr-{pull_number}-{sha}"


def validate_source_pr(
    pull: dict[str, Any], repository: str, pull_number: int, expected_sha: str
) -> dict[str, str]:
    if pull.get("number") != pull_number:
        raise ValueError("GitHub returned a different pull request number")
    if pull.get("state") != "open":
        raise ValueError(f"pull request #{pull_number} is not open")
    if pull.get("draft"):
        raise ValueError(f"pull request #{pull_number} is still a draft")

    base = pull.get("base") or {}
    base_repo = base.get("repo") or {}
    if base_repo.get("full_name") != repository or base.get("ref") != BASE_BRANCH:
        raise ValueError(
            f"pull request #{pull_number} must target {repository}:{BASE_BRANCH}"
        )

    head = pull.get("head") or {}
    head_repo = head.get("repo") or {}
    if not head_repo or head_repo.get("full_name") == repository:
        raise ValueError(f"pull request #{pull_number} is not from a fork")
    if not head_repo.get("fork"):
        raise ValueError(f"pull request #{pull_number} head repository is not a fork")

    actual_sha = str(head.get("sha", "")).lower()
    if not SHA_PATTERN.fullmatch(expected_sha) or actual_sha != expected_sha.lower():
        raise ValueError(
            f"pull request #{pull_number} head changed: expected {expected_sha}, "
            f"found {actual_sha or 'unavailable'}"
        )

    author = str((pull.get("user") or {}).get("login", ""))
    return {
        "author": author,
        "head_repository": str(head_repo.get("full_name", "")),
        "html_url": str(pull.get("html_url", "")),
        "sha": actual_sha,
    }


def collaborator_permission(api: GitHubApi, repository: str, username: str) -> str:
    if not username:
        return "none"
    try:
        result = api.get(
            f"/repos/{repository}/collaborators/{quote(username, safe='')}/permission"
        )
    except ApiError as error:
        # GitHub can return 404 when the user has no relationship to the repo.
        if error.status == 404:
            return "none"
        raise
    return str(result.get("permission", "none")).lower()


def ensure_ref(api: GitHubApi, repository: str, branch: str, sha: str) -> None:
    ref_path = f"/repos/{repository}/git/ref/heads/{quote(branch, safe='/')}"
    try:
        existing = api.get(ref_path)
    except ApiError as error:
        if error.status != 404:
            raise
    else:
        existing_sha = str((existing.get("object") or {}).get("sha", ""))
        if existing_sha != sha:
            raise RuntimeError(
                f"existing promotion branch {branch} points to "
                f"{existing_sha}, not {sha}"
            )
        return

    try:
        api.post(
            f"/repos/{repository}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": sha},
        )
    except ApiError as error:
        # A concurrent run may have created the same SHA-addressed ref.
        if error.status != 422:
            raise
        existing = api.get(ref_path)
        existing_sha = str((existing.get("object") or {}).get("sha", ""))
        if existing_sha != sha:
            raise


def paginated_get(
    api: GitHubApi, path: str, query: dict[str, str | int]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = api.get(path, {**query, "per_page": 100, "page": page})
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def ensure_no_workflow_file_changes(
    api: GitHubApi, repository: str, pull_number: int
) -> None:
    files = paginated_get(
        api,
        f"/repos/{repository}/pulls/{pull_number}/files",
        {},
    )
    workflow_paths = sorted(
        {
            path
            for file in files
            for path in (file.get("filename"), file.get("previous_filename"))
            if isinstance(path, str) and path.startswith(WORKFLOW_DIRECTORY)
        }
    )
    if workflow_paths:
        paths = ", ".join(workflow_paths)
        raise RuntimeError(
            f"pull request #{pull_number} changes privileged workflow files: "
            f"{paths}. Workflow changes from forks must be recreated on a "
            "trusted internal branch"
        )


def find_internal_pr(
    api: GitHubApi, repository: str, branch: str
) -> dict[str, Any] | None:
    owner = repository.split("/", maxsplit=1)[0]
    pulls = paginated_get(
        api,
        f"/repos/{repository}/pulls",
        {"state": "all", "base": BASE_BRANCH, "head": f"{owner}:{branch}"},
    )
    return pulls[0] if pulls else None


def create_internal_pr(
    api: GitHubApi,
    repository: str,
    branch: str,
    source: dict[str, str],
    pull_number: int,
    mode: str,
    actor: str,
) -> dict[str, Any]:
    existing = find_internal_pr(api, repository, branch)
    if existing:
        if existing.get("state") == "closed":
            internal_number = existing.get("number")
            if not isinstance(internal_number, int):
                raise RuntimeError("existing internal pull request has no number")
            details = api.get(f"/repos/{repository}/pulls/{internal_number}")
            if not details.get("merged"):
                return api.patch(
                    f"/repos/{repository}/pulls/{internal_number}",
                    {"state": "open"},
                )
            return details
        return existing

    body = "\n".join(
        [
            f"<!-- fork-promotion: source-pr={pull_number} -->",
            "Promotes the exact revision from a fork pull request into an "
            "internal branch.",
            "",
            f"- Original pull request: {source['html_url']}",
            f"- Source repository: `{source['head_repository']}`",
            f"- Reviewed commit: `{source['sha']}`",
            f"- Promotion mode: `{mode}`",
            f"- Promoted by: `@{actor}`",
            "",
            "The required Black Duck guard accepts this branch only while its "
            "head remains at the reviewed commit. A changed fork head requires "
            "a new promotion.",
        ]
    )
    return api.post(
        f"/repos/{repository}/pulls",
        {
            "base": BASE_BRANCH,
            "body": body,
            "head": branch,
            "title": branch,
        },
    )


def comment_on_source_pr(
    api: GitHubApi,
    repository: str,
    source_pull_number: int,
    source_sha: str,
    internal_url: str,
) -> None:
    marker = (
        f"<!-- fork-promotion-result: source-pr={source_pull_number} "
        f"source-sha={source_sha} -->"
    )
    comments = paginated_get(
        api,
        f"/repos/{repository}/issues/{source_pull_number}/comments",
        {},
    )
    if any(marker in str(comment.get("body", "")) for comment in comments):
        return
    api.post(
        f"/repos/{repository}/issues/{source_pull_number}/comments",
        {
            "body": (
                f"{marker}\nThe reviewed revision `{source_sha}` was promoted to "
                f"the internal pull request {internal_url}. Credentialed checks "
                "run there."
            )
        },
    )


def close_source_pr(
    api: GitHubApi,
    repository: str,
    source_pull_number: int,
    source_sha: str,
) -> bool:
    latest = api.get(f"/repos/{repository}/pulls/{source_pull_number}")
    latest_sha = str(((latest.get("head") or {}).get("sha", ""))).lower()
    if latest.get("state") != "open" or latest_sha != source_sha.lower():
        return False
    api.patch(
        f"/repos/{repository}/pulls/{source_pull_number}",
        {"state": "closed"},
    )
    # GitHub cannot make the state update conditional on the head SHA. Re-read
    # after closing and recover if a synchronize update won that race.
    closed = api.get(f"/repos/{repository}/pulls/{source_pull_number}")
    closed_sha = str(((closed.get("head") or {}).get("sha", ""))).lower()
    if closed_sha != source_sha.lower():
        if closed.get("state") == "closed":
            api.patch(
                f"/repos/{repository}/pulls/{source_pull_number}",
                {"state": "open"},
            )
        return False
    return closed.get("state") == "closed"


def write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def append_summary(lines: list[str]) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("auto", "manual"), required=True)
    parser.add_argument("--pull-number", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--actor", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    if repository != ALLOWED_REPOSITORY:
        raise RuntimeError(
            f"fork promotion is restricted to {ALLOWED_REPOSITORY}, got {repository!r}"
        )
    if not token:
        raise RuntimeError("GH_TOKEN is required")

    api = GitHubApi(api_url, token)
    pull = api.get(f"/repos/{repository}/pulls/{args.pull_number}")
    source = validate_source_pr(
        pull, repository, args.pull_number, args.expected_sha
    )

    author_permission = collaborator_permission(api, repository, source["author"])
    source_is_trusted = is_trusted_permission(author_permission)

    if args.mode == "auto":
        actor_permission = collaborator_permission(api, repository, args.actor)
        source_is_trusted = source_is_trusted and is_trusted_permission(
            actor_permission
        )
        if not source_is_trusted:
            print(
                "::notice title=Manual fork promotion required::"
                f"Pull request #{args.pull_number} must be reviewed and promoted "
                "with the manual workflow."
            )
            write_output("promoted", "false")
            append_summary(
                [
                    "### Fork pull request promotion",
                    "",
                    f"- Source pull request: `#{args.pull_number}`",
                    "- Classification: `external contributor`",
                    "- Result: `manual maintainer review required`",
                ]
            )
            return 0
    else:
        actor_permission = collaborator_permission(api, repository, args.actor)
        if not is_trusted_permission(actor_permission):
            raise RuntimeError(
                f"manual promoter @{args.actor} does not have write-level access"
            )

    ensure_no_workflow_file_changes(api, repository, args.pull_number)
    branch = promotion_branch(
        args.mode, source["author"], args.pull_number, source["sha"]
    )
    ensure_ref(api, repository, branch, source["sha"])
    internal = create_internal_pr(
        api,
        repository,
        branch,
        source,
        args.pull_number,
        args.mode,
        args.actor,
    )
    internal_url = str(internal["html_url"])
    comment_on_source_pr(
        api,
        repository,
        args.pull_number,
        source["sha"],
        internal_url,
    )
    source_closed = close_source_pr(
        api, repository, args.pull_number, source["sha"]
    )

    write_output("promoted", "true")
    write_output("branch", branch)
    write_output("pull_request_url", internal_url)
    append_summary(
        [
            "### Fork pull request promotion",
            "",
            f"- Source pull request: `#{args.pull_number}`",
            f"- Source commit: `{source['sha']}`",
            f"- Internal branch: `{branch}`",
            f"- Internal pull request: {internal_url}",
            f"- Mode: `{args.mode}`",
            "- Source pull request: "
            + (
                "`closed`"
                if source_closed
                else "`left open because its state or head changed`"
            ),
        ]
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiError, RuntimeError, ValueError) as error:
        print(f"::error title=Fork promotion failed::{error}", file=sys.stderr)
        raise SystemExit(1) from error
