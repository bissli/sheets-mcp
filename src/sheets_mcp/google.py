"""Drive v3 and Sheets v4 clients, and the lookups every module shares.
"""
import string
from dataclasses import dataclass
from typing import Any

from google.auth.credentials import Credentials
from googleapiclient.discovery import build

SHEET_MIME = 'application/vnd.google-apps.spreadsheet'
FOLDER_MIME = 'application/vnd.google-apps.folder'


@dataclass(frozen=True)
class Clients:
    """Drive v3 and Sheets v4 service objects for one tool call.

    Attributes
    ----------
    drive : Any
        googleapiclient Drive v3 resource.
    sheets : Any
        googleapiclient Sheets v4 resource.
    """

    drive: Any
    sheets: Any


def build_clients(credentials: Credentials) -> Clients:
    """Fresh clients on credentials. The client library is not thread-safe,
    so each tool call takes its own.
    """
    return Clients(
        drive=build('drive', 'v3', credentials=credentials, cache_discovery=False),
        sheets=build('sheets', 'v4', credentials=credentials, cache_discovery=False))


def tab_properties(clients: Clients, spreadsheet_id: str, tab: str) -> dict:
    """The Sheets API SheetProperties of one tab.

    Parameters
    ----------
    clients : Clients
    spreadsheet_id : str
    tab : str
        Tab title, matched exactly.

    Returns
    -------
    dict
        Holds 'sheetId', 'title', 'index' and 'gridProperties'.

    Raises
    ------
    ValueError
        No tab has that title. The message lists the titles.
    """
    reply = clients.sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields='sheets.properties').execute()
    properties_by_title = {
        sheet['properties']['title']: sheet['properties']
        for sheet in reply.get('sheets', [])
        }
    if tab not in properties_by_title:
        raise ValueError(
            f'no tab {tab!r}; the tabs are {sorted(properties_by_title)}')
    return properties_by_title[tab]


def rgb_color(hex_color: str) -> dict:
    """Sheets API Color of '#RRGGBB', each channel scaled to 0..1.

    Raises
    ------
    ValueError
        hex_color is not '#' and six hex digits.
    """
    digits = hex_color.removeprefix('#')
    if len(digits) != 6 or any(digit not in string.hexdigits for digit in digits):
        raise ValueError(f'{hex_color!r} is not a color such as #1A73E8')
    red, green, blue = (int(digits[at:at + 2], 16) / 255 for at in (0, 2, 4))
    return {'red': red, 'green': green, 'blue': blue}
