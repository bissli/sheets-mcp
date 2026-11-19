"""A1 range text: parsing, building, and conversion to grid ranges.
"""
import re
from dataclasses import dataclass

RANGE_PATTERN = re.compile(
    r"""
    ^(?P<tab>'(?:[^']|'')+'|[^'!:]+)
    (?:!
      \$?(?P<first_column>[A-Z]+)?\$?(?P<first_row>[1-9][0-9]*)?
      (?::\$?(?P<last_column>[A-Z]+)?\$?(?P<last_row>[1-9][0-9]*)?)?
    )?$
    """,
    re.IGNORECASE | re.VERBOSE)


@dataclass(frozen=True)
class CellRange:
    """A block of cells on one tab.

    Rows and columns count from 1 and both ends are inclusive. None on an
    end means the range runs to that edge of the grid: 'Data!A:F' has no
    rows, and 'Data' has no rows or columns.

    Attributes
    ----------
    tab : str
        Tab title, unquoted.
    first_row, last_row : int or None
        Row bounds.
    first_column, last_column : int or None
        Column bounds; column D is 4.
    """

    tab: str
    first_row: int | None = None
    last_row: int | None = None
    first_column: int | None = None
    last_column: int | None = None


def column_number(letters: str) -> int:
    """Column number of letters, counted from 1: 'A' is 1, 'AA' is 27.
    """
    number = 0
    for letter in letters.upper():
        number = number * 26 + ord(letter) - ord('A') + 1
    return number


def column_letters(number: int) -> str:
    """Letters of column number, counted from 1: 1 is 'A', 27 is 'AA'.
    """
    letters = ''
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord('A') + remainder) + letters
    return letters


def quote_tab(tab: str) -> str:
    """Tab title quoted for A1 text, with each ' doubled.
    """
    return "'" + tab.replace("'", "''") + "'"


def parse_range(text: str) -> CellRange:
    """CellRange of A1 text that names its tab.

    Parameters
    ----------
    text : str
        'Tab!A1:F10', 'Tab!B3', 'Tab!A:F', 'Tab!A2:F', 'Tab!2:5' or 'Tab'.
        A tab title with spaces or punctuation is quoted: "'Q3 Model'!B2".
        A '$' before a column or row is dropped, so 'Tab!$A$1' is
        'Tab!A1'. A '$' in the tab title stays.

    Returns
    -------
    CellRange

    Raises
    ------
    ValueError
        The text does not parse, names no tab or row 0, mixes a column end
        with a row-only end ('Tab!A1:5'), or runs backward.
    """
    match = RANGE_PATTERN.match(text.strip())
    if match is None:
        raise ValueError(
            f'{text!r} is not an A1 range with a tab, such as '
            "'Data!A1:F10' or \"'Q3 Model'!B2:F40\"")
    tab = match['tab']
    if tab.startswith("'"):
        tab = tab[1:-1].replace("''", "'")
    first_column = match['first_column'] and column_number(match['first_column'])
    first_row = match['first_row'] and int(match['first_row'])
    single_cell = match['last_column'] is None and match['last_row'] is None
    if single_cell:
        last_column, last_row = first_column, first_row
    else:
        last_column = match['last_column'] and column_number(match['last_column'])
        last_row = match['last_row'] and int(match['last_row'])
    if bool(first_column) != bool(last_column) or (last_row and not first_row):
        raise ValueError(
            f'{text!r} mixes cell, column and row forms; write it as '
            "'Tab!A1:F10', 'Tab!A:F', 'Tab!A2:F' or 'Tab!2:5'")
    if (first_column and first_column > last_column
        or first_row and last_row and first_row > last_row):
        raise ValueError(f'{text!r} runs backward')
    return CellRange(
        tab=tab,
        first_row=first_row or None,
        last_row=last_row or None,
        first_column=first_column or None,
        last_column=last_column or None)


def to_a1(cell_range: CellRange) -> str:
    """A1 text of cell_range, with the tab quoted.

    Parameters
    ----------
    cell_range : CellRange
        An open end becomes an open A1 end: no rows gives 'Tab!A:F', and no
        rows or columns gives 'Tab'. A single cell gives 'Tab!B3', which a
        write may fill past.

    Returns
    -------
    str
    """
    tab = quote_tab(cell_range.tab)
    if (cell_range.first_row and cell_range.first_column
        and cell_range.first_row == cell_range.last_row
        and cell_range.first_column == cell_range.last_column):
        return f'{tab}!{column_letters(cell_range.first_column)}{cell_range.first_row}'
    no_columns = cell_range.first_column is None and cell_range.last_column is None
    no_rows = cell_range.first_row is None and cell_range.last_row is None
    if no_columns and no_rows:
        return tab

    def corner(column: int | None, row: int | None) -> str:
        return (column_letters(column) if column else '') + (str(row) if row else '')

    first = corner(cell_range.first_column, cell_range.first_row)
    last = corner(cell_range.last_column, cell_range.last_row)
    return f'{tab}!{first}:{last}'


def grid_range(cell_range: CellRange, sheet_id: int) -> dict:
    """The Sheets API GridRange of cell_range: 0-based, end exclusive.

    An open end leaves its key out, which the API reads as the grid edge.
    """
    bounds = {'sheetId': sheet_id}
    if cell_range.first_row:
        bounds['startRowIndex'] = cell_range.first_row - 1
    if cell_range.last_row:
        bounds['endRowIndex'] = cell_range.last_row
    if cell_range.first_column:
        bounds['startColumnIndex'] = cell_range.first_column - 1
    if cell_range.last_column:
        bounds['endColumnIndex'] = cell_range.last_column
    return bounds
