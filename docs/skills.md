# CLI skills and MCP client compatibility

Arm MCP exposes only `knowledge_base_search` as a tool. Image inspection,
migration scans, and assembly analysis run through the agent's shell. The server
ships their instructions as portable Agent Skills:

| Skill/prompt name | Resource URI |
| --- | --- |
| `arm-container-inspect` | `skill://arm-container-inspect/SKILL.md` |
| `arm-migration-scan` | `skill://arm-migration-scan/SKILL.md` |
| `arm-assembly-analyze` | `skill://arm-assembly-analyze/SKILL.md` |

## How the server publishes skills

The canonical files live in `mcp-local/skills/` and are copied to `/app/skills`
in the image. Each has Agent Skills YAML frontmatter (`name`, `description`).
FastMCP's built-in
[SkillsDirectoryProvider](https://gofastmcp.com/servers/providers/skills)
publishes them through `resources/list` and `resources/read`, including a
`skill://<name>/_manifest` resource with file sizes and SHA-256 hashes.
Same-named, zero-argument MCP prompts return the same document through
`prompts/list` and `prompts/get`. Server instructions point agents to these
entry points without putting every workflow into tool descriptions.

This uses standard resources and prompts, supported by existing clients.
The server does not advertise the newer
[`io.modelcontextprotocol/skills` extension](https://skills.extensions.modelcontextprotocol.io/):
the bundled FastMCP provider uses resource discovery, not that extension's
`skills/list` and `skills/get` methods. Reading a resource supplies context;
automatic installation or activation in a client's native skill system is a
separate client capability. No extra skill-loading MCP tool is registered.

## Loading instructions in clients

| Client | Loading path |
| --- | --- |
| Claude Code | Select a server prompt from slash-command completion, or attach its MCP resource. See [Claude MCP documentation](https://code.claude.com/docs/en/mcp). |
| VS Code / GitHub Copilot | Use **MCP: Browse Resources** or **Add Context → MCP Resources**, or select the server prompt from slash-command completion. See [VS Code MCP capabilities](https://code.visualstudio.com/docs/agent-customization/mcp-servers#other-mcp-capabilities). |
| Gemini CLI | Use the discovered skill prompt as a slash command, for example `/arm-migration-scan`; `/mcp` shows the server's resources and prompts. See [Gemini MCP documentation](https://geminicli.com/docs/tools/mcp-server/). |
| Codex and other clients with MCP resource access | List the `arm-mcp` resources and read the relevant `skill://` URI. For native skill discovery, install the files locally as below. |
| Clients exposing only MCP tools | Knowledge search works directly. Install or attach the skill files using the client's local instructions mechanism; the server cannot force resource/prompt support. |

These are protocol-compatible loading paths, not a claim that every client
automatically activates remote skills. A client must also provide a shell to
execute the workflow; a chat-only host can display commands for a person to run.
CLI execution uses the client's normal permissions, credentials, timeouts, and
filesystem access. The server does not execute commands when a skill is read.

## Installing the same skills locally

Copy the three skill directories from `mcp-local/skills/` into the skill directory
supported by your client. For example, from a repository checkout:

```sh
# Codex user skills; choose your client's directory if using a different host.
mkdir -p "$HOME/.agents/skills"
cp -R mcp-local/skills/arm-container-inspect \
  mcp-local/skills/arm-migration-scan \
  mcp-local/skills/arm-assembly-analyze "$HOME/.agents/skills/"
```

For an image-only installation, extract the same files to a fresh staging
directory, inspect them, and then copy the skill folders into the client's skill
directory. Set the image to the version/digest used by the project:

```sh
skill_stage="$(mktemp -d)"
docker run --rm --entrypoint tar "${ARM_MCP_IMAGE:-armlimited/arm-mcp:latest}" \
  -C /app/skills -cf - . | tar -xf - -C "$skill_stage"
```

Restart or reload the client's skills after installation. The CLI skills are
self-contained; they do not depend on the repository being available later.

## Migrating existing configurations

Remove `check_image`, `skopeo`, `migrate_ease_scan`, and `mca` from explicit MCP
tool allowlists and reload the server. Keep `knowledge_base_search`. Existing
stdio Docker configurations still work. Their `/workspace` mount is optional
and used for logs; the CLI invocations have independent source and report mounts.

Skopeo, LLVM MCA, and migrate-ease remain in the image as CLI dependencies. The
skills show both native commands and `docker run --entrypoint` alternatives.
Choose the project's version/digest through `ARM_MCP_IMAGE`; a newly built image
can be selected the same way. Scans retain output files for review and validation.

## Validation

`tests/test_server_skills.py` uses the real FastMCP client/server with a stubbed
knowledge backend to test legacy and modern negotiation, the exact one-tool
catalog, removed-tool rejection, resource/prompt content, manifest hashes, and
invalid resource paths. The container integration suite checks the legacy stdio
wire format, real knowledge retrieval, bundled skills, and CLI execution.
Client-specific UI behavior should be checked in the client versions used for
a release; protocol tests do not automate those UIs.
