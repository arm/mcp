# Maintaining MCP catalog listings

The release maintainer owns catalog verification for every production release.
Docker Hub image publication, the official MCP Registry, and Docker's MCP
Catalog are separate publication steps.

## Official MCP Registry

The trusted production workflow calls **Publish MCP Registry** after creating
the GitHub Release. Before requesting production approval, it retrieves
`mcp-local/server.json` from the released tag's exact commit and verifies that:

- The GitHub Release is published, is not a prerelease, and is not withdrawn.
- Its source is on `main` and matches the automatic release's authorized commit.
- The OCI image tag matches the digest recorded in the GitHub Release.
- Registry-attached provenance identifies that source and the trusted workflow.
- The manifest identifies the correct server, release version, image and transport.

The publishing job uses the `production` environment, a checksum-pinned
`mcp-publisher`, and GitHub OIDC. No personal registry token is needed.
Pull requests validate metadata without obtaining a publishing identity.

After publication, the workflow reads the exact version back from the registry
and checks its active status and metadata. An identical existing entry is a
successful no-op; a conflicting or withdrawn entry fails instead of being
overwritten or reactivated.

### Catch up or retry an existing release

Run this from the repository's default branch after the workflow is merged:

```bash
gh workflow run publish-mcp-registry.yml --repo arm/mcp --ref main -f version=3.0.0
```

Replace `3.0.0` with the approved released version. Approve the `production`
deployment after reviewing the validation summary. This path uses release data
from the original commit, even when `main` contains a newer manifest. It does
not rebuild or retag an image, or create another GitHub Release.

If the registry is unavailable, the image and GitHub Release remain published;
retry this workflow when service recovers. A failed publication must remain
visible as outstanding release work.

Verify the latest advertised version separately after catch-up:

```bash
curl --fail --silent --show-error \
  'https://registry.modelcontextprotocol.io/v0.1/servers/io.github.arm%2Farm-mcp/versions/latest'
```

The [withdrawal workflow](release-withdrawal.md) hides registered versions before
deleting their Docker tags. Historical registry entries are not overwritten.

## Docker MCP Catalog

The Docker MCP Catalog has its own reviewed source:
[docker/mcp-registry](https://github.com/docker/mcp-registry/tree/main/servers/arm-mcp).
Publishing to the official registry does not replace this process.

For each release, the release maintainer must:

1. Update `servers/arm-mcp/server.yaml` in a fork of `docker/mcp-registry`:
   set the released image version and exact source commit, retain the correct
   Dockerfile path (`mcp-local/Dockerfile`), and check description and configuration.
2. Refresh `servers/arm-mcp/tools.json` against `tools/list` from that released
   image. Remove obsolete tools and configuration; do not advertise changes
   that exist only on `main`.
3. Follow Docker's [validation and PR process](https://github.com/docker/mcp-registry/blob/main/CONTRIBUTING.md).
   Retain `/workspace` mounting and test initialization and tool discovery.
4. Record the upstream PR URL with the release tracking work. An upstream review
   delay is pending catalog work, not a reason to rebuild the image.
5. After upstream merge, verify the
   [published catalog entry](https://hub.docker.com/mcp/server/arm-mcp/overview)
   shows the expected image, configuration and tool set.

For withdrawals, submit a catalog update to the approved fallback release if
the catalog still references the withdrawn image. Downstream directories may
cache either registry; verify their refresh separately after these sources are
correct, without treating their cache state as a new image release.
