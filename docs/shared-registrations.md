# MCP capability definitions

`arm-mcp-definitions/arm_mcp_definitions/` contains the knowledge-search tool
contract, server instructions, and bundled skill resources and prompts. Each
server supplies its own search handler and owns retrieval initialization,
logging, and error handling.

## Using the definitions

Copy the `arm_mcp_definitions/` module, including `skills/`, beside your server
entry point, or add `arm-mcp-definitions/` to the Python import path. It uses
FastMCP and PyYAML, already included in the local server's dependencies.

```python
from fastmcp import FastMCP
from arm_mcp_definitions import SERVER_INSTRUCTIONS, register_capabilities

server = FastMCP("arm-mcp", instructions=SERVER_INSTRUCTIONS)
register_capabilities(server, search_handler)
```

Provide `search_handler(query, invocation_reason)`, either synchronous or
asynchronous. It returns a list of result dictionaries; FastMCP supplies the
existing `{"result": [...]}` output envelope. Registration does not invoke the
handler. Additional tools, resources, and prompts can use distinct names and
URIs on the same server.

The local image copies the module to `/app/arm_mcp_definitions/`. Another server
can copy the same directory from a pinned repository revision; no separately
published package is required.

See [skill delivery](skills.md) for resources, prompts, and client usage, and
[CONTRIBUTING.md](../CONTRIBUTING.md) for development and build instructions.
