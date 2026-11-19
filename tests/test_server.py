import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httplib2
import pytest
import sheets_mcp
from googleapiclient.errors import HttpError
from mcp.server.mcpserver.exceptions import ToolError
from sheets_mcp.server import TOOLS, bind, build_server

CORE_MODULES = ('a1', 'auth', 'files', 'formulas', 'google', 'layout', 'tabs', 'values')


def listed_tools(read_only):
    return asyncio.run(build_server(lambda: None, read_only=read_only).list_tools())


def test_every_tool_registers_without_clients():
    """Verify every tool in TOOLS registers, and neither its input schema
    nor its description mentions the clients parameter.

    Mutation: bind leaving clients in the signature or the docstring.
    Oracle: the parameter is server-side only, so the schema and the
    description the model reads must not carry it.
    """
    tools = listed_tools(read_only=False)
    assert len(tools) == len(TOOLS)
    for tool in tools:
        assert 'clients' not in tool.input_schema['properties']
        assert 'clients' not in tool.description


def test_read_only_serves_only_read_tools():
    """Verify --read-only leaves exactly the tools annotated read-only.

    Mutation: inverting the read-only filter, or filtering on
    destructive_hint instead.
    Oracle: the READ entries of TOOLS, counted apart from the server.
    """
    expected = {
        func.__name__ for func, annotations in TOOLS if annotations.read_only_hint}
    assert {tool.name for tool in listed_tools(read_only=True)} == expected
    assert expected == {
        'list_files', 'list_permissions', 'describe_spreadsheet', 'read_range'}


def test_bind_turns_google_refusal_into_tool_error():
    """Verify a Google HttpError reaches the caller as a ToolError that
    keeps Google's status and reason.

    Mutation: letting HttpError through, which the SDK hides from the
    caller as a bare failure.
    Oracle: the status and message put in the stub's error.
    """
    def refused(clients, spreadsheet_id):
        """Stub tool.

        Parameters
        ----------
        clients : Clients
            Google clients; the server passes them.
        spreadsheet_id : str
        """
        content = json.dumps({'error': {'code': 404, 'message': 'File not found'}})
        raise HttpError(httplib2.Response({'status': 404}), content.encode())

    with pytest.raises(ToolError, match=r'\(404\): File not found'):
        bind(refused, lambda: None)(spreadsheet_id='1AbC')


def test_bind_turns_refusal_into_tool_error():
    """Verify a core ValueError reaches the caller as a ToolError with the
    same text.

    Mutation: dropping the ValueError branch, which the SDK reports as a
    crash with the text kept on the server.
    Oracle: the message put in the stub's error.
    """
    def refused(clients, spreadsheet_id):
        """Stub tool.

        Parameters
        ----------
        clients : Clients
            Google clients; the server passes them.
        spreadsheet_id : str
        """
        raise ValueError("no tab named 'Q4'")

    with pytest.raises(ToolError, match=r"^no tab named 'Q4'$"):
        bind(refused, lambda: None)(spreadsheet_id='1AbC')


def test_core_modules_import_no_mcp():
    """Verify importing every core module loads no mcp module, so a host on
    another mcp version can use the core.

    Mutation: a core module importing ToolError or anything else from mcp.
    Oracle: sys.modules in a fresh interpreter after the imports.
    """
    imports = '; '.join(f'import sheets_mcp.{name}' for name in CORE_MODULES)
    check = (
        f'import sys; {imports}; '
        "print(sorted(m for m in sys.modules if m.split('.')[0] == 'mcp'))")
    # Run from the source root this test imports, since another install of
    # sheets_mcp may sit on the interpreter's path.
    loaded = subprocess.run(
        [sys.executable, '-c', check],
        cwd=Path(sheets_mcp.__file__).parents[1],
        capture_output=True,
        text=True,
        check=True).stdout
    assert loaded.strip() == '[]'


def test_bind_passes_fresh_clients_first():
    """Verify the bound tool hands make_clients' result to the function as
    its first argument, built anew on each call.

    Mutation: building clients once at bind time, which shares one
    thread-unsafe client across concurrent calls.
    Oracle: a counter in the stub factory.
    """
    built = []

    def make_clients():
        built.append(len(built))
        return built[-1]

    def echo(clients, value):
        """Stub tool.

        Parameters
        ----------
        clients : Clients
            Google clients; the server passes them.
        value : int
        """
        return clients, value

    tool = bind(echo, make_clients)
    assert [tool(value=5), tool(value=6)] == [(0, 5), (1, 6)]
