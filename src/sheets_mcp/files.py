"""Tools for Drive files: find, create, copy, rename, move, delete, share,
import and export.
"""
import csv
import io
from pathlib import Path
from typing import Literal

from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from sheets_mcp import a1
from sheets_mcp.google import FOLDER_MIME, SHEET_MIME, Clients

FILE_FIELDS = 'id,name,mimeType,modifiedTime,webViewLink,parents'
PAGE_SIZE = 100
SHORTCUT_MIME = 'application/vnd.google-apps.shortcut'
KIND_BY_MIME = {SHEET_MIME: 'spreadsheet', FOLDER_MIME: 'folder'}
IMPORT_MIMES = {
    '.csv': 'text/csv',
    '.tsv': 'text/tab-separated-values',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls': 'application/vnd.ms-excel',
    '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
    }
KIND_BY_MIME.update({mime: ext[1:] for ext, mime in IMPORT_MIMES.items()})
EXPORT_MIMES = {
    'xlsx': IMPORT_MIMES['.xlsx'],
    'ods': IMPORT_MIMES['.ods'],
    'pdf': 'application/pdf',
    }
DRIVE_FLAGS = {'supportsAllDrives': True}


def all_permissions(clients: Clients, file_id: str) -> list[dict]:
    """Every permission on a file, across pages: a shared drive returns at
    most 100 a page.
    """
    permissions = []
    page_token = None
    while True:
        reply = clients.drive.permissions().list(
            fileId=file_id,
            fields='nextPageToken,permissions(id,type,role,emailAddress,domain)',
            pageToken=page_token,
            **DRIVE_FLAGS).execute()
        permissions += reply.get('permissions', [])
        page_token = reply.get('nextPageToken')
        if page_token is None:
            return permissions


def file_summary(file: dict) -> dict:
    """The fields of a Drive file a caller acts on.
    """
    return {
        'id': file['id'],
        'name': file['name'],
        'kind': KIND_BY_MIME.get(file['mimeType'], file['mimeType']),
        'modified': file.get('modifiedTime'),
        'url': file.get('webViewLink'),
        'parents': file.get('parents', []),
        }


def quote_query(text: str) -> str:
    """Text as a Drive query string literal.
    """
    return "'" + text.replace('\\', '\\\\').replace("'", "\\'") + "'"


def get_file(clients: Clients, file_id: str, fields: str = FILE_FIELDS) -> dict:
    """A Drive file's metadata, or its target's when file_id is a shortcut.

    Parameters
    ----------
    clients : Clients
        Google clients.
    file_id : str
        File, folder or shortcut id.
    fields : str, default FILE_FIELDS
        Drive v3 field mask of the file. mimeType and shortcutDetails are
        always added, so the answer may hold them beyond the mask.

    Returns
    -------
    dict
        The masked fields of the file, or of the shortcut's target.

    Raises
    ------
    HttpError
        404 when the account cannot open the file or the target.
    """
    mask = f'{fields},mimeType,shortcutDetails'
    file = clients.drive.files().get(
        fileId=file_id, fields=mask, **DRIVE_FLAGS).execute()
    if file['mimeType'] == SHORTCUT_MIME:
        file = clients.drive.files().get(
            fileId=file['shortcutDetails']['targetId'], fields=mask,
            **DRIVE_FLAGS).execute()
    return file


def drive_files(
        clients: Clients,
        drive_id: str,
        query: str,
        fields: str,
        limit: int | None = None) -> list[dict]:
    """Every file of one shared drive that matches a Drive search query.

    Parameters
    ----------
    clients : Clients
        Google clients.
    drive_id : str
        Shared drive id.
    query : str
        Drive v3 q string, such as "trashed = false". Untrashed is not
        implied.
    fields : str
        Field mask of each file, placed inside files(...).
    limit : int, optional
        Stop reading pages once more than limit files are held, so the
        answer holds more than limit files and may miss some matches. None
        reads every page.

    Returns
    -------
    list of dict
        The masked fields of each match, in no set order.
    """
    found = []
    page_token = None
    while True:
        reply = clients.drive.files().list(
            corpora='drive',
            driveId=drive_id,
            includeItemsFromAllDrives=True,
            q=query,
            fields=f'nextPageToken,files({fields})',
            pageSize=1000,
            pageToken=page_token,
            **DRIVE_FLAGS).execute()
        found += reply.get('files', [])
        page_token = reply.get('nextPageToken')
        if not page_token or (limit is not None and len(found) > limit):
            return found


def move_to_folder(clients: Clients, file_id: str, folder_id: str) -> dict:
    """Move a Drive file into folder_id, out of every folder it was in.
    Returns the moved file.
    """
    current = clients.drive.files().get(
        fileId=file_id, fields='parents', **DRIVE_FLAGS).execute()
    return clients.drive.files().update(
        fileId=file_id,
        addParents=folder_id,
        removeParents=','.join(current.get('parents', [])),
        fields=FILE_FIELDS,
        **DRIVE_FLAGS).execute()


def list_files(
        clients: Clients,
        name_contains: str | None = None,
        folder_id: str | None = None,
        kind: Literal['spreadsheets', 'folders', 'all'] = 'all',
        page_token: str | None = None) -> dict:
    """Find spreadsheets and folders the account can open, newest first.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    name_contains : str, optional
        Keep files whose name, or a word in it, starts with this text,
        ignoring case: 'budg' finds 'Q3 budget' but 'udget' does not.
    folder_id : str, optional
        Keep files directly inside this folder.
    kind : {'spreadsheets', 'folders', 'all'}, default 'all'
        'all' also finds csv, tsv, xlsx, xls and ods files, whose kind is
        their extension. Only convert_file opens one of those.
    page_token : str, optional
        next_page_token from the previous page. Omit it for the first.

    Returns
    -------
    dict
        'files' lists each file's 'id', 'name', 'kind', 'modified', 'url'
        and 'parents' (folder ids). 'next_page_token' is set when more
        files match. 'incomplete' is True when Google searched only some
        drives, so a match may be missing.

    Examples
    --------
    list_files(name_contains='budget', kind='spreadsheets')
    -> {'files': [{'id': '1AbC', 'name': 'Budget 2026',
                   'kind': 'spreadsheet', 'modified': '2026-11-02T14:03:11Z',
                   'url': 'https://docs.google.com/...', 'parents': ['0Fld']}],
        'next_page_token': None}
    """
    mimes = {
        'spreadsheets': [SHEET_MIME],
        'folders': [FOLDER_MIME],
        'all': [SHEET_MIME, FOLDER_MIME, *IMPORT_MIMES.values()],
        }[kind]
    mime_terms = ' or '.join(f'mimeType = {quote_query(mime)}' for mime in mimes)
    terms = ['trashed = false', f'({mime_terms})']
    if name_contains:
        terms.append(f'name contains {quote_query(name_contains)}')
    if folder_id:
        terms.append(f'{quote_query(folder_id)} in parents')
    reply = clients.drive.files().list(
        q=' and '.join(terms),
        fields=f'nextPageToken,incompleteSearch,files({FILE_FIELDS})',
        orderBy='modifiedTime desc',
        pageSize=PAGE_SIZE,
        pageToken=page_token,
        corpora='allDrives',
        includeItemsFromAllDrives=True,
        **DRIVE_FLAGS).execute()
    return {
        'files': [file_summary(file) for file in reply.get('files', [])],
        'next_page_token': reply.get('nextPageToken'),
        'incomplete': reply.get('incompleteSearch', False),
        }


def create_spreadsheet(
        clients: Clients,
        title: str,
        folder_id: str | None = None,
        tabs: list[str] | None = None) -> dict:
    """Create an empty spreadsheet.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    title : str
    folder_id : str, optional
        Folder to create it in. Omitted, it goes in My Drive.
    tabs : list of str, optional
        Tab titles in order. Omitted, the spreadsheet has one tab,
        'Sheet1'.

    Returns
    -------
    dict
        'spreadsheet_id', 'title' and 'url'.

    Examples
    --------
    create_spreadsheet(title='Budget 2026', tabs=['Inputs', 'Summary'])
    -> {'spreadsheet_id': '1AbC', 'title': 'Budget 2026',
        'url': 'https://docs.google.com/...'}
    """
    body = {'name': title, 'mimeType': SHEET_MIME}
    if folder_id:
        body['parents'] = [folder_id]
    created = clients.drive.files().create(
        body=body, fields=FILE_FIELDS, **DRIVE_FLAGS).execute()
    if tabs:
        first_tab = {'updateSheetProperties': {
            'properties': {'sheetId': 0, 'title': tabs[0]},
            'fields': 'title',
            }}
        more_tabs = [
            {'addSheet': {'properties': {'title': tab}}} for tab in tabs[1:]
            ]
        clients.sheets.spreadsheets().batchUpdate(
            spreadsheetId=created['id'],
            body={'requests': [first_tab, *more_tabs]}).execute()
    return {
        'spreadsheet_id': created['id'],
        'title': created['name'],
        'url': created.get('webViewLink'),
        }


def copy_spreadsheet(
        clients: Clients,
        spreadsheet_id: str,
        title: str,
        folder_id: str | None = None) -> dict:
    """Copy a whole spreadsheet into a new file.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet to copy.
    title : str
        Name of the copy.
    folder_id : str, optional
        Folder for the copy. Omitted, it sits beside the original.

    Returns
    -------
    dict
        The copy's 'spreadsheet_id', 'title' and 'url'.

    Examples
    --------
    copy_spreadsheet(spreadsheet_id='1AbC', title='Budget 2027')
    -> {'spreadsheet_id': '1XyZ', 'title': 'Budget 2027',
        'url': 'https://docs.google.com/...'}
    """
    body = {'name': title}
    if folder_id:
        body['parents'] = [folder_id]
    copied = clients.drive.files().copy(
        fileId=spreadsheet_id, body=body, fields=FILE_FIELDS, **DRIVE_FLAGS).execute()
    return {
        'spreadsheet_id': copied['id'],
        'title': copied['name'],
        'url': copied.get('webViewLink'),
        }


def convert_file(
        clients: Clients,
        file_id: str,
        title: str | None = None,
        folder_id: str | None = None) -> dict:
    """Copy a csv, tsv, xlsx, xls or ods file in Drive into a new
    spreadsheet. The original file stays as it is.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    file_id : str
        Drive id of the file to convert.
    title : str, optional
        Name of the spreadsheet. Omitted, the file name without its
        extension.
    folder_id : str, optional
        Folder for the spreadsheet. Omitted, it goes in the original's
        folder when the account can see that folder, else in My Drive.

    Returns
    -------
    dict
        'spreadsheet_id', 'title' and 'url'.

    Raises
    ------
    ValueError
        The file is already a spreadsheet, or is not one of the five types.

    Examples
    --------
    convert_file(file_id='1XlS')
    -> {'spreadsheet_id': '1AbC', 'title': 'prices',
        'url': 'https://docs.google.com/...'}
    """
    source = get_file(clients, file_id, 'id,name')
    if source['mimeType'] == SHEET_MIME:
        raise ValueError(f'{source["name"]!r} is already a spreadsheet')
    if source['mimeType'] not in IMPORT_MIMES.values():
        raise ValueError(f'{source["name"]!r} is {source["mimeType"]}; only '
                         f'{sorted(IMPORT_MIMES)} files convert')
    name = source['name']
    suffix = Path(name).suffix
    if suffix.lower() in IMPORT_MIMES:
        name = name[:-len(suffix)]
    body = {'name': title or name, 'mimeType': SHEET_MIME}
    if folder_id:
        body['parents'] = [folder_id]
    converted = clients.drive.files().copy(
        fileId=source['id'], body=body, fields=FILE_FIELDS,
        **DRIVE_FLAGS).execute()
    return {
        'spreadsheet_id': converted['id'],
        'title': converted['name'],
        'url': converted.get('webViewLink'),
        }


def update_file(
        clients: Clients,
        file_id: str,
        title: str | None = None,
        folder_id: str | None = None) -> dict:
    """Rename a spreadsheet or folder, or move it to another folder.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    file_id : str
        Spreadsheet or folder id.
    title : str, optional
        New name.
    folder_id : str, optional
        Folder to move it into. It leaves every folder it was in.

    Returns
    -------
    dict
        The file as list_files describes it.

    Raises
    ------
    ValueError
        Neither title nor folder_id was given.

    Examples
    --------
    update_file(file_id='1AbC', title='Budget 2026 (final)', folder_id='0Fld')
    -> {'id': '1AbC', 'name': 'Budget 2026 (final)', 'kind': 'spreadsheet',
        'modified': '2026-11-18T15:20:00Z', 'url': 'https://docs.google.com/...',
        'parents': ['0Fld']}
    """
    if title is None and folder_id is None:
        raise ValueError('give a new title, a folder_id, or both')
    updated = None
    if title is not None:
        updated = clients.drive.files().update(
            fileId=file_id, body={'name': title}, fields=FILE_FIELDS,
            **DRIVE_FLAGS).execute()
    if folder_id is not None:
        updated = move_to_folder(clients, file_id, folder_id)
    return file_summary(updated)


def delete_file(clients: Clients, file_id: str, permanent: bool = False) -> dict:
    """Move a spreadsheet or folder to the trash, or delete it for good.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    file_id : str
        Spreadsheet or folder id. Trashing a folder trashes its contents;
        deleting it deletes only the contents the account owns.
    permanent : bool, default False
        False moves it to the trash, where the owner can restore it for 30
        days. True deletes it at once, beyond recovery.

    Returns
    -------
    dict
        'file_id' and 'outcome': 'trashed' or 'deleted'.

    Examples
    --------
    delete_file(file_id='1AbC')
    -> {'file_id': '1AbC', 'outcome': 'trashed'}
    """
    if permanent:
        clients.drive.files().delete(fileId=file_id, **DRIVE_FLAGS).execute()
        return {'file_id': file_id, 'outcome': 'deleted'}
    clients.drive.files().update(
        fileId=file_id, body={'trashed': True}, fields='id', **DRIVE_FLAGS).execute()
    return {'file_id': file_id, 'outcome': 'trashed'}


def create_folder(
        clients: Clients,
        name: str,
        parent_id: str | None = None,
        app_properties: dict[str, str] | None = None) -> dict:
    """Create a folder.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    name : str
    parent_id : str, optional
        Folder to create it in. Omitted, it goes in My Drive.
    app_properties : dict of str to str, optional
        Drive appProperties: tags only this Google Cloud app can read, which
        a Drive query matches as appProperties has {key='k' and value='v'}.

    Returns
    -------
    dict
        The folder as list_files describes it.

    Examples
    --------
    create_folder(name='Reports')
    -> {'id': '0Fld', 'name': 'Reports', 'kind': 'folder', ...}
    """
    body = {'name': name, 'mimeType': FOLDER_MIME}
    if parent_id:
        body['parents'] = [parent_id]
    if app_properties:
        body['appProperties'] = app_properties
    created = clients.drive.files().create(
        body=body, fields=FILE_FIELDS, **DRIVE_FLAGS).execute()
    return file_summary(created)


def list_permissions(clients: Clients, file_id: str) -> dict:
    """Who can open a spreadsheet or folder, and with what role.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    file_id : str
        Spreadsheet or folder id.

    Returns
    -------
    dict
        'permissions' lists each grant's 'type' ('user', 'group',
        'domain' or 'anyone'), 'role', and 'email' or 'domain' where the
        type has one.

    Examples
    --------
    list_permissions(file_id='1AbC')
    -> {'permissions': [{'type': 'user', 'role': 'owner',
                         'email': 'ana@example.com'},
                        {'type': 'anyone', 'role': 'reader'}]}
    """
    permissions = []
    for permission in all_permissions(clients, file_id):
        entry = {'type': permission['type'], 'role': permission['role']}
        if 'emailAddress' in permission:
            entry['email'] = permission['emailAddress']
        if 'domain' in permission:
            entry['domain'] = permission['domain']
        permissions.append(entry)
    return {'permissions': permissions}


def share_file(
        clients: Clients,
        file_id: str,
        role: Literal['reader', 'commenter', 'writer', 'none'],
        email: str | None = None,
        anyone_with_link: bool = False,
        notify: bool = False) -> dict:
    """Give, change or remove one person's access, or link access.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    file_id : str
        Spreadsheet or folder id.
    role : {'reader', 'commenter', 'writer', 'none'}
        'none' removes the access.
    email : str, optional
        The person's email. Give email or anyone_with_link, not both. An
        address with no Google account needs notify=True, or Google
        refuses the grant.
    anyone_with_link : bool, default False
        True sets the access of anyone who has the link.
    notify : bool, default False
        True emails the person about a new grant.

    Returns
    -------
    dict
        'file_id', who the change covers as 'email' or 'anyone_with_link',
        and the 'role' of that direct grant. Access through a group or
        domain grant is untouched.

    Raises
    ------
    ValueError
        Both or neither of email and anyone_with_link were given.

    Examples
    --------
    share_file(file_id='1AbC', role='writer', email='ana@example.com')
    -> {'file_id': '1AbC', 'email': 'ana@example.com', 'role': 'writer'}
    """
    if bool(email) == anyone_with_link:
        raise ValueError('give email or anyone_with_link=true, not both')
    grantee = {'email': email} if email else {'anyone_with_link': True}
    permissions = all_permissions(clients, file_id)
    if email:
        matching = [
            permission for permission in permissions
            if permission.get('emailAddress', '').lower() == email.lower()
            ]
    else:
        matching = [
            permission for permission in permissions if permission['type'] == 'anyone'
            ]
    existing = matching[0] if matching else None
    if role == 'none':
        if existing:
            clients.drive.permissions().delete(
                fileId=file_id, permissionId=existing['id'], **DRIVE_FLAGS).execute()
    elif existing:
        clients.drive.permissions().update(
            fileId=file_id, permissionId=existing['id'], body={'role': role},
            **DRIVE_FLAGS).execute()
    else:
        body = {'role': role}
        body |= {'type': 'user', 'emailAddress': email} if email else {'type': 'anyone'}
        clients.drive.permissions().create(
            fileId=file_id, body=body, sendNotificationEmail=notify and bool(email),
            **DRIVE_FLAGS).execute()
    return {'file_id': file_id, **grantee, 'role': role}


def import_file(
        clients: Clients,
        path: str,
        title: str | None = None,
        folder_id: str | None = None) -> dict:
    """Upload a local csv, tsv, xlsx, xls or ods file as a new spreadsheet.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    path : str
        Path to the file on the machine running this server. '~' expands.
    title : str, optional
        Name of the spreadsheet. Omitted, the file name without its
        extension.
    folder_id : str, optional
        Folder to create it in. Omitted, it goes in My Drive.

    Returns
    -------
    dict
        'spreadsheet_id', 'title' and 'url'.

    Raises
    ------
    ValueError
        The file does not exist or its extension is not one of the five.

    Examples
    --------
    import_file(path='~/Downloads/prices.xlsx', folder_id='0Fld')
    -> {'spreadsheet_id': '1AbC', 'title': 'prices',
        'url': 'https://docs.google.com/...'}
    """
    source = Path(path).expanduser()
    if not source.is_file():
        raise ValueError(f'no file at {source}')
    mime = IMPORT_MIMES.get(source.suffix.lower())
    if mime is None:
        raise ValueError(f'{source.suffix!r} files are not imported; use one of '
                         f'{sorted(IMPORT_MIMES)}')
    body = {'name': title or source.stem, 'mimeType': SHEET_MIME}
    if folder_id:
        body['parents'] = [folder_id]
    created = clients.drive.files().create(
        body=body,
        media_body=MediaFileUpload(str(source), mimetype=mime, resumable=True),
        fields=FILE_FIELDS,
        **DRIVE_FLAGS).execute()
    return {
        'spreadsheet_id': created['id'],
        'title': created['name'],
        'url': created.get('webViewLink'),
        }


def import_bytes(
        clients: Clients,
        data: bytes,
        mime_type: str,
        title: str,
        folder_id: str) -> dict:
    """Upload file contents held in memory as a new spreadsheet.

    Parameters
    ----------
    clients : Clients
        Google clients.
    data : bytes
        Contents of a csv, tsv, xlsx, xls or ods file. Nothing checks
        them before upload, so screen untrusted contents first.
    mime_type : str
        Type of data, a value of IMPORT_MIMES.
    title : str
        Name of the spreadsheet.
    folder_id : str
        Folder to create it in.

    Returns
    -------
    dict
        'spreadsheet_id', 'title' and 'url', as import_file gives.
    """
    upload = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=True)
    created = clients.drive.files().create(
        body={'name': title, 'mimeType': SHEET_MIME, 'parents': [folder_id]},
        media_body=upload,
        fields=FILE_FIELDS,
        **DRIVE_FLAGS).execute()
    return {
        'spreadsheet_id': created['id'],
        'title': created['name'],
        'url': created.get('webViewLink'),
        }


def export_spreadsheet(
        clients: Clients,
        spreadsheet_id: str,
        path: str,
        file_format: Literal['xlsx', 'ods', 'pdf', 'csv', 'tsv'],
        tab: str | None = None,
        overwrite: bool = False) -> dict:
    """Save a spreadsheet to a local file.

    Parameters
    ----------
    clients : Clients
        Google clients; the server passes them.
    spreadsheet_id : str
        Spreadsheet id from list_files or a Sheets URL.
    path : str
        Where to write, on the machine running this server. '~' expands.
    file_format : {'xlsx', 'ods', 'pdf', 'csv', 'tsv'}
        xlsx, ods and pdf hold every tab. csv and tsv hold one tab's
        values as the Sheets UI shows them.
    tab : str, optional
        For csv and tsv: the tab to save. Required for those formats.
    overwrite : bool, default False
        False refuses a path where a file exists.

    Returns
    -------
    dict
        'path' written and its size in 'bytes'.

    Raises
    ------
    ValueError
        The file exists and overwrite is False, or csv or tsv lacks tab.

    Examples
    --------
    export_spreadsheet(spreadsheet_id='1AbC', path='~/budget.xlsx',
                       file_format='xlsx')
    -> {'path': '/home/ana/budget.xlsx', 'bytes': 48213}
    """
    target = Path(path).expanduser()
    if (target.exists() or target.is_symlink()) and not overwrite:
        raise ValueError(f'{target} exists; pass overwrite=true to replace it')
    if file_format in EXPORT_MIMES:
        content = clients.drive.files().export(
            fileId=spreadsheet_id, mimeType=EXPORT_MIMES[file_format]).execute()
    else:
        if tab is None:
            raise ValueError(f'{file_format} holds one tab; name it with tab')
        reply = clients.sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=a1.quote_tab(tab),
            valueRenderOption='FORMATTED_VALUE').execute()
        text = io.StringIO()
        delimiter = ',' if file_format == 'csv' else '\t'
        csv.writer(text, delimiter=delimiter, lineterminator='\n').writerows(
            reply.get('values', []))
        content = text.getvalue().encode()
    target.write_bytes(content)
    return {'path': str(target), 'bytes': len(content)}
