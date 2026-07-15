# Services Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `semi/services` (`SampleService`, `OrderService`, `ProductionService`, `MonitoringService`) per `docs/superpowers/specs/2026-07-15-services-design.md`, along with the minimal `semi/domain` dataclasses/enums and `semi/storage` exception type these services depend on.

**Architecture:** Bottom-up: domain dataclasses/enums first (pure data, no logic), then the `storage.NotFoundError` exception type, then one services module per class, each built with TDD against hand-written **in-memory fake repositories** (defined in `tests/conftest.py`) that implement the exact method signatures from `docs/superpowers/specs/2026-07-15-storage-design.md` §3. The real SQLite-backed repositories (`semi/storage/*_repository.py`, `semi/storage/db.py`) are **out of scope for this plan** — a future plan implements them against the same interface, at which point these fakes can be deleted and the same service tests should keep passing unchanged against a real-DB fixture.

**Tech Stack:** Python 3.14+, `pytest` + `pytest-mock` (the `test` extra in `pyproject.toml`), `ruff` for lint/format.

## Global Constraints

- Target Python 3.14+ (use `StrEnum`, PEP 604 `X | None` unions).
- Domain dataclasses are `@dataclass(frozen=True)` with **no validation/transition logic** — that's 100% a services-layer responsibility (per `2026-07-15-domain-design.md` §3).
- Every write-transaction service method that spans multiple repositories commits/rolls back exactly once, itself, via `<repo>.conn.commit()` / `.conn.rollback()` — repositories (real or fake) never commit.
- `OrderService` and `ProductionService` each take a shared `lock` (`threading.Lock`) and wrap every write method (`approve`, `reject`, `release`, `tick`) in `with self._lock: ... try/except: rollback`. `create_order` and read-only methods do not take the lock (per `DESIGN.md` §5, only 승인/거절/출고/tick are serialized).
- `OrderService.__init__` and `ProductionService.__init__` must `assert` that all injected repositories share the same `.conn` object.
- Validation/state-transition violations raise `semi.services.exceptions.DomainError`. Lookup-miss (`get_by_id` etc.) raises `semi.storage.exceptions.NotFoundError` and is **not** caught/converted — it propagates as-is.
- Run `ruff check --fix .` and `ruff format .` after every task, before committing.
- Commit messages follow Conventional Commits (there's a `commitizen` hook on `commit-msg`).

---

### Task 1: Domain layer — enums and dataclasses

**Files:**
- Create: `semi/domain/__init__.py`
- Create: `semi/domain/models.py`
- Test: `tests/test_domain_models.py`

**Interfaces:**
- Produces: `OrderStatus` (`StrEnum`: `RESERVED`, `REJECTED`, `PRODUCING`, `CONFIRMED`, `RELEASE`), `JobStatus` (`StrEnum`: `QUEUED`, `IN_PROGRESS`, `DONE`), `Sample(sample_id, name, avg_production_seconds, yield_rate, stock_quantity)`, `Order(order_id, sample_id, customer_name, quantity, status, created_at)`, `ProductionJob(job_id, order_id, sample_id, shortfall_quantity, actual_quantity, total_duration_seconds, status, enqueued_at, started_at)`. All later tasks import these from `semi.domain.models`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_domain_models.py`:

```python
import dataclasses
from datetime import datetime

import pytest

from semi.domain.models import JobStatus, Order, OrderStatus, ProductionJob, Sample


def test_order_status_values():
    assert list(OrderStatus) == [
        OrderStatus.RESERVED,
        OrderStatus.REJECTED,
        OrderStatus.PRODUCING,
        OrderStatus.CONFIRMED,
        OrderStatus.RELEASE,
    ]
    assert OrderStatus.RESERVED == "RESERVED"


def test_job_status_values():
    assert list(JobStatus) == [JobStatus.QUEUED, JobStatus.IN_PROGRESS, JobStatus.DONE]
    assert JobStatus.QUEUED == "QUEUED"


def test_sample_is_frozen():
    sample = Sample(
        sample_id="S1",
        name="Wafer A",
        avg_production_seconds=10.0,
        yield_rate=0.9,
        stock_quantity=5,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        sample.stock_quantity = 6


def test_order_is_frozen():
    order = Order(
        order_id=1,
        sample_id="S1",
        customer_name="ACME",
        quantity=3,
        status=OrderStatus.RESERVED,
        created_at=datetime.now(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        order.status = OrderStatus.REJECTED


def test_production_job_is_frozen_and_allows_none_started_at():
    job = ProductionJob(
        job_id=1,
        order_id=1,
        sample_id="S1",
        shortfall_quantity=2,
        actual_quantity=3,
        total_duration_seconds=30.0,
        status=JobStatus.QUEUED,
        enqueued_at=datetime.now(),
        started_at=None,
    )
    assert job.started_at is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        job.status = JobStatus.IN_PROGRESS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_domain_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.domain'`

- [ ] **Step 3: Write minimal implementation**

Create `semi/domain/__init__.py` (empty file).

Create `semi/domain/models.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OrderStatus(StrEnum):
    RESERVED = "RESERVED"
    REJECTED = "REJECTED"
    PRODUCING = "PRODUCING"
    CONFIRMED = "CONFIRMED"
    RELEASE = "RELEASE"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


@dataclass(frozen=True)
class Sample:
    sample_id: str
    name: str
    avg_production_seconds: float
    yield_rate: float
    stock_quantity: int


@dataclass(frozen=True)
class Order:
    order_id: int
    sample_id: str
    customer_name: str
    quantity: int
    status: OrderStatus
    created_at: datetime


@dataclass(frozen=True)
class ProductionJob:
    job_id: int
    order_id: int
    sample_id: str
    shortfall_quantity: int
    actual_quantity: int
    total_duration_seconds: float
    status: JobStatus
    enqueued_at: datetime
    started_at: datetime | None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_domain_models.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix semi/domain tests/test_domain_models.py
ruff format semi/domain tests/test_domain_models.py
git add semi/domain/__init__.py semi/domain/models.py tests/test_domain_models.py
git commit -m "feat: add domain enums and dataclasses"
```

---

### Task 2: Storage exception + in-memory fake repositories for testing

**Files:**
- Create: `semi/storage/__init__.py`
- Create: `semi/storage/exceptions.py`
- Create: `tests/conftest.py`
- Test: `tests/test_fakes.py`

**Interfaces:**
- Consumes: `Sample`, `Order`, `ProductionJob`, `OrderStatus`, `JobStatus` from `semi.domain.models` (Task 1).
- Produces: `semi.storage.exceptions.NotFoundError`. Pytest fixtures `conn`, `sample_repo`, `order_repo`, `job_repo`, `lock` in `tests/conftest.py`, available to every later test file with no imports needed (conftest fixtures are auto-discovered). `sample_repo`/`order_repo`/`job_repo` implement exactly the method set from `2026-07-15-storage-design.md` §3:
  - `SampleRepository`: `create`, `get_by_id`, `exists`, `list_all`, `search_by_name`, `increment_stock`, `decrement_stock`
  - `OrderRepository`: `create`, `get_by_id`, `list_by_status`, `update_status`, `sum_quantity_by_status`, `sum_quantity_by_statuses`
  - `ProductionJobRepository`: `create`, `get_by_order_id`, `list_producing_with_shortfall`, `get_current_in_progress`, `list_queued_fifo`, `mark_in_progress`, `mark_done`
  - All three expose `.conn`, and `sample_repo.conn is order_repo.conn is job_repo.conn` (the `conn` fixture).
  - Note: the real `ProductionJobRepository(conn)` (a future plan) computes `list_producing_with_shortfall` via a SQL JOIN against `orders`. The fake can't do a SQL join, so its constructor also takes the fake `order_repo` (`FakeProductionJobRepository(conn, order_repo)`) purely as a test-fixture convenience — this extra constructor arg is not part of the real repository's interface and services never construct repositories themselves, so it doesn't leak into service code.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fakes.py`:

```python
import pytest

from semi.domain.models import JobStatus, OrderStatus
from semi.storage.exceptions import NotFoundError


def test_sample_repo_create_and_get(sample_repo):
    created = sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    assert created.stock_quantity == 0
    fetched = sample_repo.get_by_id("S1")
    assert fetched == created


def test_sample_repo_get_missing_raises_not_found(sample_repo):
    with pytest.raises(NotFoundError):
        sample_repo.get_by_id("missing")


def test_sample_repo_exists(sample_repo):
    assert sample_repo.exists("S1") is False
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    assert sample_repo.exists("S1") is True


def test_sample_repo_increment_and_decrement_stock(sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 5)
    assert sample_repo.get_by_id("S1").stock_quantity == 5
    sample_repo.decrement_stock("S1", 2)
    assert sample_repo.get_by_id("S1").stock_quantity == 3


def test_sample_repo_search_by_name(sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.create("S2", "Die B", 5.0, 0.8)
    assert [s.sample_id for s in sample_repo.search_by_name("Wafer")] == ["S1"]


def test_order_repo_create_assigns_incrementing_ids(order_repo):
    first = order_repo.create("S1", "ACME", 3)
    second = order_repo.create("S1", "ACME", 4)
    assert first.order_id == 1
    assert second.order_id == 2
    assert first.status == OrderStatus.RESERVED


def test_order_repo_get_missing_raises_not_found(order_repo):
    with pytest.raises(NotFoundError):
        order_repo.get_by_id(999)


def test_order_repo_update_status_and_list_by_status(order_repo):
    order = order_repo.create("S1", "ACME", 3)
    order_repo.update_status(order.order_id, OrderStatus.CONFIRMED)
    assert order_repo.get_by_id(order.order_id).status == OrderStatus.CONFIRMED
    assert [o.order_id for o in order_repo.list_by_status(OrderStatus.CONFIRMED)] == [order.order_id]
    assert order_repo.list_by_status(OrderStatus.RESERVED) == []


def test_order_repo_sum_quantity_by_status(order_repo):
    a = order_repo.create("S1", "ACME", 3)
    b = order_repo.create("S1", "ACME", 4)
    order_repo.create("S2", "ACME", 100)
    order_repo.update_status(a.order_id, OrderStatus.CONFIRMED)
    order_repo.update_status(b.order_id, OrderStatus.CONFIRMED)
    assert order_repo.sum_quantity_by_status("S1", OrderStatus.CONFIRMED) == 7


def test_order_repo_sum_quantity_by_statuses(order_repo):
    a = order_repo.create("S1", "ACME", 3)
    b = order_repo.create("S1", "ACME", 4)
    order_repo.update_status(b.order_id, OrderStatus.CONFIRMED)
    total = order_repo.sum_quantity_by_statuses("S1", (OrderStatus.RESERVED, OrderStatus.CONFIRMED))
    assert total == 7
    assert a.status == OrderStatus.RESERVED


def test_job_repo_create_and_get_by_order_id(order_repo, job_repo):
    order = order_repo.create("S1", "ACME", 10)
    job = job_repo.create(order.order_id, "S1", shortfall_quantity=4, actual_quantity=5, total_duration_seconds=50.0)
    assert job.status == JobStatus.QUEUED
    assert job.started_at is None
    assert job_repo.get_by_order_id(order.order_id) == job


def test_job_repo_get_by_order_id_missing_raises_not_found(job_repo):
    with pytest.raises(NotFoundError):
        job_repo.get_by_order_id(999)


def test_job_repo_list_producing_with_shortfall_joins_order_status(order_repo, job_repo):
    producing_order = order_repo.create("S1", "ACME", 10)
    order_repo.update_status(producing_order.order_id, OrderStatus.PRODUCING)
    job_repo.create(producing_order.order_id, "S1", shortfall_quantity=4, actual_quantity=5, total_duration_seconds=50.0)

    reserved_order = order_repo.create("S1", "ACME", 3)
    job_repo.create(reserved_order.order_id, "S1", shortfall_quantity=1, actual_quantity=1, total_duration_seconds=10.0)

    pairs = job_repo.list_producing_with_shortfall("S1")
    assert pairs == [(10, 4)]


def test_job_repo_mark_in_progress_and_get_current_in_progress(order_repo, job_repo):
    order = order_repo.create("S1", "ACME", 10)
    job = job_repo.create(order.order_id, "S1", 4, 5, 50.0)
    assert job_repo.get_current_in_progress() is None
    import datetime as dt

    started_at = dt.datetime.now()
    job_repo.mark_in_progress(job.job_id, started_at)
    current = job_repo.get_current_in_progress()
    assert current.job_id == job.job_id
    assert current.status == JobStatus.IN_PROGRESS
    assert current.started_at == started_at


def test_job_repo_list_queued_fifo_orders_by_enqueued_at_then_job_id(order_repo, job_repo):
    o1 = order_repo.create("S1", "ACME", 1)
    o2 = order_repo.create("S1", "ACME", 1)
    job_repo.create(o1.order_id, "S1", 1, 1, 10.0)
    job_repo.create(o2.order_id, "S1", 1, 1, 10.0)
    queued = job_repo.list_queued_fifo()
    assert [j.order_id for j in queued] == [o1.order_id, o2.order_id]


def test_job_repo_mark_done(order_repo, job_repo):
    order = order_repo.create("S1", "ACME", 10)
    job = job_repo.create(order.order_id, "S1", 4, 5, 50.0)
    job_repo.mark_done(job.job_id)
    assert job_repo.get_by_order_id(order.order_id).status == JobStatus.DONE


def test_repos_share_the_same_connection(conn, sample_repo, order_repo, job_repo):
    assert sample_repo.conn is conn
    assert order_repo.conn is conn
    assert job_repo.conn is conn
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fakes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.storage'` (and fixtures `sample_repo`/`order_repo`/`job_repo`/`conn` not found, since `tests/conftest.py` doesn't exist yet)

- [ ] **Step 3: Write minimal implementation**

Create `semi/storage/__init__.py` (empty file).

Create `semi/storage/exceptions.py`:

```python
class NotFoundError(Exception):
    pass
```

Create `tests/conftest.py`:

```python
from dataclasses import replace
from datetime import datetime

import pytest

from semi.domain.models import JobStatus, Order, OrderStatus, ProductionJob, Sample
from semi.storage.exceptions import NotFoundError


class FakeConnection:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeSampleRepository:
    def __init__(self, conn):
        self.conn = conn
        self._samples: dict[str, Sample] = {}

    def create(self, sample_id, name, avg_production_seconds, yield_rate) -> Sample:
        sample = Sample(sample_id, name, avg_production_seconds, yield_rate, 0)
        self._samples[sample_id] = sample
        return sample

    def get_by_id(self, sample_id) -> Sample:
        try:
            return self._samples[sample_id]
        except KeyError:
            raise NotFoundError(sample_id) from None

    def exists(self, sample_id) -> bool:
        return sample_id in self._samples

    def list_all(self) -> list[Sample]:
        return list(self._samples.values())

    def search_by_name(self, query) -> list[Sample]:
        return [s for s in self._samples.values() if query in s.name]

    def increment_stock(self, sample_id, amount) -> None:
        sample = self.get_by_id(sample_id)
        self._samples[sample_id] = replace(sample, stock_quantity=sample.stock_quantity + amount)

    def decrement_stock(self, sample_id, amount) -> None:
        sample = self.get_by_id(sample_id)
        self._samples[sample_id] = replace(sample, stock_quantity=sample.stock_quantity - amount)


class FakeOrderRepository:
    def __init__(self, conn):
        self.conn = conn
        self._orders: dict[int, Order] = {}
        self._next_id = 1

    def create(self, sample_id, customer_name, quantity) -> Order:
        order = Order(
            order_id=self._next_id,
            sample_id=sample_id,
            customer_name=customer_name,
            quantity=quantity,
            status=OrderStatus.RESERVED,
            created_at=datetime.now(),
        )
        self._orders[order.order_id] = order
        self._next_id += 1
        return order

    def get_by_id(self, order_id) -> Order:
        try:
            return self._orders[order_id]
        except KeyError:
            raise NotFoundError(order_id) from None

    def list_by_status(self, status) -> list[Order]:
        return [o for o in self._orders.values() if o.status == status]

    def update_status(self, order_id, status) -> None:
        order = self.get_by_id(order_id)
        self._orders[order_id] = replace(order, status=status)

    def sum_quantity_by_status(self, sample_id, status) -> int:
        return sum(
            o.quantity for o in self._orders.values() if o.sample_id == sample_id and o.status == status
        )

    def sum_quantity_by_statuses(self, sample_id, statuses) -> int:
        return sum(
            o.quantity
            for o in self._orders.values()
            if o.sample_id == sample_id and o.status in statuses
        )


class FakeProductionJobRepository:
    def __init__(self, conn, order_repo):
        self.conn = conn
        self._order_repo = order_repo
        self._jobs: dict[int, ProductionJob] = {}
        self._next_id = 1

    def create(self, order_id, sample_id, shortfall_quantity, actual_quantity, total_duration_seconds) -> ProductionJob:
        job = ProductionJob(
            job_id=self._next_id,
            order_id=order_id,
            sample_id=sample_id,
            shortfall_quantity=shortfall_quantity,
            actual_quantity=actual_quantity,
            total_duration_seconds=total_duration_seconds,
            status=JobStatus.QUEUED,
            enqueued_at=datetime.now(),
            started_at=None,
        )
        self._jobs[job.job_id] = job
        self._next_id += 1
        return job

    def get_by_order_id(self, order_id) -> ProductionJob:
        for job in self._jobs.values():
            if job.order_id == order_id:
                return job
        raise NotFoundError(order_id)

    def list_producing_with_shortfall(self, sample_id) -> list[tuple[int, int]]:
        pairs = []
        for job in self._jobs.values():
            if job.sample_id != sample_id:
                continue
            order = self._order_repo.get_by_id(job.order_id)
            if order.status == OrderStatus.PRODUCING:
                pairs.append((order.quantity, job.shortfall_quantity))
        return pairs

    def get_current_in_progress(self) -> ProductionJob | None:
        for job in self._jobs.values():
            if job.status == JobStatus.IN_PROGRESS:
                return job
        return None

    def list_queued_fifo(self) -> list[ProductionJob]:
        queued = [j for j in self._jobs.values() if j.status == JobStatus.QUEUED]
        return sorted(queued, key=lambda j: (j.enqueued_at, j.job_id))

    def mark_in_progress(self, job_id, started_at) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(job, status=JobStatus.IN_PROGRESS, started_at=started_at)

    def mark_done(self, job_id) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(job, status=JobStatus.DONE)


@pytest.fixture
def conn():
    return FakeConnection()


@pytest.fixture
def sample_repo(conn):
    return FakeSampleRepository(conn)


@pytest.fixture
def order_repo(conn):
    return FakeOrderRepository(conn)


@pytest.fixture
def job_repo(conn, order_repo):
    return FakeProductionJobRepository(conn, order_repo)


@pytest.fixture
def lock():
    import threading

    return threading.Lock()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fakes.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix semi/storage tests/conftest.py tests/test_fakes.py
ruff format semi/storage tests/conftest.py tests/test_fakes.py
git add semi/storage/__init__.py semi/storage/exceptions.py tests/conftest.py tests/test_fakes.py
git commit -m "test: add NotFoundError and in-memory fake repositories"
```

---

### Task 3: `services/exceptions.py` + `SampleService`

**Files:**
- Create: `semi/services/__init__.py`
- Create: `semi/services/exceptions.py`
- Create: `semi/services/sample_service.py`
- Test: `tests/test_sample_service.py`

**Interfaces:**
- Consumes: `sample_repo` fixture (Task 2), `Sample` (Task 1).
- Produces: `semi.services.exceptions.DomainError`; `SampleService(sample_repo)` with `register(sample_id, name, avg_production_seconds, yield_rate) -> Sample`, `list_all() -> list[Sample]`, `search_by_name(query) -> list[Sample]`. Later tasks import `DomainError` from `semi.services.exceptions`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sample_service.py`:

```python
import pytest

from semi.services.exceptions import DomainError
from semi.services.sample_service import SampleService


def test_register_creates_sample_with_zero_initial_stock(sample_repo):
    service = SampleService(sample_repo)
    sample = service.register("S1", "Wafer A", 10.0, 0.9)
    assert sample.sample_id == "S1"
    assert sample.stock_quantity == 0
    assert sample_repo.conn.committed is True


def test_register_rejects_non_positive_avg_production_seconds(sample_repo):
    service = SampleService(sample_repo)
    with pytest.raises(DomainError):
        service.register("S1", "Wafer A", 0, 0.9)
    with pytest.raises(DomainError):
        service.register("S1", "Wafer A", -1.0, 0.9)


@pytest.mark.parametrize("yield_rate", [0, -0.1, 1.1])
def test_register_rejects_yield_rate_out_of_range(sample_repo, yield_rate):
    service = SampleService(sample_repo)
    with pytest.raises(DomainError):
        service.register("S1", "Wafer A", 10.0, yield_rate)


def test_register_accepts_yield_rate_boundary_of_one(sample_repo):
    service = SampleService(sample_repo)
    sample = service.register("S1", "Wafer A", 10.0, 1.0)
    assert sample.yield_rate == 1.0


def test_register_rejects_duplicate_sample_id(sample_repo):
    service = SampleService(sample_repo)
    service.register("S1", "Wafer A", 10.0, 0.9)
    with pytest.raises(DomainError):
        service.register("S1", "Wafer B", 5.0, 0.8)


def test_list_all_and_search_by_name(sample_repo):
    service = SampleService(sample_repo)
    service.register("S1", "Wafer A", 10.0, 0.9)
    service.register("S2", "Die B", 5.0, 0.8)
    assert {s.sample_id for s in service.list_all()} == {"S1", "S2"}
    assert [s.sample_id for s in service.search_by_name("Wafer")] == ["S1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sample_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.services'`

- [ ] **Step 3: Write minimal implementation**

Create `semi/services/__init__.py` (empty file).

Create `semi/services/exceptions.py`:

```python
class DomainError(Exception):
    pass
```

Create `semi/services/sample_service.py`:

```python
from semi.domain.models import Sample
from semi.services.exceptions import DomainError


class SampleService:
    def __init__(self, sample_repo):
        self._sample_repo = sample_repo

    def register(self, sample_id, name, avg_production_seconds, yield_rate) -> Sample:
        if avg_production_seconds <= 0:
            raise DomainError(
                f"avg_production_seconds must be > 0, got {avg_production_seconds}"
            )
        if not (0 < yield_rate <= 1):
            raise DomainError(f"yield_rate must be in (0, 1], got {yield_rate}")
        if self._sample_repo.exists(sample_id):
            raise DomainError(f"sample_id already exists: {sample_id}")
        sample = self._sample_repo.create(sample_id, name, avg_production_seconds, yield_rate)
        self._sample_repo.conn.commit()
        return sample

    def list_all(self) -> list[Sample]:
        return self._sample_repo.list_all()

    def search_by_name(self, query) -> list[Sample]:
        return self._sample_repo.search_by_name(query)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sample_service.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix semi/services tests/test_sample_service.py
ruff format semi/services tests/test_sample_service.py
git add semi/services/__init__.py semi/services/exceptions.py semi/services/sample_service.py tests/test_sample_service.py
git commit -m "feat: add DomainError and SampleService"
```

---

### Task 4: `OrderService` — constructor, `create_order`, `reject`

**Files:**
- Create: `semi/services/order_service.py`
- Test: `tests/test_order_service.py`

**Interfaces:**
- Consumes: `sample_repo`, `order_repo`, `job_repo`, `lock` fixtures (Task 2); `DomainError` (Task 3); `Order`, `OrderStatus` (Task 1).
- Produces: `OrderService(order_repo, job_repo, sample_repo, lock)` with `create_order(sample_id, customer_name, quantity) -> Order` and `reject(order_id) -> Order`. Task 5 (`approve`) and Task 6 (`release`) add methods to this same class/file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_order_service.py`:

```python
import pytest

from semi.domain.models import OrderStatus
from semi.services.exceptions import DomainError
from semi.services.order_service import OrderService
from semi.storage.exceptions import NotFoundError


@pytest.fixture
def order_service(order_repo, job_repo, sample_repo, lock):
    return OrderService(order_repo, job_repo, sample_repo, lock)


def test_constructor_asserts_shared_connection(job_repo, sample_repo, lock):
    from tests.conftest import FakeOrderRepository, FakeConnection

    mismatched_order_repo = FakeOrderRepository(FakeConnection())
    with pytest.raises(AssertionError):
        OrderService(mismatched_order_repo, job_repo, sample_repo, lock)


def test_create_order_rejects_non_positive_quantity(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    with pytest.raises(DomainError):
        order_service.create_order("S1", "ACME", 0)
    with pytest.raises(DomainError):
        order_service.create_order("S1", "ACME", -3)


def test_create_order_rejects_unknown_sample_id(order_service):
    with pytest.raises(DomainError):
        order_service.create_order("unknown", "ACME", 3)


def test_create_order_creates_reserved_order(order_service, sample_repo, order_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_service.create_order("S1", "ACME", 3)
    assert order.status == OrderStatus.RESERVED
    assert order.sample_id == "S1"
    assert order.quantity == 3
    assert order_repo.conn.committed is True


def test_reject_transitions_reserved_order_to_rejected(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_service.create_order("S1", "ACME", 3)
    rejected = order_service.reject(order.order_id)
    assert rejected.status == OrderStatus.REJECTED


def test_reject_non_reserved_order_raises_domain_error(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_service.create_order("S1", "ACME", 3)
    order_service.reject(order.order_id)
    with pytest.raises(DomainError):
        order_service.reject(order.order_id)


def test_reject_unknown_order_raises_not_found(order_service):
    with pytest.raises(NotFoundError):
        order_service.reject(999)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_order_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.services.order_service'`

- [ ] **Step 3: Write minimal implementation**

Create `semi/services/order_service.py`:

```python
from semi.domain.models import Order, OrderStatus
from semi.services.exceptions import DomainError


class OrderService:
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
        with self._lock:
            try:
                order = self._order_repo.get_by_id(order_id)
                if order.status != OrderStatus.RESERVED:
                    raise DomainError(
                        f"order {order_id} is not RESERVED (status={order.status})"
                    )
                self._order_repo.update_status(order_id, OrderStatus.REJECTED)
                self._order_repo.conn.commit()
                return self._order_repo.get_by_id(order_id)
            except Exception:
                self._order_repo.conn.rollback()
                raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_order_service.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix semi/services/order_service.py tests/test_order_service.py
ruff format semi/services/order_service.py tests/test_order_service.py
git add semi/services/order_service.py tests/test_order_service.py
git commit -m "feat: add OrderService create_order and reject"
```

---

### Task 5: `OrderService.approve` — available-stock calculation and CONFIRMED/PRODUCING branch

**Files:**
- Modify: `semi/services/order_service.py`
- Modify: `tests/test_order_service.py`

**Interfaces:**
- Consumes: `sample_repo.get_by_id`, `order_repo.sum_quantity_by_status`, `job_repo.list_producing_with_shortfall`, `job_repo.create` (Task 2); `math.ceil`.
- Produces: `OrderService.approve(order_id) -> Order` and private `OrderService._available_stock(sample) -> int`, per the formula in `2026-07-15-services-design.md` §4.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_order_service.py`:

```python
def test_approve_non_reserved_order_raises_domain_error(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_service.create_order("S1", "ACME", 3)
    order_service.reject(order.order_id)
    with pytest.raises(DomainError):
        order_service.approve(order.order_id)


def test_approve_confirms_order_when_stock_sufficient(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 10)
    order = order_service.create_order("S1", "ACME", 3)
    approved = order_service.approve(order.order_id)
    assert approved.status == OrderStatus.CONFIRMED
    assert sample_repo.get_by_id("S1").stock_quantity == 10  # stock untouched at approval


def test_approve_confirms_order_when_available_stock_exactly_matches_quantity(
    order_service, sample_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 3)
    order = order_service.create_order("S1", "ACME", 3)
    approved = order_service.approve(order.order_id)
    assert approved.status == OrderStatus.CONFIRMED


def test_approve_excludes_confirmed_orders_from_available_stock(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 10)
    already_confirmed = order_service.create_order("S1", "ACME", 8)
    order_service.approve(already_confirmed.order_id)  # available 10 >= 8 -> CONFIRMED

    new_order = order_service.create_order("S1", "ACME", 3)
    approved = order_service.approve(new_order.order_id)  # available = 10 - 8 = 2 < 3
    assert approved.status == OrderStatus.PRODUCING


def test_approve_queues_production_job_when_stock_insufficient(
    order_service, sample_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)  # avg_production_seconds=10, yield_rate=0.9
    order = order_service.create_order("S1", "ACME", 5)  # available = 0 -> shortfall 5

    approved = order_service.approve(order.order_id)

    assert approved.status == OrderStatus.PRODUCING
    job = job_repo.get_by_order_id(order.order_id)
    assert job.shortfall_quantity == 5
    assert job.actual_quantity == 6  # ceil(5 / 0.9) == 6
    assert job.total_duration_seconds == 60.0  # 10 * 6


def test_approve_excludes_producing_orders_original_stock_claim_from_available_stock(
    order_service, sample_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 1.0)
    first = order_service.create_order("S1", "ACME", 5)
    order_service.approve(first.order_id)  # available 0 -> PRODUCING, claims 0 of existing stock

    sample_repo.increment_stock("S1", 3)  # simulate some other unrelated stock arriving
    second = order_service.create_order("S1", "ACME", 2)
    approved = order_service.approve(second.order_id)  # available = 3 - 0 (first's claim) = 3 >= 2
    assert approved.status == OrderStatus.CONFIRMED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_order_service.py -v`
Expected: FAIL with `AttributeError: 'OrderService' object has no attribute 'approve'`

- [ ] **Step 3: Write minimal implementation**

Modify `semi/services/order_service.py` — add `import math` at the top, and add these two methods to `OrderService`:

```python
    def approve(self, order_id) -> Order:
        with self._lock:
            try:
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
                        order_id, sample.sample_id, shortfall, actual_quantity, total_duration_seconds
                    )
                    self._order_repo.update_status(order_id, OrderStatus.PRODUCING)
                self._order_repo.conn.commit()
                return self._order_repo.get_by_id(order_id)
            except Exception:
                self._order_repo.conn.rollback()
                raise

    def _available_stock(self, sample) -> int:
        confirmed_sum = self._order_repo.sum_quantity_by_status(
            sample.sample_id, OrderStatus.CONFIRMED
        )
        producing_reserved_sum = sum(
            qty - shortfall
            for qty, shortfall in self._job_repo.list_producing_with_shortfall(sample.sample_id)
        )
        return sample.stock_quantity - confirmed_sum - producing_reserved_sum
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_order_service.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix semi/services/order_service.py tests/test_order_service.py
ruff format semi/services/order_service.py tests/test_order_service.py
git add semi/services/order_service.py tests/test_order_service.py
git commit -m "feat: add OrderService.approve with available-stock calculation"
```

---

### Task 6: `OrderService.release`

**Files:**
- Modify: `semi/services/order_service.py`
- Modify: `tests/test_order_service.py`

**Interfaces:**
- Consumes: `sample_repo.decrement_stock` (Task 2).
- Produces: `OrderService.release(order_id) -> Order`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_order_service.py`:

```python
def test_release_non_confirmed_order_raises_domain_error(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_service.create_order("S1", "ACME", 3)
    with pytest.raises(DomainError):
        order_service.release(order.order_id)


def test_release_decrements_stock_and_transitions_to_release(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 10)
    order = order_service.create_order("S1", "ACME", 3)
    order_service.approve(order.order_id)  # -> CONFIRMED, stock still 10

    released = order_service.release(order.order_id)

    assert released.status == OrderStatus.RELEASE
    assert sample_repo.get_by_id("S1").stock_quantity == 7


def test_release_already_released_order_raises_domain_error(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 10)
    order = order_service.create_order("S1", "ACME", 3)
    order_service.approve(order.order_id)
    order_service.release(order.order_id)
    with pytest.raises(DomainError):
        order_service.release(order.order_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_order_service.py -v`
Expected: FAIL with `AttributeError: 'OrderService' object has no attribute 'release'`

- [ ] **Step 3: Write minimal implementation**

Add to `semi/services/order_service.py`, inside `OrderService`:

```python
    def release(self, order_id) -> Order:
        with self._lock:
            try:
                order = self._order_repo.get_by_id(order_id)
                if order.status != OrderStatus.CONFIRMED:
                    raise DomainError(
                        f"order {order_id} is not CONFIRMED (status={order.status})"
                    )
                self._sample_repo.decrement_stock(order.sample_id, order.quantity)
                self._order_repo.update_status(order_id, OrderStatus.RELEASE)
                self._order_repo.conn.commit()
                return self._order_repo.get_by_id(order_id)
            except Exception:
                self._order_repo.conn.rollback()
                raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_order_service.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix semi/services/order_service.py tests/test_order_service.py
ruff format semi/services/order_service.py tests/test_order_service.py
git add semi/services/order_service.py tests/test_order_service.py
git commit -m "feat: add OrderService.release"
```

---

### Task 7: `ProductionService.tick()`

**Files:**
- Create: `semi/services/production_service.py`
- Test: `tests/test_production_service.py`

**Interfaces:**
- Consumes: `job_repo.get_current_in_progress`, `.list_queued_fifo`, `.mark_in_progress`, `.mark_done` (Task 2); `sample_repo.increment_stock`; `order_repo.update_status`.
- Produces: `ProductionService(order_repo, job_repo, sample_repo, lock)` with `tick() -> None`. Task 8 adds `ProductionJobStatus`, `get_current_status()`, `list_queue_status()` to this same file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_production_service.py`:

```python
from datetime import datetime, timedelta

import pytest

from semi.domain.models import JobStatus, OrderStatus
from semi.services.production_service import ProductionService


@pytest.fixture
def production_service(order_repo, job_repo, sample_repo, lock):
    return ProductionService(order_repo, job_repo, sample_repo, lock)


def test_constructor_asserts_shared_connection(job_repo, sample_repo, lock):
    from tests.conftest import FakeConnection, FakeOrderRepository

    mismatched_order_repo = FakeOrderRepository(FakeConnection())
    with pytest.raises(AssertionError):
        ProductionService(mismatched_order_repo, job_repo, sample_repo, lock)


def test_tick_promotes_oldest_queued_job_to_in_progress_when_idle(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(order.order_id, OrderStatus.PRODUCING)
    job = job_repo.create(order.order_id, "S1", shortfall_quantity=5, actual_quantity=6, total_duration_seconds=60.0)

    production_service.tick()

    in_progress = job_repo.get_current_in_progress()
    assert in_progress.job_id == job.job_id
    assert in_progress.status == JobStatus.IN_PROGRESS
    assert in_progress.started_at is not None


def test_tick_does_nothing_when_in_progress_job_not_yet_complete(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(order.order_id, OrderStatus.PRODUCING)
    job = job_repo.create(order.order_id, "S1", 5, 6, total_duration_seconds=999.0)
    job_repo.mark_in_progress(job.job_id, datetime.now())

    production_service.tick()

    assert job_repo.get_current_in_progress().status == JobStatus.IN_PROGRESS
    assert sample_repo.get_by_id("S1").stock_quantity == 0
    assert order_repo.get_by_id(order.order_id).status == OrderStatus.PRODUCING


def test_tick_completes_job_increments_stock_confirms_order_and_promotes_next(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    finishing_order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(finishing_order.order_id, OrderStatus.PRODUCING)
    finishing_job = job_repo.create(finishing_order.order_id, "S1", 5, 6, total_duration_seconds=30.0)
    job_repo.mark_in_progress(finishing_job.job_id, datetime.now() - timedelta(seconds=31))

    next_order = order_repo.create("S1", "ACME", 2)
    order_repo.update_status(next_order.order_id, OrderStatus.PRODUCING)
    next_job = job_repo.create(next_order.order_id, "S1", 2, 3, total_duration_seconds=20.0)

    production_service.tick()

    assert job_repo.get_by_order_id(finishing_order.order_id).status == JobStatus.DONE
    assert sample_repo.get_by_id("S1").stock_quantity == 6
    assert order_repo.get_by_id(finishing_order.order_id).status == OrderStatus.CONFIRMED

    promoted = job_repo.get_current_in_progress()
    assert promoted.job_id == next_job.job_id
    assert promoted.started_at is not None


def test_tick_with_no_queued_or_in_progress_jobs_is_a_no_op(production_service):
    production_service.tick()  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_production_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.services.production_service'`

- [ ] **Step 3: Write minimal implementation**

Create `semi/services/production_service.py`:

```python
from datetime import datetime

from semi.domain.models import OrderStatus


class ProductionService:
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
        with self._lock:
            try:
                self._promote_if_idle()
                current = self._job_repo.get_current_in_progress()
                if current is not None:
                    elapsed = (datetime.now() - current.started_at).total_seconds()
                    if elapsed >= current.total_duration_seconds:
                        self._sample_repo.increment_stock(current.sample_id, current.actual_quantity)
                        self._order_repo.update_status(current.order_id, OrderStatus.CONFIRMED)
                        self._job_repo.mark_done(current.job_id)
                        self._promote_if_idle()
                self._order_repo.conn.commit()
            except Exception:
                self._order_repo.conn.rollback()
                raise

    def _promote_if_idle(self) -> None:
        if self._job_repo.get_current_in_progress() is not None:
            return
        queue = self._job_repo.list_queued_fifo()
        if queue:
            self._job_repo.mark_in_progress(queue[0].job_id, datetime.now())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_production_service.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix semi/services/production_service.py tests/test_production_service.py
ruff format semi/services/production_service.py tests/test_production_service.py
git add semi/services/production_service.py tests/test_production_service.py
git commit -m "feat: add ProductionService.tick"
```

---

### Task 8: `ProductionService.get_current_status()` / `list_queue_status()`

**Files:**
- Modify: `semi/services/production_service.py`
- Modify: `tests/test_production_service.py`

**Interfaces:**
- Produces: `ProductionJobStatus(job, progress_ratio, produced_so_far, estimated_completion_at)` (frozen dataclass), `ProductionService.get_current_status() -> ProductionJobStatus | None`, `ProductionService.list_queue_status() -> list[ProductionJobStatus]`, per `2026-07-15-services-design.md` §5 and `DESIGN.md` §4.2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_production_service.py`:

```python
def test_get_current_status_returns_none_when_nothing_in_progress(production_service):
    assert production_service.get_current_status() is None


def test_get_current_status_reports_progress_ratio_and_produced_so_far(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(order.order_id, OrderStatus.PRODUCING)
    job = job_repo.create(order.order_id, "S1", 5, 6, total_duration_seconds=60.0)
    started_at = datetime.now() - timedelta(seconds=30)
    job_repo.mark_in_progress(job.job_id, started_at)

    status = production_service.get_current_status()

    assert status.job.job_id == job.job_id
    assert status.progress_ratio == pytest.approx(0.5, abs=0.05)
    assert status.produced_so_far == 3  # floor(0.5 * 6)
    assert status.estimated_completion_at == started_at + timedelta(seconds=60.0)


def test_get_current_status_caps_progress_ratio_at_one_when_overdue(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(order.order_id, OrderStatus.PRODUCING)
    job = job_repo.create(order.order_id, "S1", 5, 6, total_duration_seconds=10.0)
    job_repo.mark_in_progress(job.job_id, datetime.now() - timedelta(seconds=100))

    status = production_service.get_current_status()

    assert status.progress_ratio == 1.0
    assert status.produced_so_far == 6


def test_list_queue_status_is_empty_when_no_queued_jobs(production_service):
    assert production_service.list_queue_status() == []


def test_list_queue_status_accumulates_remaining_time_of_current_and_preceding_jobs(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)

    current_order = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(current_order.order_id, OrderStatus.PRODUCING)
    current_job = job_repo.create(current_order.order_id, "S1", 1, 1, total_duration_seconds=100.0)
    job_repo.mark_in_progress(current_job.job_id, datetime.now() - timedelta(seconds=40))
    # current job has ~60s remaining

    first_queued_order = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(first_queued_order.order_id, OrderStatus.PRODUCING)
    first_queued_job = job_repo.create(
        first_queued_order.order_id, "S1", 1, 1, total_duration_seconds=20.0
    )

    second_queued_order = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(second_queued_order.order_id, OrderStatus.PRODUCING)
    second_queued_job = job_repo.create(
        second_queued_order.order_id, "S1", 1, 1, total_duration_seconds=30.0
    )

    statuses = production_service.list_queue_status()

    assert [s.job.job_id for s in statuses] == [first_queued_job.job_id, second_queued_job.job_id]
    first_remaining_seconds = (statuses[0].estimated_completion_at - datetime.now()).total_seconds()
    assert first_remaining_seconds == pytest.approx(60 + 20, abs=2)
    second_remaining_seconds = (statuses[1].estimated_completion_at - datetime.now()).total_seconds()
    assert second_remaining_seconds == pytest.approx(60 + 20 + 30, abs=2)
    assert statuses[0].progress_ratio == 0.0
    assert statuses[0].produced_so_far == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_production_service.py -v`
Expected: FAIL with `AttributeError: 'ProductionService' object has no attribute 'get_current_status'`

- [ ] **Step 3: Write minimal implementation**

Modify `semi/services/production_service.py` — update the imports and add the dataclass and two methods:

```python
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from semi.domain.models import OrderStatus, ProductionJob


@dataclass(frozen=True)
class ProductionJobStatus:
    job: ProductionJob
    progress_ratio: float
    produced_so_far: int
    estimated_completion_at: datetime
```

Add these methods to `ProductionService`:

```python
    def get_current_status(self) -> ProductionJobStatus | None:
        job = self._job_repo.get_current_in_progress()
        if job is None:
            return None
        now = datetime.now()
        elapsed = (now - job.started_at).total_seconds()
        progress_ratio = min(1.0, elapsed / job.total_duration_seconds)
        produced_so_far = math.floor(progress_ratio * job.actual_quantity)
        estimated_completion_at = job.started_at + timedelta(seconds=job.total_duration_seconds)
        return ProductionJobStatus(job, progress_ratio, produced_so_far, estimated_completion_at)

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_production_service.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix semi/services/production_service.py tests/test_production_service.py
ruff format semi/services/production_service.py tests/test_production_service.py
git add semi/services/production_service.py tests/test_production_service.py
git commit -m "feat: add ProductionService status reporting"
```

---

### Task 9: `MonitoringService`

**Files:**
- Create: `semi/services/monitoring_service.py`
- Test: `tests/test_monitoring_service.py`

**Interfaces:**
- Consumes: `order_repo.list_by_status`, `order_repo.sum_quantity_by_statuses`, `sample_repo.list_all` (Task 2).
- Produces: `StockStatus` (`StrEnum`: `SUFFICIENT`, `SHORT`, `DEPLETED`), `SampleStockStatus(sample, outstanding, status)` (frozen dataclass), `MonitoringService(order_repo, sample_repo)` with `count_by_status() -> dict[OrderStatus, int]`, `list_by_status(status) -> list[Order]`, `stock_status() -> list[SampleStockStatus]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_monitoring_service.py`:

```python
from semi.domain.models import OrderStatus
from semi.services.monitoring_service import MonitoringService, StockStatus


def make_service(order_repo, sample_repo):
    return MonitoringService(order_repo, sample_repo)


def test_count_by_status_excludes_rejected(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    reserved = order_repo.create("S1", "ACME", 1)
    confirmed = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(confirmed.order_id, OrderStatus.CONFIRMED)
    rejected = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(rejected.order_id, OrderStatus.REJECTED)

    service = make_service(order_repo, sample_repo)
    counts = service.count_by_status()

    assert counts == {
        OrderStatus.RESERVED: 1,
        OrderStatus.CONFIRMED: 1,
        OrderStatus.PRODUCING: 0,
        OrderStatus.RELEASE: 0,
    }
    assert OrderStatus.REJECTED not in counts


def test_list_by_status_delegates_to_repo(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 1)
    service = make_service(order_repo, sample_repo)
    assert [o.order_id for o in service.list_by_status(OrderStatus.RESERVED)] == [order.order_id]


def test_stock_status_depleted_takes_priority_over_outstanding(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)  # stock stays 0

    service = make_service(order_repo, sample_repo)
    statuses = {s.sample.sample_id: s for s in service.stock_status()}

    assert statuses["S1"].status == StockStatus.DEPLETED
    assert statuses["S1"].outstanding == 0


def test_stock_status_sufficient_when_stock_covers_outstanding(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 5)
    order_repo.create("S1", "ACME", 5)  # RESERVED, counts toward outstanding

    service = make_service(order_repo, sample_repo)
    status = next(s for s in service.stock_status() if s.sample.sample_id == "S1")

    assert status.outstanding == 5
    assert status.status == StockStatus.SUFFICIENT


def test_stock_status_short_when_stock_below_outstanding(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 2)
    order_repo.create("S1", "ACME", 5)  # RESERVED

    service = make_service(order_repo, sample_repo)
    status = next(s for s in service.stock_status() if s.sample.sample_id == "S1")

    assert status.outstanding == 5
    assert status.status == StockStatus.SHORT


def test_stock_status_outstanding_includes_reserved_confirmed_and_producing_only(
    order_repo, sample_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 100)
    reserved = order_repo.create("S1", "ACME", 1)
    confirmed = order_repo.create("S1", "ACME", 2)
    order_repo.update_status(confirmed.order_id, OrderStatus.CONFIRMED)
    producing = order_repo.create("S1", "ACME", 3)
    order_repo.update_status(producing.order_id, OrderStatus.PRODUCING)
    released = order_repo.create("S1", "ACME", 4)
    order_repo.update_status(released.order_id, OrderStatus.RELEASE)
    rejected = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(rejected.order_id, OrderStatus.REJECTED)

    service = make_service(order_repo, sample_repo)
    status = next(s for s in service.stock_status() if s.sample.sample_id == "S1")

    assert status.outstanding == 1 + 2 + 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_monitoring_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.services.monitoring_service'`

- [ ] **Step 3: Write minimal implementation**

Create `semi/services/monitoring_service.py`:

```python
from dataclasses import dataclass
from enum import StrEnum

from semi.domain.models import Order, OrderStatus, Sample


class StockStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    SHORT = "SHORT"
    DEPLETED = "DEPLETED"


@dataclass(frozen=True)
class SampleStockStatus:
    sample: Sample
    outstanding: int
    status: StockStatus


class MonitoringService:
    _COUNTED_STATUSES = (
        OrderStatus.RESERVED,
        OrderStatus.CONFIRMED,
        OrderStatus.PRODUCING,
        OrderStatus.RELEASE,
    )
    _OUTSTANDING_STATUSES = (OrderStatus.RESERVED, OrderStatus.CONFIRMED, OrderStatus.PRODUCING)

    def __init__(self, order_repo, sample_repo):
        self._order_repo = order_repo
        self._sample_repo = sample_repo

    def count_by_status(self) -> dict[OrderStatus, int]:
        return {
            status: len(self._order_repo.list_by_status(status))
            for status in self._COUNTED_STATUSES
        }

    def list_by_status(self, status) -> list[Order]:
        return self._order_repo.list_by_status(status)

    def stock_status(self) -> list[SampleStockStatus]:
        results = []
        for sample in self._sample_repo.list_all():
            outstanding = self._order_repo.sum_quantity_by_statuses(
                sample.sample_id, self._OUTSTANDING_STATUSES
            )
            if sample.stock_quantity == 0:
                status = StockStatus.DEPLETED
            elif sample.stock_quantity >= outstanding:
                status = StockStatus.SUFFICIENT
            else:
                status = StockStatus.SHORT
            results.append(SampleStockStatus(sample, outstanding, status))
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_monitoring_service.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Lint, full-suite check, and commit**

```bash
ruff check --fix semi/services/monitoring_service.py tests/test_monitoring_service.py
ruff format semi/services/monitoring_service.py tests/test_monitoring_service.py
pytest -v
git add semi/services/monitoring_service.py tests/test_monitoring_service.py
git commit -m "feat: add MonitoringService"
```

---

## Self-Review Notes

- **Spec coverage:** every method signature in `2026-07-15-services-design.md` §3–6 has a task producing it (`SampleService` §3 → Task 3; `OrderService` §4 → Tasks 4–6; `ProductionService` §5 → Tasks 7–8; `MonitoringService` §6 → Task 9). The shared-connection `assert` (§2) is tested in Tasks 4 and 7. The `DomainError`/`NotFoundError` split (§1) is tested throughout (`DomainError` on validation/transition, `NotFoundError` propagating untouched from `get_by_id`).
- **Placeholder scan:** no "TBD"/"handle appropriately" steps remain; every step has literal code.
- **Type consistency:** `ProductionJobStatus`, `StockStatus`, and `SampleStockStatus` field names match between their Task 8/9 definitions and every test's usage (`.job`, `.progress_ratio`, `.produced_so_far`, `.estimated_completion_at`, `.sample`, `.outstanding`, `.status`). Constructor parameter order (`order_repo, job_repo, sample_repo, lock`) is identical across `OrderService` and `ProductionService`, matching §4/§5 of the spec.
- **Out-of-scope flag:** `semi/storage/db.py` and the real `sample_repository.py` / `order_repository.py` / `production_job_repository.py` are **not** built by this plan (per the earlier scope decision — services only, storage/domain minimal). A follow-up plan should implement those against the exact method set validated here by `tests/conftest.py`'s fakes, then re-run this plan's service tests against a real SQLite-backed fixture as a regression check.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-15-services-design.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
