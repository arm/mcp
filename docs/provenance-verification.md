# Verify Arm MCP Server image provenance

Production releases of the Arm MCP Server publish GitHub artifact
attestations for the immutable digest of the final multi-architecture image.
GitHub signs the provenance with a short-lived certificate obtained through
GitHub OIDC and Sigstore; the release process does not use a long-lived signing
key.

## Expected identity

- Image: `docker.io/armlimited/arm-mcp`
- Source and signer repository: `arm/mcp`
- Signer workflow: `arm/mcp/.github/workflows/build-mcp-image.yml`
- Source ref: `refs/heads/main`
- Environment: `production`
- Event: an approved production run of the Build MCP Image workflow

The GitHub Release records the released tag, immutable digest, and source
commit. Use those values rather than resolving a mutable tag during
verification.

## Verify with GitHub CLI

Install a current version of the GitHub CLI with the `attestation` commands,
then authenticate to Docker Hub if the registry requires it. Substitute the
digest and source commit shown in the GitHub Release:

```bash
DIGEST='sha256:replace-with-release-digest'
SOURCE_COMMIT='replace-with-release-source-commit'

gh attestation verify \
  "oci://docker.io/armlimited/arm-mcp@${DIGEST}" \
  --repo arm/mcp \
  --signer-repo arm/mcp \
  --signer-workflow arm/mcp/.github/workflows/build-mcp-image.yml \
  --source-ref refs/heads/main \
  --source-digest "${SOURCE_COMMIT}"
```

A successful result verifies the Sigstore signature and GitHub OIDC identity,
confirms that the attestation belongs to `arm/mcp`, enforces the approved
workflow and main source ref, and matches the image's immutable digest and
source commit. Add `--format json` to inspect the complete verification result,
including the signed workflow run, triggering event, and production
environment identity.

To fetch the copy attached to the image in Docker Hub instead of GitHub's
artifact-attestation service, add `--bundle-from-oci` to the command.

Artifact attestation establishes signed provenance. It does not by itself
claim SLSA Build Level 3; that generally also requires a protected trusted
reusable workflow and is outside this release workflow's scope.
