# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_DIR=/workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip curl sudo && \
    rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://raw.githubusercontent.com/arm/arm-linux-migration-tools/main/scripts/install.sh | bash

WORKDIR /app
ENV VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH
RUN python3 -m venv "$VIRTUAL_ENV" && pip install --upgrade pip

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY utils/ ./utils/
COPY server.py .
COPY usearch_index.bin .
COPY metadata.json .

VOLUME ["/workspace"]
ENTRYPOINT ["python", "-u", "server.py"]