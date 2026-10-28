---
name: arm-container-inspect
description: Inspect container tags and exact digests for Arm64 support using Skopeo or Docker Buildx from the command line. Use when assessing container images for an Arm migration.
---

# Inspect container architecture support

Run commands through the agent's shell. This replaces the former `check_image`
and `skopeo` MCP tools. Preserve the exact image tag or digest from the project.

Use an installed Skopeo, or the CLI bundled in the Arm MCP image. Set `ARM_MCP_IMAGE`
to the version or digest configured for this project (or the newly built local
image); the examples default to `armlimited/arm-mcp:latest`.

```sh
image='docker.io/library/nginx:latest'
skopeo inspect --raw "docker://$image"
# Docker fallback, without starting the MCP server or mounting a workspace:
docker run --rm --entrypoint skopeo "${ARM_MCP_IMAGE:-armlimited/arm-mcp:latest}" \
  inspect --raw "docker://$image"
```

If Docker Buildx is already available, `docker buildx imagetools inspect "$image"`
is another way to inspect registry platforms without pulling image layers.

For an OCI index or Docker manifest list, inspect `manifests[].platform` and
report OS, architecture, and variant. `linux/arm64` is the common server target;
`arm` is 32-bit and does not establish Arm64 support. Ignore attestation entries
with `unknown/unknown`. For a single manifest, query its configuration with
`skopeo inspect "docker://$image"` and read `Os` and `Architecture`. Default
non-raw inspection of a multi-platform tag selects one platform, so it cannot
establish all supported architectures.

Inspect pinned digests directly: an Arm-capable tag does not make a digest
pointing at an amd64-only manifest portable. Record the reference, manifest type,
platforms, and command used. Registry access, authentication, or rate-limit
failures mean support is unverified, not absent. Use the user's existing registry
authentication; a Docker subprocess does not automatically inherit host Skopeo
credentials. Do not print secrets or put passwords in command arguments.

For `oci:` or `dir:` transports, use the real local path with Skopeo and mount it
read-only when using Docker. Remote image inspection needs registry networking;
it does not require a Docker daemon socket inside the container.
