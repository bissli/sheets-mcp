# sheets-mcp

A general-purpose [MCP](https://modelcontextprotocol.io) server for Google
Sheets. It lets an MCP client such as Claude find, create, copy, move,
share, import, export and delete spreadsheets; add, edit, copy and delete
tabs; read, write, append and clear values; insert, move, resize and delete
rows and columns; and format cells.

## Tools

| Object         | Tools                                                                                                 |
| -------------- | ----------------------------------------------------------------------------------------------------- |
| Files          | `list_files`, `create_spreadsheet`, `copy_spreadsheet`, `update_file`, `delete_file`, `create_folder` |
| Sharing        | `share_file`, `list_permissions`                                                                      |
| Import, export | `import_file`, `export_spreadsheet`                                                                   |
| Tabs           | `describe_spreadsheet`, `add_tab`, `edit_tab`, `copy_tab`, `delete_tab`                               |
| Values         | `read_range`, `write_ranges`, `append_rows`, `clear_ranges`                                           |
| Rows, columns  | `edit_rows_columns`, `delete_rows_columns`                                                            |
| Formatting     | `format_range`                                                                                        |

Each tool carries MCP annotations. The four read tools are marked
read-only, and every tool that overwrites or removes data is marked
destructive, so a client can ask before running one.

## Installation

```
pipx install 'sheets-mcp[server] @ git+https://github.com/bissli/sheets-mcp'
```

Without the `server` extra, the package installs as a library with no
`mcp` dependency: every module but `sheets_mcp.server` and
`sheets_mcp.__main__` imports.

## Credentials

The server reads one of three kinds of Google credentials:

- **Application Default Credentials.** With no `--credentials` flag, the
  server uses the account set by
  `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/cloud-platform`.
- **A personal Google account.** A Desktop app OAuth client from the Google
  Cloud console, with the Sheets and Drive APIs enabled.
  `sheets-mcp login client.json` runs the browser consent once and stores
  the token in `~/.config/sheets-mcp/token.json`. The server then runs
  with `--credentials client.json`.
- **A service account.** `--credentials key.json` with the account's key
  file. A service account sees only the files shared with its email
  address, and has no My Drive storage, so it creates files in a shared
  drive folder.

The server asks for the `spreadsheets` and `drive` scopes. Moving, sharing
and deleting any file the account can reach needs the full Drive scope.

## Client setup

Claude Code:

```
claude mcp add sheets -- sheets-mcp --credentials ~/client.json
```

Claude Desktop, in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sheets": {
      "command": "sheets-mcp",
      "args": ["--credentials", "/home/ana/client.json"]
    }
  }
}
```

`--read-only` serves only the four read tools.

## Safety

- `delete_file` moves a file to the trash. Only `permanent=true` deletes
  it beyond recovery.
- A written value that Sheets would parse as a formula may not call
  IMPORTXML, IMPORTHTML, IMPORTDATA, IMPORTFEED, IMPORTRANGE or IMAGE.
  Those functions fetch a URL, so a prompt injection could use them to
  send cell contents to a third party. `copy_tab` applies the same check
  to a tab it copies into another spreadsheet.
- The check closes only that channel. Any write or copy into a file or
  folder someone else can read shows them the data, so a client should
  confirm write tools whose target it did not choose.
- `read_range` answers in pages of at most 60 KB, with `next_offset` for
  the next page.
- `export_spreadsheet` keeps an existing local file unless the call sets
  `overwrite=true`.
- The server runs over stdio only, so no network port exposes the
  account.

## Development

```
poetry install --with test --extras server
poetry run pytest
```

The tests run against an in-memory fake of the Drive and Sheets APIs in
`tests/fake_google.py` and make no network calls.

## License

MIT
