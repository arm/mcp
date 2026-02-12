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

# Stage 1: Build main application with embedded vector database generation
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_DIR=/workspace

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

COPY embedding-generation/generate-chunks.py /tmp/embedding-generation/generate-chunks.py
COPY embedding-generation/local_vectorstore_creation.py /tmp/embedding-generation/local_vectorstore_creation.py
COPY embedding-generation/requirements.txt /tmp/embedding-generation/requirements.txt
COPY embedding-generation/urls-to-chunk.csv /tmp/embedding-generation/urls-to-chunk.csv

# Copy embedding data and scripts from the embedding base image
COPY --from=joestech324/mcp-embedding-base:latest /embedding-data/intrinsic_chunks /tmp/embedding-generation/intrinsic_chunks

# Install dependencies for vector database generation
WORKDIR /tmp/embedding-generation
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Generate vector database
RUN python3 generate-chunks.py urls-to-chunk.csv && \
    python3 local_vectorstore_creation.py

# Set up MCP server application
WORKDIR /app
ENV VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

RUN python3 -m venv "$VIRTUAL_ENV" && pip install --upgrade pip

COPY mcp-local/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy generated vector database files
RUN mkdir -p ./data
RUN cp /tmp/embedding-generation/metadata.json ./data/ && \
    cp /tmp/embedding-generation/usearch_index.bin ./data/

COPY mcp-local/utils/ ./utils/
COPY mcp-local/server.py .

FROM ubuntu:24.04 AS runtime

# MCP Registry verification label
LABEL io.modelcontextprotocol.server.name="io.github.arm/arm-mcp"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_DIR=/workspace \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    ca-certificates libmagic1 git llvm \
    libgpgme11 libassuan0 libdevmapper1.02.1 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/arm-migration-tools /opt/arm-migration-tools
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/bin/skopeo /usr/bin/skopeo
COPY --from=builder /app /app

WORKDIR /app

VOLUME ["/workspace"]
ENTRYPOINT ["python", "-u", "server.py"]
