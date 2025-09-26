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

## ARM-Specific nginx Configuration

When deploying nginx on ARM-based infrastructure (such as AWS Graviton instances), specific optimizations can significantly improve performance. This section provides ARM-specific configuration recommendations based on ARM architecture characteristics and AWS Graviton best practices.

### System-Level Optimizations

#### Transparent Huge Pages Configuration
Enable Transparent Huge Pages (THP) to reduce TLB miss rates and improve memory performance:

```bash
# Enable THP for better memory performance
echo always > /sys/kernel/mm/transparent_hugepage/enabled
# Alternative: use madvise for more conservative approach
echo madvise > /sys/kernel/mm/transparent_hugepage/enabled
```

For Linux kernels 6.9+, enable extended THP with Folios for additional page sizes:
```bash
# Enable 16kB pages
echo inherit > /sys/kernel/mm/transparent_hugepage/hugepages-16kB/enabled
# Enable 64kB pages  
echo inherit > /sys/kernel/mm/transparent_hugepage/hugepages-64kB/enabled
# Enable 2MB pages
echo inherit > /sys/kernel/mm/transparent_hugepage/hugepages-2048kB/enabled
```

#### Network Interface Optimizations
For high-performance nginx deployments on ARM instances with ENA (Elastic Network Adapter):

```bash
# Disable adaptive RX for latency-sensitive workloads
ethtool -C eth0 adaptive-rx off

# Stop irqbalance and set dedicated cores for IRQ processing
systemctl stop irqbalance

# Assign ethernet interrupts to specific cores
irqs=$(grep "eth0-Tx-Rx" /proc/interrupts | awk -F':' '{print $1}')
cpu=0
for i in $irqs; do
  echo $cpu > /proc/irq/$i/smp_affinity_list
  let cpu=${cpu}+1
done

# Disable Receive Packet Steering (RPS) - generally not needed on Graviton2+
for queue in /sys/class/net/eth0/queues/rx-*/rps_cpus; do
  echo 0 > $queue
done
```

### nginx Configuration for ARM

#### Compiler Optimizations for Custom nginx Builds
When building nginx from source on ARM architecture, use these compiler flags:

```bash
# For Graviton2/3/4 instances - balanced approach
export CFLAGS="-O2 -march=armv8.2-a -mtune=neoverse-n1"

# For Graviton3-specific optimizations
export CFLAGS="-O2 -mcpu=neoverse-v1"

# For Graviton4-specific optimizations  
export CFLAGS="-O2 -mcpu=neoverse-v2"

# Configure nginx with optimized flags
./configure --with-cc-opt="$CFLAGS" --with-ld-opt="-Wl,-O1"
```

#### nginx.conf ARM-Specific Tuning

```nginx
# ARM-optimized nginx configuration

# Worker processes - set to number of ARM cores
worker_processes auto;

# Use epoll on Linux ARM systems
events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
    worker_aio_requests 32;
}

http {
    # Enable sendfile for efficient file transfers on ARM
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    
    # ARM-optimized buffer sizes
    client_body_buffer_size 128k;
    client_max_body_size 10m;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 4k;
    output_buffers 1 32k;
    postpone_output 1460;
    
    # Connection handling optimized for ARM
    keepalive_timeout 65;
    keepalive_requests 100;
    reset_timedout_connection on;
    
    # Gzip compression settings for ARM processors
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_comp_level 6;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/xml+rss;
    
    # ARM-specific SSL optimizations
    ssl_buffer_size 4k;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # Optimize for ARM's cache hierarchy
    open_file_cache max=10000 inactive=20s;
    open_file_cache_valid 30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;
}
```

#### Performance Monitoring for ARM

Monitor ARM-specific performance metrics:

```bash
# Check ARM CPU utilization
top -p $(pgrep nginx)

# Monitor ARM-specific PMU counters (if available)
perf stat -e cycles,instructions,cache-misses,cache-references nginx -t

# Check memory usage patterns on ARM
cat /proc/$(pgrep nginx | head -1)/smaps | grep -E "Pss|Rss"

# Monitor network performance
ss -tulpn | grep nginx
```

### ARM Load Balancing Configuration

For ARM-based load balancing scenarios:

```nginx
upstream backend_arm {
    # Use consistent hashing for ARM-optimized distribution
    hash $remote_addr consistent;
    
    # ARM instances with keep-alive optimization
    server 10.0.1.10:80 max_fails=3 fail_timeout=30s;
    server 10.0.1.11:80 max_fails=3 fail_timeout=30s;
    
    # Connection pooling for ARM efficiency
    keepalive 32;
    keepalive_requests 100;
    keepalive_timeout 60s;
}

server {
    location / {
        proxy_pass http://backend_arm;
        
        # ARM-optimized proxy settings
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
        proxy_busy_buffers_size 8k;
        
        # Connection reuse for ARM efficiency
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

### Container Deployment on ARM

When deploying nginx in containers on ARM:

```dockerfile
# Use ARM-optimized base image
FROM arm64v8/nginx:alpine

# Copy ARM-optimized configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Set ARM-specific environment variables
ENV NGINX_WORKER_PROCESSES=auto
ENV NGINX_WORKER_CONNECTIONS=4096
```

### Troubleshooting ARM nginx Issues

Common ARM-specific nginx troubleshooting:

```bash
# Check if nginx is compiled with ARM optimizations
nginx -V 2>&1 | grep -o '\-march=\S*\|\-mcpu=\S*'

# Verify LSE (Large System Extensions) support
objdump -d /usr/sbin/nginx | grep -E 'cas|casp|swp|ldadd' | wc -l

# Check for ARM NEON SIMD usage in SSL/crypto
ldd /usr/sbin/nginx | grep ssl

# Monitor ARM-specific performance counters
perf record -g nginx
perf report
```

### References

- [AWS Graviton Getting Started Guide](https://github.com/aws/aws-graviton-getting-started)
- [ARM Developer Documentation](https://developer.arm.com/documentation/)
- [nginx ARM64 Optimization Guide](https://nginx.org/en/docs/)
- [AWS Graviton Performance Runbook](https://github.com/aws/aws-graviton-getting-started/tree/main/perfrunbook)