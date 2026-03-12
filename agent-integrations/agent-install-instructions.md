# Arm MCP Server Installation

Search online for the latest MCP configuration instructions for your agent, then configure the Arm MCP server using the Docker image.

Pull the Docker image:

```
docker pull armlimited/arm-mcp:latest
```

Use the following command and args in your MCP configuration (adjusting the format as required by your agent):

For JSON-based configurations:

```json
{
  "command": "docker",
  "args": [
    "run",
    "--rm",
    "-i",
    "--pull=always",
    "-v", "/path/to/your/workspace:/workspace",
    "--name", "arm-mcp",
    "armlimited/arm-mcp:latest"
  ]
}
```

For TOML-based configurations:

```toml
[mcp_servers."arm-mcp"]
type = "stdio"
command = "docker"
args = [
    "run",
    "--rm",
    "-i",
    "--pull=always",
    "-v",
    "/path/to/your/workspace:/workspace",
    "--name",
    "arm-mcp",
    "armlimited/arm-mcp:latest",
]
```

Replace `/path/to/your/workspace` with the absolute path to the project you want to migrate.
