FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        wget \
        libopenblas-dev \
        libomp-dev \
        && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/ArmDeveloperEcosystem/sysreport.git /app/sysreport && \
    git clone https://github.com/migrate-ease/migrate-ease.git /app/migrate-ease && \
    git clone https://github.com/arm/arm-linux-migration-tools.git /app/arm-linux-migration-tools

# Copy requirements and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r /app/migrate-ease/requirements.txt

# Copy server code and supporting files
COPY server.py ./
COPY usearch_index.bin ./
COPY metadata.json ./

# Set Python to run in unbuffered mode for proper MCP communication
ENV PYTHONUNBUFFERED=1

VOLUME ["/workspace"]
ENV WORKSPACE_DIR=/workspace

# Run the MCP server
ENTRYPOINT ["python", "-u", "server.py"]