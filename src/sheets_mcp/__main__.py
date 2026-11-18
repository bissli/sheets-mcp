"""Command line: `sheets-mcp` serves over stdio, `sheets-mcp login` stores
an OAuth token.
"""
import argparse
import functools
from pathlib import Path

from sheets_mcp import auth
from sheets_mcp.google import build_clients
from sheets_mcp.server import build_server


def main() -> None:
    """Parse the command line and serve, or run the OAuth login.
    """
    parser = argparse.ArgumentParser(
        prog='sheets-mcp',
        description='MCP server for Google Sheets, over stdio.')
    parser.add_argument(
        '--credentials', type=Path,
        help='service account key or Desktop app OAuth client JSON; '
        'omit to use Application Default Credentials')
    parser.add_argument(
        '--read-only', action='store_true',
        help='serve only the tools that change nothing')
    commands = parser.add_subparsers(dest='command')
    login = commands.add_parser(
        'login', help='run the browser consent for an OAuth client and store the token')
    login.add_argument('client', type=Path, help='Desktop app OAuth client JSON')
    args = parser.parse_args()
    if args.command == 'login':
        print(f'token stored at {auth.login(args.client)}')
        return
    credentials = auth.load_credentials(args.credentials)
    make_clients = functools.partial(build_clients, credentials)
    build_server(make_clients, read_only=args.read_only).run('stdio')


if __name__ == '__main__':
    main()
