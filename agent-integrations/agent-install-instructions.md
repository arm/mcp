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

The `/workspace` mount is optional and stores MCP invocation/error logs. CLI scans
run through the client shell with their own workspace mount.

## Load the CLI skills

The only MCP tool is `knowledge_base_search`. Load the server resources or prompts
`arm-container-inspect`, `arm-migration-scan`, and `arm-assembly-analyze` before
using the corresponding CLI workflow. See [client compatibility and local skill
installation](../docs/skills.md). Shell access is required to execute commands.

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

When using Docker for CLI scans, mount the project opened in the agent at
`/workspace` in that CLI invocation. The MCP server mount is only for logs.
