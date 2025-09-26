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

This section provides comprehensive guidance for configuring Nginx on ARM-based infrastructure, specifically optimized for AWS Graviton processors and ARM64 architecture.

### Nginx on ARM64/Graviton Instances

#### Installation on Ubuntu 24.04 ARM64

The MCP server infrastructure uses Ubuntu 24.04 ARM64 AMI with native nginx installation:

```bash
# Update package repositories
apt-get update

# Install nginx with ARM64 native package
apt-get install -y nginx

# Verify ARM64 architecture
uname -m  # Should show aarch64
```

#### AWS Graviton-Optimized Configuration

When deploying on AWS Graviton instances (like m8g.large used in the MCP stack), consider these ARM-specific optimizations:

**Instance Configuration:**
- **Instance Type**: m8g.large (ARM64 Graviton4 processor)
- **Operating System**: Ubuntu 24.04 ARM64 Server
- **Architecture**: aarch64 (ARM64)

**Nginx Worker Process Configuration:**
```nginx
# /etc/nginx/nginx.conf
worker_processes auto;  # Automatically detect ARM64 cores
worker_cpu_affinity auto;  # Optimize for ARM64 core topology

# ARM64-optimized worker connections
events {
    worker_connections 1024;
    use epoll;  # Efficient for ARM64 architecture
    multi_accept on;
}
```

#### Container-Based Nginx on ARM64

For containerized deployments, ensure ARM64 compatibility:

**Multi-Architecture Docker Images:**
```bash
# Verify nginx image supports ARM64
docker manifest inspect nginx:latest

# Run nginx container on ARM64
docker run -d --platform linux/arm64 \
  -p 80:80 \
  -p 443:443 \
  nginx:latest
```

**Kubernetes Deployment with ARM64 Node Selector:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-arm64
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      nodeSelector:
        kubernetes.io/arch: arm64  # Schedule on ARM64 nodes
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
        - containerPort: 443
```

#### Load Balancer Integration

The MCP infrastructure uses Application Load Balancer (ALB) with the following ARM64-specific configuration:

**Security Group Configuration:**
- **Inbound Rule**: TCP port 5000 (application traffic)
- **Protocol**: HTTP/HTTPS
- **Health Check Path**: `/health`

**ALB Target Configuration:**
```python
# CDK Configuration for ARM64 instances
listener.add_targets("ASGTarget",
    port=5000,
    targets=[asg],  # ARM64 Auto Scaling Group
    protocol=elbv2.ApplicationProtocol.HTTP,
    health_check=elbv2.HealthCheck(
        path="/health",
        healthy_http_codes="200-299"
    ))
```

#### Performance Optimization for ARM64

**Memory and CPU Optimization:**
```nginx
# ARM64-specific nginx configuration
http {
    # Optimize for ARM64 cache lines
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    
    # ARM64 memory optimization
    keepalive_timeout 65;
    keepalive_requests 100;
    
    # Gzip compression (ARM64 native support)
    gzip on;
    gzip_vary on;
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
}
```

#### SSL/TLS Configuration for ARM64

**Certificate Management:**
```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    # SSL certificate paths
    ssl_certificate /path/to/certificate.crt;
    ssl_certificate_key /path/to/private.key;
    
    # ARM64-optimized SSL protocols
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    
    # ARM64 hardware acceleration for cryptographic operations
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
}
```

#### Monitoring and Logging

**ARM64 Performance Monitoring:**
```nginx
# Enable status module for ARM64 monitoring
location /nginx_status {
    stub_status on;
    access_log off;
    allow 127.0.0.1;
    deny all;
}

# Custom log format for ARM64 performance analysis
log_format arm64_performance '$remote_addr - $remote_user [$time_local] '
                             '"$request" $status $bytes_sent '
                             '"$http_referer" "$http_user_agent" '
                             '$request_time $upstream_response_time';
```

#### Migration Considerations

When migrating existing nginx configurations to ARM64:

1. **Image Compatibility**: Ensure all container images support ARM64 architecture
2. **Performance Testing**: Benchmark performance on ARM64 vs x86_64
3. **Module Compatibility**: Verify third-party nginx modules support ARM64
4. **Monitoring**: Update monitoring tools to recognize ARM64 architecture

#### Troubleshooting ARM64 Nginx

**Common Issues and Solutions:**

1. **Architecture Mismatch**:
   ```bash
   # Check current architecture
   lscpu | grep Architecture
   
   # Verify nginx binary architecture
   file /usr/sbin/nginx
   ```

2. **Container Platform Issues**:
   ```bash
   # Force ARM64 platform for Docker
   docker run --platform linux/arm64 nginx:latest
   ```

3. **Performance Monitoring**:
   ```bash
   # Monitor ARM64-specific performance metrics
   cat /proc/cpuinfo | grep -E "(processor|model name|Features)"
   ```

#### References

- [AWS Graviton Getting Started Guide - Containers](https://github.com/aws/aws-graviton-getting-started/blob/main/containers.md)
- [Kubernetes Multi-Architecture Support](https://kubernetes.io/docs/concepts/cluster-administration/platforms/)
- [Docker Multi-Platform Builds](https://docs.docker.com/build/building/multi-platform/)
- [Nginx ARM64 Performance Optimization](https://nginx.org/en/docs/)