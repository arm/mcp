# Fork pull request promotion

## Summary

- Promotes an exact, authorized fork commit into a SHA-addressed same-repository
  branch and pull request where credentialed Black Duck checks can run safely.
- Keeps the original fork pull request as the canonical discussion thread and
  leaves it open for a maintainer to close manually after the internal pull
  request merges.
- Uses SHA pinning, write-level trust checks, and explicit maintainer promotion for untrusted forks.

### Fork PR Behavior

| Source | Original Fork PR | Promotion | Black Duck Scan |
| --- | --- | --- | --- |
| Trusted fork | Deliberately fails before checkout | Automatic when both the author and triggering user have write-level access | Runs on the `trusted-fork-*` internal pull request |
| Untrusted fork | Deliberately fails before checkout | A maintainer manually promotes the exact reviewed SHA | Runs on the `external-contributions/*` internal pull request |

## Process flow

- A contributor opens or updates a fork pull request. Its Black Duck check
  fails intentionally and directs reviewers to use the promoted internal pull
  request.
- For untrusted forked PR, promote workflow will be successful however following message will be displayed in the workflow logs - `Manual fork promotion required, Pull request ## must be reviewed and promoted with the manual workflow.`
- For an untrusted fork PR, after code review and successful applicable non-Black-Duck checks, a maintainer runs **Promote reviewed fork pull request** manually using `workflow_dispatch`, providing the source PR number and the full reviewed head SHA. Black Duck intentionally fails on the source fork PR and must pass on the resulting internal PR.
- The exact fork head SHA follows one of the promotion paths below.
- The workflow applies the promotion safeguards before creating an internal
  pull request.
- The workflow creates or reopens a SHA-addressed internal pull request and closes
  older open, unmerged promotions as superseded.
- The required Black Duck check runs on the promoted pull request.
- If changes are requested, the contributor pushes a new SHA to the original
  fork pull request and the authorization and promotion process repeats.
- After the internal pull request merges, the merging maintainer closes the
  original fork pull request manually.

## Promotion paths

- **Automatic:** When both the author and triggering user have `write`,
  `maintain`, or `admin` access, the exact SHA is promoted to
  `trusted-fork-<user>/pr-<number>-<sha>`.
- **Manual:** All other revisions require a maintainer to review and promote
  the exact SHA to `external-contributions/pr-<number>-<sha>`. This includes a
  trusted author's revision when the triggering user is untrusted.

## Promotion safeguards

- The SHA-addressed branch name is also used as the internal pull request
  title.
- Draft, closed, non-fork, stale, and non-`main` pull requests are rejected.
- Changes under `.github/workflows/`, including renames and deletions, must be
  recreated and reviewed on a trusted internal branch.
- Promotion fails closed at GitHub's 3,000-file listing limit and revalidates
  the source head after file inspection.
- Re-promoting the same SHA reopens a closed-unmerged internal pull request.
  A newer promotion closes older open, unmerged promotions as superseded;
  merged promotions remain closed.
- A pull request is eligible for superseding only when the Pulls API identifies
  its author as the configured promotion App's bot through `user.login` and
  `user.type`; a matching branch, SHA, and body marker are not sufficient on
  their own.

## Black Duck scan

The required `CI Black Duck security scan / Black Duck security scan` check
fails before checkout on the original fork pull request. On the promoted pull
request, it verifies that the branch head still matches the SHA in its name
before exposing credentials. Do not use **Update branch** or manually modify a
promoted branch; either action invalidates this guard.

The scan checks out the exact pull request head and creates an isolated source
directory from the raw contents of every tracked Git blob without running
repository code.
The inline exporter runs Python in isolated mode (`python3 -I`) and reads Git
objects with `git ls-tree` and `git cat-file`; it cannot import modules or site
customizations from the contributor checkout. It does not use `git archive`,
checkout filters, or contributor-controlled `.gitattributes`, so
`export-ignore` and `export-subst` cannot omit or rewrite reviewed files.
Executable files and symlink targets are materialized as non-executable regular
files, and unsupported tree paths fail the job rather than producing a partial
scan. Black Duck receives this directory through its `project_directory` input.
The scan job has read-only repository permissions and receives no token capable
of commenting on or changing the pull request.

`Main Push and Scheduled full source scan` is the separate full scan for `main`
pushes and scheduled runs; it is not a pull-request merge gate.

## Manual source pull request closure

The workflow never closes or reopens the original fork pull request. After the
matching internal pull request has merged, the merging maintainer verifies the
source link in the internal pull request body and closes the source pull request
manually. This avoids race-prone state reconciliation when the contributor
updates the fork while the internal pull request is merging.

## GitHub App configuration

Created and installed a dedicated GitHub App on `arm/mcp` with these repository
permissions:

- Contents: read and write
- Metadata: read
- Pull requests: read and write

Do not grant the App Workflows permission. The promotion helper rejects
workflow-file changes before creating an internal ref, and the missing
permission provides a second enforcement layer at the GitHub API boundary.

Configured the repository with:

- Variable `GH_APP_ID`: the App client ID
- Secret `GH_APP_TOKEN`: one of the App private keys

The App token is used so the internal PR triggers normal `pull_request`
workflows without the approval-required behavior applied to PRs created by the
built-in `GITHUB_TOKEN`. Comments created by the promotion helper are
informational only and are not used as workflow state.
The workflow passes the App slug emitted with the installation token to the
promotion helper so only PRs created by that App can be classified and closed
as superseded promotions.

## Actions policy

Automatic promotion uses `pull_request_target`, but the workflow checks out
only `main` and treats the fork revision strictly as an opaque Git object. It
never checks out or executes fork content. The organization Actions policy must
allow `pull_request_target` for this workflow and `workflow_dispatch` for
explicit maintainer promotion.
