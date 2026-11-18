"""The error a tool raises to tell the caller what to change.
"""
from mcp.server.mcpserver.exceptions import ToolError


class SheetsError(ToolError):
    """A refusal or a bad argument. The MCP SDK sends its text to the
    caller; any other exception reaches the caller as a bare failure.
    """
