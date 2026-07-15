# Domain Models (semi/domain) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `semi/domain/models.py` — the two status enums and three frozen dataclasses that every later layer (`storage`, `services`, `cli`) will import as the shared vocabulary for samples, orders, and production jobs.

**Architecture:** A single new subpackage `semi/domain/` with one module, `models.py`, containing `OrderStatus`/`JobStatus` (`StrEnum`) and `Sample`/`Order`/`ProductionJob` (`@dataclass(frozen=True)`). No validation, no state-transition logic, no I/O — this layer is intentionally anemic; all of that belongs to `semi/services` in a later plan. Each class is added in its own task so a reviewer can accept/reject one independently of the others.

**Tech Stack:** Python 3.14 (`enum.StrEnum`, `dataclasses`), pytest + pytest-mock (already declared in `pyproject.toml`'s `test` extra, not yet installed in the dev environment), ruff for lint/format.

## Global Constraints

- Target Python: 3.14+ (per `pyproject.toml` `requires-python`).
- Use `StrEnum` (not `str, Enum` multiple inheritance) for `OrderStatus`/`JobStatus` — exact string values must match the DB `CHECK (status IN (...))` constraints in `DESIGN.md` §2.
- All three dataclasses are `@dataclass(frozen=True)` with **no methods** (no validation, no transition logic) — that responsibility belongs to `semi/services`, not this layer.
- `order_id` and `job_id` fields are always required `int` (never `Optional`/`None`) — repositories only ever construct these objects post-INSERT with a real assigned id.
- Timestamp fields (`created_at`, `enqueued_at`, `started_at`) are typed `datetime`, not `str` — ISO8601 string conversion is the `storage` layer's job, not this layer's.
- Field names/types must exactly match `docs/superpowers/specs/2026-07-15-domain-design.md` §2, since `storage`/`services` plans (written later) will consume these exact names.
- Run `ruff check --fix .` and `ruff format .` before each commit (matches `prek`/pre-commit hooks already configured in this repo).
- Commit messages must follow Conventional Commits (`feat: ...`, `test: ...`) since the `commitizen` commit-msg hook enforces this.

---

### Task 1: Project test scaffolding — install test extra, verify pytest runs

**Files:**
- Modify: none (installs existing declared dependencies)
- Verify: `tests/__init__.py` (already exists, empty)

**Interfaces:**
- Consumes: nothing
- Produces: a working `pytest` command in this environment, used by every later task's test steps.

- [ ] **Step 1: Install the package with the `test` extra**

Run: `pip install -e ".[test]"`
Expected: `pytest` and `pytest-mock` install successfully (they are already declared in `pyproject.toml` under `[project.optional-dependencies].test`).

- [ ] **Step 2: Verify pytest collects the (currently empty) test suite**

Run: `pytest tests/ -v`
Expected: `no tests ran` (or similar) with exit code 0 — confirms pytest is wired up and `tests/__init__.py` is picked up as a package before any real test files exist.

- [ ] **Step 3: Commit only if `pip install -e` changed lockable state**

No commit needed for this step — installing an already-declared extra does not change any tracked file. Skip straight to Task 2.

---

### Task 2: `OrderStatus` and `JobStatus` enums

**Files:**
- Create: `semi/domain/__init__.py` (empty, matches the existing empty `semi/__init__.py`)
- Create: `semi/domain/models.py`
- Test: `tests/domain/__init__.py` (empty, new test subpackage)
- Test: `tests/domain/test_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: `semi.domain.models.OrderStatus` with members `RESERVED`, `REJECTED`, `PRODUCING`, `CONFIRMED`, `RELEASE`; `semi.domain.models.JobStatus` with members `QUEUED`, `IN_PROGRESS`, `DONE`. Both are `StrEnum` subclasses whose `.value` equals the member name as a string (e.g. `OrderStatus.RESERVED.value == "RESERVED"`). Later tasks' dataclasses import these two names from `semi.domain.models`.

- [ ] **Step 1: Write the failing tests**

Create `tests/domain/__init__.py` (empty file).

Create `tests/domain/test_models.py`:

```python
from enum import StrEnum

from semi.domain.models import JobStatus, OrderStatus


def test_order_status_is_str_enum():
    assert issubclass(OrderStatus, StrEnum)


def test_order_status_members_match_db_check_constraint():
    assert [member.value for member in OrderStatus] == [
        "RESERVED",
        "REJECTED",
        "PRODUCING",
        "CONFIRMED",
        "RELEASE",
    ]


def test_order_status_value_equals_member_name():
    assert OrderStatus.RESERVED.value == "RESERVED"
    assert OrderStatus.CONFIRMED == "CONFIRMED"


def test_job_status_is_str_enum():
    assert issubclass(JobStatus, StrEnum)


def test_job_status_members_match_db_check_constraint():
    assert [member.value for member in JobStatus] == ["QUEUED", "IN_PROGRESS", "DONE"]


def test_job_status_value_equals_member_name():
    assert JobStatus.QUEUED.value == "QUEUED"
    assert JobStatus.DONE == "DONE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/domain/test_models.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'semi.domain'`

- [ ] **Step 3: Create the `semi.domain` subpackage and implement the enums**

Create `semi/domain/__init__.py` (empty file, no content).

Create `semi/domain/models.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/domain/test_models.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Lint and format**

Run: `ruff check --fix . && ruff check --select I --fix . && ruff format .`
Expected: no errors; no unexpected diff beyond formatting

- [ ] **Step 6: Commit**

```bash
git add semi/domain/__init__.py semi/domain/models.py tests/domain/__init__.py tests/domain/test_models.py
git commit -m "feat: add OrderStatus and JobStatus enums"
```

---

### Task 3: `Sample` dataclass

**Files:**
- Modify: `semi/domain/models.py`
- Test: `tests/domain/test_models.py`

**Interfaces:**
- Consumes: nothing (no dependency on `OrderStatus`/`JobStatus`)
- Produces: `semi.domain.models.Sample`, a frozen dataclass with fields `sample_id: str`, `name: str`, `avg_production_seconds: float`, `yield_rate: float`, `stock_quantity: int`. Consumed by `semi.storage.sample_repository` and `semi.services.sample_service` in later plans (not part of this plan).

- [ ] **Step 1: Write the failing tests**

Append to `tests/domain/test_models.py`:

```python
import dataclasses

import pytest

from semi.domain.models import Sample


def _make_sample(**overrides):
    fields = {
        "sample_id": "SMP-001",
        "name": "Test Sample",
        "avg_production_seconds": 12.5,
        "yield_rate": 0.9,
        "stock_quantity": 10,
    }
    fields.update(overrides)
    return Sample(**fields)


def test_sample_holds_all_fields():
    sample = _make_sample()
    assert sample.sample_id == "SMP-001"
    assert sample.name == "Test Sample"
    assert sample.avg_production_seconds == 12.5
    assert sample.yield_rate == 0.9
    assert sample.stock_quantity == 10


def test_sample_is_frozen():
    sample = _make_sample()
    with pytest.raises(dataclasses.FrozenInstanceError):
        sample.stock_quantity = 999
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/domain/test_models.py -v -k Sample`
Expected: FAIL — `ImportError: cannot import name 'Sample' from 'semi.domain.models'`

- [ ] **Step 3: Implement `Sample`**

Add to `semi/domain/models.py` (below the enums, add the `dataclasses` import at the top):

```python
from dataclasses import dataclass
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/domain/test_models.py -v -k Sample`
Expected: both tests PASS

- [ ] **Step 5: Run the full domain test file to check for regressions**

Run: `pytest tests/domain/test_models.py -v`
Expected: all previously-passing tests (Task 2) still PASS, plus the 2 new `Sample` tests

- [ ] **Step 6: Lint and format**

Run: `ruff check --fix . && ruff check --select I --fix . && ruff format .`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add semi/domain/models.py tests/domain/test_models.py
git commit -m "feat: add Sample dataclass"
```

---

### Task 4: `Order` dataclass

**Files:**
- Modify: `semi/domain/models.py`
- Test: `tests/domain/test_models.py`

**Interfaces:**
- Consumes: `OrderStatus` from Task 2 (this module).
- Produces: `semi.domain.models.Order`, a frozen dataclass with fields `order_id: int`, `sample_id: str`, `customer_name: str`, `quantity: int`, `status: OrderStatus`, `created_at: datetime`. Consumed by `semi.storage.order_repository` and `semi.services.order_service` in later plans.

- [ ] **Step 1: Write the failing tests**

Append to `tests/domain/test_models.py`:

```python
from datetime import UTC, datetime

from semi.domain.models import Order, OrderStatus


def _make_order(**overrides):
    fields = {
        "order_id": 1,
        "sample_id": "SMP-001",
        "customer_name": "Acme Labs",
        "quantity": 5,
        "status": OrderStatus.RESERVED,
        "created_at": datetime(2026, 7, 15, 9, 0, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    return Order(**fields)


def test_order_holds_all_fields():
    order = _make_order()
    assert order.order_id == 1
    assert order.sample_id == "SMP-001"
    assert order.customer_name == "Acme Labs"
    assert order.quantity == 5
    assert order.status == OrderStatus.RESERVED
    assert order.created_at == datetime(2026, 7, 15, 9, 0, 0, tzinfo=UTC)


def test_order_is_frozen():
    order = _make_order()
    with pytest.raises(dataclasses.FrozenInstanceError):
        order.status = OrderStatus.CONFIRMED


def test_order_created_at_is_datetime_not_str():
    order = _make_order()
    assert isinstance(order.created_at, datetime)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/domain/test_models.py -v -k Order`
Expected: FAIL — `ImportError: cannot import name 'Order' from 'semi.domain.models'`

- [ ] **Step 3: Implement `Order`**

Add to `semi/domain/models.py` (add `datetime` import at top, add class after `Sample`):

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/domain/test_models.py -v -k Order`
Expected: all 3 tests PASS

- [ ] **Step 5: Run the full domain test file to check for regressions**

Run: `pytest tests/domain/test_models.py -v`
Expected: all previously-passing tests (Tasks 2–3) still PASS, plus the 3 new `Order` tests

- [ ] **Step 6: Lint and format**

Run: `ruff check --fix . && ruff check --select I --fix . && ruff format .`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add semi/domain/models.py tests/domain/test_models.py
git commit -m "feat: add Order dataclass"
```

---

### Task 5: `ProductionJob` dataclass

**Files:**
- Modify: `semi/domain/models.py`
- Test: `tests/domain/test_models.py`

**Interfaces:**
- Consumes: `JobStatus` from Task 2 (this module).
- Produces: `semi.domain.models.ProductionJob`, a frozen dataclass with fields `job_id: int`, `order_id: int`, `sample_id: str`, `shortfall_quantity: int`, `actual_quantity: int`, `total_duration_seconds: float`, `status: JobStatus`, `enqueued_at: datetime`, `started_at: datetime | None`. Consumed by `semi.storage.production_job_repository` and `semi.services.production_service` in later plans.

- [ ] **Step 1: Write the failing tests**

Append to `tests/domain/test_models.py`:

```python
from semi.domain.models import JobStatus, ProductionJob


def _make_production_job(**overrides):
    fields = {
        "job_id": 1,
        "order_id": 1,
        "sample_id": "SMP-001",
        "shortfall_quantity": 3,
        "actual_quantity": 4,
        "total_duration_seconds": 50.0,
        "status": JobStatus.QUEUED,
        "enqueued_at": datetime(2026, 7, 15, 9, 0, 0, tzinfo=UTC),
        "started_at": None,
    }
    fields.update(overrides)
    return ProductionJob(**fields)


def test_production_job_holds_all_fields():
    job = _make_production_job()
    assert job.job_id == 1
    assert job.order_id == 1
    assert job.sample_id == "SMP-001"
    assert job.shortfall_quantity == 3
    assert job.actual_quantity == 4
    assert job.total_duration_seconds == 50.0
    assert job.status == JobStatus.QUEUED
    assert job.enqueued_at == datetime(2026, 7, 15, 9, 0, 0, tzinfo=UTC)
    assert job.started_at is None


def test_production_job_started_at_accepts_datetime_once_in_progress():
    started = datetime(2026, 7, 15, 9, 5, 0, tzinfo=UTC)
    job = _make_production_job(status=JobStatus.IN_PROGRESS, started_at=started)
    assert job.started_at == started


def test_production_job_is_frozen():
    job = _make_production_job()
    with pytest.raises(dataclasses.FrozenInstanceError):
        job.status = JobStatus.DONE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/domain/test_models.py -v -k ProductionJob`
Expected: FAIL — `ImportError: cannot import name 'ProductionJob' from 'semi.domain.models'`

- [ ] **Step 3: Implement `ProductionJob`**

Add to `semi/domain/models.py` (append after `Order`):

```python
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

The full file `semi/domain/models.py` now reads:

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/domain/test_models.py -v -k ProductionJob`
Expected: all 3 tests PASS

- [ ] **Step 5: Run the full domain test suite to check for regressions**

Run: `pytest tests/domain/test_models.py -v`
Expected: all tests from Tasks 2–5 PASS (14 tests total)

- [ ] **Step 6: Lint and format**

Run: `ruff check --fix . && ruff check --select I --fix . && ruff format .`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add semi/domain/models.py tests/domain/test_models.py
git commit -m "feat: add ProductionJob dataclass"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only)

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: confidence that `semi/domain` is complete and matches `docs/superpowers/specs/2026-07-15-domain-design.md` §1–2 exactly, ready for later `storage`/`services` plans to import from.

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: all 14 tests in `tests/domain/test_models.py` PASS, exit code 0

- [ ] **Step 2: Run lint across the whole repo**

Run: `ruff check .`
Expected: no errors

- [ ] **Step 3: Diff `semi/domain/models.py` against the spec field-by-field**

Run: `git show HEAD:docs/superpowers/specs/2026-07-15-domain-design.md | sed -n '13,66p'` (or open the file) and manually compare every field name/type/order in `semi/domain/models.py` against spec §1–2.
Expected: exact match — no extra fields, no renamed fields, no reordering that would break keyword-arg construction used by `storage` repositories in later plans.

- [ ] **Step 4: No commit needed**

This task is verification-only; nothing changes in the working tree.

---

## Self-Review Notes

- **Spec coverage:** §1 (enums) → Task 2. §2 (`Sample`) → Task 3. §2 (`Order`) → Task 4. §2 (`ProductionJob`) → Task 5. §3 design decisions (frozen, `datetime` fields, non-optional ids) are encoded directly into each task's implementation step and asserted in each task's tests (frozen-instance tests, `isinstance(..., datetime)` test, no-default-id fields). Nothing in the spec is left uncovered.
- **Placeholder scan:** every step has real, runnable code and exact `pytest`/`ruff` commands with stated expected output — no "TBD"/"add validation" placeholders (correctly so: the spec explicitly forbids validation logic in this layer).
- **Type consistency:** `OrderStatus`/`JobStatus` introduced in Task 2 are reused by name (not redefined) in `Order` (Task 4) and `ProductionJob` (Task 5); `Sample`/`Order`/`ProductionJob` field names match verbatim across every task and match spec §2 exactly.
