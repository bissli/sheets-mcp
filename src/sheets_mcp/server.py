"""The MCP server: one tool per function in TOOLS, bound to Google clients.
"""
import functools
import inspect
from collections.abc import Callable
from typing import Any

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from sheets_mcp import __version__, files, layout, tabs, values
from sheets_mcp.errors import SheetsError
from sheets_mcp.google import Clients

READ = ToolAnnotations(read_only_hint=True)
ADD = ToolAnnotations(read_only_hint=False, destructive_hint=False)
CHANGE = ToolAnnotations(read_only_hint=False, destructive_hint=True)

TOOLS = (
    (files.list_files, READ),
    (files.create_spreadsheet, ADD),
    (files.copy_spreadsheet, ADD),
    (files.update_file, CHANGE),
    (files.delete_file, CHANGE),
    (files.create_folder, ADD),
    (files.list_permissions, READ),
    (files.share_file, CHANGE),
    (files.import_file, ADD),
    (files.export_spreadsheet, CHANGE),
    (tabs.describe_spreadsheet, READ),
    (tabs.add_tab, ADD),
    (tabs.edit_tab, CHANGE),
    (tabs.copy_tab, ADD),
    (tabs.delete_tab, CHANGE),
    (values.read_range, READ),
    (values.write_ranges, CHANGE),
    (values.append_rows, ADD),
    (values.clear_ranges, CHANGE),
    (layout.edit_rows_columns, CHANGE),
    (layout.delete_rows_columns, CHANGE),
    (layout.format_range, CHANGE),
    )

CLIENTS_ENTRY = 'clients : Clients\n    Google clients; the server passes them.\n'
INSTRUCTIONS = (
    'Google Sheets and the Drive files that hold them. Find a spreadsheet '
    'with list_files and see its tabs with describe_spreadsheet before '
    'reading or writing. Ranges are A1 text with the tab name.')


def bind(func: Callable[..., Any], make_clients: Callable[[], Clients]) -> Callable:
    """Func as a tool: Google clients fill its first parameter, and a
    Google API refusal, a failed sign-in or a local file error reaches the
    caller as a SheetsError with its reason.

    Parameters
    ----------
    func : Callable
        A tool function whose first parameter is `clients`.
    make_clients : Callable
        Returns fresh Clients for each call.

    Returns
    -------
    Callable
        Keeps func's name. `clients` leaves its signature, so the tool
        schema leaves it out, and leaves its docstring, which is the tool
        description.

    Raises
    ------
    ValueError
        func's docstring lacks the CLIENTS_ENTRY text.
    """
    description = inspect.cleandoc(func.__doc__)
    if CLIENTS_ENTRY not in description:
        raise ValueError(f'{func.__name__} docstring lacks the clients entry')

    @functools.wraps(func)
    def tool(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(make_clients(), *args, **kwargs)
        except HttpError as exc:
            raise SheetsError(
                f'Google refused the call ({exc.status_code}): {exc.reason}') from exc
        except RefreshError as exc:
            raise SheetsError(
                f'Google sign-in failed: {exc}. For an OAuth client, run '
                'sheets-mcp login again') from exc
        except OSError as exc:
            raise SheetsError(f'local file error: {exc}') from exc

    tool.__doc__ = description.replace(CLIENTS_ENTRY, '')
    signature = inspect.signature(func)
    tool.__signature__ = signature.replace(
        parameters=list(signature.parameters.values())[1:])
    return tool


def build_server(make_clients: Callable[[], Clients], read_only: bool) -> MCPServer:
    """MCP server with every tool in TOOLS, or only the read-only ones.

    Parameters
    ----------
    make_clients : Callable
        Returns fresh Clients for each tool call.
    read_only : bool
        True registers only the tools annotated read-only.

    Returns
    -------
    MCPServer
    """
    server = MCPServer('sheets-mcp', version=__version__, instructions=INSTRUCTIONS)
    for func, annotations in TOOLS:
        if read_only and not annotations.read_only_hint:
            continue
        server.tool(annotations=annotations)(bind(func, make_clients))
    return server
