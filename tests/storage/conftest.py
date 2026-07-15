import sqlite3
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_conn() -> MagicMock:
    return MagicMock(spec=sqlite3.Connection)
