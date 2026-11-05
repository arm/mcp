# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / ".github/scripts/promote-fork-pr.py"
SPEC = importlib.util.spec_from_file_location("promote_fork_pr", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PROMOTION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROMOTION
SPEC.loader.exec_module(PROMOTION)


SHA = "a" * 40
APP_SLUG = "arm-mcp-promotion"


@pytest.fixture(autouse=True)
def configured_promotion_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_APP_SLUG", APP_SLUG)


def source_pr(*, sha: str = SHA, draft: bool = False) -> dict:
    return {
        "number": 185,
        "state": "open",
        "draft": draft,
        "title": "A fork contribution",
        "html_url": "https://github.com/arm/mcp/pull/185",
        "user": {"login": "trusted-user"},
        "base": {"ref": "main", "repo": {"full_name": "arm/mcp"}},
        "head": {
            "sha": sha,
            "repo": {
                "id": 1234,
                "fork": True,
                "full_name": "trusted-user/mcp",
                "owner": {"login": "trusted-user", "type": "User"},
            },
        },
    }


def internal_pr(
    *,
    number: int = 186,
    source_number: int = 185,
    sha: str = SHA,
    branch: str | None = None,
    state: str = "open",
    author_login: str | None = f"{APP_SLUG}[bot]",
    author_type: str = "Bot",
) -> dict:
    branch = branch or f"external-contributions/pr-{source_number}-{sha}"
    marker = (
        "<!-- fork-promotion: "
        f"source-pr={source_number} source-sha={sha} -->"
    )
    pull = {
        "number": number,
        "state": state,
        "html_url": f"https://github.com/arm/mcp/pull/{number}",
        "body": marker,
        "base": {"ref": "main", "repo": {"full_name": "arm/mcp"}},
        "head": {
            "ref": branch,
            "sha": sha,
            "repo": {"full_name": "arm/mcp"},
        },
    }
    if author_login is not None:
        pull["user"] = {"login": author_login, "type": author_type}
    return pull


def test_promotion_branch_names_match_trust_classification() -> None:
    assert PROMOTION.promotion_branch("manual", "ignored", 185, SHA) == (
        f"external-contributions/pr-185-{SHA}"
    )
    assert PROMOTION.promotion_branch("auto", "trusted-user", 185, SHA) == (
        f"trusted-fork-trusted-user/pr-185-{SHA}"
    )
    assert PROMOTION.parse_promotion_branch(
        f"external-contributions/pr-185-{SHA}"
    ) == (185, SHA)
    assert PROMOTION.parse_promotion_branch(
        f"trusted-fork-trusted-user/pr-185-{SHA}"
    ) == (185, SHA)
    assert PROMOTION.parse_promotion_branch(f"feature/pr-185-{SHA}") is None


def test_internal_pr_uses_the_promotion_name_for_its_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingApi:
        def __init__(self) -> None:
            self.payload: dict | None = None

        def post(self, _path: str, payload: dict) -> dict:
            self.payload = payload
            return {"number": 186, "html_url": "https://github.com/arm/mcp/pull/186"}

    api = RecordingApi()
    monkeypatch.setattr(PROMOTION, "find_internal_pr", lambda *_args: None)
    branch = f"external-contributions/pr-185-{SHA}"
    PROMOTION.create_internal_pr(
        api,
        "arm/mcp",
        branch,
        {
            "head_repository": "external-user/mcp",
            "html_url": "https://github.com/arm/mcp/pull/185",
            "sha": SHA,
        },
        185,
        "manual",
        "maintainer",
    )

    assert api.payload is not None
    assert api.payload["head"] == branch
    assert api.payload["title"] == branch
    assert f"source-pr=185 source-sha={SHA}" in api.payload["body"]
    assert (
        "After this internal pull request merges, close the original pull "
        "request manually."
    ) in api.payload["body"]


def test_closed_unmerged_internal_pr_is_reopened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingApi:
        def __init__(self) -> None:
            self.patch_request: tuple[str, dict] | None = None

        def get(self, path: str) -> dict:
            assert path == "/repos/arm/mcp/pulls/186"
            return {"number": 186, "state": "closed", "merged": False}

        def patch(self, path: str, payload: dict) -> dict:
            self.patch_request = (path, payload)
            return {
                "number": 186,
                "state": "open",
                "html_url": "https://github.com/arm/mcp/pull/186",
            }

    api = RecordingApi()
    monkeypatch.setattr(
        PROMOTION,
        "find_internal_pr",
        lambda *_args: {"number": 186, "state": "closed"},
    )

    internal = PROMOTION.create_internal_pr(
        api,
        "arm/mcp",
        f"external-contributions/pr-185-{SHA}",
        {
            "head_repository": "external-user/mcp",
            "html_url": "https://github.com/arm/mcp/pull/185",
            "sha": SHA,
        },
        185,
        "manual",
        "maintainer",
    )

    assert api.patch_request == (
        "/repos/arm/mcp/pulls/186",
        {"state": "open"},
    )
    assert internal["state"] == "open"


def test_merged_internal_pr_is_not_reopened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MergedApi:
        def get(self, _path: str) -> dict:
            return {
                "number": 186,
                "state": "closed",
                "merged": True,
                "html_url": "https://github.com/arm/mcp/pull/186",
            }

        def patch(self, _path: str, _payload: dict) -> None:
            pytest.fail("a merged internal pull request must not be reopened")

    monkeypatch.setattr(
        PROMOTION,
        "find_internal_pr",
        lambda *_args: {"number": 186, "state": "closed"},
    )

    internal = PROMOTION.create_internal_pr(
        MergedApi(),
        "arm/mcp",
        f"external-contributions/pr-185-{SHA}",
        {
            "head_repository": "external-user/mcp",
            "html_url": "https://github.com/arm/mcp/pull/185",
            "sha": SHA,
        },
        185,
        "manual",
        "maintainer",
    )

    assert internal["merged"] is True


def test_write_level_permissions_are_trusted() -> None:
    for permission in ("write", "maintain", "admin"):
        assert PROMOTION.is_trusted_permission(permission)
    for permission in ("none", "read", "triage"):
        assert not PROMOTION.is_trusted_permission(permission)


def test_missing_collaborator_is_treated_as_external() -> None:
    class MissingCollaboratorApi:
        def get(self, _path: str) -> None:
            raise PROMOTION.ApiError(404, "GET", "test", "Not Found")

    assert (
        PROMOTION.collaborator_permission(
            MissingCollaboratorApi(), "arm/mcp", "external-user"
        )
        == "none"
    )


def test_replacement_internal_pr_closes_the_superseded_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = internal_pr()
    current_sha = "b" * 40
    current_branch = f"external-contributions/pr-185-{current_sha}"
    current_url = "https://github.com/arm/mcp/pull/187"

    class RecordingApi:
        def __init__(self) -> None:
            self.requests: list[tuple[str, dict]] = []

        def get(self, path: str) -> dict:
            assert path == "/repos/arm/mcp/pulls/186"
            return old

        def patch(self, path: str, payload: dict) -> None:
            self.requests.append((path, payload))

    api = RecordingApi()
    monkeypatch.setattr(
        PROMOTION,
        "paginated_get",
        lambda *_args: [
            old,
            internal_pr(
                number=187,
                sha=current_sha,
                branch=current_branch,
            ),
            internal_pr(number=188, source_number=999),
        ],
    )
    comments: list[tuple[int, str]] = []
    monkeypatch.setattr(
        PROMOTION,
        "post_comment",
        lambda _api, _repository, number, body: comments.append((number, body)),
    )

    superseded = PROMOTION.supersede_internal_prs(
        api, "arm/mcp", 185, current_branch, current_url
    )

    assert superseded == ["https://github.com/arm/mcp/pull/186"]
    assert api.requests == [
        ("/repos/arm/mcp/pulls/186", {"state": "closed"})
    ]
    assert comments == [
        (186, f"Superseded by {current_url}. Do not merge this older revision.")
    ]


@pytest.mark.parametrize(
    ("author_login", "author_type"),
    [
        (None, "Bot"),
        ("lookalike-app[bot]", "Bot"),
        (f"{APP_SLUG}[bot]", "User"),
    ],
)
def test_lookalike_internal_pr_is_not_closed(
    monkeypatch: pytest.MonkeyPatch,
    author_login: str | None,
    author_type: str,
) -> None:
    lookalike = internal_pr(
        author_login=author_login,
        author_type=author_type,
    )

    class NoMutationApi:
        def get(self, _path: str) -> None:
            pytest.fail("an unattributed PR must not be re-read for mutation")

        def patch(self, _path: str, _payload: dict) -> None:
            pytest.fail("an unattributed PR must not be closed")

    monkeypatch.setattr(
        PROMOTION,
        "paginated_get",
        lambda *_args: [lookalike],
    )
    monkeypatch.setattr(
        PROMOTION,
        "post_comment",
        lambda *_args: pytest.fail("an unattributed PR must not be commented on"),
    )

    assert PROMOTION.supersede_internal_prs(
        NoMutationApi(),
        "arm/mcp",
        185,
        f"external-contributions/pr-185-{'b' * 40}",
        "https://github.com/arm/mcp/pull/187",
    ) == []


def test_invalid_promotion_app_slug_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_APP_SLUG", "")

    with pytest.raises(RuntimeError, match="GH_APP_SLUG"):
        PROMOTION.internal_pr_identity(internal_pr(), "arm/mcp")


@pytest.mark.parametrize(
    "file",
    [
        {"filename": ".github/workflows/untrusted.yml"},
        {
            "filename": "docs/renamed-workflow.yml",
            "previous_filename": ".github/workflows/untrusted.yml",
        },
    ],
)
def test_workflow_file_changes_are_rejected(file: dict) -> None:
    class FilesApi:
        def get(self, path: str, query: dict) -> list[dict]:
            assert path == "/repos/arm/mcp/pulls/185/files"
            assert query == {"per_page": 100, "page": 1}
            return [file]

    with pytest.raises(RuntimeError, match="privileged workflow files"):
        PROMOTION.ensure_no_workflow_file_changes(FilesApi(), "arm/mcp", 185)


def test_non_workflow_file_changes_can_be_promoted() -> None:
    class FilesApi:
        def get(self, _path: str, _query: dict) -> list[dict]:
            return [{"filename": "src/example.py"}]

    PROMOTION.ensure_no_workflow_file_changes(FilesApi(), "arm/mcp", 185)


def test_truncated_pull_request_file_list_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        PROMOTION,
        "paginated_get",
        lambda *_args: [
            {"filename": f"src/generated-{index}.py"}
            for index in range(PROMOTION.MAX_PULL_REQUEST_FILES)
        ],
    )

    with pytest.raises(RuntimeError, match="truncated the file list"):
        PROMOTION.ensure_no_workflow_file_changes(object(), "arm/mcp", 185)


def test_source_head_is_revalidated_after_file_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UpdatingSourceApi:
        def __init__(self) -> None:
            self.get_count = 0

        def get(self, path: str) -> dict:
            assert path == "/repos/arm/mcp/pulls/185"
            self.get_count += 1
            return source_pr(sha=SHA if self.get_count == 1 else "b" * 40)

    monkeypatch.setattr(
        PROMOTION,
        "parse_args",
        lambda: SimpleNamespace(
            command="promote",
            mode="auto",
            pull_number=185,
            expected_sha=SHA,
            actor="trusted-user",
        ),
    )
    monkeypatch.setattr(PROMOTION, "GitHubApi", lambda *_args: UpdatingSourceApi())
    monkeypatch.setattr(PROMOTION, "collaborator_permission", lambda *_args: "write")
    monkeypatch.setattr(
        PROMOTION, "ensure_no_workflow_file_changes", lambda *_args: None
    )
    monkeypatch.setattr(
        PROMOTION,
        "ensure_ref",
        lambda *_args: pytest.fail("a changed source head must not create a ref"),
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "arm/mcp")
    monkeypatch.setenv("GH_TOKEN", "test-token")

    with pytest.raises(ValueError, match="head changed"):
        PROMOTION.main()


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_source_pr_stays_open_after_internal_pr_is_created(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    class SourceApi:
        def get(self, _path: str) -> dict:
            return source_pr()

    calls: list[str] = []
    monkeypatch.setattr(
        PROMOTION,
        "parse_args",
        lambda: SimpleNamespace(
            command="promote",
            mode=mode,
            pull_number=185,
            expected_sha=SHA,
            actor="trusted-user",
        ),
    )
    monkeypatch.setattr(PROMOTION, "GitHubApi", lambda *_args: SourceApi())
    monkeypatch.setattr(PROMOTION, "collaborator_permission", lambda *_args: "write")
    monkeypatch.setattr(
        PROMOTION, "ensure_no_workflow_file_changes", lambda *_args: None
    )
    monkeypatch.setattr(
        PROMOTION, "ensure_ref", lambda *_args: calls.append("ensure-ref")
    )

    def create_internal(*_args: object) -> dict:
        calls.append("create-internal-pr")
        return {"html_url": "https://github.com/arm/mcp/pull/186"}

    monkeypatch.setattr(PROMOTION, "create_internal_pr", create_internal)
    monkeypatch.setattr(
        PROMOTION,
        "comment_on_source_pr",
        lambda *_args: calls.append("comment-on-source-pr"),
    )
    monkeypatch.setattr(
        PROMOTION,
        "supersede_internal_prs",
        lambda *_args: calls.append("supersede-internal-prs") or [],
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "arm/mcp")
    monkeypatch.setenv("GH_TOKEN", "test-token")

    assert PROMOTION.main() == 0
    assert calls == [
        "ensure-ref",
        "create-internal-pr",
        "comment-on-source-pr",
        "supersede-internal-prs",
    ]


def test_source_validation_pins_the_exact_reviewed_sha() -> None:
    validated = PROMOTION.validate_source_pr(source_pr(), "arm/mcp", 185, SHA)
    assert validated["author"] == "trusted-user"
    assert validated["sha"] == SHA

    with pytest.raises(ValueError, match="head changed"):
        PROMOTION.validate_source_pr(source_pr(), "arm/mcp", 185, "b" * 40)


def test_source_validation_rejects_draft_prs() -> None:
    with pytest.raises(ValueError, match="still a draft"):
        PROMOTION.validate_source_pr(
            source_pr(draft=True), "arm/mcp", 185, SHA
        )


def test_automatic_branch_rejects_unsafe_usernames() -> None:
    with pytest.raises(ValueError, match="unsafe GitHub username"):
        PROMOTION.promotion_branch("auto", "bad/user", 185, SHA)
