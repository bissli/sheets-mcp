"""Tools that read, write, append and clear cell values.
"""
import json
from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sheets_mcp import a1
from sheets_mcp.errors import SheetsError
from sheets_mcp.formulas import refuse_url_functions
from sheets_mcp.google import Clients, tab_properties

CellValue = str | int | float | bool | None
Render = Literal['values', 'formatted', 'formulas']

PAGE_BYTES = 60_000
RENDER_OPTIONS = {
    'values': 'UNFORMATTED_VALUE',
    'formatted': 'FORMATTED_VALUE',
    'formulas': 'FORMULA',
    }


class RangeValues(BaseModel):
    """One block of a write_ranges call.
    """

    model_config = ConfigDict(extra='forbid')

    range: str
    values: list[list[CellValue]]


def row_bytes(row: list) -> int:
    """Size of row as compact JSON, plus one for the separating comma.
    """
    return len(json.dumps(row, separators=(',', ':'), ensure_ascii=False)) + 1


def read_range(
        clients: Clients,
        spreadsheet_id: str,
        range_a1: str,
        render: Render = 'values',
        offset: int | None = None) -> dict:
    """Read the values of one range, a page at a time.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    range_a1 : str
        A1 range with its tab: 'Data!A1:F500', "'Q3 Model'!B2:F40". An
        open range reads to the last row with data: 'Data!A:F', 'Data!A2:F',
        or 'Data' for the whole tab. Each page reads the range from offset
        to its end, so page a very large tab by bounded ranges.
    render : {'values', 'formatted', 'formulas'}, default 'values'
        'values' gives numbers as numbers and dates as shown. 'formatted'
        gives every cell as the text the Sheets UI shows. 'formulas' gives
        each formula's text instead of its result.
    offset : int, optional
        next_offset from the previous page, a row inside the range. Omit it
        for the first page.

    Returns
    -------
    dict
        'range' is the A1 range of the rows returned. 'values' is a list of
        rows; an empty cell is '' and a row's trailing empty cells are
        left out. 'next_offset' is the row to pass as offset for the next
        page, or None after the last page.

    Examples
    --------
    read_range(spreadsheet_id='1AbC', range_a1='Data!A1:F')
    -> {'range': "'Data'!A1:F310", 'values': [['Name', 'Price'], ...],
        'next_offset': 311}
    """
    cell_range = a1.parse_range(range_a1)
    window = cell_range
    if offset is not None:
        if (offset < (cell_range.first_row or 1)
            or cell_range.last_row and offset > cell_range.last_row):
            raise SheetsError(f'offset {offset} is outside {range_a1}')
        window = replace(cell_range, first_row=offset)
    if window.first_row and window.last_row is None and window.first_column is None:
        # 'Tab!5:' is not A1, so a whole-tab read past row 1 names its
        # columns.
        grid = tab_properties(clients, spreadsheet_id, window.tab)['gridProperties']
        window = replace(window, first_column=1, last_column=grid['columnCount'])
    rows = clients.sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=a1.to_a1(window),
        valueRenderOption=RENDER_OPTIONS[render],
        dateTimeRenderOption='FORMATTED_STRING').execute().get('values', [])
    page = []
    page_bytes = 0
    for row in rows:
        size = row_bytes(row)
        if page and page_bytes + size > PAGE_BYTES:
            break
        page.append(row)
        page_bytes += size
    first_row = window.first_row or 1
    page_range = replace(
        cell_range, first_row=first_row, last_row=first_row + max(len(page), 1) - 1)
    return {
        'range': a1.to_a1(page_range),
        'values': page,
        'next_offset': first_row + len(page) if len(page) < len(rows) else None,
        }


def write_ranges(
        clients: Clients,
        spreadsheet_id: str,
        data: list[RangeValues],
        parse: bool = True) -> dict:
    """Write values into one or more ranges in one call.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    data : list of {'range': str, 'values': list of rows}
        Each range is A1 with its tab, and its values fill it row by row
        from its top-left cell. A single cell such as 'Data!A1' takes a
        block of any size; a bounded range smaller than its values is
        refused by Google. A None value leaves its cell as it is, and ''
        clears it.
    parse : bool, default True
        True parses each string as if typed in the Sheets UI: '=SUM(A1:A3)'
        becomes a formula and '12%' a number. False stores strings as
        text. A parsed formula that calls IMPORTXML, IMPORTHTML,
        IMPORTDATA, IMPORTFEED, IMPORTRANGE or IMAGE is refused.

    Returns
    -------
    dict
        'updated_ranges' lists the A1 ranges written, and 'updated_cells'
        counts their cells.

    Examples
    --------
    write_ranges(spreadsheet_id='1AbC', data=[
        {'range': 'Data!A1:B2', 'values': [['Name', 'Price'], ['ACME', 12.5]]},
        {'range': 'Data!D1', 'values': [['=SUM(B2:B100)']]}])
    -> {'updated_ranges': ['Data!A1:B2', 'Data!D1'], 'updated_cells': 5}
    """
    body_data = []
    for block in data:
        if parse:
            for row in block.values:
                for value in row:
                    refuse_url_functions(value)
        target = a1.to_a1(a1.parse_range(block.range))
        body_data.append({'range': target, 'values': block.values})
    reply = clients.sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            'valueInputOption': 'USER_ENTERED' if parse else 'RAW',
            'data': body_data,
            }).execute()
    responses = reply.get('responses', [])
    return {
        'updated_ranges': [response['updatedRange'] for response in responses],
        'updated_cells': reply.get('totalUpdatedCells', 0),
        }


def append_rows(
        clients: Clients,
        spreadsheet_id: str,
        tab: str,
        rows: list[list[CellValue]],
        parse: bool = True) -> dict:
    """Add rows below the table of data on a tab.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    tab : str
        Tab title, matched exactly.
    rows : list of rows
        Sheets finds the table that starts at the tab's first cell with
        data, and each row starts in the table's first column. Rows are
        inserted, so nothing below the table is overwritten.
    parse : bool, default True
        As in write_ranges: True parses strings as typed in the Sheets UI
        and refuses URL-fetching formulas; False stores text.

    Returns
    -------
    dict
        'updated_range' is the A1 range the new rows fill.

    Examples
    --------
    append_rows(spreadsheet_id='1AbC', tab='Log', rows=[['2026-11-18', 4]])
    -> {'updated_range': 'Log!A42:B42'}
    """
    if parse:
        for row in rows:
            for value in row:
                refuse_url_functions(value)
    reply = clients.sheets.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=a1.quote_tab(tab),
        valueInputOption='USER_ENTERED' if parse else 'RAW',
        insertDataOption='INSERT_ROWS',
        body={'values': rows}).execute()
    return {'updated_range': reply['updates']['updatedRange']}


def clear_ranges(clients: Clients, spreadsheet_id: str, ranges: list[str]) -> dict:
    """Clear the values of one or more ranges, keeping their formatting.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    ranges : list of str
        A1 ranges with their tabs. 'Data' clears the whole tab.

    Returns
    -------
    dict
        'cleared_ranges' lists the A1 ranges cleared.

    Examples
    --------
    clear_ranges(spreadsheet_id='1AbC', ranges=['Data!A2:F'])
    -> {'cleared_ranges': ["'Data'!A2:F1000"]}
    """
    targets = [a1.to_a1(a1.parse_range(text)) for text in ranges]
    reply = clients.sheets.spreadsheets().values().batchClear(
        spreadsheetId=spreadsheet_id, body={'ranges': targets}).execute()
    return {'cleared_ranges': reply.get('clearedRanges', [])}
