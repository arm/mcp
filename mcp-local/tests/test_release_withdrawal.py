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
    assert '"${CONFIRMATION^^}" != "WITHDRAW"' in WORKFLOW
    assert "Confirmation must be WITHDRAW." in WORKFLOW
    assert '"${WITHDRAW_VERSION}" != "${RESTORE_VERSION}"' in WORKFLOW


def test_validation_runs_before_production_approval() -> None:
    validation_job = WORKFLOW.split("  validate:", maxsplit=1)[1].split(
        "  withdraw:", maxsplit=1
    )[0]
    withdrawal_job = WORKFLOW.split("  withdraw:", maxsplit=1)[1]

    assert "environment:" not in validation_job
    assert "DOCKERHUB_TOKEN" not in validation_job
    assert "### Withdrawal request" in validation_job
    assert "needs: validate" in withdrawal_job
    assert "environment: production" in withdrawal_job
    assert "DOCKERHUB_TOKEN" in withdrawal_job


def test_latest_is_restored_before_release_tags_are_deleted() -> None:
    preflight = WORKFLOW.index(
        'for version in "${WITHDRAW_VERSION}" "${RESTORE_VERSION}"'
    )
    restore = WORKFLOW.index("- name: Restore latest")
    delete_docker = WORKFLOW.index("- name: Delete withdrawn Docker tags")
    edit_github = WORKFLOW.index("- name: Mark GitHub release withdrawn")

    assert preflight < restore < delete_docker < edit_github
    assert '"${WITHDRAW_VERSION}-amd64"' in WORKFLOW
    assert '"${WITHDRAW_VERSION}-arm64"' in WORKFLOW


def test_withdrawal_can_resume_after_latest_or_tags_were_updated() -> None:
    assert 'digest "${IMAGE_FQDN}:${WITHDRAW_VERSION}" 2>/dev/null || true' in WORKFLOW
    assert '"${latest_digest}" = "${restore_digest}"' in WORKFLOW
    assert "<!-- arm-mcp-withdrawn -->" in WORKFLOW
    assert "202|204|404" in WORKFLOW


def test_withdrawn_release_and_git_tag_are_retained() -> None:
    assert "gh release delete" not in WORKFLOW
    assert 'git/refs/tags/v${WITHDRAW_VERSION}' not in WORKFLOW
    assert "--latest=false" in WORKFLOW
    assert "its Docker images are no longer available" in WORKFLOW
    assert "--json body" in WORKFLOW


def test_workflow_does_not_change_main_and_runbook_covers_compromise() -> None:
    assert "git push" not in WORKFLOW
    assert "git reset" not in WORKFLOW
    assert "does not modify `main`" in RUNBOOK
    assert "Suspected malicious release" in RUNBOOK
