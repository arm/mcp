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

## ARM-Specific Nginx Configuration

This section provides comprehensive guidance for configuring and optimizing Nginx on ARM architectures, particularly for ARM64 (aarch64) systems like AWS Graviton processors.

### Building Nginx for ARM64

#### Compiler Optimizations
When building Nginx from source on ARM64 systems, use these compiler flags for optimal performance:

```bash
./configure \
    --with-cc-opt="-O3 -march=armv8-a+crc -mtune=generic -fPIC" \
    --with-ld-opt="-Wl,-rpath=/usr/local/lib" \
    --prefix=/etc/nginx \
    --sbin-path=/usr/sbin/nginx \
    --modules-path=/usr/lib/nginx/modules \
    --conf-path=/etc/nginx/nginx.conf \
    --error-log-path=/var/log/nginx/error.log \
    --http-log-path=/var/log/nginx/access.log \
    --with-pcre-jit \
    --with-file-aio \
    --with-http_ssl_module \
    --with-http_v2_module \
    --with-http_realip_module \
    --with-http_stub_status_module \
    --with-http_gzip_static_module \
    --with-threads \
    --with-stream \
    --with-stream_ssl_module
```

#### Key ARM64 Optimizations:
- **`-march=armv8-a+crc`**: Enables ARM64 CRC extensions for better performance
- **`-mtune=generic`**: Optimizes for generic ARM64 processors
- **`--with-pcre-jit`**: Enables PCRE JIT compilation for faster regex processing
- **`--with-file-aio`**: Enables asynchronous file I/O on ARM64

### ARM64-Optimized Configuration

#### Worker Process Configuration
```nginx
# /etc/nginx/nginx.conf

# Set worker processes to match ARM64 CPU cores
# For AWS Graviton instances, this typically ranges from 2-64 cores
worker_processes auto;

# ARM64 processors benefit from CPU affinity binding
worker_cpu_affinity auto;

# Optimize for ARM64 memory page sizes (typically 4KB or 64KB)
worker_rlimit_nofile 65536;

events {
    # ARM64 optimized event handling
    use epoll;
    worker_connections 4096;
    
    # Enable multi_accept for better performance on ARM64
    multi_accept on;
}

http {
    # ARM64 memory optimization
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    
    # Optimized buffer sizes for ARM64 cache lines (64-128 bytes)
    client_body_buffer_size 128k;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 4k;
    output_buffers 1 32k;
    postpone_output 1460;
    
    # ARM64 optimized keepalive settings
    keepalive_timeout 65;
    keepalive_requests 1000;
}
```

#### Caching Configuration for ARM64
```nginx
# Proxy cache configuration optimized for ARM64 memory hierarchy
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=my_cache:64m max_size=1g 
                 inactive=60m use_temp_path=off;

server {
    location / {
        # ARM64 optimized caching
        proxy_cache my_cache;
        proxy_cache_valid 200 302 60m;
        proxy_cache_valid 404 1m;
        
        # Buffer sizes optimized for ARM64
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
        proxy_busy_buffers_size 8k;
        
        # ARM64 specific headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-ARM64-Optimized "true";
        
        proxy_pass http://backend;
    }
}
```

### Container Deployment on ARM64

#### Dockerfile Optimizations for ARM64
```dockerfile
FROM nginx:alpine

# Use ARM64-specific base image
# alpine images are well-optimized for ARM64

# Install additional modules optimized for ARM64
RUN apk add --no-cache \
    nginx-mod-http-geoip \
    nginx-mod-http-image-filter \
    nginx-mod-http-perl \
    nginx-mod-http-xslt-filter

# Copy ARM64-optimized configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Expose ports
EXPOSE 80 443

# Health check optimized for ARM64
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
```

#### Docker Compose for ARM64
```yaml
version: '3.8'
services:
  nginx:
    image: nginx:alpine
    platform: linux/arm64
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    environment:
      - ARM64_OPTIMIZED=true
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 512M
```

### Performance Tuning for ARM64

#### System-level Optimizations
```bash
# /etc/sysctl.conf - ARM64 specific optimizations

# Network optimizations for ARM64
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 1200
net.ipv4.tcp_max_orphans = 3276800

# ARM64 memory optimizations
vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5

# File descriptor limits for ARM64
fs.file-max = 2097152
fs.nr_open = 2097152
```

#### CPU Governor Settings for ARM64
```bash
# Set CPU governor for optimal ARM64 performance
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Enable ARM64 CPU turbo boost if available
echo 1 | sudo tee /sys/devices/system/cpu/cpufreq/boost
```

### Monitoring ARM64 Performance

#### Key Metrics for ARM64 Nginx
```nginx
# Status configuration for ARM64 monitoring
server {
    listen 8080;
    server_name localhost;
    
    location /nginx_status {
        stub_status on;
        access_log off;
        allow 127.0.0.1;
        deny all;
        
        # Add ARM64 specific headers
        add_header X-ARM64-Server "true";
        add_header X-CPU-Architecture "aarch64";
    }
}
```

#### Logging Configuration for ARM64
```nginx
# ARM64 optimized log format
log_format arm64_combined '$remote_addr - $remote_user [$time_local] '
                          '"$request" $status $body_bytes_sent '
                          '"$http_referer" "$http_user_agent" '
                          'rt=$request_time uct="$upstream_connect_time" '
                          'uht="$upstream_header_time" urt="$upstream_response_time" '
                          'arch="aarch64"';

access_log /var/log/nginx/access.log arm64_combined;
```

### SSL/TLS Optimization for ARM64

#### ARM64-Optimized SSL Configuration
```nginx
# SSL configuration optimized for ARM64 processors
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers off;

# ARM64 optimized SSL session settings
ssl_session_cache shared:SSL:50m;
ssl_session_timeout 1d;
ssl_session_tickets off;

# OCSP stapling optimized for ARM64
ssl_stapling on;
ssl_stapling_verify on;

# Diffie-Hellman parameters for ARM64
ssl_dhparam /etc/nginx/ssl/dhparam.pem;
```

### Load Balancing for ARM64

#### Upstream Configuration for ARM64 Clusters
```nginx
upstream arm64_backend {
    # ARM64 optimized load balancing
    least_conn;
    
    # ARM64 server instances
    server 10.0.1.10:8080 max_fails=3 fail_timeout=30s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=30s;
    server 10.0.1.12:8080 max_fails=3 fail_timeout=30s;
    
    # Keep-alive connections optimized for ARM64
    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}

server {
    location / {
        proxy_pass http://arm64_backend;
        
        # ARM64 optimized proxy settings
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_connect_timeout 5s;
        proxy_send_timeout 10s;
        proxy_read_timeout 10s;
    }
}
```

### Troubleshooting ARM64 Nginx Issues

#### Common ARM64-Specific Issues:
1. **Memory alignment issues**: Ensure proper buffer sizes align with ARM64 cache lines
2. **Endianness concerns**: ARM64 is little-endian; verify binary module compatibility  
3. **Instruction set support**: Some modules may require ARM64-specific compilation
4. **Performance regression**: Compare with x86_64 baselines using consistent workloads

#### Debug Configuration:
```nginx
error_log /var/log/nginx/error.log debug;
rewrite_log on;

# ARM64 specific debug info
add_header X-Debug-Architecture $server_addr;
add_header X-Debug-CPU-Count $worker_processes;
```

### ARM64 Best Practices Summary

1. **Always build with ARM64-specific compiler optimizations**
2. **Use CPU affinity and optimize worker processes for available cores**
3. **Adjust buffer sizes to match ARM64 memory architecture**
4. **Enable hardware acceleration features when available**
5. **Monitor performance metrics specific to ARM64 workloads**
6. **Test thoroughly when migrating from x86_64 to ARM64**
7. **Keep ARM64-optimized container images updated**