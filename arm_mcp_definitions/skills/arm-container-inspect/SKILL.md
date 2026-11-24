---
name: arm-container-inspect
description: Inspect container tags and exact digests for Arm64 support using Skopeo or Docker Buildx from the command line. Use when assessing container images for an Arm migration.
---

# Inspect container architecture support

Run commands through the agent's shell. Preserve the exact image tag or digest from the project.

This skill runs in the user's environment; Skopeo is not installed in the Arm
MCP server image. Prefer an existing Skopeo installation. If Skopeo is absent,
use Docker Buildx when available or ask before installing the `skopeo` package
with the user's platform package manager. Do not modify the server container.

Check the available CLI before inspecting an image:

```sh
image='docker.io/library/nginx:latest'
if command -v skopeo >/dev/null 2>&1; then
  skopeo inspect --raw "docker://$image"
elif docker buildx version >/dev/null 2>&1; then
  docker buildx imagetools inspect --raw "$image"
else
  echo "Install Skopeo or Docker Buildx to inspect container images." >&2
  exit 1
fi
```

The Docker Buildx fallback inspects registry platforms without pulling image
layers.

For an OCI index or Docker manifest list, inspect `manifests[].platform` and
report OS, architecture, and variant. `linux/arm64` is the common server target;
`arm` is 32-bit and does not establish Arm64 support. Ignore attestation entries
with `unknown/unknown`. For a single manifest, query its configuration with
`skopeo inspect "docker://$image"` and read `Os` and `Architecture`, or use
`docker buildx imagetools inspect --format '{{json .Image}}' "$image"` and read
`os` and `architecture`. Default non-raw inspection of a multi-platform tag
selects one platform, so it cannot establish all supported architectures.

Inspect pinned digests directly: an Arm-capable tag does not make a digest
pointing at an amd64-only manifest portable. Record the reference, manifest type,
platforms, and command used. Registry access, authentication, or rate-limit
failures mean support is unverified, not absent. Use the user's existing registry
authentication; a Docker subprocess does not automatically inherit host Skopeo
credentials. Do not print secrets or put passwords in command arguments.

For `oci:` or `dir:` transports, use the real local path with Skopeo. Remote
image inspection needs registry networking. Docker Buildx requires access to
the user's Docker daemon; Skopeo does not.
