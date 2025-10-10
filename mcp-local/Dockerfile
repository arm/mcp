# syntax=docker/dockerfile:1.7
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

RUN curl -sSL https://raw.githubusercontent.com/arm/arm-linux-migration-tools/main/scripts/install.sh | bash

RUN rm -f /usr/local/bin/aperf \
         /usr/local/bin/topdown-tool \
         /usr/local/bin/processwatch \
         /usr/local/bin/papi_* && \
    rm -rf /opt/arm-migration-tools/aperf \
           /opt/arm-migration-tools/topdown-tool \
           /opt/arm-migration-tools/telemetry-solution \
           /opt/arm-migration-tools/processwatch \
           /opt/arm-migration-tools/papi

WORKDIR /app
ENV VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

RUN python3 -m venv "$VIRTUAL_ENV" && pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY data/ ./data/
COPY utils/ ./utils/
COPY server.py .

FROM ubuntu:24.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_DIR=/workspace \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    ca-certificates libmagic1 git llvm && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/arm-migration-tools /opt/arm-migration-tools
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /app /app

WORKDIR /app

VOLUME ["/workspace"]
ENTRYPOINT ["python", "-u", "server.py"]
