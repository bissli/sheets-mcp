import pytest
from sheets_mcp import values
from sheets_mcp.errors import SheetsError
from sheets_mcp.values import RangeValues


def test_read_range_pages_cover_every_row_once(fake, clients, monkeypatch):
    """Verify paging returns every row exactly once, in order, with each
    page's range naming its own rows.

    Mutation: next_offset pointing at the last row served instead of the
    one after it, which repeats a row on every page.
    Oracle: the seeded rows; each row is 9 bytes as compact JSON plus a
    comma, so a 20-byte budget holds two rows.
    """
    seeded = [[f'r{number}', number] for number in range(1, 6)]
    book = fake.add_spreadsheet('Book', {'Data': seeded})
    monkeypatch.setattr(values, 'PAGE_BYTES', 20)
    pages = []
    offset = None
    while True:
        page = values.read_range(clients, book, 'Data!A1:B5', offset=offset)
        pages.append(page)
        offset = page['next_offset']
        if offset is None:
            break
    assert [page['range'] for page in pages] == [
        "'Data'!A1:B2", "'Data'!A3:B4", "'Data'!A5:B5"]
    assert [row for page in pages for row in page['values']] == seeded


def test_read_range_open_range_stops_at_last_data_row(fake, clients):
    """Verify an open range keeps empty rows between data and ends at the
    last row with data, though the grid runs to row 1000.

    Mutation: reading to the grid's rowCount, which pads the page with
    hundreds of empty rows.
    Oracle: hand-placed rows 1 and 5 on a 1000-row grid.
    """
    book = fake.add_spreadsheet('Book', {'Data': [['top'], [], [], [], ['bottom']]})
    page = values.read_range(clients, book, 'Data!A:A')
    assert page == {
        'range': "'Data'!A1:A5",
        'values': [['top'], [], [], [], ['bottom']],
        'next_offset': None,
        }


def test_read_range_whole_tab_offset_names_columns(fake, clients, monkeypatch):
    """Verify a whole-tab read resumed at an offset reads from that row.

    Mutation: sending 'Data!3:' (not A1) or restarting at row 1.
    Oracle: the third seeded row; each row is 6 bytes, so 12 holds two.
    """
    book = fake.add_spreadsheet('Book', {'Data': [['a'], ['b'], ['c']]})
    monkeypatch.setattr(values, 'PAGE_BYTES', 12)
    first = values.read_range(clients, book, 'Data')
    assert first['next_offset'] == 3
    second = values.read_range(clients, book, 'Data', offset=3)
    assert (second['values'], second['next_offset']) == ([['c']], None)


def test_read_range_refuses_offset_outside_range(fake, clients):
    """Verify an offset before or past the range is refused.

    Mutation: dropping the bounds check, which reads rows the caller did
    not ask for.
    Oracle: the range is rows 2 to 3.
    """
    book = fake.add_spreadsheet('Book', {'Data': [['a'], ['b'], ['c']]})
    for offset in (1, 4):
        with pytest.raises(SheetsError, match='outside'):
            values.read_range(clients, book, 'Data!A2:A3', offset=offset)


def test_write_ranges_block_from_single_cell(fake, clients):
    """Verify a block of values written at one cell fills down and right.

    Mutation: to_a1 sending 'A1:A1', which Google refuses for a 2x2 block.
    Oracle: the fake refuses values past a bounded range, as Google does.
    """
    book = fake.add_spreadsheet('Book', {'Data': []})
    values.write_ranges(
        clients, book, [RangeValues(range='Data!B2', values=[['a', 'b'], ['c', 'd']])])
    assert fake.cells(book, 'Data') == [[], ['', 'a', 'b'], ['', 'c', 'd']]


def test_write_ranges_parse_controls_number_and_formula_handling(fake, clients):
    """Verify parse=True types '12' as a number and parse=False keeps it as
    text, in one call per mode.

    Mutation: swapping USER_ENTERED and RAW.
    Oracle: the fake stores USER_ENTERED numeric text as a number, as
    Sheets does.
    """
    book = fake.add_spreadsheet('Book', {'Data': []})
    values.write_ranges(clients, book, [RangeValues(range='Data!A1', values=[['12']])])
    values.write_ranges(
        clients, book, [RangeValues(range='Data!B1', values=[['12']])], parse=False)
    assert fake.cells(book, 'Data') == [[12, '12']]


def test_write_ranges_refuses_url_formula_and_writes_nothing(fake, clients):
    """Verify a URL-fetching formula in any block stops the whole call
    before Google is reached, while parse=False stores it as plain text.

    Mutation: checking formulas after the first block is sent, or checking
    them with parse=False.
    Oracle: the cells stay empty after the refused call.
    """
    book = fake.add_spreadsheet('Book', {'Data': []})
    blocks = [
        RangeValues(range='Data!A1', values=[['safe']]),
        RangeValues(range='Data!B1', values=[['=IMPORTXML("https://example.com","//a")']]),
        ]
    with pytest.raises(SheetsError, match='IMPORTXML'):
        values.write_ranges(clients, book, blocks)
    assert fake.cells(book, 'Data') == []
    values.write_ranges(clients, book, blocks, parse=False)
    assert fake.cells(book, 'Data')[0][1].startswith('=IMPORTXML')


def test_append_rows_lands_below_last_data_row(fake, clients):
    """Verify appended rows start below the last row with data, in column A.

    Mutation: writing at the tab's first row, or at the grid's last row.
    Oracle: a two-row table, so the new row is row 3.
    """
    book = fake.add_spreadsheet('Book', {'Log': [['day', 'n'], ['mon', 1]]})
    answer = values.append_rows(clients, book, 'Log', [['tue', '2']])
    assert answer == {'updated_range': "'Log'!A3:B3"}
    assert fake.cells(book, 'Log') == [['day', 'n'], ['mon', 1], ['tue', 2]]


def test_append_rows_refuses_url_formula(fake, clients):
    """Verify append_rows applies the formula check when parsing.

    Mutation: append_rows skipping refuse_url_functions.
    Oracle: IMAGE is one of the refused functions.
    """
    book = fake.add_spreadsheet('Book', {'Log': [['day']]})
    with pytest.raises(SheetsError, match='IMAGE'):
        values.append_rows(clients, book, 'Log', [['=IMAGE("https://example.com/x")']])


def test_clear_ranges_clears_only_the_range(fake, clients):
    """Verify clear_ranges empties its range and leaves the rest.

    Mutation: clearing the whole tab, or the range shifted by one.
    Oracle: a 3x2 grid with the middle row cleared.
    """
    book = fake.add_spreadsheet('Book', {'Data': [['a', 'b'], ['c', 'd'], ['e', 'f']]})
    values.clear_ranges(clients, book, ['Data!A2:B2'])
    assert fake.cells(book, 'Data') == [['a', 'b'], [], ['e', 'f']]
