# Withdrawing an MCP release

The **Withdraw MCP Release** workflow removes an unintended public release. It
does not modify `main` or change the version in `mcp-local/server.json`.

The `DOCKERHUB_TOKEN` must have read, write, and delete access to
`armlimited/arm-mcp`.

For example, to withdraw `4.2.0` and restore `4.1.0`:

```bash
gh workflow run withdraw-mcp-release.yml \
  --repo arm/mcp \
  --ref main \
  -f withdraw_version=4.2.0 \
  -f restore_version=4.1.0 \
  -f confirmation='WITHDRAW 4.2.0 TO 4.1.0'
```

The workflow checks that `latest` is currently the withdrawn image, moves
`latest` to the fallback image, deletes the version and architecture-specific
Docker tags, and marks the fallback GitHub release as latest. It retains the Git
tag and marks the GitHub release as withdrawn while preserving its original
notes.

The workflow can be rerun if an earlier attempt only completed some of these
steps.

Leave `main` at the withdrawn version; that version is used and must not be
republished. Choose the next version according to the reason for the withdrawal.
For example, skip to the next minor version with:

```bash
gh workflow run build-mcp-image.yml \
  --repo arm/mcp \
  --ref main \
  -f release_action=minor
```

Use `hotfix` or `major` instead when that is the appropriate next version.

## Suspected malicious release

This workflow does not cover releases involving suspected malicious code or a
repository or credential compromise. Follow the security incident response
process instead.
