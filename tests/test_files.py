import pytest
from sheets_mcp import files
from sheets_mcp.errors import SheetsError


def test_list_files_filters_kind_name_folder_and_trash(fake, clients):
    """Verify list_files keeps only matching, untrashed files of the kind
    asked for, and that a quote in the name search is escaped.

    Mutation: dropping 'trashed = false', the kind term, or the quote
    escape, which the fake parser rejects. Drive matches the start of a
    word, so 'udget' finds nothing.
    Oracle: hand-picked matches among seeded files.
    """
    reports = fake.add_folder('Reports')
    kept = fake.add_spreadsheet("Bob's budget", parents=[reports])
    fake.add_spreadsheet("Bob's budget old")
    trashed = fake.add_spreadsheet("Bob's budget", parents=[reports])
    fake.files[trashed]['trashed'] = True
    fake.add_folder("Bob's budget folder", parents=[reports])
    answer = files.list_files(
        clients, name_contains="bob's", folder_id=reports, kind='spreadsheets')
    assert [file['id'] for file in answer['files']] == [kept]
    assert files.list_files(clients, name_contains='udget')['files'] == []
    assert answer['files'][0]['kind'] == 'spreadsheet'


def test_create_spreadsheet_in_folder_with_tabs(fake, clients):
    """Verify a spreadsheet created in a folder sits only in that folder,
    with the tabs asked for.

    Mutation: adding the folder without removing My Drive, which leaves
    the file in two places.
    Oracle: the fake's parents and tab titles.
    """
    reports = fake.add_folder('Reports')
    created = files.create_spreadsheet(
        clients, 'Budget', folder_id=reports, tabs=['Inputs', 'Summary'])
    stored = fake.files[created['spreadsheet_id']]
    assert stored['parents'] == [reports]
    assert [tab['properties']['title'] for tab in stored['tabs']] == [
        'Inputs', 'Summary']


def test_copy_spreadsheet_keeps_cells(fake, clients):
    """Verify copy_spreadsheet makes a new file with the same cells.

    Mutation: returning the source id as the copy's id.
    Oracle: seeded cells.
    """
    book = fake.add_spreadsheet('Budget', {'Data': [['a', 1]]})
    copied = files.copy_spreadsheet(clients, book, 'Budget 2027')
    assert copied['spreadsheet_id'] != book
    assert fake.cells(copied['spreadsheet_id'], 'Data') == [['a', 1]]


def test_update_file_renames_and_moves(fake, clients):
    """Verify update_file renames and moves out of every old folder.

    Mutation: removeParents left empty, so the file stays in its old
    folder too.
    Oracle: the fake's name and parents.
    """
    old = fake.add_folder('Old')
    new = fake.add_folder('New')
    book = fake.add_spreadsheet('Budget', parents=[old])
    answer = files.update_file(clients, book, title='Budget final', folder_id=new)
    assert (answer['name'], answer['parents']) == ('Budget final', [new])
    assert fake.files[book]['parents'] == [new]


def test_delete_file_trashes_unless_permanent(fake, clients):
    """Verify delete_file trashes by default and deletes only when asked.

    Mutation: the default deleting for good, which cannot be undone.
    Oracle: the fake's trashed flag and file table.
    """
    first = fake.add_spreadsheet('One')
    second = fake.add_spreadsheet('Two')
    assert files.delete_file(clients, first)['outcome'] == 'trashed'
    assert fake.files[first]['trashed'] is True
    assert files.delete_file(clients, second, permanent=True)['outcome'] == 'deleted'
    assert second not in fake.files


def test_share_file_grants_changes_and_removes(fake, clients):
    """Verify share_file adds a grant, changes it when the email matches in
    another case, and removes it with role 'none'.

    Mutation: a case-sensitive email match, which adds a second grant
    instead of changing the first.
    Oracle: the permissions listed after each call.
    """
    book = fake.add_spreadsheet('Budget')
    files.share_file(clients, book, 'reader', email='ana@example.com')
    files.share_file(clients, book, 'writer', email='Ana@Example.com')
    granted = [
        permission for permission in files.list_permissions(clients, book)['permissions']
        if permission.get('email') == 'ana@example.com'
        ]
    assert [permission['role'] for permission in granted] == ['writer']
    files.share_file(clients, book, 'none', email='ana@example.com')
    emails = [
        permission.get('email')
        for permission in files.list_permissions(clients, book)['permissions']
        ]
    assert 'ana@example.com' not in emails


def test_share_file_anyone_with_link(fake, clients):
    """Verify anyone_with_link grants type 'anyone' access.

    Mutation: sending type 'user' with no email.
    Oracle: the permission list.
    """
    book = fake.add_spreadsheet('Budget')
    files.share_file(clients, book, 'reader', anyone_with_link=True)
    assert {'type': 'anyone', 'role': 'reader'} in files.list_permissions(
        clients, book)['permissions']


@pytest.mark.parametrize('arguments', [
    {}, {'email': 'ana@example.com', 'anyone_with_link': True}])
def test_share_file_needs_one_grantee(fake, clients, arguments):
    """Verify share_file refuses both or neither of email and link access.

    Mutation: dropping the check, which shares with anyone when the email
    is forgotten.
    Oracle: the argument sets.
    """
    book = fake.add_spreadsheet('Budget')
    with pytest.raises(SheetsError):
        files.share_file(clients, book, 'reader', **arguments)


def test_import_csv_becomes_spreadsheet(fake, clients, tmp_path):
    """Verify a csv uploads as a converted spreadsheet named after the file.

    Mutation: uploading without the spreadsheet mimeType, which stores a
    plain csv file in Drive.
    Oracle: the fake converts only uploads that ask for a spreadsheet.
    """
    source = tmp_path / 'prices.csv'
    source.write_text('name,price\nacme,12\n')
    imported = files.import_file(clients, str(source))
    assert imported['title'] == 'prices'
    assert fake.cells(imported['spreadsheet_id'], 'Sheet1') == [
        ['name', 'price'], ['acme', 12]]


def test_import_refuses_unknown_extension(clients, tmp_path):
    """Verify import_file refuses a file type Sheets cannot convert.

    Mutation: falling back to a default mime type.
    Oracle: .txt is not among the five types.
    """
    source = tmp_path / 'notes.txt'
    source.write_text('x')
    with pytest.raises(SheetsError, match="'.txt'"):
        files.import_file(clients, str(source))


def test_export_refuses_overwrite_then_writes(fake, clients, tmp_path):
    """Verify export refuses an existing path unless overwrite is set.

    Mutation: dropping the exists check, which replaces a local file.
    Oracle: the file content before and after.
    """
    book = fake.add_spreadsheet('Budget')
    target = tmp_path / 'budget.xlsx'
    target.write_bytes(b'mine')
    with pytest.raises(SheetsError, match='overwrite'):
        files.export_spreadsheet(clients, book, str(target), 'xlsx')
    assert target.read_bytes() == b'mine'
    answer = files.export_spreadsheet(clients, book, str(target), 'xlsx', overwrite=True)
    assert target.read_bytes().startswith(b'PK')
    assert answer['bytes'] == target.stat().st_size


def test_export_csv_writes_one_tab(fake, clients, tmp_path):
    """Verify csv export writes the named tab's rows, quoting as csv does.

    Mutation: tsv delimiter for csv, or exporting the first tab instead
    of the named one.
    Oracle: hand-written csv text.
    """
    book = fake.add_spreadsheet(
        'Budget', {'First': [['x']], 'Data': [['name', 'note'], ['acme', 'a,b']]})
    target = tmp_path / 'data.csv'
    files.export_spreadsheet(clients, book, str(target), 'csv', tab='Data')
    assert target.read_text() == 'name,note\nacme,"a,b"\n'
