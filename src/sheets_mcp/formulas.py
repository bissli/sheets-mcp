"""The formula check on values written with parse=true.
"""
import re

URL_FUNCTIONS = (
    'IMPORTXML', 'IMPORTHTML', 'IMPORTDATA', 'IMPORTFEED', 'IMPORTRANGE',
    'IMAGE',
    )
FORMULA_STARTS = ('=', '+', '-')
QUOTED_TEXT = re.compile(r'"(?:[^"]|"")*"|\'(?:[^\']|\'\')*\'')
TABLE_REFERENCE = re.compile(r'[A-Za-z_][\w.]*\[(?:[^\[\]]|\[[^\[\]]*\])*\]')
URL_CALL = re.compile(
    r'(?<![A-Z0-9_])(' + '|'.join(URL_FUNCTIONS) + r')\s*\(', re.IGNORECASE)


def refuse_url_functions(value: object) -> None:
    """Raise when value is a formula that calls a URL-fetching function.

    Parameters
    ----------
    value : object
        A cell value as the caller sent it. A str whose first non-space
        character is '=', '+' or '-' is a formula, as Sheets parses it;
        every other value passes.

    Raises
    ------
    ValueError
        The formula calls IMPORTXML, IMPORTHTML, IMPORTDATA, IMPORTFEED,
        IMPORTRANGE or IMAGE, with or without a prefix such as '_xlfn.'.
        A function name inside a string literal, a quoted tab name or a
        table reference such as Prices[IMAGE (old)] passes.
    """
    if not isinstance(value, str) or not value.lstrip().startswith(FORMULA_STARTS):
        return
    unquoted = QUOTED_TEXT.sub('""', value)
    match = URL_CALL.search(TABLE_REFERENCE.sub('""', unquoted))
    if match:
        raise ValueError(
            f'{match[1].upper()} is refused: it fetches a URL and can send '
            'cell contents to a third party. Write the data itself instead')
