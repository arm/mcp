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

## 3. Arm-specific nginx Configuration

This section provides nginx configuration guidance specifically for Arm64 architecture deployments, based on the production infrastructure used by this MCP server.

### Production Architecture Overview

The MCP server is deployed on **AWS Graviton3 (m8g.large)** instances running **Ubuntu 24.04 ARM64**. The architecture includes:

- **ARM64 Ubuntu 24.04** base system
- **nginx** as reverse proxy and load balancer
- **Application Load Balancer (ALB)** with HTTPS termination
- **Auto Scaling Group** for high availability
- **Health checks** at `/health` endpoint

### nginx Installation on ARM64

Install nginx on ARM64 Ubuntu systems:

```bash
# Update package repositories
apt-get update

# Install nginx (automatically detects ARM64 architecture)
apt-get install -y nginx

# Verify installation and architecture
nginx -v
uname -m  # Should show aarch64
```

### Recommended nginx Configuration for ARM64

#### Basic Reverse Proxy Configuration

Create `/etc/nginx/sites-available/arm-mcp`:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    # Redirect HTTP to HTTPS (if using ALB with SSL termination)
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    # SSL configuration (if terminating SSL at nginx level)
    # ssl_certificate /path/to/your/certificate.pem;
    # ssl_certificate_key /path/to/your/private.key;
    
    # ARM64-optimized worker configuration
    # Set in /etc/nginx/nginx.conf:
    # worker_processes auto;  # Automatically detects ARM64 cores
    # worker_connections 1024;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeout configurations optimized for ARM64
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Enable keepalive for better performance on ARM64
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
    
    # Health check endpoint
    location /health {
        proxy_pass http://127.0.0.1:5000/health;
        access_log off;
    }
    
    # ARM64-specific performance optimizations
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        
        # Enable compression (ARM64 has efficient compression)
        gzip on;
        gzip_vary on;
        gzip_comp_level 6;
        gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
    }
}
```

### ARM64-Specific Performance Tuning

#### `/etc/nginx/nginx.conf` Optimizations

```nginx
# ARM64-optimized global configuration
user www-data;
worker_processes auto;  # Automatically detects ARM64 CPU cores
pid /run/nginx.pid;

events {
    worker_connections 1024;
    use epoll;  # Efficient on ARM64 Linux
    multi_accept on;
}

http {
    # Basic settings optimized for ARM64
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    
    # ARM64 has efficient GZIP compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/xml+rss
        application/atom+xml
        image/svg+xml;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    
    # Include virtual host configs
    include /etc/nginx/sites-enabled/*;
}
```

### Deployment Commands for ARM64

```bash
# Enable the site
ln -s /etc/nginx/sites-available/arm-mcp /etc/nginx/sites-enabled/

# Test configuration
nginx -t

# Start/restart nginx
systemctl start nginx
systemctl enable nginx
systemctl restart nginx

# Check status
systemctl status nginx

# View ARM64-specific process information
ps aux | grep nginx
cat /proc/cpuinfo | grep -E "(processor|model name|cpu cores)"
```

### Load Balancer Integration

When using AWS Application Load Balancer (ALB) with ARM64 instances:

```nginx
# ALB health check configuration
server {
    listen 80;
    
    location /health {
        proxy_pass http://127.0.0.1:5000/health;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # ALB health check requirements
        proxy_connect_timeout 5s;
        proxy_send_timeout 5s;
        proxy_read_timeout 5s;
    }
    
    # Main application proxy
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Monitoring and Logging

Enable comprehensive logging for ARM64 deployments:

```nginx
# In /etc/nginx/nginx.conf
http {
    # Custom log format including ARM64 system info
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    '$request_time $upstream_response_time';
    
    access_log /var/log/nginx/access.log main;
    error_log /var/log/nginx/error.log warn;
}
```

### Key ARM64 Advantages

- **Performance**: ARM64 Graviton processors provide excellent price-performance for web workloads
- **Energy Efficiency**: Lower power consumption compared to x86_64 alternatives
- **Native Support**: Modern nginx versions have full ARM64 optimization
- **Ecosystem**: Comprehensive ARM64 package availability in Ubuntu 24.04

### Troubleshooting ARM64 nginx Issues

```bash
# Check architecture compatibility
file /usr/sbin/nginx
# Should show: ELF 64-bit LSB executable, ARM aarch64

# Verify nginx modules are ARM64 compatible
nginx -V

# Check system resources
htop  # Monitor CPU usage on ARM64 cores
free -h  # Memory usage
iostat  # I/O performance

# nginx-specific debugging
nginx -t -c /etc/nginx/nginx.conf
journalctl -u nginx.service --no-pager
```

This configuration is based on the production deployment architecture used by the Arm MCP server, running on AWS Graviton3 instances with proven performance characteristics.