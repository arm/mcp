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

## Arm Nginx Tuning

This MCP server can help with Arm server optimization, including nginx tuning for Arm processors like AWS Graviton. Here are key nginx tuning recommendations for Arm servers:

### Nginx Version Compatibility
- **NGINX** works on Arm Linux servers starting from version 1.7.7 (October 2014)
- **Recommended**: Version 1.20.1 and above for best performance on Arm (released December 2022)
- **NGINX Plus** supported on Arm from December 2014

### Key Configuration Optimizations

#### Worker Configuration
```nginx
user www-data;
worker_processes auto;
worker_rlimit_nofile 1000000;
worker_connections 512;
```

#### Performance Directives
```nginx
# Enable sendfile for better performance
sendfile on;
tcp_nopush on;

# Connection tuning
keepalive_timeout 75;
keepalive_requests 1000000000;

# Disable access logging for better performance
access_log off;
error_log /var/log/nginx/error.log;
```

#### Upstream Configuration
```nginx
upstream backend {
    server backend1.example.com;
    server backend2.example.com;
    keepalive 1024;  # Enable connection caching
}
```

#### Proxy Settings
```nginx
proxy_http_version 1.1;
proxy_set_header Connection "";  # Clear connection header for keepalive
```

### System-Level Tuning

Optimize Linux network stack parameters:
```bash
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.core.rmem_max=8388607
sudo sysctl -w net.core.wmem_max=8388607
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=65535
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"
sudo sysctl -w net.ipv4.tcp_rmem="4096 8338607 8338607"
sudo sysctl -w net.ipv4.tcp_wmem="4096 8338607 8338607"
```

### Performance Impact
Proper tuning can provide significant performance improvements on Arm servers, potentially allowing you to:
- Downsize instance types (e.g., m7g.2xlarge → m7g.xlarge)
- Achieve better cost efficiency
- Handle higher connection volumes

### Additional Resources
- [ARM Nginx Learning Path](https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx/)
- [ARM Nginx Tuning Guide](https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx_tune/)
- [ARM Ecosystem Dashboard](https://www.arm.com/developer-hub/ecosystem-dashboard/?package=nginx)

Use the `knowledge_base_search` tool in this MCP server to find more detailed nginx tuning information and other Arm-specific optimizations.