# sheets-mcp design

A general-purpose MCP server for Google Sheets. It covers the whole life of
a spreadsheet: find, create, copy, rename, move, share, import, export and
delete files; add, edit, copy and delete tabs; read, write, append and clear
values; insert, move, resize and delete rows and columns; format cells. It
holds no logic for any one data source or workflow.

## Scope

v1 tools, grouped by the object they act on:

| Object         | Tools                                                                                                 |
| -------------- | ----------------------------------------------------------------------------------------------------- |
| Files          | `list_files`, `create_spreadsheet`, `copy_spreadsheet`, `update_file`, `delete_file`, `create_folder` |
| Sharing        | `share_file`, `list_permissions`                                                                      |
| Import, export | `import_file`, `export_spreadsheet`                                                                   |
| Tabs           | `describe_spreadsheet`, `add_tab`, `edit_tab`, `copy_tab`, `delete_tab`                               |
| Values         | `read_range`, `write_ranges`, `append_rows`, `clear_ranges`                                           |
| Rows, columns  | `edit_rows_columns`, `delete_rows_columns`                                                            |
| Formatting     | `format_range`                                                                                        |

v1.1 adds `find_replace`, `sort_range`, data validation, conditional
formats, named ranges and protected ranges. Charts and comments follow.

## Tool shape

- One tool per object and kind of change. An operation that removes data
  gets its own tool, because MCP tool annotations (`readOnlyHint`,
  `destructiveHint`) attach to a whole tool, and a client gates on them.
- A tool takes a spreadsheet id and A1 ranges with tab names. The server
  looks up the numeric sheet id that `batchUpdate` needs.
- Rows and columns are numbered from 1, so column D is 4.
- There is no raw `batchUpdate` pass-through. It would skip the formula
  check below.

## Sign-in

`--credentials PATH` takes either JSON file Google issues:

- a service account key, for servers and automation
- an OAuth client of type Desktop app. `sheets-mcp login` runs the browser
  consent once and stores the token under `~/.config/sheets-mcp/`.

With no `--credentials`, the server uses Application Default Credentials,
as set by `gcloud auth application-default login`. Scopes are
`spreadsheets` and `drive`: moving, sharing and deleting any file the user
can reach needs the full Drive scope.

## Safety

- `--read-only` registers only the tools that change nothing.
- `delete_file` moves a file to the trash. `permanent=true` deletes it.
- A value written with `parse=true` that starts with `=` passes a formula
  check. The check refuses IMPORTXML, IMPORTHTML, IMPORTDATA, IMPORTFEED,
  IMPORTRANGE and IMAGE, which fetch a URL and can send cell contents to a
  third party when a prompt injection writes them.
- `read_range` answers in pages under a byte budget, with `next_offset`
  for the next page. A range may be open (`Data!A:F`, `Data`), and the
  server reads it in row blocks.
- `export_spreadsheet` refuses to overwrite an existing local file unless
  `overwrite=true`.

## Layout

| Module     | Holds                                               |
| ---------- | --------------------------------------------------- |
| `auth`     | credentials from a key file, an OAuth token, or ADC |
| `google`   | Drive v3 and Sheets v4 clients, built per call      |
| `a1`       | A1 parsing, column letters, grid ranges             |
| `formulas` | the formula check                                   |
| `files`    | Drive files, folders, sharing, import and export    |
| `tabs`     | spreadsheet metadata and tab changes                |
| `values`   | reads, writes, appends and clears                   |
| `layout`   | rows, columns and cell formats                      |
| `server`   | tool registration, annotations, error translation   |

The Google API client is not thread-safe, and the MCP SDK runs each sync
tool on a worker thread, so every call builds its own clients.

## Tests

`tests/fake_google.py` is an in-memory Drive and Sheets. It keeps files,
tabs and cell values, and applies the structural `batchUpdate` requests.
It records formatting requests without applying them, so a format test
checks the request the server sent. No test calls Google.
