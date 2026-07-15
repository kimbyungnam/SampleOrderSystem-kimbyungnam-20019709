# Service Layer Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplication and tighten a few loose ends in `semi/services` and `semi/storage` that were flagged in code review, without changing any observable behavior.

**Architecture:** Four independent, small refactors: (1) extract the repeated lock/commit/rollback boilerplate in `OrderService`/`ProductionService` into a shared mixin, (2) collapse `OrderRepository.sum_quantity_by_status` into `sum_quantity_by_statuses` and fix its type hint, (3) extract the shortfall/actual-quantity/duration formula out of `OrderService.approve` into a pure, independently-testable function, (4) generate the `CHECK (status IN (...))` clauses in the DB schema from the `OrderStatus`/`JobStatus` enums instead of hand-duplicated string literals.

**Tech Stack:** Python 3.14, pytest, pytest-mock, sqlite3 (stdlib).

## Global Constraints

- No behavior change: every existing test in `tests/` must keep passing unmodified except where a task explicitly says to update a test (only Task 2 touches an existing test's expected SQL).
- Follow existing code style: no comments unless non-obvious, type hints on public methods, `DomainError`/`NotFoundError` usage unchanged.
- Run `ruff check --fix .` and `ruff format .` after each task's implementation step, before committing.

---

### Task 1: Extract transaction lock/commit/rollback boilerplate

**Files:**
- Create: `semi/services/transactional.py`
- Modify: `semi/services/order_service.py` (`reject`, `approve`, `release` methods, `OrderService` class declaration)
- Modify: `semi/services/production_service.py` (`tick` method, `ProductionService` class declaration)
- Test: Create `tests/test_transactional.py`

**Interfaces:**
- Produces: `TransactionalMixin` class in `semi/services/transactional.py` with a `_transaction()` context manager. Any class using it must set `self._order_repo` (an object with `.conn`, a connection exposing `.commit()`/`.rollback()`) and `self._lock` (a `threading.Lock`-like object) before calling `_transaction()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transactional.py
import pytest

from semi.services.transactional import TransactionalMixin


class _FakeRepo:
    def __init__(self, conn):
        self.conn = conn


class _FakeService(TransactionalMixin):
    def __init__(self, conn, lock):
        self._order_repo = _FakeRepo(conn)
        self._lock = lock


def test_transaction_commits_on_success(conn, lock):
    service = _FakeService(conn, lock)
    with service._transaction():
        pass
    assert conn.committed is True
    assert conn.rolled_back is False


def test_transaction_rolls_back_and_reraises_on_exception(conn, lock):
    service = _FakeService(conn, lock)
    with pytest.raises(ValueError):
        with service._transaction():
            raise ValueError("boom")
    assert conn.committed is False
    assert conn.rolled_back is True
```

(`conn` and `lock` fixtures already exist in `tests/conftest.py` — `FakeConnection` and a `threading.Lock`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transactional.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.services.transactional'`

- [ ] **Step 3: Write the mixin**

```python
# semi/services/transactional.py
from contextlib import contextmanager


class TransactionalMixin:
    @contextmanager
    def _transaction(self):
        with self._lock:
            try:
                yield
                self._order_repo.conn.commit()
            except Exception:
                self._order_repo.conn.rollback()
                raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transactional.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Wire `OrderService` to use the mixin**

In `semi/services/order_service.py`, change the class declaration and the three methods that currently repeat `with self._lock: try: ... commit() except Exception: rollback(); raise`:

```python
import math

from semi.domain.models import Order, OrderStatus
from semi.services.exceptions import DomainError
from semi.services.transactional import TransactionalMixin


class OrderService(TransactionalMixin):
    def __init__(self, order_repo, job_repo, sample_repo, lock):
        assert order_repo.conn is sample_repo.conn, (
            "OrderRepository and SampleRepository must share the same connection"
        )
        assert order_repo.conn is job_repo.conn, (
            "OrderRepository and ProductionJobRepository must share the same connection"
        )
        self._order_repo = order_repo
        self._job_repo = job_repo
        self._sample_repo = sample_repo
        self._lock = lock

    def create_order(self, sample_id, customer_name, quantity) -> Order:
        if quantity <= 0:
            raise DomainError(f"quantity must be > 0, got {quantity}")
        if not self._sample_repo.exists(sample_id):
            raise DomainError(f"unknown sample_id: {sample_id}")
        order = self._order_repo.create(sample_id, customer_name, quantity)
        self._order_repo.conn.commit()
        return order

    def reject(self, order_id) -> Order:
        with self._transaction():
            order = self._order_repo.get_by_id(order_id)
            if order.status != OrderStatus.RESERVED:
                raise DomainError(
                    f"order {order_id} is not RESERVED (status={order.status})"
                )
            self._order_repo.update_status(order_id, OrderStatus.REJECTED)
        return self._order_repo.get_by_id(order_id)

    def approve(self, order_id) -> Order:
        with self._transaction():
            order = self._order_repo.get_by_id(order_id)
            if order.status != OrderStatus.RESERVED:
                raise DomainError(
                    f"order {order_id} is not RESERVED (status={order.status})"
                )
            sample = self._sample_repo.get_by_id(order.sample_id)
            available = self._available_stock(sample)
            if available >= order.quantity:
                self._order_repo.update_status(order_id, OrderStatus.CONFIRMED)
            else:
                shortfall = order.quantity - available
                actual_quantity = math.ceil(shortfall / sample.yield_rate)
                total_duration_seconds = sample.avg_production_seconds * actual_quantity
                self._job_repo.create(
                    order_id,
                    sample.sample_id,
                    shortfall,
                    actual_quantity,
                    total_duration_seconds,
                )
                self._order_repo.update_status(order_id, OrderStatus.PRODUCING)
        return self._order_repo.get_by_id(order_id)

    def release(self, order_id) -> Order:
        with self._transaction():
            order = self._order_repo.get_by_id(order_id)
            if order.status != OrderStatus.CONFIRMED:
                raise DomainError(
                    f"order {order_id} is not CONFIRMED (status={order.status})"
                )
            self._sample_repo.decrement_stock(order.sample_id, order.quantity)
            self._order_repo.update_status(order_id, OrderStatus.RELEASE)
        return self._order_repo.get_by_id(order_id)

    def _available_stock(self, sample) -> int:
        confirmed_sum = self._order_repo.sum_quantity_by_status(
            sample.sample_id, OrderStatus.CONFIRMED
        )
        producing_reserved_sum = sum(
            qty - shortfall
            for qty, shortfall in self._job_repo.list_producing_with_shortfall(
                sample.sample_id
            )
        )
        return sample.stock_quantity - confirmed_sum - producing_reserved_sum
```

(The `math.ceil`/shortfall math here will be replaced again in Task 3 — leave it as-is for this task.)

- [ ] **Step 6: Wire `ProductionService` to use the mixin**

In `semi/services/production_service.py`, change the class declaration and `tick`:

```python
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from semi.domain.models import OrderStatus, ProductionJob
from semi.services.transactional import TransactionalMixin


@dataclass(frozen=True)
class ProductionJobStatus:
    job: ProductionJob
    progress_ratio: float
    produced_so_far: int
    estimated_completion_at: datetime


class ProductionService(TransactionalMixin):
    def __init__(self, order_repo, job_repo, sample_repo, lock):
        assert order_repo.conn is sample_repo.conn, (
            "OrderRepository and SampleRepository must share the same connection"
        )
        assert order_repo.conn is job_repo.conn, (
            "OrderRepository and ProductionJobRepository must share the same connection"
        )
        self._order_repo = order_repo
        self._job_repo = job_repo
        self._sample_repo = sample_repo
        self._lock = lock

    def tick(self) -> None:
        with self._transaction():
            self._promote_if_idle()
            current = self._job_repo.get_current_in_progress()
            if current is not None:
                elapsed = (datetime.now() - current.started_at).total_seconds()
                if elapsed >= current.total_duration_seconds:
                    self._sample_repo.increment_stock(
                        current.sample_id, current.actual_quantity
                    )
                    self._order_repo.update_status(
                        current.order_id, OrderStatus.CONFIRMED
                    )
                    self._job_repo.mark_done(current.job_id)
                    self._promote_if_idle()

    def _promote_if_idle(self) -> None:
        if self._job_repo.get_current_in_progress() is not None:
            return
        queue = self._job_repo.list_queued_fifo()
        if queue:
            self._job_repo.mark_in_progress(queue[0].job_id, datetime.now())

    def get_current_status(self) -> ProductionJobStatus | None:
        job = self._job_repo.get_current_in_progress()
        if job is None:
            return None
        now = datetime.now()
        elapsed = (now - job.started_at).total_seconds()
        progress_ratio = min(1.0, elapsed / job.total_duration_seconds)
        produced_so_far = math.floor(progress_ratio * job.actual_quantity)
        estimated_completion_at = job.started_at + timedelta(
            seconds=job.total_duration_seconds
        )
        return ProductionJobStatus(
            job, progress_ratio, produced_so_far, estimated_completion_at
        )

    def list_queue_status(self) -> list[ProductionJobStatus]:
        now = datetime.now()
        current = self._job_repo.get_current_in_progress()
        cumulative_seconds = 0.0
        if current is not None:
            elapsed = (now - current.started_at).total_seconds()
            cumulative_seconds = max(0.0, current.total_duration_seconds - elapsed)

        statuses = []
        for job in self._job_repo.list_queued_fifo():
            cumulative_seconds += job.total_duration_seconds
            estimated_completion_at = now + timedelta(seconds=cumulative_seconds)
            statuses.append(ProductionJobStatus(job, 0.0, 0, estimated_completion_at))
        return statuses
```

- [ ] **Step 7: Run the full test suite to confirm no regressions**

Run: `pytest tests/ -v`
Expected: PASS, all tests green (in particular `tests/test_order_service.py` and `tests/test_production_service.py`, which exercise `reject`/`approve`/`release`/`tick` behavior end to end via the fakes).

- [ ] **Step 8: Lint and format**

Run: `ruff check --fix . && ruff format .`

- [ ] **Step 9: Commit**

```bash
git add semi/services/transactional.py semi/services/order_service.py semi/services/production_service.py tests/test_transactional.py
git commit -m "refactor(services): extract shared transaction lock/commit/rollback into TransactionalMixin"
```

---

### Task 2: Collapse `sum_quantity_by_status` into `sum_quantity_by_statuses`

**Files:**
- Modify: `semi/storage/order_repository.py:46-63`
- Test: Modify `tests/storage/test_order_repository.py:85-94` (`test_sum_quantity_by_status_returns_total`)

**Interfaces:**
- Produces: `OrderRepository.sum_quantity_by_status(sample_id: str, status: OrderStatus) -> int` (unchanged signature/behavior, now implemented in terms of `sum_quantity_by_statuses`), `OrderRepository.sum_quantity_by_statuses(sample_id: str, statuses: Sequence[OrderStatus]) -> int` (type hint changed from `list[OrderStatus]` to `Sequence[OrderStatus]` to match its real callers, e.g. `MonitoringService` passing a tuple).

- [ ] **Step 1: Update the existing test's expected SQL first (it currently pins the old duplicated query)**

```python
# tests/storage/test_order_repository.py
def test_sum_quantity_by_status_returns_total(mock_conn) -> None:
    mock_conn.execute.return_value.fetchone.return_value = {"total": 12}
    repo = OrderRepository(mock_conn)
    result = repo.sum_quantity_by_status("S1", "CONFIRMED")
    assert result == 12
    mock_conn.execute.assert_called_once_with(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
        "WHERE sample_id = ? AND status IN (?)",
        ("S1", "CONFIRMED"),
    )
```

- [ ] **Step 2: Run test to verify it fails against the current implementation**

Run: `pytest tests/storage/test_order_repository.py::test_sum_quantity_by_status_returns_total -v`
Expected: FAIL — actual call was `"...status = ?"` not `"...status IN (?)"`.

- [ ] **Step 3: Implement the delegation**

```python
# semi/storage/order_repository.py
import sqlite3
from collections.abc import Sequence
from datetime import datetime

from semi.domain.models import Order, OrderStatus
from semi.storage._datetime import from_iso, to_iso
from semi.storage.exceptions import NotFoundError


class OrderRepository:
    # ... create / get_by_id / list_by_status / update_status unchanged ...

    def sum_quantity_by_status(self, sample_id: str, status: OrderStatus) -> int:
        return self.sum_quantity_by_statuses(sample_id, (status,))

    def sum_quantity_by_statuses(
        self, sample_id: str, statuses: Sequence[OrderStatus]
    ) -> int:
        placeholders = ",".join("?" for _ in statuses)
        row = self.conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
            f"WHERE sample_id = ? AND status IN ({placeholders})",
            (sample_id, *statuses),
        ).fetchone()
        return row["total"]
```

Only the two method bodies and the new `Sequence` import change; everything else in the file (imports, `create`, `get_by_id`, `list_by_status`, `update_status`, `_row_to_order`) stays as-is.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/storage/test_order_repository.py -v`
Expected: PASS (all tests in the file, including `test_sum_quantity_by_statuses_returns_total` which is unaffected)

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS — `tests/test_order_service.py` and `tests/test_monitoring_service.py` use the `Fake*Repository` versions from `tests/conftest.py`, not the real SQL, so they're unaffected. `tests/storage/test_order_repository.py::test_order_repo_sum_quantity_by_status` (the real-sqlite functional test) only checks the resulting integer, not the SQL shape, so it stays green.

- [ ] **Step 6: Lint and format**

Run: `ruff check --fix . && ruff format .`

- [ ] **Step 7: Commit**

```bash
git add semi/storage/order_repository.py tests/storage/test_order_repository.py
git commit -m "refactor(storage): implement sum_quantity_by_status via sum_quantity_by_statuses"
```

---

### Task 3: Extract shortfall/actual-quantity/duration formula into a pure function

**Files:**
- Create: `semi/services/production_math.py`
- Modify: `semi/services/order_service.py` (`approve` method)
- Test: Create `tests/test_production_math.py`

**Interfaces:**
- Consumes: nothing beyond stdlib `math`.
- Produces: `compute_shortfall_job(order_quantity: int, available: int, yield_rate: float, avg_production_seconds: float) -> tuple[int, int, float]` returning `(shortfall, actual_quantity, total_duration_seconds)`, used by `OrderService.approve`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_production_math.py
from semi.services.production_math import compute_shortfall_job


def test_compute_shortfall_job_from_zero_available_stock():
    shortfall, actual_quantity, total_duration_seconds = compute_shortfall_job(
        order_quantity=5, available=0, yield_rate=0.9, avg_production_seconds=10.0
    )
    assert shortfall == 5
    assert actual_quantity == 6  # ceil(5 / 0.9)
    assert total_duration_seconds == 60.0


def test_compute_shortfall_job_from_partial_available_stock():
    shortfall, actual_quantity, total_duration_seconds = compute_shortfall_job(
        order_quantity=5, available=3, yield_rate=1.0, avg_production_seconds=10.0
    )
    assert shortfall == 2
    assert actual_quantity == 2
    assert total_duration_seconds == 20.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_production_math.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.services.production_math'`

- [ ] **Step 3: Write the function**

```python
# semi/services/production_math.py
import math


def compute_shortfall_job(
    order_quantity: int,
    available: int,
    yield_rate: float,
    avg_production_seconds: float,
) -> tuple[int, int, float]:
    shortfall = order_quantity - available
    actual_quantity = math.ceil(shortfall / yield_rate)
    total_duration_seconds = avg_production_seconds * actual_quantity
    return shortfall, actual_quantity, total_duration_seconds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_production_math.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Use it from `OrderService.approve`**

In `semi/services/order_service.py`, drop the now-unused `import math` and replace the inline computation in `approve`:

```python
from semi.domain.models import Order, OrderStatus
from semi.services.exceptions import DomainError
from semi.services.production_math import compute_shortfall_job
from semi.services.transactional import TransactionalMixin


class OrderService(TransactionalMixin):
    # ... __init__, create_order, reject unchanged ...

    def approve(self, order_id) -> Order:
        with self._transaction():
            order = self._order_repo.get_by_id(order_id)
            if order.status != OrderStatus.RESERVED:
                raise DomainError(
                    f"order {order_id} is not RESERVED (status={order.status})"
                )
            sample = self._sample_repo.get_by_id(order.sample_id)
            available = self._available_stock(sample)
            if available >= order.quantity:
                self._order_repo.update_status(order_id, OrderStatus.CONFIRMED)
            else:
                shortfall, actual_quantity, total_duration_seconds = (
                    compute_shortfall_job(
                        order.quantity,
                        available,
                        sample.yield_rate,
                        sample.avg_production_seconds,
                    )
                )
                self._job_repo.create(
                    order_id,
                    sample.sample_id,
                    shortfall,
                    actual_quantity,
                    total_duration_seconds,
                )
                self._order_repo.update_status(order_id, OrderStatus.PRODUCING)
        return self._order_repo.get_by_id(order_id)

    # ... release, _available_stock unchanged ...
```

- [ ] **Step 6: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS — `tests/test_order_service.py::test_approve_queues_production_job_when_stock_insufficient` and `test_approve_excludes_producing_orders_original_stock_claim_from_available_stock` exercise this path end to end and assert the exact `shortfall_quantity`/`actual_quantity`/`total_duration_seconds` values, so they double as regression tests for the extraction.

- [ ] **Step 7: Lint and format**

Run: `ruff check --fix . && ruff format .`

- [ ] **Step 8: Commit**

```bash
git add semi/services/production_math.py semi/services/order_service.py tests/test_production_math.py
git commit -m "refactor(services): extract shortfall/actual-quantity/duration formula into compute_shortfall_job"
```

---

### Task 4: Generate schema `CHECK (status IN (...))` clauses from the enums

**Files:**
- Modify: `semi/storage/db.py`
- Test: Modify `tests/storage/test_db.py` (add one new test)

**Interfaces:**
- Consumes: `OrderStatus`, `JobStatus` from `semi/domain/models.py`.
- Produces: `SCHEMA_SQL` (module-level constant, same name/type as before — a `str`) with its two status `CHECK` clauses built from the enums instead of hand-typed literals. `connect_db` signature/behavior unchanged.

- [ ] **Step 1: Write the failing test (proves the generated clause actually accepts every real enum value)**

```python
# tests/storage/test_db.py — add after test_production_jobs_check_constraint_rejects_invalid_status
def test_orders_check_constraint_accepts_every_order_status_value(
    tmp_path: Path,
) -> None:
    from semi.domain.models import OrderStatus

    conn = connect_db(tmp_path / "test.db")
    conn.execute(
        "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate) "
        "VALUES ('S1', 'wafer', 10.0, 0.9)"
    )
    for status in OrderStatus:
        conn.execute(
            "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
            "VALUES ('S1', 'acme', 1, ?, '2026-01-01T00:00:00')",
            (status.value,),
        )
    conn.close()
```

This passes against the current hand-written schema too (it's not a red/green step for behavior change, just a safety net) — the point is to confirm it still passes after Step 3's rewrite, which is the real regression risk (a typo or missing enum member in the generated SQL).

- [ ] **Step 2: Run test to verify it passes against the current implementation (sanity baseline)**

Run: `pytest tests/storage/test_db.py::test_orders_check_constraint_accepts_every_order_status_value -v`
Expected: PASS (this establishes the baseline before the refactor; it must still pass after Step 3)

- [ ] **Step 3: Generate the CHECK clauses from the enums**

```python
# semi/storage/db.py
import sqlite3
from pathlib import Path

from semi.domain.models import JobStatus, OrderStatus

_ORDER_STATUSES = ", ".join(f"'{status.value}'" for status in OrderStatus)
_JOB_STATUSES = ", ".join(f"'{status.value}'" for status in JobStatus)

SCHEMA_SQL = f"""
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
    status        TEXT NOT NULL CHECK (status IN ({_ORDER_STATUSES})),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS production_jobs (
    job_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id             INTEGER NOT NULL UNIQUE REFERENCES orders(order_id),
    sample_id            TEXT NOT NULL REFERENCES samples(sample_id),
    shortfall_quantity   INTEGER NOT NULL,
    actual_quantity      INTEGER NOT NULL,
    total_duration_seconds REAL NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ({_JOB_STATUSES})),
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

- [ ] **Step 4: Run test to verify it still passes**

Run: `pytest tests/storage/test_db.py -v`
Expected: PASS, all tests including the new one and the existing `test_orders_check_constraints_reject_invalid_values` / `test_production_jobs_check_constraint_rejects_invalid_status` (which insert `'BOGUS'` and expect `sqlite3.IntegrityError`).

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions anywhere else (no other module reads `SCHEMA_SQL` directly).

- [ ] **Step 6: Lint and format**

Run: `ruff check --fix . && ruff format .`

- [ ] **Step 7: Commit**

```bash
git add semi/storage/db.py tests/storage/test_db.py
git commit -m "refactor(storage): derive schema status CHECK clauses from OrderStatus/JobStatus enums"
```
