# Arm MCP Server

This repository contains a Model Context Protocol (MCP) server that integrates:
- [migrate-ease](https://github.com/migrate-ease/migrate-ease) for scanning codebases
- [sysreport](https://github.com/ArmDeveloperEcosystem/sysreport) for system information
- Docker image architecture checks
- A semantic search knowledge base (using USearch + embeddings)

The server is designed to run inside a Docker container and expose tools to MCP clients such as **q CLI** or **VS Code MCP integration**.

The Dockerfile is located in mcp-local.

embedding-generation is exclusively for creating the vector db, and mcp-remote is the IaC for AWS

---

## 1. Build the container

From the root of this project (where the `Dockerfile` lives):

```bash
docker buildx build --platform linux/arm64 -t arm-mcp .
```

The command above will only build the Arm version. To build the multi-arch version and push to dockerhub:

```bash
docker buildx build \
  --platform linux/arm64,linux/amd64 \
  -t joestech324/mcp:arm-mcp-[version-number] \
  -t joestech324/mcp:latest \
  . --push
```

Where [version-number] is the current version.

To get into the container for troubleshooting, use

```bash
docker run --rm -it --entrypoint /bin/bash arm-mcp
```

## 2. Set up the MCP config

### for q cli

```json
{
  "mcpServers": {
    "arm_torq": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v", "[local directory path]:/workspace",
        "--name", "arm-mcp",
        "arm-mcp"
      ],
      "env": {},
      "timeout": 60000
    }
  }
}
```

Replace [local directory path] with the local path that you want the mcp server to be able to access.

For q cli this config should be placed in ~/.aws/amazonq/mcp.json

### Codex CLI

```toml
[projects."/path/to/your/project"]
trust_level = "trusted"

[mcp_servers.arm_torq]
command = "docker"
args = [
  "run",
  "--rm",
  "-i",
  "-v", "[local directory path]:/workspace",
  "--name", "arm-mcp",
  "arm-mcp"
]
env = {}
```

Replace `[local directory path]` with the local path that you want the mcp server to be able to access, and replace `/path/to/your/project` with your actual project path.

For Codex CLI this config should be saved in `~/.codex/config.toml`.

### GitHub Copilot in VS Code

```json
{
  "servers": {
    "arm_torq": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v", "[local directory path]:/workspace",
        "arm-mcp"
      ]
    }
  }
}
```

The config can either be put in:

`.vscode/mcp.json` local to the open project folder, or

globally here (for macOS):

`~/Library/Application Support/Code/User/mcp.json`

The easiest way to open this file in VS Code for editing is command+shift+p and search for

MCP: Open User Configuration

---

## 3. Arm nginx Performance Tuning

This section covers performance tuning recommendations for nginx running on Arm-based systems (ARM64/AArch64). These optimizations can significantly improve throughput, reduce latency, and enhance overall performance when migrating from x86 to Arm infrastructure.

### 3.1 Compilation and Build Optimizations

**Use ARM-optimized nginx builds:**
```bash
# Install nginx with ARM64 optimizations
sudo apt update
sudo apt install nginx

# Or build from source with ARM-specific optimizations
./configure --with-cc-opt="-O2 -march=armv8-a+crc" \
            --with-ld-opt="-Wl,-O1" \
            --with-file-aio \
            --with-http_v2_module \
            --with-http_realip_module \
            --with-http_ssl_module
```

**Compiler flags for optimal ARM performance:**
- `-march=armv8-a+crc`: Enable ARMv8-A with CRC instructions
- `-mtune=cortex-a76`: Tune for specific ARM CPU (adjust based on your hardware)
- `-O2` or `-O3`: Enable aggressive optimizations

### 3.2 Worker Process Configuration

**Optimize worker processes for ARM cores:**
```nginx
# Set worker processes to match ARM CPU cores
worker_processes auto;

# Bind workers to specific ARM cores for better cache locality
worker_cpu_affinity auto;

# Increase worker connections for ARM's efficient handling
events {
    worker_connections 8192;
    use epoll;
    multi_accept on;
}
```

### 3.3 Memory and Buffer Tuning

**ARM-optimized buffer sizes:**
```nginx
# Optimize buffer sizes for ARM cache lines (typically 64 bytes)
client_body_buffer_size 16K;
client_header_buffer_size 1k;
client_max_body_size 8m;
large_client_header_buffers 4 16k;

# Output buffering optimization
output_buffers 2 32k;
postpone_output 1460;
```

**Memory management for ARM:**
```nginx
# ARM-friendly memory allocation
client_body_timeout 12;
client_header_timeout 12;
keepalive_timeout 15;
send_timeout 10;
```

### 3.4 ARM-Specific SSL/TLS Optimizations

**Leverage ARM cryptographic extensions:**
```nginx
# SSL optimization for ARM Crypto Extensions
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305;
ssl_prefer_server_ciphers off;

# Enable SSL session caching
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 10m;
```

### 3.5 Gzip and Compression

**ARM-optimized compression settings:**
```nginx
# Gzip compression tuned for ARM
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_proxied any;
gzip_comp_level 6;
gzip_types
    application/atom+xml
    application/javascript
    application/json
    application/rss+xml
    application/vnd.ms-fontobject
    application/x-font-ttf
    application/x-web-app-manifest+json
    application/xhtml+xml
    application/xml
    font/opentype
    image/svg+xml
    image/x-icon
    text/css
    text/plain
    text/x-component;
```

### 3.6 File System and I/O Optimization

**Optimize for ARM storage subsystems:**
```nginx
# Enable efficient file operations
sendfile on;
tcp_nopush on;
tcp_nodelay on;

# ARM-friendly file caching
open_file_cache max=100000 inactive=20s;
open_file_cache_valid 30s;
open_file_cache_min_uses 2;
open_file_cache_errors on;
```

### 3.7 Load Balancing for ARM Clusters

**ARM-aware upstream configuration:**
```nginx
upstream arm_backend {
    # Use least connections for ARM's efficient context switching
    least_conn;
    
    # ARM backend servers
    server 10.0.1.10:8080 weight=3;
    server 10.0.1.11:8080 weight=3;
    server 10.0.1.12:8080 weight=3;
    
    # Health checks
    keepalive 32;
    keepalive_requests 100;
    keepalive_timeout 60s;
}
```

### 3.8 Monitoring and Performance Analysis

**Key metrics for ARM nginx performance:**
```bash
# Monitor ARM-specific performance metrics
# CPU utilization per core
top -p $(pgrep nginx)

# Memory usage patterns
cat /proc/$(pgrep nginx)/smaps

# Network performance
ss -tuln | grep :80
```

**Tools for ARM nginx tuning:**
- `perf`: ARM performance analysis
- `htop`: Multi-core utilization monitoring  
- `iotop`: I/O performance on ARM storage
- `nginx-amplify`: Real-time ARM nginx monitoring

### 3.9 ARM Graviton-Specific Optimizations

**For AWS Graviton instances:**
```nginx
# Graviton2/3 optimized worker configuration
worker_processes auto;
worker_rlimit_nofile 65535;

# Graviton memory optimization
worker_connections 4096;
keepalive_timeout 30;
keepalive_requests 1000;
```

### 3.10 Performance Testing on ARM

**Benchmark commands for ARM nginx:**
```bash
# Basic performance test
ab -n 10000 -c 100 http://your-arm-server/

# Sustained load test with ARM considerations
wrk -t12 -c400 -d30s --latency http://your-arm-server/

# SSL performance test
openssl speed -evp aes-256-gcm
```

### References and Further Reading

- [ARM Architecture Reference Manual](https://developer.arm.com/documentation/ddi0487/latest)
- [ARM Neoverse N1 Software Optimization Guide](https://developer.arm.com/documentation/swog309707/latest)
- [nginx Performance Tuning](https://nginx.org/en/docs/http/ngx_http_core_module.html)
- [AWS Graviton Performance Optimization](https://github.com/aws/aws-graviton-getting-started)

*This tuning guide was compiled using ARM performance optimization knowledge and best practices for nginx deployment on ARM64 architectures.*