# Storage Layer (`semi.storage`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `semi/storage` (SQLite connection/schema init, `NotFoundError`, datetime helpers, and one repository per entity) exactly as specified in `docs/superpowers/specs/2026-07-15-storage-design.md` — and **only** `semi/storage`. `semi/domain` is out of scope and must not be implemented.

**Architecture:** Each repository (`SampleRepository`, `OrderRepository`, `ProductionJobRepository`) wraps a single `sqlite3.Connection` passed in at construction, exposes it as a public `.conn` attribute, and does nothing but `conn.execute(...)` — no `commit()`/`rollback()`, no business formulas. Rows map to `semi.domain.models` dataclasses; `get_by_id`-style lookups raise `NotFoundError` instead of returning `None`. Repository production code imports `from semi.domain.models import Sample, ...` exactly as storage-design.md specifies, even though that module doesn't exist yet — see "Domain mocking strategy" below for how tests make that importable without implementing it.

**Tech Stack:** Python 3.14+, standard-library `sqlite3`, `pytest` + `pytest-mock` (`mocker` fixture) from the `test` extra.

## Domain mocking strategy (read before Task 1)

`semi/domain` has not been implemented (that's a separate, out-of-scope plan) but `storage-design.md` requires repository code to import real names from it (`Sample`, `Order`, `ProductionJob`, `OrderStatus`, `JobStatus`). Since those imports run at module-import time — before any per-test fixture can intervene — `tests/storage/conftest.py` installs `MagicMock` stand-ins directly into `sys.modules["semi.domain"]` / `sys.modules["semi.domain.models"]` as **module-level code** (not inside a fixture), so it runs once when pytest loads the conftest, before any `tests/storage/test_*.py` file is collected and imports `semi.storage.*`. This is test-only plumbing to satisfy Python's import system — it contains no dataclass fields, no enum values, no domain logic, and is never imported by production code.

Every individual test then narrows this down with `mocker.patch("semi.storage.<module>.<Name>", ...)` to assert exactly how that repository method calls the (mocked) domain constructor/enum, and asserts the method returns whatever the mock produced — not real dataclass equality. Consequence of this tradeoff (accepted): no test exercises a real row → dataclass round-trip, and repository tests do not hit a real SQLite file (`conn` is `MagicMock(spec=sqlite3.Connection)`) since mocked `OrderStatus`/`JobStatus` members can't bind as real SQL parameters. `CHECK` constraint enforcement (schema-level correctness) is verified separately in Task 1's `test_db.py` using raw SQL against a real database, which has no dependency on domain at all.

## Global Constraints

- Python 3.14+ (`pyproject.toml` `requires-python = ">=3.14"`).
- Install once before starting: `pip install -e ".[dev,test]"`.
- Before every commit: `ruff check --fix .` then `ruff format .`.
- Commit messages follow Conventional Commits (enforced by the `commitizen` `commit-msg` hook).
- No code comments except where the WHY is non-obvious (per project style).
- **Scope is strictly `semi/storage`.** Do not create `semi/domain/*` — mock it in tests as described above instead.
- Repositories never call `conn.commit()` or `conn.rollback()` — that is the Service layer's job (out of scope here).
- `get_by_id`/`get_by_order_id`-style lookups always return a domain object or raise `storage.exceptions.NotFoundError` — never `None`. `get_current_in_progress()` is the one documented exception, returning `ProductionJob | None`.
- Datetime fields are stored as ISO8601 `TEXT`; conversion happens only inside `storage` (`_datetime.to_iso`/`from_iso`), which is real, implemented code (not domain, not mocked).

---

### Task 1: DB connection/schema init, exceptions, datetime helpers, domain-mock scaffolding

**Files:**
- Create: `semi/storage/__init__.py`
- Create: `semi/storage/exceptions.py`
- Create: `semi/storage/_datetime.py`
- Create: `semi/storage/db.py`
- Create: `tests/storage/__init__.py`
- Create: `tests/storage/conftest.py`
- Test: `tests/storage/test_db.py`
- Modify: `pyproject.toml` (add `[tool.pytest.ini_options]`)

**Interfaces:**
- Consumes: nothing (this task has no domain dependency at all — that's why its tests hit a real SQLite file instead of mocks).
- Produces (used by Tasks 2-4): `semi.storage.db.connect_db(db_path: Path) -> sqlite3.Connection`, `semi.storage.exceptions.NotFoundError`, `semi.storage._datetime.to_iso(dt: datetime) -> str`, `semi.storage._datetime.from_iso(value: str) -> datetime`; the `sys.modules["semi.domain.models"]` `MagicMock` stand-in (installed as a side effect of loading `tests/storage/conftest.py`, described above); and a `mock_conn` pytest fixture (`MagicMock(spec=sqlite3.Connection)`) that every repository test file uses instead of a real connection.

- [ ] **Step 1: Install test tooling and add pytest config**

```bash
pip install -e ".[dev,test]"
```

Append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing schema/connection tests**

`tests/storage/__init__.py` (empty file).

`tests/storage/test_db.py`:

```python
import sqlite3
from pathlib import Path

import pytest

from semi.storage.db import connect_db


def test_connect_db_creates_schema(tmp_path: Path) -> None:
    conn = connect_db(tmp_path / "test.db")
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"samples", "orders", "production_jobs"} <= tables
    conn.close()


def test_connect_db_sets_wal_mode(tmp_path: Path) -> None:
    conn = connect_db(tmp_path / "test.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    conn.close()


def test_connect_db_is_idempotent_and_reopens_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn1 = connect_db(db_path)
    conn1.execute(
        "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate) "
        "VALUES ('S1', 'wafer', 10.0, 0.9)"
    )
    conn1.commit()
    conn1.close()

    conn2 = connect_db(db_path)
    row = conn2.execute("SELECT * FROM samples WHERE sample_id = 'S1'").fetchone()
    assert row["name"] == "wafer"
    conn2.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/storage/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.storage'`

- [ ] **Step 4: Implement db.py, exceptions.py, _datetime.py**

`semi/storage/__init__.py` (empty file).

`semi/storage/exceptions.py`:

```python
class NotFoundError(Exception):
    """id로 조회했으나 대상 row가 없을 때 발생."""
```

`semi/storage/_datetime.py`:

```python
from datetime import datetime


def to_iso(dt: datetime) -> str:
    return dt.isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
```

`semi/storage/db.py`:

```python
import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS samples (
    sample_id             TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    avg_production_seconds REAL NOT NULL CHECK (avg_production_seconds > 0),
    yield_rate            REAL NOT NULL CHECK (yield_rate > 0 AND yield_rate <= 1),
    stock_quantity        INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id     TEXT NOT NULL REFERENCES samples(sample_id),
    customer_name TEXT NOT NULL,
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    status        TEXT NOT NULL CHECK (status IN
                    ('RESERVED','REJECTED','PRODUCING','CONFIRMED','RELEASE')),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS production_jobs (
    job_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id             INTEGER NOT NULL UNIQUE REFERENCES orders(order_id),
    sample_id            TEXT NOT NULL REFERENCES samples(sample_id),
    shortfall_quantity   INTEGER NOT NULL,
    actual_quantity      INTEGER NOT NULL,
    total_duration_seconds REAL NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('QUEUED','IN_PROGRESS','DONE')),
    enqueued_at          TEXT NOT NULL,
    started_at           TEXT
);
"""


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA_SQL)
    return conn
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/storage/test_db.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Add failing `CHECK`-constraint tests (defense-in-depth, verified here since it needs no domain dependency)**

Append to `tests/storage/test_db.py`:

```python
def test_samples_check_constraints_reject_invalid_values(tmp_path: Path) -> None:
    conn = connect_db(tmp_path / "test.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
            "VALUES ('S1', 'wafer', 0, 0.9, 0)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
            "VALUES ('S2', 'wafer', 10.0, 1.5, 0)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
            "VALUES ('S3', 'wafer', 10.0, 0.9, -1)"
        )
    conn.close()


def test_orders_check_constraints_reject_invalid_values(tmp_path: Path) -> None:
    conn = connect_db(tmp_path / "test.db")
    conn.execute(
        "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate) "
        "VALUES ('S1', 'wafer', 10.0, 0.9)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
            "VALUES ('S1', 'acme', 0, 'RESERVED', '2026-01-01T00:00:00')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
            "VALUES ('S1', 'acme', 5, 'BOGUS', '2026-01-01T00:00:00')"
        )
    conn.close()


def test_production_jobs_check_constraint_rejects_invalid_status(tmp_path: Path) -> None:
    conn = connect_db(tmp_path / "test.db")
    conn.execute(
        "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate) "
        "VALUES ('S1', 'wafer', 10.0, 0.9)"
    )
    conn.execute(
        "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
        "VALUES ('S1', 'acme', 5, 'RESERVED', '2026-01-01T00:00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO production_jobs "
            "(order_id, sample_id, shortfall_quantity, actual_quantity, "
            "total_duration_seconds, status, enqueued_at) "
            "VALUES (1, 'S1', 2, 3, 30.0, 'BOGUS', '2026-01-01T00:00:00')"
        )
    conn.close()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/storage/test_db.py -v`
Expected: PASS (6 passed)

- [ ] **Step 8: Add the domain-mock scaffolding and `mock_conn` fixture**

`tests/storage/conftest.py`:

```python
import sqlite3
import sys
import types
from unittest.mock import MagicMock

import pytest

if "semi.domain.models" not in sys.modules:
    domain_pkg = types.ModuleType("semi.domain")
    domain_models_stub = MagicMock(name="semi.domain.models (test-only import stub, not an implementation)")
    sys.modules["semi.domain"] = domain_pkg
    sys.modules["semi.domain.models"] = domain_models_stub
    domain_pkg.models = domain_models_stub


@pytest.fixture
def mock_conn() -> MagicMock:
    return MagicMock(spec=sqlite3.Connection)
```

- [ ] **Step 9: Run the full test suite to confirm the stub doesn't break anything yet**

Run: `pytest tests/storage -v`
Expected: PASS (6 passed) — `conftest.py` has no tests of its own; this just confirms collection still works after adding the stub.

- [ ] **Step 10: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add pyproject.toml semi/storage tests/storage
git commit -m "feat(storage): add SQLite connection/schema init, NotFoundError, datetime helpers"
```

---

### Task 2: `SampleRepository`

**Files:**
- Create: `semi/storage/sample_repository.py`
- Test: `tests/storage/test_sample_repository.py`

**Interfaces:**
- Consumes: `semi.storage.exceptions.NotFoundError` (Task 1, real); `mock_conn` fixture (Task 1); `Sample` from `semi.domain.models` — patched per-test via `mocker.patch("semi.storage.sample_repository.Sample")`, never imported for real.
- Produces (used only as an example pattern for Tasks 3-4, no runtime coupling): `semi.storage.sample_repository.SampleRepository(conn)` with `create(sample_id, name, avg_production_seconds, yield_rate) -> Sample`, `get_by_id(sample_id) -> Sample`, `exists(sample_id) -> bool`, `list_all() -> list[Sample]`, `search_by_name(query) -> list[Sample]`, `increment_stock(sample_id, amount) -> None`, `decrement_stock(sample_id, amount) -> None`.

- [ ] **Step 1: Write failing tests for `create` and `get_by_id`**

`tests/storage/test_sample_repository.py`:

```python
import pytest

from semi.storage.exceptions import NotFoundError
from semi.storage.sample_repository import SampleRepository


def test_create_inserts_row_and_returns_mapped_sample(mock_conn, mocker) -> None:
    sample_cls = mocker.patch("semi.storage.sample_repository.Sample")
    mock_conn.execute.return_value.fetchone.return_value = {
        "sample_id": "S1",
        "name": "wafer",
        "avg_production_seconds": 10.0,
        "yield_rate": 0.9,
        "stock_quantity": 0,
    }

    repo = SampleRepository(mock_conn)
    result = repo.create("S1", "wafer", 10.0, 0.9)

    mock_conn.execute.assert_any_call(
        "INSERT INTO samples "
        "(sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
        "VALUES (?, ?, ?, ?, 0)",
        ("S1", "wafer", 10.0, 0.9),
    )
    sample_cls.assert_called_once_with(
        sample_id="S1",
        name="wafer",
        avg_production_seconds=10.0,
        yield_rate=0.9,
        stock_quantity=0,
    )
    assert result is sample_cls.return_value


def test_get_by_id_raises_not_found_when_row_missing(mock_conn, mocker) -> None:
    mocker.patch("semi.storage.sample_repository.Sample")
    mock_conn.execute.return_value.fetchone.return_value = None

    repo = SampleRepository(mock_conn)
    with pytest.raises(NotFoundError):
        repo.get_by_id("missing")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_sample_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.storage.sample_repository'`

- [ ] **Step 3: Implement `create` and `get_by_id`**

`semi/storage/sample_repository.py`:

```python
import sqlite3

from semi.domain.models import Sample
from semi.storage.exceptions import NotFoundError


class SampleRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        sample_id: str,
        name: str,
        avg_production_seconds: float,
        yield_rate: float,
    ) -> Sample:
        self.conn.execute(
            "INSERT INTO samples "
            "(sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
            "VALUES (?, ?, ?, ?, 0)",
            (sample_id, name, avg_production_seconds, yield_rate),
        )
        return self.get_by_id(sample_id)

    def get_by_id(self, sample_id: str) -> Sample:
        row = self.conn.execute(
            "SELECT * FROM samples WHERE sample_id = ?", (sample_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"sample_id={sample_id!r} not found")
        return _row_to_sample(row)


def _row_to_sample(row: sqlite3.Row) -> Sample:
    return Sample(
        sample_id=row["sample_id"],
        name=row["name"],
        avg_production_seconds=row["avg_production_seconds"],
        yield_rate=row["yield_rate"],
        stock_quantity=row["stock_quantity"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_sample_repository.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Add failing tests for `exists`, `list_all`, `search_by_name`**

Append to `tests/storage/test_sample_repository.py`:

```python
def test_exists_true_when_row_found(mock_conn) -> None:
    mock_conn.execute.return_value.fetchone.return_value = {"1": 1}
    repo = SampleRepository(mock_conn)
    assert repo.exists("S1") is True
    mock_conn.execute.assert_called_once_with(
        "SELECT 1 FROM samples WHERE sample_id = ?", ("S1",)
    )


def test_exists_false_when_row_missing(mock_conn) -> None:
    mock_conn.execute.return_value.fetchone.return_value = None
    repo = SampleRepository(mock_conn)
    assert repo.exists("S1") is False


def test_list_all_maps_every_row(mock_conn, mocker) -> None:
    sample_cls = mocker.patch("semi.storage.sample_repository.Sample")
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "sample_id": "S1",
            "name": "a",
            "avg_production_seconds": 1.0,
            "yield_rate": 0.5,
            "stock_quantity": 1,
        },
        {
            "sample_id": "S2",
            "name": "b",
            "avg_production_seconds": 2.0,
            "yield_rate": 0.6,
            "stock_quantity": 2,
        },
    ]

    repo = SampleRepository(mock_conn)
    result = repo.list_all()

    mock_conn.execute.assert_called_once_with("SELECT * FROM samples")
    assert sample_cls.call_count == 2
    assert result == [sample_cls.return_value, sample_cls.return_value]


def test_search_by_name_uses_like_query(mock_conn, mocker) -> None:
    sample_cls = mocker.patch("semi.storage.sample_repository.Sample")
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "sample_id": "S1",
            "name": "wafer-a",
            "avg_production_seconds": 1.0,
            "yield_rate": 0.5,
            "stock_quantity": 1,
        },
    ]

    repo = SampleRepository(mock_conn)
    result = repo.search_by_name("wafer")

    mock_conn.execute.assert_called_once_with(
        "SELECT * FROM samples WHERE name LIKE ?", ("%wafer%",)
    )
    assert result == [sample_cls.return_value]
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/storage/test_sample_repository.py -v`
Expected: FAIL with `AttributeError: 'SampleRepository' object has no attribute 'exists'`

- [ ] **Step 7: Implement `exists`, `list_all`, `search_by_name`**

Add to the `SampleRepository` class in `semi/storage/sample_repository.py`:

```python
    def exists(self, sample_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM samples WHERE sample_id = ?", (sample_id,)
        ).fetchone()
        return row is not None

    def list_all(self) -> list[Sample]:
        rows = self.conn.execute("SELECT * FROM samples").fetchall()
        return [_row_to_sample(row) for row in rows]

    def search_by_name(self, query: str) -> list[Sample]:
        rows = self.conn.execute(
            "SELECT * FROM samples WHERE name LIKE ?", (f"%{query}%",)
        ).fetchall()
        return [_row_to_sample(row) for row in rows]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/storage/test_sample_repository.py -v`
Expected: PASS (6 passed)

- [ ] **Step 9: Add failing tests for `increment_stock`/`decrement_stock`**

Append to `tests/storage/test_sample_repository.py`:

```python
def test_increment_stock_executes_update(mock_conn) -> None:
    repo = SampleRepository(mock_conn)
    repo.increment_stock("S1", 5)
    mock_conn.execute.assert_called_once_with(
        "UPDATE samples SET stock_quantity = stock_quantity + ? WHERE sample_id = ?",
        (5, "S1"),
    )


def test_decrement_stock_executes_update(mock_conn) -> None:
    repo = SampleRepository(mock_conn)
    repo.decrement_stock("S1", 2)
    mock_conn.execute.assert_called_once_with(
        "UPDATE samples SET stock_quantity = stock_quantity - ? WHERE sample_id = ?",
        (2, "S1"),
    )
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `pytest tests/storage/test_sample_repository.py -v`
Expected: FAIL with `AttributeError: 'SampleRepository' object has no attribute 'increment_stock'`

- [ ] **Step 11: Implement `increment_stock`/`decrement_stock`**

Add to the `SampleRepository` class in `semi/storage/sample_repository.py`:

```python
    def increment_stock(self, sample_id: str, amount: int) -> None:
        self.conn.execute(
            "UPDATE samples SET stock_quantity = stock_quantity + ? WHERE sample_id = ?",
            (amount, sample_id),
        )

    def decrement_stock(self, sample_id: str, amount: int) -> None:
        self.conn.execute(
            "UPDATE samples SET stock_quantity = stock_quantity - ? WHERE sample_id = ?",
            (amount, sample_id),
        )
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `pytest tests/storage/test_sample_repository.py -v`
Expected: PASS (8 passed)

- [ ] **Step 13: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/storage/sample_repository.py tests/storage/test_sample_repository.py
git commit -m "feat(storage): add SampleRepository"
```

---

### Task 3: `OrderRepository`

**Files:**
- Create: `semi/storage/order_repository.py`
- Test: `tests/storage/test_order_repository.py`

**Interfaces:**
- Consumes: `semi.storage.exceptions.NotFoundError`, `mock_conn` fixture (Task 1); `Order`/`OrderStatus` from `semi.domain.models` — patched per-test via `mocker.patch("semi.storage.order_repository.Order")` / `mocker.patch("semi.storage.order_repository.OrderStatus")`, never imported for real.
- Produces (no runtime coupling to later tasks — Task 4 mirrors the same pattern independently): `semi.storage.order_repository.OrderRepository(conn)` with `create(sample_id, customer_name, quantity) -> Order`, `get_by_id(order_id) -> Order`, `list_by_status(status) -> list[Order]`, `update_status(order_id, status) -> None`, `sum_quantity_by_status(sample_id, status) -> int`, `sum_quantity_by_statuses(sample_id, statuses) -> int`.

- [ ] **Step 1: Write failing tests for `create` and `get_by_id`**

`tests/storage/test_order_repository.py`:

```python
from datetime import datetime

import pytest

from semi.storage.exceptions import NotFoundError
from semi.storage.order_repository import OrderRepository


def test_create_inserts_row_and_returns_mapped_order(mock_conn, mocker) -> None:
    order_cls = mocker.patch("semi.storage.order_repository.Order")
    order_status = mocker.patch("semi.storage.order_repository.OrderStatus")
    fixed_now = datetime(2026, 1, 1, 12, 0, 0)
    mock_datetime = mocker.patch("semi.storage.order_repository.datetime")
    mock_datetime.now.return_value = fixed_now
    mock_conn.execute.return_value.lastrowid = 7
    mock_conn.execute.return_value.fetchone.return_value = {
        "order_id": 7,
        "sample_id": "S1",
        "customer_name": "acme corp",
        "quantity": 5,
        "status": "RESERVED",
        "created_at": fixed_now.isoformat(),
    }

    repo = OrderRepository(mock_conn)
    result = repo.create("S1", "acme corp", 5)

    mock_conn.execute.assert_any_call(
        "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("S1", "acme corp", 5, order_status.RESERVED, fixed_now.isoformat()),
    )
    order_cls.assert_called_once_with(
        order_id=7,
        sample_id="S1",
        customer_name="acme corp",
        quantity=5,
        status=order_status.return_value,
        created_at=fixed_now,
    )
    assert result is order_cls.return_value


def test_get_by_id_raises_not_found_when_row_missing(mock_conn, mocker) -> None:
    mocker.patch("semi.storage.order_repository.Order")
    mocker.patch("semi.storage.order_repository.OrderStatus")
    mock_conn.execute.return_value.fetchone.return_value = None

    repo = OrderRepository(mock_conn)
    with pytest.raises(NotFoundError):
        repo.get_by_id(999)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_order_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.storage.order_repository'`

- [ ] **Step 3: Implement `create` and `get_by_id`**

`semi/storage/order_repository.py`:

```python
import sqlite3
from datetime import datetime

from semi.domain.models import Order, OrderStatus
from semi.storage._datetime import from_iso, to_iso
from semi.storage.exceptions import NotFoundError


class OrderRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, sample_id: str, customer_name: str, quantity: int) -> Order:
        cursor = self.conn.execute(
            "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                sample_id,
                customer_name,
                quantity,
                OrderStatus.RESERVED,
                to_iso(datetime.now()),
            ),
        )
        return self.get_by_id(cursor.lastrowid)

    def get_by_id(self, order_id: int) -> Order:
        row = self.conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"order_id={order_id!r} not found")
        return _row_to_order(row)


def _row_to_order(row: sqlite3.Row) -> Order:
    return Order(
        order_id=row["order_id"],
        sample_id=row["sample_id"],
        customer_name=row["customer_name"],
        quantity=row["quantity"],
        status=OrderStatus(row["status"]),
        created_at=from_iso(row["created_at"]),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_order_repository.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Add failing tests for `list_by_status` and `update_status`**

Append to `tests/storage/test_order_repository.py`:

```python
def test_list_by_status_maps_every_row(mock_conn, mocker) -> None:
    order_cls = mocker.patch("semi.storage.order_repository.Order")
    mocker.patch("semi.storage.order_repository.OrderStatus")
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "order_id": 1,
            "sample_id": "S1",
            "customer_name": "acme",
            "quantity": 5,
            "status": "CONFIRMED",
            "created_at": "2026-01-01T00:00:00",
        },
    ]

    repo = OrderRepository(mock_conn)
    result = repo.list_by_status("CONFIRMED")

    mock_conn.execute.assert_called_once_with(
        "SELECT * FROM orders WHERE status = ?", ("CONFIRMED",)
    )
    assert result == [order_cls.return_value]


def test_update_status_executes_update(mock_conn) -> None:
    repo = OrderRepository(mock_conn)
    repo.update_status(1, "CONFIRMED")
    mock_conn.execute.assert_called_once_with(
        "UPDATE orders SET status = ? WHERE order_id = ?", ("CONFIRMED", 1)
    )
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/storage/test_order_repository.py -v`
Expected: FAIL with `AttributeError: 'OrderRepository' object has no attribute 'list_by_status'`

- [ ] **Step 7: Implement `list_by_status` and `update_status`**

Add to the `OrderRepository` class in `semi/storage/order_repository.py`:

```python
    def list_by_status(self, status: OrderStatus) -> list[Order]:
        rows = self.conn.execute(
            "SELECT * FROM orders WHERE status = ?", (status,)
        ).fetchall()
        return [_row_to_order(row) for row in rows]

    def update_status(self, order_id: int, status: OrderStatus) -> None:
        self.conn.execute(
            "UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id)
        )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/storage/test_order_repository.py -v`
Expected: PASS (4 passed)

- [ ] **Step 9: Add failing tests for `sum_quantity_by_status` and `sum_quantity_by_statuses`**

Append to `tests/storage/test_order_repository.py`:

```python
def test_sum_quantity_by_status_returns_total(mock_conn) -> None:
    mock_conn.execute.return_value.fetchone.return_value = {"total": 12}
    repo = OrderRepository(mock_conn)
    result = repo.sum_quantity_by_status("S1", "CONFIRMED")
    assert result == 12
    mock_conn.execute.assert_called_once_with(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
        "WHERE sample_id = ? AND status = ?",
        ("S1", "CONFIRMED"),
    )


def test_sum_quantity_by_statuses_returns_total(mock_conn) -> None:
    mock_conn.execute.return_value.fetchone.return_value = {"total": 15}
    repo = OrderRepository(mock_conn)
    result = repo.sum_quantity_by_statuses("S1", ["RESERVED", "CONFIRMED", "PRODUCING"])
    assert result == 15
    mock_conn.execute.assert_called_once_with(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
        "WHERE sample_id = ? AND status IN (?,?,?)",
        ("S1", "RESERVED", "CONFIRMED", "PRODUCING"),
    )
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `pytest tests/storage/test_order_repository.py -v`
Expected: FAIL with `AttributeError: 'OrderRepository' object has no attribute 'sum_quantity_by_status'`

- [ ] **Step 11: Implement `sum_quantity_by_status` and `sum_quantity_by_statuses`**

Add to the `OrderRepository` class in `semi/storage/order_repository.py`:

```python
    def sum_quantity_by_status(self, sample_id: str, status: OrderStatus) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
            "WHERE sample_id = ? AND status = ?",
            (sample_id, status),
        ).fetchone()
        return row["total"]

    def sum_quantity_by_statuses(
        self, sample_id: str, statuses: list[OrderStatus]
    ) -> int:
        placeholders = ",".join("?" for _ in statuses)
        row = self.conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
            f"WHERE sample_id = ? AND status IN ({placeholders})",
            (sample_id, *statuses),
        ).fetchone()
        return row["total"]
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `pytest tests/storage/test_order_repository.py -v`
Expected: PASS (6 passed)

- [ ] **Step 13: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/storage/order_repository.py tests/storage/test_order_repository.py
git commit -m "feat(storage): add OrderRepository"
```

---

### Task 4: `ProductionJobRepository`

**Files:**
- Create: `semi/storage/production_job_repository.py`
- Test: `tests/storage/test_production_job_repository.py`

**Interfaces:**
- Consumes: `semi.storage.exceptions.NotFoundError`, `mock_conn` fixture (Task 1); `ProductionJob`/`JobStatus`/`OrderStatus` from `semi.domain.models` — patched per-test via `mocker.patch("semi.storage.production_job_repository.<Name>")`, never imported for real.
- Produces (for the out-of-scope `services` plan, not used elsewhere in this plan): `semi.storage.production_job_repository.ProductionJobRepository(conn)` with `create(order_id, sample_id, shortfall_quantity, actual_quantity, total_duration_seconds) -> ProductionJob`, `get_by_order_id(order_id) -> ProductionJob`, `list_producing_with_shortfall(sample_id) -> list[tuple[int, int]]`, `get_current_in_progress() -> ProductionJob | None`, `list_queued_fifo() -> list[ProductionJob]`, `mark_in_progress(job_id, started_at) -> None`, `mark_done(job_id) -> None`.

- [ ] **Step 1: Write failing tests for `create` and `get_by_order_id`**

`tests/storage/test_production_job_repository.py`:

```python
from datetime import datetime

import pytest

from semi.storage.exceptions import NotFoundError
from semi.storage.production_job_repository import ProductionJobRepository


def test_create_inserts_row_and_returns_mapped_job(mock_conn, mocker) -> None:
    job_cls = mocker.patch("semi.storage.production_job_repository.ProductionJob")
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")
    fixed_now = datetime(2026, 1, 1, 12, 0, 0)
    mock_datetime = mocker.patch("semi.storage.production_job_repository.datetime")
    mock_datetime.now.return_value = fixed_now
    mock_conn.execute.return_value.fetchone.return_value = {
        "job_id": 1,
        "order_id": 7,
        "sample_id": "S1",
        "shortfall_quantity": 3,
        "actual_quantity": 4,
        "total_duration_seconds": 40.0,
        "status": "QUEUED",
        "enqueued_at": fixed_now.isoformat(),
        "started_at": None,
    }

    repo = ProductionJobRepository(mock_conn)
    result = repo.create(
        7, "S1", shortfall_quantity=3, actual_quantity=4, total_duration_seconds=40.0
    )

    mock_conn.execute.assert_any_call(
        "INSERT INTO production_jobs "
        "(order_id, sample_id, shortfall_quantity, actual_quantity, "
        "total_duration_seconds, status, enqueued_at, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
        (7, "S1", 3, 4, 40.0, job_status.QUEUED, fixed_now.isoformat()),
    )
    job_cls.assert_called_once_with(
        job_id=1,
        order_id=7,
        sample_id="S1",
        shortfall_quantity=3,
        actual_quantity=4,
        total_duration_seconds=40.0,
        status=job_status.return_value,
        enqueued_at=fixed_now,
        started_at=None,
    )
    assert result is job_cls.return_value


def test_get_by_order_id_raises_not_found_when_row_missing(mock_conn, mocker) -> None:
    mocker.patch("semi.storage.production_job_repository.ProductionJob")
    mocker.patch("semi.storage.production_job_repository.JobStatus")
    mock_conn.execute.return_value.fetchone.return_value = None

    repo = ProductionJobRepository(mock_conn)
    with pytest.raises(NotFoundError):
        repo.get_by_order_id(999)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_production_job_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.storage.production_job_repository'`

- [ ] **Step 3: Implement `create` and `get_by_order_id`**

`semi/storage/production_job_repository.py`:

```python
import sqlite3
from datetime import datetime

from semi.domain.models import JobStatus, OrderStatus, ProductionJob
from semi.storage._datetime import from_iso, to_iso
from semi.storage.exceptions import NotFoundError


class ProductionJobRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        order_id: int,
        sample_id: str,
        shortfall_quantity: int,
        actual_quantity: int,
        total_duration_seconds: float,
    ) -> ProductionJob:
        self.conn.execute(
            "INSERT INTO production_jobs "
            "(order_id, sample_id, shortfall_quantity, actual_quantity, "
            "total_duration_seconds, status, enqueued_at, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                order_id,
                sample_id,
                shortfall_quantity,
                actual_quantity,
                total_duration_seconds,
                JobStatus.QUEUED,
                to_iso(datetime.now()),
            ),
        )
        return self.get_by_order_id(order_id)

    def get_by_order_id(self, order_id: int) -> ProductionJob:
        row = self.conn.execute(
            "SELECT * FROM production_jobs WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"order_id={order_id!r} has no production job")
        return _row_to_job(row)


def _row_to_job(row: sqlite3.Row) -> ProductionJob:
    return ProductionJob(
        job_id=row["job_id"],
        order_id=row["order_id"],
        sample_id=row["sample_id"],
        shortfall_quantity=row["shortfall_quantity"],
        actual_quantity=row["actual_quantity"],
        total_duration_seconds=row["total_duration_seconds"],
        status=JobStatus(row["status"]),
        enqueued_at=from_iso(row["enqueued_at"]),
        started_at=from_iso(row["started_at"]) if row["started_at"] is not None else None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_production_job_repository.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Add failing tests for `list_producing_with_shortfall`**

Append to `tests/storage/test_production_job_repository.py`:

```python
def test_list_producing_with_shortfall_returns_raw_pairs(mock_conn, mocker) -> None:
    order_status = mocker.patch("semi.storage.production_job_repository.OrderStatus")
    mock_conn.execute.return_value.fetchall.return_value = [
        {"quantity": 5, "shortfall_quantity": 3},
    ]

    repo = ProductionJobRepository(mock_conn)
    result = repo.list_producing_with_shortfall("S1")

    mock_conn.execute.assert_called_once_with(
        "SELECT o.quantity, pj.shortfall_quantity FROM production_jobs pj "
        "JOIN orders o ON o.order_id = pj.order_id "
        "WHERE o.sample_id = ? AND o.status = ?",
        ("S1", order_status.PRODUCING),
    )
    assert result == [(5, 3)]
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/storage/test_production_job_repository.py -v`
Expected: FAIL with `AttributeError: 'ProductionJobRepository' object has no attribute 'list_producing_with_shortfall'`

- [ ] **Step 7: Implement `list_producing_with_shortfall`**

Add to the `ProductionJobRepository` class in `semi/storage/production_job_repository.py`:

```python
    def list_producing_with_shortfall(self, sample_id: str) -> list[tuple[int, int]]:
        rows = self.conn.execute(
            "SELECT o.quantity, pj.shortfall_quantity FROM production_jobs pj "
            "JOIN orders o ON o.order_id = pj.order_id "
            "WHERE o.sample_id = ? AND o.status = ?",
            (sample_id, OrderStatus.PRODUCING),
        ).fetchall()
        return [(row["quantity"], row["shortfall_quantity"]) for row in rows]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/storage/test_production_job_repository.py -v`
Expected: PASS (3 passed)

- [ ] **Step 9: Add failing tests for `get_current_in_progress`, `list_queued_fifo`, `mark_in_progress`, `mark_done`**

Append to `tests/storage/test_production_job_repository.py`:

```python
def test_get_current_in_progress_returns_none_when_empty(mock_conn, mocker) -> None:
    mocker.patch("semi.storage.production_job_repository.JobStatus")
    mock_conn.execute.return_value.fetchone.return_value = None

    repo = ProductionJobRepository(mock_conn)
    assert repo.get_current_in_progress() is None


def test_get_current_in_progress_maps_row_when_present(mock_conn, mocker) -> None:
    job_cls = mocker.patch("semi.storage.production_job_repository.ProductionJob")
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")
    mock_conn.execute.return_value.fetchone.return_value = {
        "job_id": 1,
        "order_id": 7,
        "sample_id": "S1",
        "shortfall_quantity": 3,
        "actual_quantity": 4,
        "total_duration_seconds": 40.0,
        "status": "IN_PROGRESS",
        "enqueued_at": "2026-01-01T00:00:00",
        "started_at": "2026-01-01T00:05:00",
    }

    repo = ProductionJobRepository(mock_conn)
    result = repo.get_current_in_progress()

    mock_conn.execute.assert_called_once_with(
        "SELECT * FROM production_jobs WHERE status = ?", (job_status.IN_PROGRESS,)
    )
    assert result is job_cls.return_value


def test_list_queued_fifo_orders_by_enqueued_at_then_job_id(mock_conn, mocker) -> None:
    job_cls = mocker.patch("semi.storage.production_job_repository.ProductionJob")
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "job_id": 1,
            "order_id": 1,
            "sample_id": "S1",
            "shortfall_quantity": 1,
            "actual_quantity": 2,
            "total_duration_seconds": 20.0,
            "status": "QUEUED",
            "enqueued_at": "2026-01-01T00:00:00",
            "started_at": None,
        },
        {
            "job_id": 2,
            "order_id": 2,
            "sample_id": "S1",
            "shortfall_quantity": 1,
            "actual_quantity": 2,
            "total_duration_seconds": 20.0,
            "status": "QUEUED",
            "enqueued_at": "2026-01-01T00:01:00",
            "started_at": None,
        },
    ]

    repo = ProductionJobRepository(mock_conn)
    result = repo.list_queued_fifo()

    mock_conn.execute.assert_called_once_with(
        "SELECT * FROM production_jobs WHERE status = ? ORDER BY enqueued_at, job_id",
        (job_status.QUEUED,),
    )
    assert result == [job_cls.return_value, job_cls.return_value]


def test_mark_in_progress_executes_update(mock_conn, mocker) -> None:
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")
    started_at = datetime(2026, 1, 1, 12, 0, 0)

    repo = ProductionJobRepository(mock_conn)
    repo.mark_in_progress(1, started_at)

    mock_conn.execute.assert_called_once_with(
        "UPDATE production_jobs SET status = ?, started_at = ? WHERE job_id = ?",
        (job_status.IN_PROGRESS, started_at.isoformat(), 1),
    )


def test_mark_done_executes_update(mock_conn, mocker) -> None:
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")

    repo = ProductionJobRepository(mock_conn)
    repo.mark_done(1)

    mock_conn.execute.assert_called_once_with(
        "UPDATE production_jobs SET status = ? WHERE job_id = ?",
        (job_status.DONE, 1),
    )
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `pytest tests/storage/test_production_job_repository.py -v`
Expected: FAIL with `AttributeError: 'ProductionJobRepository' object has no attribute 'get_current_in_progress'`

- [ ] **Step 11: Implement `get_current_in_progress`, `list_queued_fifo`, `mark_in_progress`, `mark_done`**

Add to the `ProductionJobRepository` class in `semi/storage/production_job_repository.py`:

```python
    def get_current_in_progress(self) -> ProductionJob | None:
        row = self.conn.execute(
            "SELECT * FROM production_jobs WHERE status = ?", (JobStatus.IN_PROGRESS,)
        ).fetchone()
        return _row_to_job(row) if row is not None else None

    def list_queued_fifo(self) -> list[ProductionJob]:
        rows = self.conn.execute(
            "SELECT * FROM production_jobs WHERE status = ? ORDER BY enqueued_at, job_id",
            (JobStatus.QUEUED,),
        ).fetchall()
        return [_row_to_job(row) for row in rows]

    def mark_in_progress(self, job_id: int, started_at: datetime) -> None:
        self.conn.execute(
            "UPDATE production_jobs SET status = ?, started_at = ? WHERE job_id = ?",
            (JobStatus.IN_PROGRESS, to_iso(started_at), job_id),
        )

    def mark_done(self, job_id: int) -> None:
        self.conn.execute(
            "UPDATE production_jobs SET status = ? WHERE job_id = ?",
            (JobStatus.DONE, job_id),
        )
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `pytest tests/storage/test_production_job_repository.py -v`
Expected: PASS (8 passed)

- [ ] **Step 13: Run the full test suite**

Run: `pytest -v`
Expected: all tests in `tests/storage` PASS (28 passed)

- [ ] **Step 14: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/storage/production_job_repository.py tests/storage/test_production_job_repository.py
git commit -m "feat(storage): add ProductionJobRepository"
```

---

## Out of scope

- `semi/domain/*` — mocked in tests as described above, not implemented by this plan.
- `threading.Lock`-wrapped transactions, `commit()`/`rollback()` calls, and the "available stock"/shortfall/production-duration formulas (services-design.md §2-5) — repositories here only ever expose raw data.
- `semi/scheduler/background_worker.py` and `semi/cli/*` — depend on `services`, not on `storage` directly.
