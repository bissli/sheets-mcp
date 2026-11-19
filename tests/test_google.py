from types import SimpleNamespace

from sheets_mcp import google, tabs
from sheets_mcp.google import Clients


def test_batch_update_replies_per_request_in_order(fake, clients):
    """Verify batch_update answers one reply per request, in order, and a
    later request can name the tab an earlier one adds.

    Mutation: returning the whole reply in place of its replies, or
    dropping the empty reply of a request kind with no reply.
    Oracle: a tab hand-added with sheetId 7 and then frozen.
    """
    book = fake.add_spreadsheet('Book', {'Data': [['a']]})
    freeze, _ = tabs.tab_update_request({'sheetId': 7, 'index': 1}, frozen_rows=1)
    replies = google.batch_update(clients, book, [
        tabs.add_tab_request('New', sheet_id=7),
        {'repeatCell': {}},
        freeze,
        ])
    assert len(replies) == 3
    assert replies[0]['addSheet']['properties']['sheetId'] == 7
    assert replies[1] == {}
    new_tab = google.tab_properties(clients, book, 'New')
    assert new_tab['gridProperties']['frozenRowCount'] == 1


def test_get_spreadsheet_sends_the_field_mask():
    """Verify get_spreadsheet passes the caller's field mask to Google.

    Mutation: dropping fields, which reads every property of every tab.
    Oracle: a stub that records the get arguments.
    """
    calls = []

    def get(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(execute=lambda: {'sheets': []})

    sheets = SimpleNamespace(spreadsheets=lambda: SimpleNamespace(get=get))
    answer = google.get_spreadsheet(Clients(None, sheets), 'book', 'sheets.properties')
    assert answer == {'sheets': []}
    assert calls == [{'spreadsheetId': 'book', 'fields': 'sheets.properties'}]
