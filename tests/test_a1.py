import pytest
from sheets_mcp import a1
from sheets_mcp.errors import SheetsError


@pytest.mark.parametrize(('text', 'expected'), [
    ('Data!A1:F10', a1.CellRange('Data', 1, 10, 1, 6)),
    ('Data!B3', a1.CellRange('Data', 3, 3, 2, 2)),
    ('Data!A:F', a1.CellRange('Data', None, None, 1, 6)),
    ('Data!A2:F', a1.CellRange('Data', 2, None, 1, 6)),
    ('Data!2:5', a1.CellRange('Data', 2, 5, None, None)),
    ('Data', a1.CellRange('Data')),
    ("'Q3 Model'!b2:aa40", a1.CellRange('Q3 Model', 2, 40, 2, 27)),
    ("'Bob''s'!A1", a1.CellRange("Bob's", 1, 1, 1, 1)),
    ('Data!$A$1:$B2', a1.CellRange('Data', 1, 2, 1, 2)),
    ])
def test_parse_range_forms(text, expected):
    """Verify each A1 form parses to its bounds, counted from 1.

    Mutation: column letters read as base 27, or 'B3' read as open to the
    grid edge, or a doubled quote left doubled in the tab title.
    Oracle: hand-computed bounds; AA is column 27.
    """
    assert a1.parse_range(text) == expected


@pytest.mark.parametrize('text', [
    'A1:B2', 'Data!A0', 'Data!C1:A1', 'Data!A5:B2', 'Data!A1:5', 'Data!1:F', 'Data!:B'])
def test_parse_range_refuses(text):
    """Verify a range with no tab, row 0, mixed forms, or backward bounds is
    refused.

    Mutation: dropping the backward or mixed-form check, or accepting row 0.
    Oracle: Sheets numbers rows from 1 and a range runs forward.
    """
    with pytest.raises(SheetsError):
        a1.parse_range(text)


@pytest.mark.parametrize('text', [
    'Data!A1:F10', 'Data!A:F', 'Data!A2:F', 'Data!2:5', "'Q3 Model'!B2:F40"])
def test_to_a1_round_trip(text):
    """Verify to_a1 writes back a range that parses to the same bounds.

    Mutation: to_a1 filling an open end with 1, or leaving the tab
    unquoted.
    Oracle: parse_range of the original text.
    """
    cell_range = a1.parse_range(text)
    assert a1.parse_range(a1.to_a1(cell_range)) == cell_range
    assert a1.to_a1(cell_range).startswith("'")


def test_column_letters_inverse():
    """Verify column_letters and column_number invert each other at the
    letter-count boundaries.

    Mutation: off-by-one in the divmod, which breaks Z/AA and ZZ/AAA.
    Oracle: Z is 26, AA 27, ZZ 702, AAA 703.
    """
    assert [a1.column_letters(number) for number in (26, 27, 702, 703)] == [
        'Z', 'AA', 'ZZ', 'AAA']
    assert [a1.column_number(letters) for letters in ('Z', 'AA', 'ZZ', 'AAA')] == [
        26, 27, 702, 703]


def test_grid_range_is_zero_based_end_exclusive():
    """Verify grid_range converts to the API's 0-based, end-exclusive form
    and leaves open ends out.

    Mutation: subtracting 1 from an end index, or emitting an open end as 0.
    Oracle: Data!B2:C3 is rows 1..3 and columns 1..3 in API indexes.
    """
    assert a1.grid_range(a1.parse_range('Data!B2:C3'), 7) == {
        'sheetId': 7,
        'startRowIndex': 1,
        'endRowIndex': 3,
        'startColumnIndex': 1,
        'endColumnIndex': 3,
        }
    assert a1.grid_range(a1.parse_range('Data!A:B'), 7) == {
        'sheetId': 7, 'startColumnIndex': 0, 'endColumnIndex': 2}
