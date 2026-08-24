# Verify Arm MCP Server image provenance

Production releases of the Arm MCP Server publish a GitHub artifact
attestation for the immutable digest of the final multi-architecture image.
GitHub signs the provenance with a short-lived certificate obtained through
GitHub OIDC and Sigstore, so the release process does not use a long-lived
signing key.

## Expected identity

- Image: `docker.io/armlimited/arm-mcp`
- Source repository: `arm/mcp`
- Signer workflow: `arm/mcp/.github/workflows/build-mcp-image.yml`
- Source ref: `refs/heads/main`
- Event: a push of a reviewed release commit to `main`

The GitHub Release records the released tag, immutable digest, source commit,
and attestation URL. Use those values rather than resolving a mutable tag when
verifying a release.

## Verify with GitHub CLI

Install a current GitHub CLI with the `attestation` commands. Authenticate to
Docker Hub if the registry requires it, then substitute the digest and source
commit recorded in the GitHub Release:

```bash
DIGEST='sha256:replace-with-release-digest'
SOURCE_COMMIT='replace-with-release-source-commit'

gh attestation verify \
  "oci://docker.io/armlimited/arm-mcp@${DIGEST}" \
  --repo arm/mcp \
  --signer-workflow arm/mcp/.github/workflows/build-mcp-image.yml \
  --source-ref refs/heads/main \
  --source-digest "${SOURCE_COMMIT}"
```

A successful result verifies the Sigstore signature and GitHub OIDC identity,
confirms that the attestation belongs to `arm/mcp`, enforces the approved
workflow and `main` source ref, and matches the image's immutable digest and
source commit. Add `--format json` to inspect the complete verification result.

To fetch the copy attached to the image in Docker Hub instead of GitHub's
artifact-attestation service, add `--bundle-from-oci` to the command.

The build and provenance jobs run on ephemeral GitHub-hosted runners with
job-scoped permissions. This establishes signed, digest-bound build provenance.
A trusted reusable build boundary and assessment of the remaining SLSA Build
Level 3 requirements are tracked separately.
