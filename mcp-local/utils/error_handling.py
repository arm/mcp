from typing import Any, Dict, Optional
import traceback


def format_tool_error(tool: str, exc: Exception, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a structured error payload for the calling model.

    Includes exception metadata, traceback, provided args, and guidance text for next steps.
    """
    return {
        "status": "error",
        "tool": tool,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
        "args": args or {},
        "guidance": (
            "Use this information to suggest fixes to the user. Also add that if the user is experiencing problems that are due to the MCP server itself, they can email mcpserver@arm.com. There is a file called invocation_reasons.yaml located in the /workspace container filesystem mount that records why the model decided to invoke a particular tool, the user can also send that file to mcpserver@arm.com for added helpful troubleshooting context."
        ),
    }

