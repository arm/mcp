# Verify Arm MCP Server image provenance

An attestation is a signed statement about a particular artifact. Our image
provenance records which source commit and build workflow produced a container
image. Verification checks the signature, the builder's identity, and whether
the statement matches the image and source commit you expect. It does not prove
that the software has no vulnerabilities.

## What the release's attestations mean

The release links to two kinds of signed statements:

| Attestation | What it describes | What it applies to |
| --- | --- | --- |
| **Provenance** | The source and build workflow that produced the release image. | The multi-architecture container image digest in the release notes. |
| **SBOM attestations (AMD64 and Arm64)** | The recorded inventory of software components in each architecture's image. | Each architecture's own container image digest. |

The commands below verify **image provenance**. They do not verify the SBOM
attestations or attest the separate SBOM files offered as release downloads.

## One provenance statement, several places to retrieve it

The provenance link and the `.intoto.jsonl` release attachment provide access
to the same signed build evidence. The attachment is a downloadable copy, not
a second build or an additional endorsement. A **bundle** packages the signed
statement together with the certificate and transparency-log material needed
to verify it.

| Verification method | Where the command gets the provenance bundle | When to use it |
| --- | --- | --- |
| Through GitHub (first code block) | GitHub's attestation service. | The usual way to check a release without downloading its provenance file yourself. |
| Release attachment (second code block) | The `.intoto.jsonl` file downloaded from the release. | To check the evidence file you downloaded or kept with your release records. |
| Registry bundle | Docker Hub, alongside the image. | To check the copy distributed through the container registry. |

These methods check the same image identity and builder identity. You normally
need only one; running more than one checks that the different copies are
available and verify successfully, rather than adding another independent signer.

## Choose the image and source to verify

Copy the **Immutable digest** and **Source commit** from the GitHub Release you
intend to use. The digest is a fingerprint of the exact image contents; the
commit identifies the expected source revision. Do not use `latest` or another
mutable image tag here, because a tag can later point to a different image.

Expected release identity:

- Image: `docker.io/armlimited/arm-mcp`
- Source repository: `arm/mcp`
- Signer workflow: `arm/mcp/.github/workflows/trusted-mcp-release.yml`
- Source ref: `refs/heads/main`

## Verify through GitHub

Use this as the default verification method. Replace both placeholders with
the values from the same release, then run:

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

The CLI retrieves the image from Docker Hub and its attestation from GitHub.
It checks the signature and enforces the expectations in the command:

- `--repo` binds the attestation to `arm/mcp`.
- `--signer-workflow` identifies the trusted reusable workflow that signed it.
- `--source-ref` requires the source to have been on `main`.
- `--source-digest` requires the exact source commit recorded in the release.

A successful result means the signed evidence matches that image digest and
those build identities. The release-note link alone does not perform these checks.

## Verify the registry bundle

The same attestation bundle is attached to the image in Docker Hub. Verify that
copy by rerunning the command with `--bundle-from-oci`.

## Verify the release attachment

Use this alternative for releases that include an
`arm-mcp-<version>.intoto.jsonl` asset. The file preserves the complete Sigstore
bundles downloaded from GitHub. The `.intoto.jsonl` suffix also makes the
provenance discoverable by OpenSSF Scorecard; it does not change the signature
or strengthen the statement.

Replace all three placeholders using the same release. This block stands on
its own; you do not need to run the first block beforehand:

```bash
VERSION='replace-with-release-version-without-v'
DIGEST='sha256:replace-with-release-digest'
SOURCE_COMMIT='replace-with-release-source-commit'

gh release download "v${VERSION}" --repo arm/mcp \
  --pattern "arm-mcp-${VERSION}.intoto.jsonl"

gh attestation verify "oci://docker.io/armlimited/arm-mcp@${DIGEST}" \
  --bundle "arm-mcp-${VERSION}.intoto.jsonl" \
  --repo arm/mcp \
  --signer-workflow arm/mcp/.github/workflows/trusted-mcp-release.yml \
  --source-ref refs/heads/main \
  --source-digest "${SOURCE_COMMIT}"
```

The first command downloads the evidence file. The second verifies it using
the same identity checks as the first code block. The `--bundle` option changes
where the CLI reads the evidence: it uses your local file instead of looking up
attestations through GitHub. The OCI image is still accessed in Docker Hub, so
this command is not a fully offline verification procedure.

## Troubleshooting

If verification fails, first confirm that the digest and commit were copied
from the same GitHub Release, update GitHub CLI if it lacks the `attestation`
commands, and authenticate to Docker Hub if registry access requires it. A
signer, source, or digest mismatch should be treated as a failed verification,
not bypassed.
