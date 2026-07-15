import sqlite3
import sys
import types
from unittest.mock import MagicMock

import pytest

if "semi.domain.models" not in sys.modules:
    domain_pkg = types.ModuleType("semi.domain")
    domain_models_stub = MagicMock(
        name="semi.domain.models (test-only import stub, not an implementation)"
    )
    sys.modules["semi.domain"] = domain_pkg
    sys.modules["semi.domain.models"] = domain_models_stub
    domain_pkg.models = domain_models_stub


@pytest.fixture
def mock_conn() -> MagicMock:
    return MagicMock(spec=sqlite3.Connection)
