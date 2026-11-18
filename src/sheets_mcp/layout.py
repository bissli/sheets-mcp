"""Tools that change rows, columns and cell formats.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sheets_mcp import a1
from sheets_mcp.errors import SheetsError
from sheets_mcp.google import Clients, rgb_color, tab_properties

Dimension = Literal['rows', 'columns']
Action = Literal['insert', 'move', 'resize', 'autofit', 'hide', 'show']

API_DIMENSIONS = {'rows': 'ROWS', 'columns': 'COLUMNS'}
OUTER_SIDES = ('top', 'bottom', 'left', 'right')
INNER_SIDES = ('innerHorizontal', 'innerVertical')
BORDER_SIDES = {
    'all': OUTER_SIDES + INNER_SIDES,
    'outer': OUTER_SIDES,
    'inner': INNER_SIDES,
    'none': OUTER_SIDES + INNER_SIDES,
    }
MERGE_TYPES = {'all': 'MERGE_ALL', 'rows': 'MERGE_ROWS', 'columns': 'MERGE_COLUMNS'}
WRAP_STRATEGIES = {'overflow': 'OVERFLOW_CELL', 'clip': 'CLIP', 'wrap': 'WRAP'}


class NumberFormat(BaseModel):
    """The number_format argument of format_range.
    """

    model_config = ConfigDict(extra='forbid')

    pattern: str
    type: Literal[
        'NUMBER', 'PERCENT', 'CURRENCY', 'DATE', 'TIME', 'DATE_TIME',
        'SCIENTIFIC', 'TEXT'] = 'NUMBER'


def dimension_range(
        sheet_id: int, dimension: Dimension, start: int, count: int) -> dict:
    """Sheets API DimensionRange of count rows or columns from start,
    counted from 1.
    """
    return {
        'sheetId': sheet_id,
        'dimension': API_DIMENSIONS[dimension],
        'startIndex': start - 1,
        'endIndex': start - 1 + count,
        }


def edit_rows_columns(
        clients: Clients,
        spreadsheet_id: str,
        tab: str,
        dimension: Dimension,
        action: Action,
        start: int,
        count: int = 1,
        destination: int | None = None,
        size: int | None = None) -> dict:
    """Insert, move, resize, autofit, hide or show rows or columns.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    tab : str
        Tab title, matched exactly.
    dimension : {'rows', 'columns'}
    action : {'insert', 'move', 'resize', 'autofit', 'hide', 'show'}
        'insert' adds count empty rows or columns at start, shifting the
        old ones down or right. 'move' needs destination. 'resize' needs
        size. 'autofit' sizes each to fit its contents.
    start : int
        First row or column acted on, counted from 1; column D is 4.
    count : int, default 1
        How many rows or columns, from start.
    destination : int, optional
        For 'move': the row or column the block lands in front of,
        numbered before the move. 1 moves the block to the top or left
        edge.
    size : int, optional
        For 'resize': height or width in pixels.

    Returns
    -------
    dict
        The 'action' done and the 'dimension', 'start' and 'count' it
        covered.

    Raises
    ------
    SheetsError
        'move' without destination, 'resize' without size, or start or
        count below 1.

    Examples
    --------
    edit_rows_columns(spreadsheet_id='1AbC', tab='Data', dimension='rows',
                      action='insert', start=2, count=3)
    -> {'action': 'insert', 'dimension': 'rows', 'start': 2, 'count': 3}
    """
    if start < 1 or count < 1:
        raise SheetsError('start and count count from 1')
    sheet_id = tab_properties(clients, spreadsheet_id, tab)['sheetId']
    span = dimension_range(sheet_id, dimension, start, count)
    if action == 'insert':
        request = {'insertDimension': {'range': span, 'inheritFromBefore': start > 1}}
    elif action == 'move':
        if destination is None or destination < 1:
            raise SheetsError("'move' needs destination, counted from 1")
        request = {'moveDimension': {
            'source': span,
            'destinationIndex': destination - 1,
            }}
    elif action == 'resize':
        if size is None or size < 1:
            raise SheetsError("'resize' needs size in pixels")
        request = {'updateDimensionProperties': {
            'range': span,
            'properties': {'pixelSize': size},
            'fields': 'pixelSize',
            }}
    elif action == 'autofit':
        request = {'autoResizeDimensions': {'dimensions': span}}
    else:
        request = {'updateDimensionProperties': {
            'range': span,
            'properties': {'hiddenByUser': action == 'hide'},
            'fields': 'hiddenByUser',
            }}
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={'requests': [request]}).execute()
    return {'action': action, 'dimension': dimension, 'start': start, 'count': count}


def delete_rows_columns(
        clients: Clients,
        spreadsheet_id: str,
        tab: str,
        dimension: Dimension,
        start: int,
        count: int = 1) -> dict:
    """Delete rows or columns and everything in them; later ones shift up
    or left.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    tab : str
        Tab title, matched exactly.
    dimension : {'rows', 'columns'}
    start : int
        First row or column deleted, counted from 1; column D is 4.
    count : int, default 1
        How many rows or columns, from start.

    Returns
    -------
    dict
        The 'dimension', 'start' and 'count' deleted.

    Raises
    ------
    SheetsError
        start or count below 1.

    Examples
    --------
    delete_rows_columns(spreadsheet_id='1AbC', tab='Data', dimension='columns',
                        start=3, count=2)
    -> {'dimension': 'columns', 'start': 3, 'count': 2}
    """
    if start < 1 or count < 1:
        raise SheetsError('start and count count from 1')
    sheet_id = tab_properties(clients, spreadsheet_id, tab)['sheetId']
    request = {'deleteDimension': {
        'range': dimension_range(sheet_id, dimension, start, count),
        }}
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={'requests': [request]}).execute()
    return {'dimension': dimension, 'start': start, 'count': count}


def format_range(
        clients: Clients,
        spreadsheet_id: str,
        range_a1: str,
        number_format: NumberFormat | None = None,
        bold: bool | None = None,
        italic: bool | None = None,
        underline: bool | None = None,
        strikethrough: bool | None = None,
        font_size: int | None = None,
        font_family: str | None = None,
        text_color: str | None = None,
        background_color: str | None = None,
        horizontal_alignment: Literal['left', 'center', 'right'] | None = None,
        vertical_alignment: Literal['top', 'middle', 'bottom'] | None = None,
        wrap: Literal['overflow', 'clip', 'wrap'] | None = None,
        borders: Literal['all', 'outer', 'inner', 'none'] | None = None,
        merge: Literal['all', 'rows', 'columns', 'none'] | None = None) -> dict:
    """Format the cells of a range: numbers, text, colors, alignment,
    wrapping, borders and merges. Only the options given change, and only
    merge changes values.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    range_a1 : str
        A1 range with its tab: 'Data!A1:F1', 'Data!C:C', 'Data'.
    number_format : {'pattern': str, 'type': str}, optional
        A Sheets number format: {'pattern': '#,##0.00'},
        {'pattern': '0.0%', 'type': 'PERCENT'}. A date pattern such as
        'yyyy-mm-dd' needs 'type': 'DATE', or dates show as serial
        numbers.
    bold, italic, underline, strikethrough : bool, optional
        Text style on or off.
    font_size : int, optional
        Points.
    font_family : str, optional
        A Sheets font name such as 'Roboto Mono'.
    text_color, background_color : str, optional
        '#RRGGBB'.
    horizontal_alignment : {'left', 'center', 'right'}, optional
    vertical_alignment : {'top', 'middle', 'bottom'}, optional
    wrap : {'overflow', 'clip', 'wrap'}, optional
        What long text does at the cell edge.
    borders : {'all', 'outer', 'inner', 'none'}, optional
        Solid black borders around and between the cells; 'none' removes
        them all.
    merge : {'all', 'rows', 'columns', 'none'}, optional
        'all' merges the range into one cell, 'rows' merges each row,
        'columns' each column. A merge keeps only the top-left value of
        each merged block and deletes the rest. 'none' unmerges.

    Returns
    -------
    dict
        'range' formatted and 'changed', the options applied.

    Raises
    ------
    SheetsError
        No option was given.

    Examples
    --------
    format_range(spreadsheet_id='1AbC', range_a1='Data!A1:F1', bold=True,
                 background_color='#E8F0FE', borders='outer')
    -> {'range': "'Data'!A1:F1", 'changed': ['bold', 'background_color',
                                             'borders']}
    """
    cell_range = a1.parse_range(range_a1)
    sheet_id = tab_properties(clients, spreadsheet_id, cell_range.tab)['sheetId']
    grid = a1.grid_range(cell_range, sheet_id)
    text_style = {
        'bold': bold,
        'italic': italic,
        'underline': underline,
        'strikethrough': strikethrough,
        'fontSize': font_size,
        'fontFamily': font_family,
        }
    text_format = {key: value for key, value in text_style.items() if value is not None}
    if text_color is not None:
        text_format['foregroundColorStyle'] = {'rgbColor': rgb_color(text_color)}
    cell_format = {}
    if text_format:
        cell_format['textFormat'] = text_format
    if number_format is not None:
        cell_format['numberFormat'] = number_format.model_dump()
    if background_color is not None:
        cell_format['backgroundColorStyle'] = {'rgbColor': rgb_color(background_color)}
    if horizontal_alignment is not None:
        cell_format['horizontalAlignment'] = horizontal_alignment.upper()
    if vertical_alignment is not None:
        cell_format['verticalAlignment'] = vertical_alignment.upper()
    if wrap is not None:
        cell_format['wrapStrategy'] = WRAP_STRATEGIES[wrap]
    requests = []
    if cell_format:
        fields = [f'userEnteredFormat.textFormat.{key}' for key in text_format]
        fields += [
            f'userEnteredFormat.{key}' for key in cell_format if key != 'textFormat'
            ]
        requests.append({'repeatCell': {
            'range': grid,
            'cell': {'userEnteredFormat': cell_format},
            'fields': ','.join(fields),
            }})
    if borders is not None:
        style = {'style': 'NONE'} if borders == 'none' else {
            'style': 'SOLID',
            'colorStyle': {'rgbColor': rgb_color('#000000')},
            }
        sides = dict.fromkeys(BORDER_SIDES[borders], style)
        requests.append({'updateBorders': {'range': grid, **sides}})
    if merge == 'none':
        requests.append({'unmergeCells': {'range': grid}})
    elif merge is not None:
        merge_type = MERGE_TYPES[merge]
        requests.append({'mergeCells': {'range': grid, 'mergeType': merge_type}})
    if not requests:
        raise SheetsError('give at least one format option')
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={'requests': requests}).execute()
    options = {
        'number_format': number_format,
        'bold': bold,
        'italic': italic,
        'underline': underline,
        'strikethrough': strikethrough,
        'font_size': font_size,
        'font_family': font_family,
        'text_color': text_color,
        'background_color': background_color,
        'horizontal_alignment': horizontal_alignment,
        'vertical_alignment': vertical_alignment,
        'wrap': wrap,
        'borders': borders,
        'merge': merge,
        }
    return {
        'range': a1.to_a1(cell_range),
        'changed': [name for name, value in options.items() if value is not None],
        }
