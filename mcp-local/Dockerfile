# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_DIR=/workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip curl sudo libelf-dev && \
    rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://raw.githubusercontent.com/arm/arm-linux-migration-tools/main/scripts/install.sh | bash

WORKDIR /app
ENV VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH
RUN python3 -m venv "$VIRTUAL_ENV" && pip install --upgrade pip

RUN dpkg --print-architecture
RUN apt-get update && apt-cache policy libgtk-3-0 | sed -n '1,40p'

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        wget \
        curl \
        unzip \
        libopenblas-dev \
        libomp-dev \
        libgtk-3-0 \
        libnotify4 \
        libnss3 \
        libx11-xcb1 \
        libxss1 \
        libxtst6 \
        xdg-utils \
        libsecret-1-0 \
        && rm -rf /var/lib/apt/lists/*

# ---- ATP (Arm Total Performance) install ----
ENV DEBIAN_FRONTEND=noninteractive

# Re-open apt index (since you cleaned it), install likely runtime deps,
# fetch the .deb, install it, and clean up — all in one layer.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgtk-3-0 \
        libnotify4 \
        libnss3 \
        libx11-xcb1 \
        libxss1 \
        libxtst6 \
        xdg-utils \
        libsecret-1-0 \
        libatspi2.0-0 \
    && curl -fsSL -o /tmp/atp.deb \
        https://artifacts.tools.arm.com/arm-total-performance/installers/latest/linux/arm64/ArmTotalPerformance-arm64.deb \
    && apt-get install -y --no-install-recommends /tmp/atp.deb \
    && rm -f /tmp/atp.deb \
    && rm -rf /var/lib/apt/lists/*

# Ensure the CLI is reachable even if the installer doesn’t put it on PATH
ENV PATH="/opt/arm/total-performance/bin:/opt/ArmTotalPerformance/bin:${PATH}"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy server code and supporting files
COPY data/ ./data/
COPY utils/ ./utils/
COPY server.py .

# Set Python to run in unbuffered mode for proper MCP communication
ENV PYTHONUNBUFFERED=1

VOLUME ["/workspace"]
ENTRYPOINT ["python", "-u", "server.py"]