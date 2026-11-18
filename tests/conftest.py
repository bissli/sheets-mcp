import pytest
from fake_google import FakeGoogle
from sheets_mcp.google import Clients


@pytest.fixture
def fake():
    return FakeGoogle()


@pytest.fixture
def clients(fake):
    return Clients(drive=fake.drive, sheets=fake.sheets)
