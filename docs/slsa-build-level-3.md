# SLSA Build Level 3 for Arm MCP Server releases

Arm MCP Server production images use GitHub's documented pattern for achieving
SLSA v1.0 Build Level 3: the build and provenance generation run in a trusted
reusable workflow using GitHub-hosted runners and GitHub artifact attestations.

See the [SLSA v1.0 Build Level 3
definition](https://slsa.dev/spec/v1.0/levels#build-l3-hardened-builds) and
GitHub's guidance on [using reusable workflows and artifact attestations to
achieve it](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/increase-security-rating).

## Implementation

- `.github/workflows/trusted-mcp-release.yml` owns the production AMD64 and
  Arm64 builds, final image digest, and provenance generation.
- GitHub-hosted runners isolate build executions. GitHub signs the provenance
  through short-lived OIDC and Sigstore credentials that are not exposed to
  build steps.
- The attestation binds the released image digest to its source commit,
  repository, and trusted workflow, and is published through GitHub and with
  the image in Docker Hub.
- Before promotion to `latest` or GitHub Release publication, the workflow
  verifies the digest, repository, signer workflow, source branch, and source
  commit.

## Verification

Follow [Verify Arm MCP Server image provenance](provenance-verification.md) to
independently verify a released image and its trusted builder identity.

This SLSA claim is limited to the production container image's build and
provenance. It is not a broader assessment of vulnerabilities, dependencies,
or other release-security controls.
