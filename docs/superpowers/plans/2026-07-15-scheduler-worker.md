# Scheduler Background Worker (`semi.scheduler`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `semi/scheduler/background_worker.py` — the single `start_worker(db_path, lock) -> threading.Thread` function that spins up the daemon thread which calls `ProductionService.tick()` once per second, exactly as specified in `docs/superpowers/specs/2026-07-15-scheduler-design.md`.

**Architecture:** One module, one public function. `start_worker` defines a nested `_run()` closure that: opens its own thread-local `sqlite3.Connection` via `connect_db`, builds a thread-local `ProductionService` wired to that connection and the shared `lock`, then loops forever calling `tick()` and sleeping 1 second, logging (not raising) any exception `tick()` raises so a transient error never kills the simulation. `start_worker` wraps `_run` in a daemon `threading.Thread`, starts it, and returns the `Thread` object to the caller (`cli/app.py`, out of scope here).

**Tech Stack:** Python 3.14+, standard-library `threading`/`time`/`traceback`, `pytest` + `pytest-mock` (`mocker` fixture) from the `test` extra (already installed per the storage-layer plan).

## Prerequisite (read before Task 1)

`background_worker.py` imports `ProductionService` from `semi.services.production_service`. That module is defined by `docs/superpowers/plans/2026-07-15-services-design.md`, a **separate, not-yet-executed** plan — as of this writing only `semi/domain` and `semi/storage` exist on disk (`semi/services` does not). Since `mocker.patch("semi.scheduler.background_worker.ProductionService", ...)` needs the real attribute to exist before it can be overwritten, and `background_worker.py` itself does a real `from semi.services.production_service import ProductionService` at import time, **Task 1 Step 0 below is a hard gate**: if it fails, stop and execute `docs/superpowers/plans/2026-07-15-services-design.md` in full first, then return here.

## Global Constraints

- Python 3.14+ (`pyproject.toml` `requires-python = ">=3.14"`).
- `pip install -e ".[dev,test]"` must already be done (it was, by the storage-layer plan); no reinstall needed unless the environment is fresh.
- Before every commit: `ruff check --fix .` then `ruff format .`.
- Commit messages follow Conventional Commits (enforced by the `commitizen` `commit-msg` hook).
- No code comments except where the WHY is non-obvious (per project style).
- `start_worker` never raises out of the loop for a `tick()` failure — only `traceback.print_exc()` and continue. This is deliberate (per `2026-07-15-scheduler-design.md` line 26): a transient error must not stop the whole production simulation.
- `_run` creates exactly one `sqlite3.Connection` (via `connect_db`) and one `ProductionService` for the entire lifetime of the worker thread — not one per tick.
- The `Lock` passed into `start_worker` is used as-is (never replaced or wrapped) — it must be the same object `cli/app.py` gives to the main-thread `OrderService`, so writes are serialized across both threads.

---

### Task 1: `background_worker.py` — `start_worker`

**Files:**
- Create: `semi/scheduler/__init__.py`
- Create: `semi/scheduler/background_worker.py`
- Create: `tests/scheduler/__init__.py`
- Test: `tests/scheduler/test_background_worker.py`

**Interfaces:**
- Consumes: `semi.storage.db.connect_db(db_path: Path) -> sqlite3.Connection`, `semi.storage.sample_repository.SampleRepository(conn)`, `semi.storage.order_repository.OrderRepository(conn)`, `semi.storage.production_job_repository.ProductionJobRepository(conn)` (all already implemented), and `semi.services.production_service.ProductionService(order_repo, job_repo, sample_repo, lock)` with a `.tick() -> None` method (from the services plan — see Prerequisite above).
- Produces: `semi.scheduler.background_worker.start_worker(db_path: Path, lock: threading.Lock) -> threading.Thread`, used by `cli/app.py` in a later, out-of-scope plan.

- [ ] **Step 0: Verify the prerequisite is met**

Run: `python -c "from semi.services.production_service import ProductionService"`
Expected: no output, exit code 0. If this raises `ModuleNotFoundError: No module named 'semi.services'`, **stop** — execute `docs/superpowers/plans/2026-07-15-services-design.md` first, then restart this task.

- [ ] **Step 1: Write the failing tests**

Create `tests/scheduler/__init__.py` (empty file).

Create `tests/scheduler/test_background_worker.py`:

```python
import threading
from pathlib import Path

import pytest

from semi.scheduler.background_worker import start_worker


class _StopWorker(Exception):
    """Test-only signal used to break the worker's `while True` loop deterministically."""


def _patch_collaborators(mocker):
    mock_conn = mocker.MagicMock(name="conn")
    connect_db = mocker.patch(
        "semi.scheduler.background_worker.connect_db", return_value=mock_conn
    )
    order_repo_cls = mocker.patch("semi.scheduler.background_worker.OrderRepository")
    job_repo_cls = mocker.patch(
        "semi.scheduler.background_worker.ProductionJobRepository"
    )
    sample_repo_cls = mocker.patch("semi.scheduler.background_worker.SampleRepository")
    prod_svc = mocker.MagicMock(name="prod_svc")
    prod_svc_cls = mocker.patch(
        "semi.scheduler.background_worker.ProductionService", return_value=prod_svc
    )
    return {
        "conn": mock_conn,
        "connect_db": connect_db,
        "order_repo_cls": order_repo_cls,
        "job_repo_cls": job_repo_cls,
        "sample_repo_cls": sample_repo_cls,
        "prod_svc": prod_svc,
        "prod_svc_cls": prod_svc_cls,
    }


def test_start_worker_returns_started_daemon_thread(mocker):
    _patch_collaborators(mocker)
    release_event = threading.Event()

    def blocking_sleep(seconds):
        release_event.wait(timeout=2)
        raise _StopWorker()

    mocker.patch(
        "semi.scheduler.background_worker.time.sleep", side_effect=blocking_sleep
    )

    thread = start_worker(Path("dummy.db"), threading.Lock())
    try:
        assert isinstance(thread, threading.Thread)
        assert thread.daemon is True
        assert thread.is_alive() is True
    finally:
        release_event.set()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_start_worker_constructs_repositories_and_service_sharing_connection_and_lock(
    mocker,
):
    collab = _patch_collaborators(mocker)
    mocker.patch(
        "semi.scheduler.background_worker.time.sleep", side_effect=_StopWorker
    )

    db_path = Path("dummy.db")
    lock = threading.Lock()
    thread = start_worker(db_path, lock)
    thread.join(timeout=2)

    collab["connect_db"].assert_called_once_with(db_path)
    collab["order_repo_cls"].assert_called_once_with(collab["conn"])
    collab["job_repo_cls"].assert_called_once_with(collab["conn"])
    collab["sample_repo_cls"].assert_called_once_with(collab["conn"])
    collab["prod_svc_cls"].assert_called_once_with(
        collab["order_repo_cls"].return_value,
        collab["job_repo_cls"].return_value,
        collab["sample_repo_cls"].return_value,
        lock,
    )


def test_start_worker_calls_tick_repeatedly_with_one_second_sleep_between_calls(
    mocker,
):
    collab = _patch_collaborators(mocker)
    stop_after = 3
    sleep_calls = []

    def counting_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= stop_after:
            raise _StopWorker()

    mocker.patch(
        "semi.scheduler.background_worker.time.sleep", side_effect=counting_sleep
    )

    thread = start_worker(Path("dummy.db"), threading.Lock())
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert sleep_calls == [1, 1, 1]
    assert collab["prod_svc"].tick.call_count == stop_after
    collab["connect_db"].assert_called_once()


def test_start_worker_logs_traceback_and_continues_when_tick_raises(mocker):
    collab = _patch_collaborators(mocker)
    collab["prod_svc"].tick.side_effect = [
        RuntimeError("boom"),
        RuntimeError("boom again"),
        None,
    ]
    stop_after = 3
    sleep_calls = []

    def counting_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= stop_after:
            raise _StopWorker()

    mocker.patch(
        "semi.scheduler.background_worker.time.sleep", side_effect=counting_sleep
    )
    print_exc = mocker.patch("semi.scheduler.background_worker.traceback.print_exc")

    thread = start_worker(Path("dummy.db"), threading.Lock())
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert collab["prod_svc"].tick.call_count == stop_after
    assert print_exc.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/scheduler/test_background_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.scheduler'`

- [ ] **Step 3: Implement `background_worker.py`**

`semi/scheduler/__init__.py` (empty file).

`semi/scheduler/background_worker.py`:

```python
import threading
import time
import traceback
from pathlib import Path

from semi.services.production_service import ProductionService
from semi.storage.db import connect_db
from semi.storage.order_repository import OrderRepository
from semi.storage.production_job_repository import ProductionJobRepository
from semi.storage.sample_repository import SampleRepository


def start_worker(db_path: Path, lock: threading.Lock) -> threading.Thread:
    def _run() -> None:
        conn = connect_db(db_path)
        prod_svc = ProductionService(
            OrderRepository(conn),
            ProductionJobRepository(conn),
            SampleRepository(conn),
            lock,
        )
        while True:
            try:
                prod_svc.tick()
            except Exception:
                traceback.print_exc()
            time.sleep(1)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/scheduler/test_background_worker.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest -v`
Expected: all tests across `tests/domain`, `tests/storage`, `tests/scheduler` (and `tests/` services tests, if the prerequisite services plan has already added them) PASS.

- [ ] **Step 6: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/scheduler tests/scheduler
git commit -m "feat(scheduler): add background_worker.start_worker"
```

---

## Out of scope

- `semi/services/production_service.py` and the rest of `semi/services` — covered by `docs/superpowers/plans/2026-07-15-services-design.md` (see Prerequisite above).
- `semi/cli/app.py` — the future entrypoint that creates the shared `Lock`, calls `start_worker(db_path, lock)`, and starts the menu loop. Not implemented by this plan.
- Graceful shutdown of the worker thread — per `2026-07-15-scheduler-design.md`, the thread is daemon-only and relies on process exit for cleanup; no stop/join API is specified or implemented here.

## Self-Review Notes

- **Spec coverage:** `2026-07-15-scheduler-design.md`'s entire content is the ~15-line `start_worker`/`_run` function plus the one paragraph of prose below it (shared `Lock` injection, daemon thread, per-thread connection). Task 1 implements the function verbatim and its tests cover: thread creation/daemon flag (test 1), per-thread connection + repository/service wiring with the shared lock (test 2), the 1-second tick loop (test 3), and exception-swallowing via `traceback.print_exc()` without stopping the loop (test 4). Nothing in the one-page spec is left uncovered.
- **Placeholder scan:** every step has full runnable code and exact `pytest` commands with stated expected output; no "TBD"/"add error handling" placeholders.
- **Type consistency:** `start_worker(db_path: Path, lock: threading.Lock) -> threading.Thread` matches the spec's signature exactly; `ProductionService(order_repo, job_repo, sample_repo, lock)` constructor argument order matches both the spec's `background_worker.py` snippet and `2026-07-15-services-design.md` §5's `ProductionService(order_repo, job_repo, sample_repo, lock)` signature.
