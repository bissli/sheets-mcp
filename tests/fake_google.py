"""In-memory Drive v3 and Sheets v4 with the googleapiclient call chains.

Every resource method returns a request whose execute() does the work and
returns the API's JSON shape. A missing file, tab or permission raises
HttpError. Tests read `FakeGoogle.requests` to see each batchUpdate request
sent, applied or not.
"""
import copy
import csv
import functools
import inspect
import io
import itertools
import json
import re
from collections.abc import Callable
from typing import Any

import httplib2
from googleapiclient.errors import HttpError
from sheets_mcp.a1 import CellRange, parse_range, to_a1
from sheets_mcp.google import FOLDER_MIME, SHEET_MIME

DEFAULT_ROWS = 1000
DEFAULT_COLUMNS = 26
OWNER_EMAIL = 'me@example.com'
MODIFIED_TIME = '2024-01-01T00:00:00.000Z'
PRIVATE_KEYS = {'tabs', 'nextSheetId', 'namedRanges'}
IGNORED_KWARGS = {
    'fields',
    'supportsAllDrives',
    'includeItemsFromAllDrives',
    'corpora',
    'orderBy',
    'valueRenderOption',
    'dateTimeRenderOption',
    'insertDataOption',
    'sendNotificationEmail',
    'ranges',
    'includeGridData',
    'pageToken',
    }
DIMENSIONS = {'ROWS': (0, 'rowCount'), 'COLUMNS': (1, 'columnCount')}
GRID_FIELDS = ('rowCount', 'columnCount', 'frozenRowCount', 'frozenColumnCount')
QUOTED = r"'((?:[^'\\]|\\.)*)'"
NUMBER_PATTERN = re.compile(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?')
INTEGER_PATTERN = re.compile(r'[+-]?\d+')


def http_error(status: int, message: str) -> HttpError:
    """HttpError whose status_code is status and whose reason is message.
    """
    body = json.dumps({'error': {'code': status, 'message': message}})
    return HttpError(httplib2.Response({'status': status}), body.encode())


class FakeRequest:
    """A request whose execute() runs the stored work.
    """

    def __init__(self, work: Callable[[], Any]) -> None:
        self.work = work

    def execute(self, num_retries: int = 0) -> Any:
        """Run the work and return the API's JSON shape.
        """
        return self.work()


def lazy(method: Callable) -> Callable:
    """Make a resource method return a FakeRequest.

    The call binds its arguments at once, so a wrong keyword raises
    TypeError at the call. A keyword in IGNORED_KWARGS that the method does
    not declare is dropped. The method body runs at execute().
    """
    signature = inspect.signature(method)

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> FakeRequest:
        kept = {
            name: value for name, value in kwargs.items()
            if name in signature.parameters or name not in IGNORED_KWARGS
            }
        signature.bind(self, *args, **kept)
        return FakeRequest(functools.partial(method, self, *args, **kept))

    return wrapper


def parse_number(text: str) -> int | float | str:
    """Text as a number when it reads as one, as USER_ENTERED does.
    """
    if not NUMBER_PATTERN.fullmatch(text):
        return text
    return int(text) if INTEGER_PATTERN.fullmatch(text) else float(text)


class RawText(str):
    """A cell value stored as text, as a RAW write stores a string that
    starts with '='.
    """


def cell_data(value: Any) -> dict:
    """The CellData of a stored value: its userEnteredValue.
    """
    if value == '':
        return {}
    if isinstance(value, bool):
        return {'userEnteredValue': {'boolValue': value}}
    if isinstance(value, int | float):
        return {'userEnteredValue': {'numberValue': value}}
    if value.startswith('=') and not isinstance(value, RawText):
        return {'userEnteredValue': {'formulaValue': value}}
    return {'userEnteredValue': {'stringValue': value}}


def new_tab(
        title: str,
        sheet_id: int,
        rows: int = DEFAULT_ROWS,
        columns: int = DEFAULT_COLUMNS) -> dict:
    """An empty tab: SheetProperties and a sparse cells dict.
    """
    return {
        'properties': {
            'sheetId': sheet_id,
            'title': title,
            'index': 0,
            'gridProperties': {
                'rowCount': rows,
                'columnCount': columns,
                'frozenRowCount': 0,
                'frozenColumnCount': 0,
                },
            'hidden': False,
            },
        'cells': {},
        }


def fill_cells(
        tab: dict,
        rows: list[list],
        top: int,
        left: int,
        parse: bool,
        raw: bool = False) -> None:
    """Write rows into tab with the first value at (top, left), 0-based.

    Parameters
    ----------
    tab : dict
    rows : list[list]
        None leaves the cell it lands on as it is; '' clears it.
    top, left : int
        Row and column of the first value.
    parse : bool
        A str that reads as a number is stored as one.
    raw : bool, default False
        A str is stored as RawText, as a RAW write stores it.
    """
    for row_offset, row in enumerate(rows):
        for column_offset, value in enumerate(row):
            position = (top + row_offset, left + column_offset)
            if value is None:
                continue
            if value == '':
                tab['cells'].pop(position, None)
            elif parse and isinstance(value, str):
                tab['cells'][position] = parse_number(value)
            elif raw and isinstance(value, str):
                tab['cells'][position] = RawText(value)
            else:
                tab['cells'][position] = value


def seeded_tab(title: str, sheet_id: int, rows: list[list], parse: bool) -> dict:
    """A tab holding rows at A1, with a grid that fits them.
    """
    widest = max((len(row) for row in rows), default=0)
    tab = new_tab(
        title,
        sheet_id,
        max(DEFAULT_ROWS, len(rows)),
        max(DEFAULT_COLUMNS, widest))
    fill_cells(tab, rows, 0, 0, parse)
    return tab


def reindex(spreadsheet: dict) -> None:
    """Number the tabs 0..n-1 in list order.
    """
    for position, tab in enumerate(spreadsheet['tabs']):
        tab['properties']['index'] = position


def take_sheet_id(spreadsheet: dict, wanted: int | None = None) -> int:
    """wanted, or the next unused sheet id, and mark it used.
    """
    sheet_id = spreadsheet['nextSheetId'] if wanted is None else wanted
    spreadsheet['nextSheetId'] = max(spreadsheet['nextSheetId'], sheet_id + 1)
    return sheet_id


def find_tab(spreadsheet: dict, sheet_id: int) -> dict:
    """The tab with sheet_id, or HttpError 400.
    """
    for tab in spreadsheet['tabs']:
        if tab['properties']['sheetId'] == sheet_id:
            return tab
    raise http_error(400, f'No sheet with id: {sheet_id}')


def find_tab_titled(spreadsheet: dict, title: str, text: str) -> dict:
    """The tab titled title, or HttpError 400 naming the range text.
    """
    for tab in spreadsheet['tabs']:
        if tab['properties']['title'] == title:
            return tab
    raise http_error(400, f'Unable to parse range: {text}')


def check_title_free(
        spreadsheet: dict,
        title: str,
        own_id: int | None = None) -> None:
    """Raise HttpError 400 when a tab other than own_id has this title.
    """
    for tab in spreadsheet['tabs']:
        properties = tab['properties']
        if properties['title'] == title and properties['sheetId'] != own_id:
            raise http_error(
                400,
                f'A sheet with the name "{title}" already exists. '
                'Please enter another name.')


def render(title: str, top: int, bottom: int, left: int, right: int) -> str:
    """A1 text of a block given 0-based rows and columns, end exclusive.
    """
    return to_a1(CellRange(
        tab=title,
        first_row=top + 1,
        last_row=bottom,
        first_column=left + 1,
        last_column=right))


def remap_cells(
        tab: dict,
        axis: int,
        mapping: Callable[[int], int | None]) -> None:
    """Move each cell along axis (0 rows, 1 columns); None drops the cell.
    """
    moved = {}
    for position, value in tab['cells'].items():
        new_index = mapping(position[axis])
        if new_index is None:
            continue
        key = list(position)
        key[axis] = new_index
        moved[tuple(key)] = value
    tab['cells'] = moved


def spreadsheet_body(spreadsheet: dict) -> dict:
    """The Spreadsheet resource JSON of a spreadsheet file.
    """
    return {
        'spreadsheetId': spreadsheet['id'],
        'spreadsheetUrl': spreadsheet['webViewLink'],
        'properties': {
            'title': spreadsheet['name'],
            'locale': 'en_US',
            'timeZone': 'America/New_York',
            },
        'sheets': [
            {'properties': copy.deepcopy(tab['properties'])}
            for tab in spreadsheet['tabs']
            ],
        'namedRanges': copy.deepcopy(spreadsheet.get('namedRanges', [])),
        }


def public(file: dict) -> dict:
    """A copy of a Drive file without the fake's private keys.
    """
    return {
        key: copy.deepcopy(value) for key, value in file.items()
        if key not in PRIVATE_KEYS
        }


def unquote(text: str) -> str:
    """Text with each backslash escape resolved.
    """
    return re.sub(r'\\(.)', r'\1', text)


def split_top_level(text: str, word: str) -> list[str]:
    """Split text at ' word ' outside quotes and parentheses.
    """
    separator = f' {word} '
    parts = []
    depth = 0
    in_quote = False
    start = 0
    position = 0
    while position < len(text):
        char = text[position]
        if in_quote:
            if char == '\\':
                position += 1
            elif char == "'":
                in_quote = False
        elif char == "'":
            in_quote = True
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and text.startswith(separator, position):
            parts.append(text[start:position])
            position += len(separator)
            start = position
            continue
        position += 1
    parts.append(text[start:])
    return parts


def term_matcher(term: str) -> Callable[[dict], bool]:
    """Predicate on a Drive file for one q term.

    Raises
    ------
    ValueError
        The term is outside the supported grammar.
    """
    term = term.strip()
    if term.startswith('(') and term.endswith(')'):
        parts = split_top_level(term[1:-1], 'or')
        alternatives = [term_matcher(part) for part in parts]
        return lambda file: any(match(file) for match in alternatives)
    found = re.fullmatch(r'trashed\s*=\s*(true|false)', term)
    if found:
        wanted = found[1] == 'true'
        return lambda file: file['trashed'] == wanted
    found = re.fullmatch(rf'mimeType\s*(=|!=)\s*{QUOTED}', term)
    if found:
        mime = unquote(found[2])
        equal = found[1] == '='
        return lambda file: (file['mimeType'] == mime) == equal
    found = re.fullmatch(rf'{QUOTED}\s+in\s+parents', term)
    if found:
        parent = unquote(found[1])
        return lambda file: parent in file['parents']
    found = re.fullmatch(rf'name\s+contains\s+{QUOTED}', term)
    if found:
        word_start = re.compile(r'(?:^|\W)' + re.escape(unquote(found[1])), re.I)
        return lambda file: word_start.search(file['name']) is not None
    raise ValueError(f'unsupported q term: {term!r}')


class FakeGoogle:
    """Drive and Sheets in memory.

    Attributes
    ----------
    drive : FakeDrive
        Stands in for the googleapiclient Drive v3 resource.
    sheets : FakeSheets
        Stands in for the googleapiclient Sheets v4 resource.
    files : dict[str, dict]
        Drive files by id. A spreadsheet file also holds 'tabs', a list in
        index order of {'properties', 'cells'} with cells keyed by 0-based
        (row, column).
    requests : list[dict]
        Every batchUpdate request sent, applied or not, in order.
    """

    def __init__(self) -> None:
        self.files: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.counter = itertools.count(1)
        self.drive = FakeDrive(self)
        self.sheets = FakeSheets(self)

    def new_id(self, prefix: str) -> str:
        """A fresh id such as 'file3' or 'perm4'.
        """
        return f'{prefix}{next(self.counter)}'

    def new_file(
            self,
            name: str,
            mime_type: str,
            parents: list[str] | None,
            tabs: list[dict] | None = None) -> dict:
        """Register a file owned by OWNER_EMAIL and return its stored dict.

        Parameters
        ----------
        name : str
        mime_type : str
        parents : list[str] or None
            None puts the file in 'root'.
        tabs : list[dict] or None
            For a spreadsheet: its tabs. None gives one empty 'Sheet1'.
        """
        file_id = self.new_id('file')
        links = {
            SHEET_MIME: f'https://docs.google.com/spreadsheets/d/{file_id}/edit',
            FOLDER_MIME: f'https://drive.google.com/drive/folders/{file_id}',
            }
        default_link = f'https://drive.google.com/file/d/{file_id}/view'
        owner_permission = {
            'id': self.new_id('perm'),
            'type': 'user',
            'role': 'owner',
            'emailAddress': OWNER_EMAIL,
            }
        file = {
            'id': file_id,
            'name': name,
            'mimeType': mime_type,
            'parents': list(parents or ['root']),
            'trashed': False,
            'modifiedTime': MODIFIED_TIME,
            'webViewLink': links.get(mime_type, default_link),
            'owners': [{'emailAddress': OWNER_EMAIL, 'displayName': 'Me'}],
            'permissions': [owner_permission],
            }
        if mime_type == SHEET_MIME:
            file['tabs'] = tabs or [new_tab('Sheet1', 0)]
            file['nextSheetId'] = 0
            for tab in file['tabs']:
                take_sheet_id(file, tab['properties']['sheetId'])
            reindex(file)
        self.files[file_id] = file
        return file

    def file(self, file_id: str) -> dict:
        """The stored file, or HttpError 404.
        """
        if file_id not in self.files:
            raise http_error(404, f'File not found: {file_id}.')
        return self.files[file_id]

    def spreadsheet(self, spreadsheet_id: str) -> dict:
        """The stored spreadsheet file, or HttpError 404.
        """
        file = self.files.get(spreadsheet_id)
        if file is None or 'tabs' not in file:
            raise http_error(404, 'Requested entity was not found.')
        return file

    def add_spreadsheet(
            self,
            name: str,
            tabs: dict[str, list[list]] | None = None,
            parents: list[str] | None = None) -> str:
        """Seed a spreadsheet and return its id.

        Parameters
        ----------
        name : str
            Drive name, which is also the spreadsheet title.
        tabs : dict[str, list[list]] or None
            Rows by tab title, written at A1 as given. Tab ids count from 0
            in order. None gives one empty 'Sheet1'.
        parents : list[str] or None
            None puts the file in 'root'.
        """
        rows_by_title = tabs or {'Sheet1': []}
        built = [
            seeded_tab(title, sheet_id, rows, parse=False)
            for sheet_id, (title, rows) in enumerate(rows_by_title.items())
            ]
        return self.new_file(name, SHEET_MIME, parents, built)['id']

    def add_folder(self, name: str, parents: list[str] | None = None) -> str:
        """Seed a folder and return its id.
        """
        return self.new_file(name, FOLDER_MIME, parents)['id']

    def cells(self, spreadsheet_id: str, tab: str) -> list[list]:
        """The tab's values as rows, trailing empties trimmed like the API.

        An empty row between two rows holding data is [].
        """
        spreadsheet = self.spreadsheet(spreadsheet_id)
        stored = find_tab_titled(spreadsheet, tab, tab)['cells']
        last_row = max((row_index for row_index, _ in stored), default=-1)
        rows: list[list] = [[] for _ in range(last_row + 1)]
        for (row_index, column_index), value in sorted(stored.items()):
            row = rows[row_index]
            row.extend([''] * (column_index - len(row)))
            row.append(value)
        return rows


class FakeSheets:
    """The Sheets v4 resource.
    """

    def __init__(self, fake: FakeGoogle) -> None:
        self.fake = fake

    def spreadsheets(self) -> 'FakeSpreadsheets':
        """The spreadsheets() resource.
        """
        return FakeSpreadsheets(self.fake)


class FakeSpreadsheets:
    """spreadsheets(): get, create, batchUpdate, sheets() and values().
    """

    def __init__(self, fake: FakeGoogle) -> None:
        self.fake = fake

    def sheets(self) -> 'FakeSheetCopies':
        """The spreadsheets().sheets() resource.
        """
        return FakeSheetCopies(self.fake)

    def values(self) -> 'FakeValues':
        """The spreadsheets().values() resource.
        """
        return FakeValues(self.fake)

    @lazy
    def get(self, spreadsheetId: str, ranges: list[str] | None = None) -> dict:
        """The Spreadsheet resource with tab properties. With ranges, only
        the tabs they name, each with its range's grid data as
        userEnteredValue. The fields mask is ignored.
        """
        spreadsheet = self.fake.spreadsheet(spreadsheetId)
        body = spreadsheet_body(spreadsheet)
        if ranges is None:
            return body
        values = FakeValues(self.fake)
        body['sheets'] = []
        for text in ranges:
            tab, top, bottom, left, right = values.resolve(spreadsheet, text)
            rows = values.read_block(tab, top, bottom, left, right)
            body['sheets'].append({
                'properties': copy.deepcopy(tab['properties']),
                'data': [{'rowData': [
                    {'values': [cell_data(value) for value in row]}
                    for row in rows]}],
                })
        return body

    @lazy
    def create(self, body: dict) -> dict:
        """Create a spreadsheet in 'root'; reply with its Spreadsheet resource.
        """
        tabs = []
        for position, sheet in enumerate(body.get('sheets') or [{}]):
            title = sheet.get('properties', {}).get('title', f'Sheet{position + 1}')
            tabs.append(new_tab(title, position))
        title = body.get('properties', {}).get('title', 'Untitled spreadsheet')
        file = self.fake.new_file(title, SHEET_MIME, None, tabs)
        return spreadsheet_body(file)

    @lazy
    def batchUpdate(self, spreadsheetId: str, body: dict) -> dict:
        """Record each request, apply the structural kinds, reply to each.

        A kind that is not applied replies {}.
        """
        spreadsheet = self.fake.spreadsheet(spreadsheetId)
        self.fake.requests.extend(copy.deepcopy(body['requests']))
        appliers = {
            'addSheet': self.add_sheet,
            'deleteSheet': self.delete_sheet,
            'updateSheetProperties': self.update_sheet_properties,
            'duplicateSheet': self.duplicate_sheet,
            'insertDimension': self.insert_dimension,
            'deleteDimension': self.delete_dimension,
            'moveDimension': self.move_dimension,
            'appendDimension': self.append_dimension,
            }
        replies = []
        for request in body['requests']:
            (kind, payload), = request.items()
            if kind in appliers:
                replies.append(appliers[kind](spreadsheet, payload))
            else:
                replies.append({})
        return {'spreadsheetId': spreadsheetId, 'replies': replies}

    def add_sheet(self, spreadsheet: dict, payload: dict) -> dict:
        """Apply addSheet.
        """
        properties = payload.get('properties', {})
        sheet_id = take_sheet_id(spreadsheet, properties.get('sheetId'))
        title = properties.get('title', f'Sheet{sheet_id + 1}')
        check_title_free(spreadsheet, title)
        tab = new_tab(title, sheet_id)
        tab['properties']['gridProperties'].update(
            properties.get('gridProperties', {}))
        for key in ('hidden', 'tabColorStyle'):
            if key in properties:
                tab['properties'][key] = properties[key]
        spreadsheet['tabs'].insert(
            properties.get('index', len(spreadsheet['tabs'])), tab)
        reindex(spreadsheet)
        return {'addSheet': {'properties': copy.deepcopy(tab['properties'])}}

    def delete_sheet(self, spreadsheet: dict, payload: dict) -> dict:
        """Apply deleteSheet; the last tab cannot go.
        """
        tab = find_tab(spreadsheet, payload['sheetId'])
        if len(spreadsheet['tabs']) == 1:
            raise http_error(
                400, "You can't remove all the visible sheets in a document.")
        spreadsheet['tabs'].remove(tab)
        reindex(spreadsheet)
        return {}

    def update_sheet_properties(self, spreadsheet: dict, payload: dict) -> dict:
        """Apply updateSheetProperties for the fields in its mask.

        Raises
        ------
        ValueError
            The mask names a field the fake does not handle.
        """
        given = payload['properties']
        tab = find_tab(spreadsheet, given['sheetId'])
        current = tab['properties']
        fields = payload['fields'].replace(' ', '').split(',')
        if fields == ['*']:
            fields = ['title', 'index', 'hidden', 'tabColorStyle', 'gridProperties']
        for field in fields:
            if field == 'title':
                check_title_free(spreadsheet, given['title'], current['sheetId'])
                current['title'] = given['title']
            elif field == 'index':
                # The API counts the index before the tab leaves its place.
                old_index = spreadsheet['tabs'].index(tab)
                new_index = given.get('index', 0)
                spreadsheet['tabs'].remove(tab)
                spreadsheet['tabs'].insert(
                    new_index - 1 if new_index > old_index else new_index, tab)
                reindex(spreadsheet)
            elif field == 'hidden':
                current['hidden'] = given.get('hidden', False)
            elif field == 'tabColorStyle':
                if 'tabColorStyle' in given:
                    current['tabColorStyle'] = copy.deepcopy(given['tabColorStyle'])
                else:
                    current.pop('tabColorStyle', None)
            elif field == 'gridProperties' or field.startswith('gridProperties.'):
                if field == 'gridProperties':
                    names = GRID_FIELDS
                else:
                    names = (field.partition('.')[2],)
                for name in names:
                    if name not in GRID_FIELDS:
                        raise ValueError(f'unsupported mask field: {field!r}')
                    keeps_current = name in {'rowCount', 'columnCount'}
                    fallback = current['gridProperties'][name] if keeps_current else 0
                    current['gridProperties'][name] = given.get(
                        'gridProperties', {}).get(name, fallback)
            else:
                raise ValueError(f'unsupported mask field: {field!r}')
        grid = current['gridProperties']
        tab['cells'] = {
            position: value for position, value in tab['cells'].items()
            if position[0] < grid['rowCount'] and position[1] < grid['columnCount']
            }
        return {}

    def duplicate_sheet(self, spreadsheet: dict, payload: dict) -> dict:
        """Apply duplicateSheet, cells included.
        """
        source = find_tab(spreadsheet, payload['sourceSheetId'])
        clone = copy.deepcopy(source)
        properties = clone['properties']
        properties['sheetId'] = take_sheet_id(spreadsheet, payload.get('newSheetId'))
        properties['title'] = payload.get(
            'newSheetName', f"Copy of {source['properties']['title']}")
        check_title_free(spreadsheet, properties['title'])
        spreadsheet['tabs'].insert(
            payload.get('insertSheetIndex', len(spreadsheet['tabs'])), clone)
        reindex(spreadsheet)
        return {'duplicateSheet': {'properties': copy.deepcopy(properties)}}

    def unpack_range(self, spreadsheet: dict, dimension_range: dict) -> tuple:
        """(tab, axis, count key, start, end) of a DimensionRange.
        """
        axis, count_key = DIMENSIONS[dimension_range['dimension']]
        return (
            find_tab(spreadsheet, dimension_range['sheetId']),
            axis,
            count_key,
            dimension_range['startIndex'],
            dimension_range['endIndex'])

    def insert_dimension(self, spreadsheet: dict, payload: dict) -> dict:
        """Apply insertDimension: later cells shift and the grid grows.
        """
        tab, axis, count_key, start, end = self.unpack_range(
            spreadsheet, payload['range'])
        grid = tab['properties']['gridProperties']
        if start > grid[count_key]:
            raise http_error(400, f'Invalid insert index: {start}')
        size = end - start
        remap_cells(tab, axis, lambda index: index + size if index >= start else index)
        grid[count_key] += size
        return {}

    def delete_dimension(self, spreadsheet: dict, payload: dict) -> dict:
        """Apply deleteDimension: the span's cells go, later cells shift up.
        """
        tab, axis, count_key, start, end = self.unpack_range(
            spreadsheet, payload['range'])
        grid = tab['properties']['gridProperties']
        if end > grid[count_key]:
            raise http_error(400, f'Cannot delete past the grid: {end}')
        size = end - start

        def shifted(index: int) -> int | None:
            if start <= index < end:
                return None
            return index - size if index >= end else index

        remap_cells(tab, axis, shifted)
        grid[count_key] -= size
        return {}

    def move_dimension(self, spreadsheet: dict, payload: dict) -> dict:
        """Apply moveDimension; destinationIndex counts before the move.
        """
        tab, axis, _, start, end = self.unpack_range(spreadsheet, payload['source'])
        destination = payload['destinationIndex']
        size = end - start
        if start <= destination <= end:
            return {}
        block_start = destination - size if destination > end else destination

        def moved(index: int) -> int:
            if start <= index < end:
                return block_start + index - start
            if end <= index < destination:
                return index - size
            if destination <= index < start:
                return index + size
            return index

        remap_cells(tab, axis, moved)
        return {}

    def append_dimension(self, spreadsheet: dict, payload: dict) -> dict:
        """Apply appendDimension: the grid grows by length.
        """
        tab = find_tab(spreadsheet, payload['sheetId'])
        _, count_key = DIMENSIONS[payload['dimension']]
        tab['properties']['gridProperties'][count_key] += payload['length']
        return {}


class FakeSheetCopies:
    """spreadsheets().sheets(): copyTo.
    """

    def __init__(self, fake: FakeGoogle) -> None:
        self.fake = fake

    @lazy
    def copyTo(self, spreadsheetId: str, sheetId: int, body: dict) -> dict:
        """Copy a tab to the end of another spreadsheet; reply with its
        properties. The new title is 'Copy of <title>'.
        """
        source = self.fake.spreadsheet(spreadsheetId)
        destination = self.fake.spreadsheet(body['destinationSpreadsheetId'])
        clone = copy.deepcopy(find_tab(source, sheetId))
        properties = clone['properties']
        properties['sheetId'] = take_sheet_id(destination)
        properties['title'] = f"Copy of {properties['title']}"
        destination['tabs'].append(clone)
        reindex(destination)
        return copy.deepcopy(properties)


class FakeValues:
    """spreadsheets().values(): get, batchUpdate, append, batchClear.
    """

    def __init__(self, fake: FakeGoogle) -> None:
        self.fake = fake

    def resolve(self, spreadsheet: dict, text: str) -> tuple:
        """(tab, top, bottom, left, right) of an A1 range.

        Rows and columns are 0-based with exclusive ends. An open end runs
        to the grid edge. A range past the grid raises HttpError 400.
        """
        cell_range = parse_range(text)
        tab = find_tab_titled(spreadsheet, cell_range.tab, text)
        grid = tab['properties']['gridProperties']
        rows, columns = grid['rowCount'], grid['columnCount']
        top = (cell_range.first_row or 1) - 1
        bottom = cell_range.last_row or rows
        left = (cell_range.first_column or 1) - 1
        right = cell_range.last_column or columns
        if top >= rows or bottom > rows or left >= columns or right > columns:
            raise http_error(
                400,
                f'Range ({text}) exceeds grid limits. '
                f'Max rows: {rows}, max columns: {columns}')
        return tab, top, bottom, left, right

    def read_block(
            self,
            tab: dict,
            top: int,
            bottom: int,
            left: int,
            right: int) -> list[list]:
        """Rows of a block with trailing empty cells and rows left out.
        """
        rows = []
        for row_index in range(top, bottom):
            row = [
                tab['cells'].get((row_index, column), '')
                for column in range(left, right)
                ]
            while row and row[-1] == '':
                row.pop()
            rows.append(row)
        while rows and not rows[-1]:
            rows.pop()
        return rows

    @lazy
    def batchGet(
            self,
            spreadsheetId: str,
            ranges: list[str],
            majorDimension: str = 'ROWS') -> dict:
        """One get reply per range, in order. Render options are ignored.
        """
        return {
            'spreadsheetId': spreadsheetId,
            'valueRanges': [
                self.get(spreadsheetId, text, majorDimension).execute()
                for text in ranges
                ],
            }

    @lazy
    def get(
            self,
            spreadsheetId: str,
            range: str,
            majorDimension: str = 'ROWS') -> dict:
        """The range's rows; 'values' is absent when nothing is left.
        """
        if majorDimension != 'ROWS':
            raise ValueError('the fake reads majorDimension ROWS only')
        spreadsheet = self.fake.spreadsheet(spreadsheetId)
        tab, top, bottom, left, right = self.resolve(spreadsheet, range)
        reply = {
            'range': render(tab['properties']['title'], top, bottom, left, right),
            'majorDimension': 'ROWS',
            }
        rows = self.read_block(tab, top, bottom, left, right)
        if rows:
            reply['values'] = rows
        return reply

    @lazy
    def batchUpdate(self, spreadsheetId: str, body: dict) -> dict:
        """Write each data block and report what changed.

        A range with no ':' is a start cell and may extend to the grid edge.
        A bounded range that the values overflow raises HttpError 400.
        """
        spreadsheet = self.fake.spreadsheet(spreadsheetId)
        parse = body['valueInputOption'] == 'USER_ENTERED'
        responses = []
        for item in body['data']:
            text, values = item['range'], item['values']
            tab, top, bottom, left, right = self.resolve(spreadsheet, text)
            grid = tab['properties']['gridProperties']
            is_start_cell = ':' not in text.rsplit('!', 1)[-1]
            if is_start_cell and parse_range(text).first_row:
                bottom, right = grid['rowCount'], grid['columnCount']
            row_count = len(values)
            column_count = max((len(row) for row in values), default=0)
            if row_count > bottom - top or column_count > right - left:
                raise http_error(
                    400,
                    f'Requested writing within range [{text}], but tried '
                    f'writing to row [{top + row_count}], '
                    f'column [{left + column_count}]')
            fill_cells(tab, values, top, left, parse, raw=not parse)
            responses.append({
                'updatedRange': render(
                    tab['properties']['title'],
                    top,
                    top + max(row_count, 1),
                    left,
                    left + max(column_count, 1)),
                'updatedCells': sum(len(row) for row in values),
                })
        return {
            'totalUpdatedCells': sum(item['updatedCells'] for item in responses),
            'responses': responses,
            }

    @lazy
    def append(
            self,
            spreadsheetId: str,
            range: str,
            valueInputOption: str,
            body: dict) -> dict:
        """Add rows below the tab's last row that holds a value, from column A.
        """
        spreadsheet = self.fake.spreadsheet(spreadsheetId)
        title = parse_range(range).tab
        tab = find_tab_titled(spreadsheet, title, range)
        grid = tab['properties']['gridProperties']
        rows = body['values']
        top = max((row_index for row_index, _ in tab['cells']), default=-1) + 1
        column_count = max((len(row) for row in rows), default=0)
        if column_count > grid['columnCount']:
            raise http_error(
                400,
                f'Range ({range}) exceeds grid limits. '
                f"Max columns: {grid['columnCount']}")
        grid['rowCount'] = max(grid['rowCount'], top + len(rows))
        parse = valueInputOption == 'USER_ENTERED'
        fill_cells(tab, rows, top, 0, parse, raw=not parse)
        updated_range = render(
            title, top, top + max(len(rows), 1), 0, max(column_count, 1))
        return {
            'updates': {
                'updatedRange': updated_range,
                'updatedRows': len(rows),
                'updatedCells': sum(len(row) for row in rows),
                },
            }

    @lazy
    def batchClear(self, spreadsheetId: str, body: dict) -> dict:
        """Clear each range and list it with grid-clipped ends.
        """
        spreadsheet = self.fake.spreadsheet(spreadsheetId)
        cleared = []
        for text in body['ranges']:
            tab, top, bottom, left, right = self.resolve(spreadsheet, text)
            tab['cells'] = {
                (row, col): value for (row, col), value in tab['cells'].items()
                if not (top <= row < bottom and left <= col < right)
                }
            cleared.append(
                render(tab['properties']['title'], top, bottom, left, right))
        return {'spreadsheetId': spreadsheetId, 'clearedRanges': cleared}


class FakeDrive:
    """The Drive v3 resource.
    """

    def __init__(self, fake: FakeGoogle) -> None:
        self.fake = fake

    def files(self) -> 'FakeFiles':
        """The files() resource.
        """
        return FakeFiles(self.fake)

    def permissions(self) -> 'FakePermissions':
        """The permissions() resource.
        """
        return FakePermissions(self.fake)


class FakeFiles:
    """files(): list, get, create, copy, update, delete, export.
    """

    def __init__(self, fake: FakeGoogle) -> None:
        self.fake = fake

    @lazy
    def list(
            self,
            q: str | None = None,
            pageSize: int = 100,
            pageToken: str | None = None,
            driveId: str | None = None) -> dict:
        """Files matching q, in creation order, one page at a time.

        pageToken is the start index as text. A q term outside the grammar
        raises ValueError. driveId keeps only files whose 'driveId' key a
        test set to it.
        """
        terms = split_top_level(q, 'and') if q else []
        matchers = [term_matcher(term) for term in terms]
        matching = [
            public(file) for file in self.fake.files.values()
            if all(match(file) for match in matchers)
            and (driveId is None or file.get('driveId') == driveId)
            ]
        start = int(pageToken or 0)
        reply: dict[str, Any] = {'files': matching[start:start + pageSize]}
        if start + pageSize < len(matching):
            reply['nextPageToken'] = str(start + pageSize)
        return reply

    @lazy
    def get(self, fileId: str) -> dict:
        """A copy of the file.
        """
        return public(self.fake.file(fileId))

    @lazy
    def create(self, body: dict, media_body: Any = None) -> dict:
        """Create a file.

        A spreadsheet body with media_body converts the upload: text/csv
        becomes tab 'Sheet1', any other type one empty tab. The source type
        is stored as 'importedFrom'.
        """
        name = body.get('name', 'Untitled')
        mime_type = body.get('mimeType', 'application/octet-stream')
        parents = body.get('parents')
        if mime_type != SHEET_MIME or media_body is None:
            return public(self.fake.new_file(name, mime_type, parents))
        source_type = media_body.mimetype()
        rows = []
        if source_type == 'text/csv':
            data = media_body.getbytes(0, media_body.size())
            rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
        tab = seeded_tab('Sheet1', 0, rows, parse=True)
        file = self.fake.new_file(name, mime_type, parents, [tab])
        file['importedFrom'] = source_type
        return public(file)

    @lazy
    def copy(self, fileId: str, body: dict) -> dict:
        """Copy a file and its tabs. Parents default to the source's.
        """
        source = self.fake.file(fileId)
        clone = self.fake.new_file(
            body.get('name', f"Copy of {source['name']}"),
            source['mimeType'],
            body.get('parents', source['parents']))
        if 'tabs' in source:
            clone['tabs'] = copy.deepcopy(source['tabs'])
            clone['nextSheetId'] = source['nextSheetId']
        return public(clone)

    @lazy
    def update(
            self,
            fileId: str,
            body: dict | None = None,
            addParents: str | None = None,
            removeParents: str | None = None) -> dict:
        """Rename, trash or move a file. Parent ids are comma-separated.
        """
        file = self.fake.file(fileId)
        body = body or {}
        for key in ('name', 'trashed'):
            if key in body:
                file[key] = body[key]
        removed = set((removeParents or '').split(','))
        file['parents'] = [
            parent for parent in file['parents'] if parent not in removed
            ]
        for parent in (addParents or '').split(','):
            if parent and parent not in file['parents']:
                file['parents'].append(parent)
        return public(file)

    @lazy
    def delete(self, fileId: str) -> str:
        """Remove the file for good.
        """
        self.fake.file(fileId)
        del self.fake.files[fileId]
        return ''

    @lazy
    def export(self, fileId: str, mimeType: str) -> bytes:
        """Bytes that start with a PDF stub or a ZIP-like stub, then the name.
        """
        name = self.fake.file(fileId)['name'].encode()
        prefix = b'%PDF-fake ' if mimeType == 'application/pdf' else b'PK-fake '
        return prefix + name


class FakePermissions:
    """permissions(): list, create, update, delete.
    """

    def __init__(self, fake: FakeGoogle) -> None:
        self.fake = fake

    def find(self, file_id: str, permission_id: str) -> tuple[dict, dict]:
        """(file, permission), or HttpError 404.
        """
        file = self.fake.file(file_id)
        for permission in file['permissions']:
            if permission['id'] == permission_id:
                return file, permission
        raise http_error(404, f'Permission not found: {permission_id}.')

    @lazy
    def list(self, fileId: str) -> dict:
        """The file's permissions.
        """
        permissions = self.fake.file(fileId)['permissions']
        return {'permissions': copy.deepcopy(permissions)}

    @lazy
    def create(self, fileId: str, body: dict) -> dict:
        """Grant a permission and return it with a new id.
        """
        permission = {
            'id': self.fake.new_id('perm'),
            'type': body['type'],
            'role': body['role'],
            }
        if 'emailAddress' in body:
            permission['emailAddress'] = body['emailAddress']
        self.fake.file(fileId)['permissions'].append(permission)
        return copy.deepcopy(permission)

    @lazy
    def update(self, fileId: str, permissionId: str, body: dict) -> dict:
        """Change a permission's role.
        """
        _, permission = self.find(fileId, permissionId)
        permission['role'] = body['role']
        return copy.deepcopy(permission)

    @lazy
    def delete(self, fileId: str, permissionId: str) -> str:
        """Revoke a permission.
        """
        file, permission = self.find(fileId, permissionId)
        file['permissions'].remove(permission)
        return ''
