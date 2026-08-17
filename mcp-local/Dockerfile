# Copyright © 2025, Arm Limited and Contributors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# syntax=docker/dockerfile:1.7

# Keep these defaults synchronized with mcp-local/build-inputs.lock.json.
ARG EMBEDDINGS_IMAGE=ghcr.io/arm/mcp-embedding-vectorstore@sha256:724a53a6a8b29893c196c406a6ba9a41a1ec3b122b7aa2ceb587a67991519f88
ARG MCP_BUILD_INPUTS_IMAGE=ghcr.io/arm/mcp-build-inputs@sha256:d38c64ad12493ddacfe7a99e49f47e6cfcf1f9d2acf1696c797645d3099758a3
ARG UBUNTU_IMAGE=ubuntu:24.04@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90

FROM ${MCP_BUILD_INPUTS_IMAGE} AS mcp-inputs

FROM --platform=linux/arm64 ${EMBEDDINGS_IMAGE} AS embeddings

FROM ${UBUNTU_IMAGE} AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

# Install the complete builder package closure from the immutable input bundle.
# apt is forbidden from downloading anything here.
COPY --from=mcp-inputs /mcp-build-inputs/debs/builder/ /var/cache/apt/archives/
RUN --network=none apt-get install -y --no-download --no-install-recommends \
      /var/cache/apt/archives/*.deb && \
    rm -f /var/cache/apt/archives/*.deb && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN --network=none python3 -m venv "$VIRTUAL_ENV"

# The requirements file and wheelhouse come from the same immutable input
# bundle. Network access is disabled for installation.
COPY --from=mcp-inputs /mcp-build-inputs/metadata/requirements.lock /tmp/requirements.lock
COPY --from=mcp-inputs /mcp-build-inputs/wheels/ /tmp/wheels/
RUN --network=none pip install \
    --no-index \
    --find-links=/tmp/wheels \
    --require-hashes \
    --only-binary=:all: \
    --requirement /tmp/requirements.lock && \
    rm -rf /tmp/wheels /tmp/requirements.lock

# Install only migrate-ease. The old arm-linux-migration-tools installer also
# installed unrelated profiling tools and then removed them again.
COPY --from=mcp-inputs /mcp-build-inputs/migrate-ease.tar.gz /tmp/migrate-ease.tar.gz
RUN --network=none mkdir -p /opt/arm-migration-tools/migrate-ease && \
    tar -xzf /tmp/migrate-ease.tar.gz \
      --strip-components=1 \
      -C /opt/arm-migration-tools/migrate-ease && \
    rm /tmp/migrate-ease.tar.gz && \
    for scanner in cpp go java js python; do \
      wrapper="/usr/local/bin/migrate-ease-${scanner}"; \
      printf '%s\n' \
        '#!/bin/sh' \
        'cd /opt/arm-migration-tools/migrate-ease' \
        "exec /app/.venv/bin/python -m ${scanner} \"\$@\"" \
        > "${wrapper}"; \
      chmod 0755 "${wrapper}"; \
    done

COPY --from=mcp-inputs /mcp-build-inputs/performix.tar.gz /tmp/performix.tar.gz
RUN --network=none mkdir -p /opt/ArmPerformix-cli-current && \
    tar -xzf /tmp/performix.tar.gz -C /opt/ArmPerformix-cli-current && \
    chmod 0755 /opt/ArmPerformix-cli-current/apx && \
    rm /tmp/performix.tar.gz

# Keep the model, metadata, and index from the same immutable vector-store
# artifact. The model is architecture-independent even though generation ran
# on arm64.
RUN --network=none mkdir -p /app/data
COPY --from=embeddings /embedding-data/embedding-model/ /app/embedding-model/
COPY --from=embeddings /embedding-data/metadata.json /app/data/metadata.json
COPY --from=embeddings /embedding-data/usearch_index.bin /app/data/usearch_index.bin

COPY mcp-local/utils/ /app/utils/
COPY arm_kb_search/ /app/arm_kb_search/
COPY mcp-local/sql /app/sql/
COPY mcp-local/server.py /app/server.py

FROM ${UBUNTU_IMAGE} AS runtime

LABEL io.modelcontextprotocol.server.name="io.github.arm/arm-mcp"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_DIR=/workspace \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    SENTENCE_TRANSFORMER_MODEL_PATH=/app/embedding-model \
    APX_HOME=/opt/ArmPerformix-cli-current \
    APX_BIN=/opt/ArmPerformix-cli-current/apx \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

COPY --from=mcp-inputs /mcp-build-inputs/debs/runtime/ /var/cache/apt/archives/
RUN --network=none apt-get install -y --no-download --no-install-recommends \
      /var/cache/apt/archives/*.deb && \
    ln -sf /usr/bin/llvm-mca-18 /usr/bin/llvm-mca && \
    rm -f /var/cache/apt/archives/*.deb && \
    rm -rf /var/lib/apt/lists/* && \
    skopeo --version && \
    llvm-mca --version && \
    git --version

COPY --from=builder /opt/ArmPerformix-cli-current /opt/ArmPerformix-cli-current
COPY --from=builder /opt/arm-migration-tools/migrate-ease /opt/arm-migration-tools/migrate-ease
COPY --from=builder /usr/local/bin/migrate-ease-* /usr/local/bin/
COPY --from=builder /app /app

RUN --network=none ln -sf "${APX_BIN}" /usr/local/bin/apx

WORKDIR /app

VOLUME ["/workspace"]
ENTRYPOINT ["python", "-u", "server.py"]
