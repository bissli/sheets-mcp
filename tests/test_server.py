import asyncio
import json

import httplib2
import pytest
from googleapiclient.errors import HttpError
from sheets_mcp.errors import SheetsError
from sheets_mcp.server import TOOLS, bind, build_server


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


def test_bind_turns_google_refusal_into_sheets_error():
    """Verify a Google HttpError reaches the caller as a SheetsError that
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

    with pytest.raises(SheetsError, match=r'\(404\): File not found'):
        bind(refused, lambda: None)(spreadsheet_id='1AbC')


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
