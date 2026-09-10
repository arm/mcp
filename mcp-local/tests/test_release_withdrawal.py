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
    preflight = WORKFLOW.index('gh release view "v${RESTORE_VERSION}"')
    restore = WORKFLOW.index("- name: Restore latest")
    delete_docker = WORKFLOW.index("- name: Delete withdrawn Docker tags")
    delete_github = WORKFLOW.index("- name: Withdraw GitHub release and tag")

    assert preflight < restore < delete_docker < delete_github
    assert '"${WITHDRAW_VERSION}-amd64"' in WORKFLOW
    assert '"${WITHDRAW_VERSION}-arm64"' in WORKFLOW
    assert 'git/refs/tags/v${WITHDRAW_VERSION}' in WORKFLOW


def test_withdrawal_can_resume_after_latest_or_tags_were_updated() -> None:
    assert 'digest "${IMAGE_FQDN}:${WITHDRAW_VERSION}" 2>/dev/null || true' in WORKFLOW
    assert '"${latest_digest}" = "${restore_digest}"' in WORKFLOW
    assert 'if gh release view "v${WITHDRAW_VERSION}"' in WORKFLOW
    assert "202|204|404" in WORKFLOW


def test_workflow_does_not_change_main_and_runbook_covers_compromise() -> None:
    assert "git push" not in WORKFLOW
    assert "git reset" not in WORKFLOW
    assert "does not modify `main`" in RUNBOOK
    assert "Suspected malicious release" in RUNBOOK
