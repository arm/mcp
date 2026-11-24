# Migrate-ease Dockerfile support versus Skopeo for Arm readiness

Tested 2026-11-17 (America/Phoenix).

## Verdict

Do **not** skip the separate container-image inspection capability. Retain
`arm-container-inspect`, with Skopeo as the preferred implementation and Docker
Buildx as its documented fallback.

The equivalence hypothesis is falsified. Migrate-ease's Docker scanner is a
source-tree linter with a small built-in registry client. Skopeo is an
image/registry inspector. They overlap only for a simple concrete `FROM` tag.
Migrate-ease adds useful Dockerfile-only checks, but it cannot provide the exact
manifest, platform, digest, authentication, or transport evidence required by
the Arm-readiness workflow.

This is not a recommendation to remove migrate-ease Docker scanning. Keep it for
static Dockerfile triage, and send every resolved external image reference to
the container-image inspection skill. An image lookup failure must be reported
as **unverified**, never as proof that Arm64 is absent.

## Test frame and decision rule

The hypothesis under test was: "migrate-ease's reported Dockerfile support is
functionally equivalent to the Skopeo functionality required by the Arm
readiness skills, so the separate Skopeo skill can be skipped."

The baseline is the checked-in
[`arm-container-inspect`](../arm_mcp_definitions/skills/arm-container-inspect/SKILL.md)
workflow. It requires exact-tag and exact-digest inspection, distinguishes an
index from a single manifest, records platforms, treats access failures as
unverified, and supports local `oci:`/`dir:` transports. The candidate is the
checked-in
[`arm-migrate-ease-scan`](../arm_mcp_definitions/skills/arm-migrate-ease-scan/SKILL.md)
workflow using migrate-ease's `docker` scanner.

The go/no-go threshold derived from the required workflow was:

- equivalent results for public multi-architecture and amd64-only tags;
- correct distinction between a multi-architecture index digest and an
  amd64-only child-manifest digest;
- no conversion of parser, registry, network, authentication, or rate-limit
  errors into "Arm64 unsupported";
- enough output to record the exact reference, media type, platforms, and
  command; and
- either support for authenticated and local-image inspection or an explicit,
  reliable handoff for those cases.

One false supported/unsupported result or loss of digest identity is a stop
condition because it can produce an incorrect migration conclusion. The
candidate failed several stop conditions.

## Versions and primary documentation

| Component | Version tested | Immutable identity | Relevant documentation |
|---|---|---|---|
| migrate-ease Docker scanner | `1.0.0` | Git commit [`e92c735f4bdfbe09e96aea7dd5b404f05d07f6fb`](https://github.com/migrate-ease/migrate-ease/commit/e92c735f4bdfbe09e96aea7dd5b404f05d07f6fb), committed 2026-03-25; the repository publishes no release tags | [README Dockerfile claims and CLI](https://github.com/migrate-ease/migrate-ease/blob/e92c735f4bdfbe09e96aea7dd5b404f05d07f6fb/README.md), [Docker scanner implementation](https://github.com/migrate-ease/migrate-ease/blob/e92c735f4bdfbe09e96aea7dd5b404f05d07f6fb/docker/advisor/dockerfile_scanner.py) |
| Skopeo | `1.24.1`, commit `e9748eb1ea474af8c72e2d92a7f0fd5b7606b9bf` | `quay.io/skopeo/stable@sha256:4b440098ada2bc2623308b0f60f5a5454084b98683e9e7dcecd77bba69797c56` | [`skopeo inspect` 1.24.1 manual](https://github.com/podman-container-tools/skopeo/blob/v1.24.1/docs/skopeo-inspect.1.md), [transports and architecture overrides](https://github.com/podman-container-tools/skopeo/blob/v1.24.1/docs/skopeo.1.md), [v1.24.1 release](https://github.com/podman-container-tools/skopeo/releases/tag/v1.24.1) |
| Registry behavior used as the protocol baseline | Docker Registry HTTP API V2 | Current primary specification | [Manifest references may be tags or digests; authentication and errors are distinct outcomes](https://github.com/distribution/distribution/blob/main/docs/content/spec/api.md) |

The migrate-ease source says it checks Dockerfiles for architecture-specific
plugins and base images lacking AArch64. Its implementation parses `FROM`
itself, calls the Docker Hub tags API or a partial Registry V2 flow, and returns
one boolean. Skopeo documents raw-manifest output, auth files/credentials,
architecture overrides, retries, and registry, daemon, archive, `dir:`, and
`oci:` transports.

## Intended use cases

### Dockerfile analysis

- Discover `Dockerfile` variants in a source tree.
- Identify concrete and unresolved `FROM` references.
- Notice syntax that changes the build target, such as `--platform`, `ARG`,
  `TARGETARCH`, and multi-stage aliases.
- Flag known architecture-specific packages or configuration strings in
  `RUN`, `CMD`, `ENTRYPOINT`, `ENV`, `ARG`, and `LABEL`.

Migrate-ease is the relevant tool for this layer, though the matched cases show
that its Dockerfile parser is incomplete. Skopeo does not parse Dockerfiles.

### Image and registry inspection

- Resolve the exact tag or digest found in source.
- Determine whether the returned object is an OCI index/Docker manifest list or
  a single image manifest.
- Enumerate real OS/architecture/variant entries, ignoring
  `unknown/unknown` attestations.
- Confirm `linux/arm64`, distinguish it from 32-bit `linux/arm`, and identify an
  amd64-only child digest even when its parent tag is multi-architecture.
- Inspect authenticated registries and local OCI layouts, while preserving
  access failures as unverified.

Skopeo is the relevant tool for this layer. Docker Buildx can cover many public
registry-platform checks but requires a Docker daemon and does not replace all
Skopeo transports.

## Reproduction

The exact inputs are checked in under
[`docs/evidence/migrate-ease-vs-skopeo/fixtures`](evidence/migrate-ease-vs-skopeo/fixtures),
and normalized observations are in
[`observed-results.json`](evidence/migrate-ease-vs-skopeo/observed-results.json).
Tags are mutable; the digest cases and tool identities make the decisive
results repeatable even if a tag later changes.

### Migrate-ease

```sh
tool_root="$(mktemp -d)"
python3 -m venv "$tool_root/venv"
git clone https://github.com/migrate-ease/migrate-ease.git "$tool_root/migrate-ease"
git -C "$tool_root/migrate-ease" checkout e92c735f4bdfbe09e96aea7dd5b404f05d07f6fb
"$tool_root/venv/bin/python" -m pip install \
  -r "$tool_root/migrate-ease/requirements.txt"

PYTHONPATH="$tool_root/migrate-ease" \
  "$tool_root/venv/bin/python" -m docker \
  --output-format json \
  --output /tmp/migrate-ease-docker-report.json \
  --march armv8-a \
  docs/evidence/migrate-ease-vs-skopeo/fixtures

jq -r '.issues[] | [.filename, .issue_type.type, (.lineno // "-")] | @tsv' \
  /tmp/migrate-ease-docker-report.json
```

Observed summary: 13 files, 18 lines, 12 findings: one scanner error, nine
`ImageIssue` entries, one `ConfigurationInfoIssue`, and one `PluginIssue`.

### Skopeo

With a native install, remove the `docker run ...` prefix and start each command
with `skopeo`. The container form below is the exact implementation tested.

```sh
skopeo_image='quay.io/skopeo/stable@sha256:4b440098ada2bc2623308b0f60f5a5454084b98683e9e7dcecd77bba69797c56'

docker run --rm "$skopeo_image" --version

docker run --rm "$skopeo_image" inspect --raw \
  docker://docker.io/library/alpine:3.20 |
  jq -r '.mediaType,
    (.manifests[] | select(.platform.architecture != "unknown") |
    [.platform.os, .platform.architecture, (.platform.variant // "-")] | @tsv)'

docker run --rm "$skopeo_image" inspect --raw \
  docker://docker.io/amd64/alpine:3.20 |
  jq -r '.mediaType,
    (.manifests[] | select(.platform.architecture != "unknown") |
    [.platform.os, .platform.architecture, (.platform.variant // "-")] | @tsv)'

docker run --rm "$skopeo_image" inspect --raw \
  docker://registry.k8s.io/pause:3.10 |
  jq -r '.mediaType,
    (.manifests[] | [.platform.os, .platform.architecture,
    (.platform.variant // "-")] | @tsv)'

docker run --rm "$skopeo_image" inspect --raw \
  docker://docker.io/library/alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc

docker run --rm "$skopeo_image" inspect --raw \
  docker://docker.io/library/alpine@sha256:c64c687cbea9300178b30c95835354e34c4e4febc4badfe27102879de0483b5e

docker run --rm "$skopeo_image" inspect --override-arch amd64 \
  --format '{{.Digest}} {{.Os}}/{{.Architecture}}' \
  docker://docker.io/library/alpine@sha256:c64c687cbea9300178b30c95835354e34c4e4febc4badfe27102879de0483b5e

# Expected to fail anonymously as unverified, not "Arm64 unsupported".
docker run --rm "$skopeo_image" inspect --raw \
  docker://ghcr.io/arm/mcp-build-inputs@sha256:8587f10da108cb7320c0b11536e2d995afc34abe5a04da10c14758b55a26abc9
```

The `--override-arch amd64` command reported the exact child digest and
`linux/amd64`. The raw index commands reported
`application/vnd.oci.image.index.v1+json` and included `linux/arm64/v8`; the raw
child command reported
`application/vnd.oci.image.manifest.v1+json`.

## Capability matrix

| Required capability | migrate-ease Docker scanner | Skopeo 1.24.1 | Result for the skill decision |
|---|---|---|---|
| Find Dockerfiles and lint their contents | Yes. Scans filename variants and checks selected commands, package patterns, and architecture strings. | No; it accepts an image reference, not source. | Keep migrate-ease for static triage. |
| Extract ordinary `FROM` base-image tags | Partial. `alpine:latest` worked, but `alpine:3.20` crashed because the dot in the tag was mistaken for a registry hostname. | Not applicable to source extraction. | A Dockerfile parser or manual extraction remains necessary. |
| Inspect public Docker Hub tag platforms | Partial. Uses the Docker Hub tags API and returns only a boolean. | Yes. Raw output preserves media type, every platform, variants, and digests. | Skopeo provides the required evidence. |
| Inspect non-Docker-Hub registries | Unreliable. The public `registry.k8s.io/pause:3.10` case became an `ImageIssue` after a token-field error. | Yes; it returned a manifest list including `linux/arm64`. | Migrate-ease produced a false positive. |
| Distinguish an index digest from a child digest | No. Both digest references were converted into malformed Docker Hub API URLs and both became the same `ImageIssue`. | Yes. `--raw` exposed index versus manifest media types; config inspection proved the child was `linux/amd64`. | Fatal equivalence gap. |
| Identify Arm64 versus 32-bit Arm | Only checks for the string `arm64`; it does not return the platform set. | Yes. Reports architecture and variant, allowing `arm64` to be separated from `arm/v6` or `arm/v7`. | Skopeo output matches the workflow. |
| Handle single-platform manifests | Not generally. The non-Hub path iterates `data.manifests`; a single manifest has no such array. | Yes, using config/normal inspection for OS and architecture. | Source-reviewed gap; retain Skopeo. |
| Preserve unsupported versus unverified | No. The function initializes `supported = False`, catches errors, and returns false; callers emit `ImageIssue`. | Yes operationally: nonzero exit plus an auth/network/not-found diagnostic. The skill maps access failures to unverified. | Fatal workflow gap. |
| Authenticated/private registry inspection | No credential/authfile interface. The private GHCR control became `ImageIssue` after a malformed anonymous token scope. | Yes: authfile, login, credentials, registry token, TLS/cert controls. Anonymous control clearly reported `unauthorized`. | Retain Skopeo for private images. |
| Registry retry and timeout controls | No CLI controls; the observed `requests.get` calls have no explicit timeout. | Yes: command timeout, retry count, and retry delay. | Skopeo is safer for agents. |
| Local OCI, archive, directory, daemon, and containers-storage inspection | No. Only constructs HTTPS registry/Docker Hub requests from a `FROM` token. | Yes, via documented transports including `oci:`, `oci-archive:`, `dir:`, `docker-archive:`, and `docker-daemon:`. | Retain Skopeo for local artifacts. |
| Understand `FROM --platform=...` | No. It queried `--platform=linux/amd64` as if that were an image repository. | No Dockerfile parsing, but correctly inspects the extracted real image and supports architecture overrides. | Requires both Dockerfile analysis and image inspection. |
| Understand `ARG`-based bases | Partial. It flags any `$` reference but did not resolve the in-file default. | Requires a resolved reference. | Report unresolved references as ambiguous, then resolve before inspection. |
| Understand `scratch` and stage aliases | No. It queried both `scratch` and the declared `build` stage as Docker Hub repositories, producing false positives. | Correctly not applicable; neither is an external image reference. | Dockerfile parser gap, not an image-inspector gap. |
| Case-insensitive Dockerfile instructions | No. Lowercase `from amd64/alpine:3.20` was silently missed. | Not applicable to source parsing. | Migrate-ease false negative. |
| Report architecture-specific Dockerfile packages/config | Yes. The static control produced a `PluginIssue` for `PyQBDI` and a `ConfigurationInfoIssue` for `TARGETARCH=amd64`. | No. | Unique, complementary migrate-ease value. |

## Matched cases and observed results

| Input | Migrate-ease result | Skopeo result | Assessment |
|---|---|---|---|
| `FROM alpine:latest` | No issue | Multi-architecture index includes `linux/arm64` | Match for the simplest control. |
| `FROM alpine:3.20` | Scanner `IndexError` | OCI index: amd64, arm variants, arm64/v8, 386, ppc64le, riscv64, s390x | False indeterminate on a common version tag. |
| `FROM amd64/alpine:3.20` | `ImageIssue` | Index has amd64 only, excluding `unknown/unknown` attestation | Match, but migrate-ease does not expose the evidence. |
| Alpine index digest `sha256:d9e853...` | `ImageIssue`; HTTP 400 from malformed URL | OCI index includes `linux/arm64/v8` | False positive. |
| Alpine amd64 child digest `sha256:c64c68...` | Same generic `ImageIssue`; HTTP 400 | Single OCI manifest; config is `linux/amd64` | Correct headline by accident, without proof or digest-type distinction. |
| `registry.k8s.io/pause:3.10` | `ImageIssue`; token JSON key error | Docker manifest list includes `linux/arm64` | False positive. |
| Private GHCR digest from this repo | `ImageIssue`; malformed anonymous token scope | Explicit `unauthorized` without credentials | Migrate-ease turns unverified into unsupported. |
| `FROM --platform=linux/amd64 alpine:3.20` | Queried the flag as the image and emitted `ImageIssue` | Can inspect `alpine:3.20`, but does not interpret source syntax | Complementary responsibilities; candidate parser is wrong. |
| `ARG BASE=...` then `FROM ${BASE}` | Generic `ImageIssue`, despite a default being present | Needs resolved concrete reference | Ambiguous until source resolution. |
| `FROM scratch` | `ImageIssue` after Docker Hub 404 | Not a registry reference | False positive. |
| `FROM build` after declaring stage `build` | `ImageIssue` after Docker Hub 404 | Not a registry reference | False positive. |
| Lowercase `from amd64/alpine:3.20` | No issue | Extracted reference is amd64-only | False negative. |
| `ENV TARGETARCH=amd64`; `RUN pip install PyQBDI` | Configuration and plugin findings | Not applicable | Demonstrates complementary migrate-ease value. |

## Setup and dependency differences for agents

Migrate-ease requires a Git checkout, Python/venv, its Python requirements, and
`libmagic` on macOS according to its README. The tested installation resolved 20
Python packages including Flask, GitPython, lxml, python-magic, requests, and
ruamel_yaml. Its Docker scanner itself needs registry networking and scans the
whole source tree. The repository commit must be recorded because the project
has no release tags even though the scanner declares version `1.0.0`.

A native Skopeo install is one binary plus its containers/image support files.
It does not require a daemon or root for ordinary remote inspection. Running the
official container, as in this test, avoids a host install but does require
Docker and explicit credential/path mounts. `jq` is useful for normalized
platform output but is not required by Skopeo. Agents must avoid putting secrets
on command lines and should use the user's authfile/login state.

Docker Buildx was present here (`v0.33.0-desktop.1`) and remains a reasonable
fallback for public registry platform inspection. It requires the Docker daemon;
the current skill correctly preserves Skopeo for daemonless operation, exact raw
manifest work, authenticated registries, and local transports.

## Recommendation and bounded follow-up

1. Retain `arm-container-inspect` as a separate skill/capability. It need not be
   branded as Skopeo-only; keeping the existing Skopeo-or-Buildx interface is the
   right abstraction.
2. Keep migrate-ease Docker scanning for static findings, but document its image
   result as triage only. Never cite an `ImageIssue` alone as proof that Arm64 is
   unavailable.
3. Require exact-reference handoff: resolve real external `FROM` references,
   skip `scratch` and stage aliases, inspect tags and digests through
   `arm-container-inspect`, and preserve supported/unsupported/unverified as
   three distinct states.
4. Optionally pursue a bounded upstream follow-up. Re-test a future migrate-ease
   revision with these checked-in fixtures only after it adopts a standards-based
   Docker reference/Dockerfile parser, supports OCI and Docker media types,
   preserves exact digests, and returns structured error states. Go/no-go remains
   zero crashes, zero false positives/negatives for the concrete public controls,
   and exact index-versus-child evidence. Authenticated and local transports may
   remain an explicit Skopeo handoff; if so, the separate capability still stays.

## Verification pass

- Falsifiable hypothesis: stated.
- Named comparison: migrate-ease Docker scanner 1.0.0 at `e92c735` versus Skopeo
  1.24.1 at the recorded container digest.
- Decisive tests and threshold: stated before the results.
- Observed evidence separated from source-reviewed limitations: the matched table
  is observed; the single-manifest and transport rows are source/documentation
  findings.
- Stop rule triggered: digest identity was lost, supported public images were
  reported as issues, and access failures were converted into unsupported.

The recommendation therefore does not depend on an untested edge case: the core
exact-digest and multi-registry requirements already fail.
