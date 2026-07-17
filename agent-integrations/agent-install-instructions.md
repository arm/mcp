# Arm MCP Server Installation

Search online for the latest MCP configuration instructions for your agent, then configure the Arm MCP server using the Docker image.

Pull the Docker image:

```bash
docker pull armlimited/arm-mcp:latest
```

Use the following command and args in your MCP configuration (adjusting the format as required by your agent).

The SSH-related volume mounts are optional and are only needed when enabling **Arm Performix**.

For JSON-based configurations:

```json
{
  "command": "docker",
  "args": [
    "run",
    "--rm",
    "-i",
    "--pull=always",
    "-v",
    "/path/to/your/workspace:/workspace",
    "-v",
    "/path/to/your/ssh/private_key:/run/keys/ssh-key.pem:ro",
    "-v",
    "/path/to/your/ssh/known_hosts:/run/keys/known_hosts:ro",
    "armlimited/arm-mcp:latest"
  ]
}
```

For TOML-based configurations:

```toml
[mcp_servers.arm-mcp]
command = "docker"
args = [
  "run",
  "--rm",
  "-i",
  "--pull=always",
  "-v",
  "/path/to/your/workspace:/workspace",
  "-v",
  "/path/to/your/ssh/private_key:/run/keys/ssh-key.pem:ro",
  "-v",
  "/path/to/your/ssh/known_hosts:/run/keys/known_hosts:ro",
  "armlimited/arm-mcp:latest",
]
```

Replace `/path/to/your/workspace` with the absolute path to the project you want the MCP server to access.
If you are enabling Arm Performix, also replace the SSH private key and `known_hosts` paths with your local files.

## Install the Arm Enablement Skill for Codex

The skill does not install or configure the Arm MCP Docker invocation. Complete the manual Arm MCP configuration above first, then install the skill from a checkout of this repository:

```bash
mkdir -p "$HOME/.agents/skills"
cp -R agent-integrations/codex/arm-enablement "$HOME/.agents/skills/"
```

Start or restart Codex in the project you want to assess. Use `/skills` to confirm that `arm-enablement` is available, then invoke it in chat:

```text
$arm-enablement Assess this repository for Arm readiness and generate the Markdown and PDF report.
```

The project opened in Codex must be the same project mounted at `/workspace` in the Arm MCP server configuration.
