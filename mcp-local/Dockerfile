# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_DIR=/workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip curl sudo libelf-dev \
    build-essential git wget unzip \
    libopenblas-dev libomp-dev \
    libgtk-3-0 libnotify4 libnss3 libx11-xcb1 libxss1 libxtst6 \
    xdg-utils libsecret-1-0 libatspi2.0-0 \
    ca-certificates file tar xz-utils jq procps \
    libmagic1 && \
    rm -rf /var/lib/apt/lists/*

# Install all ARM migration tools
RUN curl -sSL https://raw.githubusercontent.com/arm/arm-linux-migration-tools/main/scripts/install.sh | bash

# Remove unwanted tools
RUN rm -f /usr/local/bin/aperf \
         /usr/local/bin/topdown-tool \
         /usr/local/bin/processwatch \
         /usr/local/bin/papi_* && \
    rm -rf /opt/arm-migration-tools/aperf \
           /opt/arm-migration-tools/topdown-tool \
           /opt/arm-migration-tools/telemetry-solution \
           /opt/arm-migration-tools/processwatch \
           /opt/arm-migration-tools/papi

# Install ATP
#RUN curl -fsSL -o /tmp/atp.deb \
#        https://artifacts.tools.arm.com/arm-total-performance/installers/latest/linux/arm64/ArmTotalPerformance-arm64.deb && \
#    apt-get install -y --no-install-recommends /tmp/atp.deb && \
#    rm -f /tmp/atp.deb

#ENV PATH="/opt/arm/total-performance/bin:/opt/ArmTotalPerformance/bin:/opt/arm-migration-tools/venv/bin:${PATH}"

# --- Install atperf into a fixed location, keep full directory structure ---
ENV ATPERF_HOME=/opt/atperf \
    ATPERF_BIN=/opt/atperf/atperf

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl tar; \
    rm -rf /var/lib/apt/lists/*; \
    \
    mkdir -p "${ATPERF_HOME}"; \
    tmpdir="$(mktemp -d)"; \
    cd "$tmpdir"; \
    \
    curl -fsSL -L -o atperf.tar.gz \
      "https://artifacts.tools.arm.com/its-arm-total-performance-cli/latest/linux/arm64/atperf.tar.gz"; \
    \
    # Extract directly into $ATPERF_HOME (preserves data/lib/etc alongside atperf)
    tar -xzf atperf.tar.gz -C "${ATPERF_HOME}"; \
    \
    # Ensure executable bit
    chmod +x "${ATPERF_BIN}"; \
    \
    # Optional: convenience symlink
    ln -sf "${ATPERF_BIN}" /usr/local/bin/atperf; \
    \
    cd /; \
    rm -rf "$tmpdir"

WORKDIR /app
ENV VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

RUN python3 -m venv "$VIRTUAL_ENV" && pip install --upgrade pip

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY data/ ./data/
COPY utils/ ./utils/
COPY server.py .
COPY test_json.py .

VOLUME ["/workspace"]
ENTRYPOINT ["python", "-u", "server.py"]