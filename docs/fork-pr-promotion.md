# Fork pull request promotion

Fork pull requests cannot access the Black Duck credentials stored in `arm/mcp`.
The `Promote reviewed fork pull request` workflow copies an exact fork revision
to an immutable branch in `arm/mcp` and opens an internal pull request where the
normal credentialed checks can run.

## Promotion paths

- A pull request authored by a user with effective `write`, `maintain`, or
  `admin` access to `arm/mcp` is promoted automatically to
  `trusted-fork-<github-username>/pr-<number>-<sha>`.
- All other forks require a maintainer to run the workflow manually with the
  pull request number and the full reviewed head SHA. These revisions are
  promoted to `external-contributions/pr-<number>-<sha>`.

Manual promotion is also available when automatic promotion declines a
trusted author's revision because the event was triggered by a user without
write-level access. The maintainer's explicit review authorizes that exact SHA.

Each value above is used for both the immutable internal branch and the
internal pull request title.

The workflow rejects draft pull requests, stale SHAs, closed pull requests,
non-fork pull requests, and pull requests that do not target `arm/mcp:main`.
For automatic promotion, the user whose event opened or updated the pull
request must also have write-level access; an untrusted user cannot update a
trusted author's fork branch and cause an automatic promotion.
Updating a fork produces a new immutable promotion branch and pull request.
If an internal pull request was closed without merging, promoting the same SHA
reopens it. A merged internal pull request remains closed.

The Black Duck check intentionally fails on the original fork pull request.
After linking the promoted internal pull request in a comment, the promotion
workflow closes the source pull request automatically. Review and merge the
internal pull request instead. If the contributor needs to submit another
revision, reopen the source pull request or create a new one; the revision must
then be promoted again.

## GitHub App configuration

Create and install a dedicated GitHub App on `arm/mcp` with these repository
permissions:

- Contents: read and write
- Metadata: read
- Pull requests: read and write
- Workflows: read and write

Configure the repository with:

- Variable `FORK_PROMOTION_APP_CLIENT_ID`: the App client ID
- Secret `FORK_PROMOTION_APP_PRIVATE_KEY`: one of the App private keys

The App token is used so the internal PR triggers normal `pull_request`
workflows without the approval-required behavior applied to PRs created by the
built-in `GITHUB_TOKEN`.

## Actions policy

Automatic promotion uses `pull_request_target`, but the workflow checks out
only `main` and treats the fork revision strictly as an opaque Git object. It
never checks out or executes fork content. The organization Actions policy must
allow `pull_request_target` for this workflow. External contributors still use
the explicit `workflow_dispatch` path after maintainer review.
