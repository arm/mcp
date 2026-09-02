# Verify Arm MCP Server image provenance

Verify a production release against the immutable image digest and source commit
recorded in its GitHub Release. Do not resolve `latest` or another mutable tag
for this check.

Expected release identity:

- Image: `docker.io/armlimited/arm-mcp`
- Source repository: `arm/mcp`
- Signer workflow: `arm/mcp/.github/workflows/trusted-mcp-release.yml`
- Source ref: `refs/heads/main`

## Verify through GitHub

Open the release and copy its **Immutable digest** and **Source commit**, then
run:

```bash
DIGEST='sha256:replace-with-release-digest'
SOURCE_COMMIT='replace-with-release-source-commit'

gh attestation verify \
  "oci://docker.io/armlimited/arm-mcp@${DIGEST}" \
  --repo arm/mcp \
  --signer-workflow arm/mcp/.github/workflows/trusted-mcp-release.yml \
  --source-ref refs/heads/main \
  --source-digest "${SOURCE_COMMIT}"
```

Success proves that GitHub verified a signed attestation for that exact image
digest, produced from that exact `arm/mcp` commit on `main` by the trusted
reusable release workflow.

## Verify the registry bundle

The same attestation bundle is attached to the image in Docker Hub. Verify that
copy by rerunning the command with `--bundle-from-oci`.

If verification fails, first confirm that the digest and commit were copied
from the same GitHub Release, update GitHub CLI if it lacks the `attestation`
commands, and authenticate to Docker Hub if registry access requires it. A
signer, source, or digest mismatch should be treated as a failed verification,
not bypassed.
