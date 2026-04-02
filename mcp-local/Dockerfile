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

ARG EMBEDDINGS_IMAGE=armlimited/arm-mcp:embeddings-latest
ARG EMBEDDING_MODEL=all-MiniLM-L6-v2
# EMBEDDINGS_IMAGE must point to an embeddings image tag (e.g., armlimited/arm-mcp:embeddings-YYYY-MM-DD).
FROM --platform=linux/arm64 ${EMBEDDINGS_IMAGE} AS embeddings

# Stage 1: Build main application with prebuilt vector database
FROM ubuntu:24.04 AS builder
ARG EMBEDDING_MODEL=all-MiniLM-L6-v2
ARG TARGETPLATFORM

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_DIR=/workspace \
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers \
    SENTENCE_TRANSFORMER_MODEL=${EMBEDDING_MODEL}

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    curl git wget unzip sudo \
    build-essential libelf-dev \
    ca-certificates file tar xz-utils jq libmagic1 && \
    rm -rf /var/lib/apt/lists/*
RUN curl -sSL https://raw.githubusercontent.com/JoeStech/arm-linux-migration-tools/main/scripts/install.sh | bash
# Temp until migrate-ease is updated
RUN curl -sSL https://raw.githubusercontent.com/JoeStech/migrate-ease/main/js/advisor/main.py \
    -o /opt/arm-migration-tools/migrate-ease/js/advisor/main.py

RUN rm -f /usr/local/bin/aperf \
         /usr/local/bin/topdown-tool \
         /usr/local/bin/processwatch \
         /usr/local/bin/papi_* && \
    rm -rf /opt/arm-migration-tools/aperf \
           /opt/arm-migration-tools/topdown-tool \
           /opt/arm-migration-tools/telemetry-solution \
           /opt/arm-migration-tools/processwatch \
           /opt/arm-migration-tools/papi

RUN set -eux; \
    if [ "$TARGETPLATFORM" = "linux/amd64" ]; then \
        echo "WARNING: Using x86_64 Performix CLI on amd64 target. Results may vary from Arm64."; \
        APX_TARBALL="ArmPerformix-cli-1.0.0-linux-x64.tar.gz"; \
    else \
        APX_TARBALL="ArmPerformix-cli-1.0.0-linux-arm64.tar.gz"; \
    fi; \
    APX_HOME="/opt/ArmPerformix-cli-current"; \
    APX_URL="https://artifacts.tools.arm.com/arm-performix/cli/1.0.0/${APX_TARBALL}"; \
    mkdir -p "${APX_HOME}"; \
    tmpdir="$(mktemp -d)"; \
    cd "$tmpdir"; \
    curl -fsSL -L -o "${APX_TARBALL}" "${APX_URL}"; \
    tar -xzf "${APX_TARBALL}" -C "${APX_HOME}"; \
    chmod +x "${APX_HOME}/apx"; \
    ln -sf "${APX_HOME}/apx" /usr/local/bin/apx; \
    rm -rf "$tmpdir"

# Set up MCP server application
WORKDIR /app
ENV VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

RUN python3 -m venv "$VIRTUAL_ENV" && pip install --upgrade pip

COPY mcp-local/requirements.txt .
# Install dependencies using CPU-only PyTorch wheels for supported Linux targets.
RUN if [ "$TARGETPLATFORM" = "linux/amd64" ] || [ "$TARGETPLATFORM" = "linux/arm64" ]; then \
        PIP_INDEX_URL=https://download.pytorch.org/whl/cpu \
        PIP_EXTRA_INDEX_URL=https://pypi.org/simple \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

RUN mkdir -p "$HF_HOME" "$SENTENCE_TRANSFORMERS_HOME" && \
    python -c "from sentence_transformers import SentenceTransformer; import os; SentenceTransformer(os.environ['SENTENCE_TRANSFORMER_MODEL'], cache_folder=os.environ['SENTENCE_TRANSFORMERS_HOME'])"

# Copy generated vector database files
RUN mkdir -p ./data
COPY --from=embeddings /embedding-data/metadata.json ./data/metadata.json
COPY --from=embeddings /embedding-data/usearch_index.bin ./data/usearch_index.bin

COPY mcp-local/utils/ ./utils/
COPY mcp-local/sql ./sql/
COPY mcp-local/server.py .

FROM ubuntu:24.04 AS runtime

# MCP Registry verification label
LABEL io.modelcontextprotocol.server.name="io.github.arm/arm-mcp"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_DIR=/workspace \
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers \
    APX_HOME=/opt/ArmPerformix-cli-current \
    APX_BIN=/opt/ArmPerformix-cli-current/apx \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    KNOWN_HOSTS_PATH=/run/keys/known_hosts \
    SSH_KEY_PATH=/run/keys/ssh-key.pem

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    ca-certificates libmagic1 git llvm-18 \
    libgpgme11 libassuan0 libdevmapper1.02.1 && \
    ln -sf /usr/bin/llvm-mca-18 /usr/bin/llvm-mca && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/ArmPerformix-cli-current /opt/ArmPerformix-cli-current
COPY --from=builder /opt/arm-migration-tools/migrate-ease /opt/arm-migration-tools/migrate-ease
COPY --from=builder /opt/arm-migration-tools/venv /opt/arm-migration-tools/venv
COPY --from=builder /usr/local/bin/migrate-ease-cpp /usr/local/bin/migrate-ease-cpp
COPY --from=builder /usr/local/bin/migrate-ease-go /usr/local/bin/migrate-ease-go
COPY --from=builder /usr/local/bin/migrate-ease-java /usr/local/bin/migrate-ease-java
COPY --from=builder /usr/local/bin/migrate-ease-js /usr/local/bin/migrate-ease-js
COPY --from=builder /usr/local/bin/migrate-ease-python /usr/local/bin/migrate-ease-python
COPY --from=builder /usr/bin/skopeo /usr/bin/skopeo
COPY --from=builder /app /app

RUN ln -sf "${APX_BIN}" /usr/local/bin/apx

WORKDIR /app

VOLUME ["/workspace"]
ENTRYPOINT ["python", "-u", "server.py"]
