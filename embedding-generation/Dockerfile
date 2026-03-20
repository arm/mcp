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

ARG EMBEDDING_BASE_IMAGE=armlimited/arm-mcp:mcp-embedding-base
FROM ${EMBEDDING_BASE_IMAGE} AS intrinsic-chunks

FROM ubuntu:24.04 AS builder

ARG SOURCES_FILE=vector-db-sources.csv
ARG EMBEDDING_MODEL=all-MiniLM-L6-v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_INDEX_URL=https://download.pytorch.org/whl/cpu \
    PIP_EXTRA_INDEX_URL=https://pypi.org/simple \
    SENTENCE_TRANSFORMER_MODEL=${EMBEDDING_MODEL} \
    HF_HOME=/embedding-data/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/embedding-data/.cache/sentence_transformers

# Install Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /embedding-data

# Copy Python scripts and dependencies
COPY generate-chunks.py .
COPY document_chunking.py .
COPY local_vectorstore_creation.py .
COPY vector-db-sources.csv .
COPY requirements.txt .

# Copy intrinsic chunks data from the cached base image
COPY --from=intrinsic-chunks /embedding-data/intrinsic_chunks ./intrinsic_chunks

# Install Python dependencies (force CPU-only torch)
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Pre-download the embedding model so local/offline loads succeed later in the build.
RUN python3 -c "from sentence_transformers import SentenceTransformer; import os; SentenceTransformer(os.environ['SENTENCE_TRANSFORMER_MODEL'], cache_folder=os.environ['SENTENCE_TRANSFORMERS_HOME'])"

# Generate vector database
RUN python3 generate-chunks.py ${SOURCES_FILE} && \
    python3 local_vectorstore_creation.py && \
    rm -f embeddings_*.txt

FROM scratch AS embeddings

COPY --from=builder /embedding-data/metadata.json /embedding-data/metadata.json
COPY --from=builder /embedding-data/usearch_index.bin /embedding-data/usearch_index.bin
