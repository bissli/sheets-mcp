import pytest
from fake_google import FakeGoogle
from googleapiclient.errors import HttpError
from sheets_mcp.google import SHEET_MIME


def send(fake: FakeGoogle, spreadsheet_id: str, *requests: dict) -> dict:
    """BatchUpdate reply for the requests.
    """
    return fake.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={'requests': list(requests)}).execute()


def row_span(sheet_id: int, start: int, end: int) -> dict:
    """A DimensionRange over rows start to end, end exclusive.
    """
    return {
        'sheetId': sheet_id,
        'dimension': 'ROWS',
        'startIndex': start,
        'endIndex': end,
        }


def row_count(fake: FakeGoogle, spreadsheet_id: str) -> int:
    """RowCount of the first tab.
    """
    reply = fake.sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return reply['sheets'][0]['properties']['gridProperties']['rowCount']


def test_insert_dimension_shifts_cells_down():
    """Verify insertDimension moves later rows down and grows rowCount.

    Mutation: shifting rows at or before startIndex, or leaving rowCount.
    Oracle: hand-computed rows for an insert of two rows at index 1.
    """
    fake = FakeGoogle()
    book = fake.add_spreadsheet('Book', {'Data': [['a'], ['b'], ['c']]})
    send(fake, book, {'insertDimension': {'range': row_span(0, 1, 3)}})
    assert fake.cells(book, 'Data') == [['a'], [], [], ['b'], ['c']]
    assert row_count(fake, book) == 1002


def test_delete_dimension_shifts_cells_up():
    """Verify deleteDimension drops the span, shifts rows up, shrinks rowCount.

    Mutation: shifting by the wrong size, or keeping the deleted rows.
    Oracle: hand-computed rows for a delete of rows 1 and 2 of four.
    """
    fake = FakeGoogle()
    book = fake.add_spreadsheet('Book', {'Data': [['a'], ['b'], ['c'], ['d']]})
    send(fake, book, {'deleteDimension': {'range': row_span(0, 1, 3)}})
    assert fake.cells(book, 'Data') == [['a'], ['d']]
    assert row_count(fake, book) == 998


def test_values_get_trims_trailing_empties_keeps_interior():
    """Verify values.get keeps interior '' and drops trailing empties.

    Mutation: trimming interior empty cells, or keeping trailing ones.
    Oracle: hand-computed rows; an empty tab has no 'values' key.
    """
    fake = FakeGoogle()
    book = fake.add_spreadsheet(
        'Book', {'Data': [['a', '', 'c', ''], [], ['', 'x']], 'Empty': []})
    values = fake.sheets.spreadsheets().values()
    reply = values.get(spreadsheetId=book, range='Data!A1:D5').execute()
    assert reply['values'] == [['a', '', 'c'], [], ['', 'x']]
    assert reply['range'] == "'Data'!A1:D5"
    assert 'values' not in values.get(spreadsheetId=book, range='Empty').execute()


def test_append_lands_below_last_data_row():
    """Verify append starts below the last row holding a value.

    Mutation: appending after the first empty row, or at the grid end.
    Oracle: hand-computed row 5 for data in rows 1 and 4.
    """
    fake = FakeGoogle()
    book = fake.add_spreadsheet('Book', {'Data': [['a'], [], [], ['z']]})
    reply = fake.sheets.spreadsheets().values().append(
        spreadsheetId=book,
        range="'Data'",
        valueInputOption='RAW',
        body={'values': [['new', 1]]}).execute()
    assert fake.cells(book, 'Data')[4] == ['new', 1]
    assert reply['updates']['updatedRange'] == "'Data'!A5:B5"


def test_list_query_filters_by_parent_and_trashed():
    """Verify the q parser applies parent, trashed, mimeType and name terms.

    Mutation: ignoring a term, or matching name case-sensitively.
    Oracle: hand-built folder holding one live and one trashed spreadsheet.
    """
    fake = FakeGoogle()
    folder = fake.add_folder('Reports')
    live = fake.add_spreadsheet('Q3 Budget', parents=[folder])
    trashed = fake.add_spreadsheet('Q2 Budget', parents=[folder])
    fake.add_spreadsheet('Elsewhere')
    fake.drive.files().update(fileId=trashed, body={'trashed': True}).execute()
    query = (
        f"'{folder}' in parents and trashed = false and "
        f"(mimeType = '{SHEET_MIME}' or mimeType = 'text/csv') "
        "and name contains 'BUDGET'")
    reply = fake.drive.files().list(q=query, pageSize=10).execute()
    assert [file['id'] for file in reply['files']] == [live]


def test_list_query_unknown_syntax_raises_value_error():
    """Verify a q term outside the grammar raises ValueError.

    Mutation: ignoring an unknown term, which would hide a misread query.
    Oracle: fullText is outside the supported grammar.
    """
    fake = FakeGoogle()
    with pytest.raises(ValueError):
        fake.drive.files().list(q="fullText contains 'x'").execute()


def test_missing_file_raises_http_error_with_status_and_reason():
    """Verify a missing file raises HttpError with status_code and reason.

    Mutation: raising KeyError, or building the error without a reason.
    Oracle: status 404 and the message text.
    """
    fake = FakeGoogle()
    with pytest.raises(HttpError) as raised:
        fake.drive.files().get(fileId='nope').execute()
    assert raised.value.status_code == 404
    assert raised.value.reason == 'File not found: nope.'
