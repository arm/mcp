from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
WORKFLOW = (
    REPOSITORY / ".github/workflows/withdraw-mcp-release.yml"
).read_text(encoding="utf-8")
RUNBOOK = (REPOSITORY / "docs/release-withdrawal.md").read_text(encoding="utf-8")


def test_withdrawal_is_manual_guarded_and_serialized() -> None:
    triggers = WORKFLOW.split("permissions:", maxsplit=1)[0]

    assert "workflow_dispatch:" in triggers
    assert "pull_request:" not in triggers
    assert "push:" not in triggers
    assert "environment: production" in WORKFLOW
    assert "group: build-mcp-image-publish" in WORKFLOW
    assert '"WITHDRAW ${WITHDRAW_VERSION} TO ${RESTORE_VERSION}"' in WORKFLOW
    assert '"${WITHDRAW_VERSION}" != "${RESTORE_VERSION}"' in WORKFLOW


def test_latest_is_restored_before_release_tags_are_deleted() -> None:
    restore = WORKFLOW.index("- name: Restore latest")
    delete_docker = WORKFLOW.index("- name: Delete withdrawn Docker tags")
    delete_github = WORKFLOW.index("- name: Withdraw GitHub release and tag")

    assert restore < delete_docker < delete_github
    assert '"${WITHDRAW_VERSION}-amd64"' in WORKFLOW
    assert '"${WITHDRAW_VERSION}-arm64"' in WORKFLOW
    assert "--cleanup-tag --yes" in WORKFLOW


def test_workflow_does_not_change_main_and_runbook_covers_compromise() -> None:
    assert "git push" not in WORKFLOW
    assert "git reset" not in WORKFLOW
    assert "does not modify `main`" in RUNBOOK
    assert "Suspected malicious release" in RUNBOOK
