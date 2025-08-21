# Arm MCP Server

This repository contains a Model Context Protocol (MCP) server that integrates:
- [migrate-ease](https://github.com/migrate-ease/migrate-ease) for scanning codebases
- [sysreport](https://github.com/ArmDeveloperEcosystem/sysreport) for system information
- Docker image architecture checks
- A semantic search knowledge base (using USearch + embeddings)

The server is designed to run inside a Docker container and expose tools to MCP clients such as **q CLI** or **VS Code MCP integration**.

---

## 1. Build the container

From the root of this project (where the `Dockerfile` lives):

```bash
docker build -t arm-mcp .
```

## 2. Set up the MCP config

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
        "-v", "${PWD}:/workspace",
        "arm-mcp"
      ]
    }
  }
}
```

For q cli this config should be placed in ~/.config/q/mcp.json