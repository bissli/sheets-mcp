import pytest
from sheets_mcp import layout
from sheets_mcp.layout import NumberFormat


@pytest.fixture
def book(fake):
    return fake.add_spreadsheet('Book', {'Data': [['a', 'b'], ['c', 'd'], ['e', 'f']]})


def test_insert_rows_counts_from_one(fake, clients, book):
    """Verify inserting at row 2 puts the empty rows below row 1, and
    copies the format of the row above.

    Mutation: sending start unchanged as the 0-based index, which inserts
    below row 2.
    Oracle: hand-shifted rows; row 1 has a row above it, so inherit.
    """
    layout.edit_rows_columns(clients, book, 'Data', 'rows', 'insert', start=2, count=2)
    assert fake.cells(book, 'Data') == [['a', 'b'], [], [], ['c', 'd'], ['e', 'f']]
    assert fake.requests[-1]['insertDimension']['inheritFromBefore'] is True


def test_move_row_to_top(fake, clients, book):
    """Verify destination 1 moves the block to the top.

    Mutation: destinationIndex off by one, which leaves the order as is.
    Oracle: row 3 moved in front of row 1.
    """
    layout.edit_rows_columns(
        clients, book, 'Data', 'rows', 'move', start=3, destination=1)
    assert fake.cells(book, 'Data') == [['e', 'f'], ['a', 'b'], ['c', 'd']]


@pytest.mark.parametrize(('action', 'arguments'), [
    ('move', {}), ('resize', {}), ('move', {'destination': 0})])
def test_move_and_resize_need_their_argument(clients, book, action, arguments):
    """Verify 'move' needs a destination of 1 or more and 'resize' a size.

    Mutation: dropping either check, which sends Google a None or -1
    index.
    Oracle: the API needs both values.
    """
    with pytest.raises(ValueError):
        layout.edit_rows_columns(
            clients, book, 'Data', 'rows', action, start=1, **arguments)


def test_hide_sends_hidden_flag_only(fake, clients, book):
    """Verify 'hide' sets hiddenByUser and masks only that field.

    Mutation: 'hide' and 'show' sending the same flag.
    Oracle: the recorded request.
    """
    layout.edit_rows_columns(clients, book, 'Data', 'columns', 'hide', start=2)
    update = fake.requests[-1]['updateDimensionProperties']
    assert update['properties'] == {'hiddenByUser': True}
    assert update['fields'] == 'hiddenByUser'
    assert update['range'] == {
        'sheetId': 0, 'dimension': 'COLUMNS', 'startIndex': 1, 'endIndex': 2}


def test_delete_columns_shifts_left(fake, clients, book):
    """Verify deleting column 1 shifts column B into A.

    Mutation: deleting column 2 instead of 1.
    Oracle: hand-shifted rows.
    """
    layout.delete_rows_columns(clients, book, 'Data', 'columns', start=1)
    assert fake.cells(book, 'Data') == [['b'], ['d'], ['f']]


def test_format_range_masks_only_given_options(fake, clients, book):
    """Verify format_range's field mask names exactly the options given, so
    formats it was not asked to change are kept.

    Mutation: masking all of userEnteredFormat, which wipes every other
    format in the range.
    Oracle: the three options passed.
    """
    answer = layout.format_range(
        clients, book, 'Data!A1:B1', bold=True,
        number_format=NumberFormat(pattern='0.0%', type='PERCENT'),
        background_color='#FF0000')
    repeat = fake.requests[-1]['repeatCell']
    assert set(repeat['fields'].split(',')) == {
        'userEnteredFormat.textFormat.bold',
        'userEnteredFormat.numberFormat',
        'userEnteredFormat.backgroundColorStyle',
        }
    assert repeat['cell']['userEnteredFormat']['backgroundColorStyle'] == {
        'rgbColor': {'red': 1.0, 'green': 0.0, 'blue': 0.0}}
    assert repeat['range'] == {
        'sheetId': 0, 'startRowIndex': 0, 'endRowIndex': 1,
        'startColumnIndex': 0, 'endColumnIndex': 2}
    assert answer['changed'] == ['number_format', 'bold', 'background_color']


def test_format_range_borders_and_unmerge(fake, clients, book):
    """Verify 'outer' borders set the four edges only, and merge 'none'
    sends an unmerge.

    Mutation: 'outer' including the inner lines, or 'none' sending a merge.
    Oracle: the recorded requests.
    """
    layout.format_range(clients, book, 'Data!A1:B3', borders='outer', merge='none')
    borders, unmerge = fake.requests[-2:]
    assert set(borders['updateBorders']) == {'range', 'top', 'bottom', 'left', 'right'}
    assert 'unmergeCells' in unmerge


def test_format_range_needs_an_option(fake, clients, book):
    """Verify format_range with no option is refused before calling Google.

    Mutation: sending an empty batchUpdate.
    Oracle: no request is recorded.
    """
    with pytest.raises(ValueError):
        layout.format_range(clients, book, 'Data!A1')
    assert fake.requests == []
