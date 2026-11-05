# Arm MCP Server Installation

Search online for the latest MCP configuration instructions for your agent, then configure the Arm MCP server using the Docker image.

Pull the Docker image:

```bash
docker pull armlimited/arm-mcp:latest
```

Use the following command and args in your MCP configuration (adjusting the format as required by your agent).

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
  "armlimited/arm-mcp:latest",
]
```

Replace `/path/to/your/workspace` with the absolute path to the project you want the MCP server to access.

## Install the Arm Skills for Codex

The skills do not install or configure the Arm MCP Docker invocation. Complete
the manual Arm MCP configuration above first, then install either or both skills
from a checkout of this repository:

```bash
mkdir -p "$HOME/.agents/skills"
cp -R agent-integrations/codex/arm-knowledgebase "$HOME/.agents/skills/"
cp -R agent-integrations/codex/arm-enablement "$HOME/.agents/skills/"
```

`arm-knowledgebase` answers Arm-specific technical questions using sourced
results from the Arm MCP Server's `knowledge_base_search` tool:

```text
$arm-knowledgebase How can I optimize NGINX performance on an Arm server?
```

`arm-enablement` assesses a repository for Arm readiness and generates a
Markdown and PDF report:

```text
$arm-enablement Assess this repository for Arm readiness and generate the Markdown and PDF report.
```

Start or restart Codex and use `/skills` to confirm that the installed skills are
available. When using `arm-enablement`, the project opened in Codex must be the
same project mounted at `/workspace` in the Arm MCP server configuration.
