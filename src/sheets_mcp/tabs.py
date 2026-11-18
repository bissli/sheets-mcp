"""Tools that describe a spreadsheet and add, change, copy or delete tabs.
"""
from sheets_mcp import a1
from sheets_mcp.errors import SheetsError
from sheets_mcp.formulas import refuse_url_functions
from sheets_mcp.google import Clients, rgb_color, tab_properties


def describe_spreadsheet(clients: Clients, spreadsheet_id: str) -> dict:
    """Title, link, tabs and named ranges of a spreadsheet.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.

    Returns
    -------
    dict
        'title', 'url', 'locale' and 'time_zone'. 'tabs' lists each tab in
        order with its 'title', 'position' (1 is the first tab), grid
        'rows' and 'columns', 'frozen_rows', 'frozen_columns' and
        'hidden'. 'named_ranges' lists each 'name' with its A1 'range'.

    Examples
    --------
    describe_spreadsheet(spreadsheet_id='1AbC')
    -> {'title': 'Budget', 'url': 'https://docs.google.com/...',
        'locale': 'en_US', 'time_zone': 'America/New_York',
        'tabs': [{'title': 'Data', 'position': 1, 'rows': 1000,
                  'columns': 26, 'frozen_rows': 1, 'frozen_columns': 0,
                  'hidden': False}],
        'named_ranges': [{'name': 'Totals', 'range': "'Data'!F2:F40"}]}
    """
    reply = clients.sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields='spreadsheetUrl,properties(title,locale,timeZone),'
        'sheets.properties,namedRanges').execute()
    tabs = []
    title_by_sheet_id = {}
    for sheet in reply.get('sheets', []):
        properties = sheet['properties']
        grid = properties.get('gridProperties', {})
        title_by_sheet_id[properties['sheetId']] = properties['title']
        tabs.append({
            'title': properties['title'],
            'position': properties['index'] + 1,
            'rows': grid.get('rowCount', 0),
            'columns': grid.get('columnCount', 0),
            'frozen_rows': grid.get('frozenRowCount', 0),
            'frozen_columns': grid.get('frozenColumnCount', 0),
            'hidden': properties.get('hidden', False),
            })
    named_ranges = []
    for named in reply.get('namedRanges', []):
        bounds = named['range']
        start_row = bounds.get('startRowIndex')
        start_column = bounds.get('startColumnIndex')
        cell_range = a1.CellRange(
            tab=title_by_sheet_id[bounds.get('sheetId', 0)],
            first_row=None if start_row is None else start_row + 1,
            last_row=bounds.get('endRowIndex'),
            first_column=None if start_column is None else start_column + 1,
            last_column=bounds.get('endColumnIndex'))
        named_ranges.append({'name': named['name'], 'range': a1.to_a1(cell_range)})
    properties = reply['properties']
    return {
        'title': properties['title'],
        'url': reply['spreadsheetUrl'],
        'locale': properties.get('locale'),
        'time_zone': properties.get('timeZone'),
        'tabs': tabs,
        'named_ranges': named_ranges,
        }


def add_tab(
        clients: Clients,
        spreadsheet_id: str,
        title: str,
        position: int | None = None,
        rows: int = 1000,
        columns: int = 26) -> dict:
    """Add an empty tab.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    title : str
        Title of the new tab. Google refuses a title another tab has.
    position : int, optional
        1 puts the tab first. Omit it to add the tab last.
    rows, columns : int, default 1000 and 26
        Grid size of the new tab.

    Returns
    -------
    dict
        The new tab's 'title' and 'position'.

    Examples
    --------
    add_tab(spreadsheet_id='1AbC', title='Q4', position=1)
    -> {'title': 'Q4', 'position': 1}
    """
    properties = {
        'title': title,
        'gridProperties': {'rowCount': rows, 'columnCount': columns},
        }
    if position is not None:
        properties['index'] = position - 1
    reply = clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={'requests': [{'addSheet': {'properties': properties}}]}).execute()
    added = reply['replies'][0]['addSheet']['properties']
    return {'title': added['title'], 'position': added['index'] + 1}


def edit_tab(
        clients: Clients,
        spreadsheet_id: str,
        tab: str,
        title: str | None = None,
        position: int | None = None,
        hidden: bool | None = None,
        color: str | None = None,
        frozen_rows: int | None = None,
        frozen_columns: int | None = None) -> dict:
    """Rename, move, hide or show, color, or freeze rows and columns of a tab.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    tab : str
        Current tab title, matched exactly.
    title : str, optional
        New title.
    position : int, optional
        New place among the tabs; 1 is first.
    hidden : bool, optional
        True hides the tab; False shows it.
    color : str, optional
        Tab color as '#RRGGBB'; '' removes the color.
    frozen_rows, frozen_columns : int, optional
        How many top rows or left columns stay in view while scrolling;
        0 unfreezes.

    Returns
    -------
    dict
        'title' of the tab after the change and 'changed', the properties
        set.

    Raises
    ------
    SheetsError
        No change was given, or no tab has that title.

    Examples
    --------
    edit_tab(spreadsheet_id='1AbC', tab='Sheet1', title='Data', frozen_rows=1)
    -> {'title': 'Data', 'changed': ['title', 'frozen_rows']}
    """
    current = tab_properties(clients, spreadsheet_id, tab)
    properties = {'sheetId': current['sheetId']}
    fields = []
    changed = []
    if title is not None:
        properties['title'] = title
        fields.append('title')
        changed.append('title')
    if position is not None:
        # The API counts the new index before the tab leaves its old
        # place, so a move to the right lands one short without the +1.
        moving_right = position - 1 > current['index']
        properties['index'] = position if moving_right else position - 1
        fields.append('index')
        changed.append('position')
    if hidden is not None:
        properties['hidden'] = hidden
        fields.append('hidden')
        changed.append('hidden')
    if color is not None:
        if color:
            properties['tabColorStyle'] = {'rgbColor': rgb_color(color)}
        fields.append('tabColorStyle')
        changed.append('color')
    grid = {}
    if frozen_rows is not None:
        grid['frozenRowCount'] = frozen_rows
        fields.append('gridProperties.frozenRowCount')
        changed.append('frozen_rows')
    if frozen_columns is not None:
        grid['frozenColumnCount'] = frozen_columns
        fields.append('gridProperties.frozenColumnCount')
        changed.append('frozen_columns')
    if grid:
        properties['gridProperties'] = grid
    if not fields:
        raise SheetsError('give at least one change to make')
    request = {'updateSheetProperties': {
        'properties': properties,
        'fields': ','.join(fields),
        }}
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={'requests': [request]}).execute()
    return {'title': title or tab, 'changed': changed}


def copy_tab(
        clients: Clients,
        spreadsheet_id: str,
        tab: str,
        destination_spreadsheet_id: str | None = None,
        title: str | None = None) -> dict:
    """Copy a tab, with its values and formatting, within a spreadsheet or
    into another one.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet that holds the tab.
    tab : str
        Title of the tab to copy, matched exactly.
    destination_spreadsheet_id : str, optional
        Spreadsheet to copy into, added as its last tab. Omit it to
        duplicate the tab in place. A tab with a URL-fetching formula is
        not copied into another spreadsheet, where it could read that
        spreadsheet's cells.
    title : str, optional
        Title of the copy. Omitted, Google names it 'Copy of <tab>'.

    Returns
    -------
    dict
        'spreadsheet_id' holding the copy and the copy's 'title'.

    Raises
    ------
    SheetsError
        The tab, copied into another spreadsheet, has a formula calling
        IMPORTXML, IMPORTHTML, IMPORTDATA, IMPORTFEED, IMPORTRANGE or
        IMAGE.

    Examples
    --------
    copy_tab(spreadsheet_id='1AbC', tab='Template', title='March')
    -> {'spreadsheet_id': '1AbC', 'title': 'March'}
    """
    sheet_id = tab_properties(clients, spreadsheet_id, tab)['sheetId']
    if destination_spreadsheet_id is None:
        duplicate = {'sourceSheetId': sheet_id}
        if title is not None:
            duplicate['newSheetName'] = title
        reply = clients.sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': [{'duplicateSheet': duplicate}]}).execute()
        copied = reply['replies'][0]['duplicateSheet']['properties']
        return {'spreadsheet_id': spreadsheet_id, 'title': copied['title']}
    formulas = clients.sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=a1.quote_tab(tab),
        valueRenderOption='FORMULA').execute().get('values', [])
    for row in formulas:
        for value in row:
            refuse_url_functions(value)
    copied = clients.sheets.spreadsheets().sheets().copyTo(
        spreadsheetId=spreadsheet_id,
        sheetId=sheet_id,
        body={'destinationSpreadsheetId': destination_spreadsheet_id}).execute()
    if title is not None:
        rename = {'updateSheetProperties': {
            'properties': {'sheetId': copied['sheetId'], 'title': title},
            'fields': 'title',
            }}
        clients.sheets.spreadsheets().batchUpdate(
            spreadsheetId=destination_spreadsheet_id,
            body={'requests': [rename]}).execute()
    return {
        'spreadsheet_id': destination_spreadsheet_id,
        'title': title or copied['title'],
        }


def delete_tab(clients: Clients, spreadsheet_id: str, tab: str) -> dict:
    """Delete a tab and everything on it.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    tab : str
        Title of the tab to delete, matched exactly. Google refuses to
        delete a spreadsheet's only tab.

    Returns
    -------
    dict
        'deleted', the tab title.

    Examples
    --------
    delete_tab(spreadsheet_id='1AbC', tab='Scratch')
    -> {'deleted': 'Scratch'}
    """
    sheet_id = tab_properties(clients, spreadsheet_id, tab)['sheetId']
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={'requests': [{'deleteSheet': {'sheetId': sheet_id}}]}).execute()
    return {'deleted': tab}
