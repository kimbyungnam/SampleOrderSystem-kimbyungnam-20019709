# Scheduler + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `semi/scheduler` (background production-tick worker) and `semi/cli` (MVC console app: views, controllers, menu loop, entrypoint) on top of the already-implemented `semi/domain`, `semi/storage`, `semi/services` layers, wiring them into a runnable console application per PRD.md §4.

**Architecture:** `semi/scheduler/background_worker.py` spawns a daemon thread with its own SQLite connection that calls `ProductionService.tick()` every second, sharing the process-wide `threading.Lock` with the main thread's services. `semi/cli` follows MVC: `views.py` is pure `print`/`input` I/O with no service/domain calls, `controllers.py` holds one class per PRD menu that calls services and delegates all rendering to `views`, `menu_loop.py` provides the generic `MenuController` Protocol + `main_loop` dispatch loop with a single exception-handling site, and `app.py` wires everything together and starts the worker.

**Tech Stack:** Python 3.14+, stdlib `sqlite3`/`threading`/`time`/`traceback`, pytest + pytest-mock for tests (no new dependencies).

## Global Constraints

- Python 3.14+ (per `pyproject.toml` / CLAUDE.md).
- Exactly one `threading.Lock` for the whole process, created in `cli/app.py`, passed to `OrderService`, `ProductionService` (both already accept `lock` in their constructors — see `semi/services/order_service.py:8` and `semi/services/production_service.py:17`).
- Background worker is a **daemon** thread, ticks every 1 second, and must not die on a transient error — catch `Exception`, `traceback.print_exc()`, keep looping (per `docs/superpowers/specs/2026-07-15-scheduler-design.md`).
- No auth/role separation — every controller is reachable from the main menu with no gating (PRD.md §5, rule 15).
- **View layer purity**: `semi/cli/views.py` functions only call `print`/`input` and render domain objects (`Sample`, `Order`, `ProductionJobStatus`, `SampleStockStatus`) — never call into `semi.services` or `semi.domain` logic beyond reading dataclass fields.
- **Input fail-safe principle** (`docs/superpowers/specs/2026-07-15-cli-design.md` §2.1, §4): menu-selection prompts never raise on bad input — main menu (`render_main_menu`) reprompts until a valid index or `"exit"` is produced; submenu prompts (`render_sample_menu`, etc.) map any unrecognized input to `"back"`. Free-form numeric data-entry prompts (e.g. `avg_production_seconds`, `yield_rate`, `quantity`) reprompt on a parse failure rather than substituting a guessed value, so invalid data never reaches the service layer disguised as a real input.
- **Controller layer**: constructor takes only the services it needs (no wider dependency than required); `run()` never catches `DomainError`/`storage.NotFoundError` — those propagate up to `main_loop`'s single dispatch-site `try/except` (`semi/cli/menu_loop.py`).
- Controllers call view functions via the module (`from semi.cli import views` then `views.render_x(...)`), never `from semi.cli.views import render_x` — this is what lets tests `mocker.patch.object(views, "render_x", ...)` and lets `app.py` compose real controllers with real views unchanged.
- `render_main_menu` is injected into `main_loop` as a parameter, never imported directly by `menu_loop.py` (`docs/superpowers/specs/2026-07-15-cli-design.md` §2).
- `StockStatus` (`semi/services/monitoring_service.py`) stays English (`SUFFICIENT`/`SHORT`/`DEPLETED`); Korean label mapping ("여유"/"부족"/"고갈") happens only in `views.py`.
- Repositories/services already exist and are not modified by this plan: `SampleService`, `OrderService`, `ProductionService`, `MonitoringService` (all in `semi/services/`), `connect_db` (`semi/storage/db.py`), and the three repositories (`semi/storage/*_repository.py`).

---

### Task 1: `semi/scheduler/background_worker.py`

**Files:**
- Create: `semi/scheduler/__init__.py`
- Create: `semi/scheduler/background_worker.py`
- Test: `tests/scheduler/__init__.py`
- Test: `tests/scheduler/test_background_worker.py`

**Interfaces:**
- Consumes: `connect_db(db_path: Path) -> sqlite3.Connection` (`semi/storage/db.py:37`), `SampleRepository(conn)`, `OrderRepository(conn)`, `ProductionJobRepository(conn)` (all take a single `conn` positional arg), `ProductionService(order_repo, job_repo, sample_repo, lock)` with `.tick() -> None` (`semi/services/production_service.py:16-48`).
- Produces: `start_worker(db_path: Path, lock: threading.Lock) -> threading.Thread` — used by Task 11 (`cli/app.py`).

- [ ] **Step 1: Write the failing test**

Create `tests/scheduler/__init__.py` (empty file, matches the `tests/domain/__init__.py` / `tests/storage/__init__.py` convention).

```python
# tests/scheduler/test_background_worker.py
import threading
import time

import pytest

from semi.domain.models import JobStatus, OrderStatus
from semi.scheduler.background_worker import start_worker
from semi.services.order_service import OrderService
from semi.storage.db import connect_db
from semi.storage.order_repository import OrderRepository
from semi.storage.production_job_repository import ProductionJobRepository
from semi.storage.sample_repository import SampleRepository


def test_start_worker_returns_running_daemon_thread(tmp_path):
    db_path = tmp_path / "worker_smoke.db"
    lock = threading.Lock()

    thread = start_worker(db_path, lock)

    assert isinstance(thread, threading.Thread)
    assert thread.daemon is True
    assert thread.is_alive()


def test_start_worker_ticks_and_completes_queued_production(tmp_path):
    db_path = tmp_path / "worker_completion.db"
    conn = connect_db(db_path)
    sample_repo = SampleRepository(conn)
    order_repo = OrderRepository(conn)
    job_repo = ProductionJobRepository(conn)
    lock = threading.Lock()
    order_service = OrderService(order_repo, job_repo, sample_repo, lock)

    sample_repo.create("S1", "Wafer A", 0.05, 1.0)
    conn.commit()
    order = order_service.create_order("S1", "ACME", 3)
    order_service.approve(order.order_id)  # stock=0 < 3 -> PRODUCING, actual_quantity=3

    start_worker(db_path, lock)

    deadline = time.monotonic() + 3.0
    updated_status = None
    while time.monotonic() < deadline:
        updated_status = order_repo.get_by_id(order.order_id).status
        if updated_status == OrderStatus.CONFIRMED:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"production job did not complete in time, last status={updated_status}")

    assert sample_repo.get_by_id("S1").stock_quantity == 3
    assert job_repo.get_by_order_id(order.order_id).status == JobStatus.DONE

    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/scheduler/test_background_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.scheduler'`

- [ ] **Step 3: Write minimal implementation**

`semi/scheduler/__init__.py` is an empty file (create it with `Write` and no content).

```python
# semi/scheduler/background_worker.py
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/scheduler/test_background_worker.py -v`
Expected: PASS (2 passed). The completion test may take up to ~1-2s wall-clock (worker ticks once per second).

- [ ] **Step 5: Commit**

```bash
git add semi/scheduler/__init__.py semi/scheduler/background_worker.py tests/scheduler/__init__.py tests/scheduler/test_background_worker.py
git commit -m "feat(scheduler): add background_worker daemon thread"
```

---

### Task 2: `semi/cli/menu_loop.py`

**Files:**
- Create: `semi/cli/__init__.py`
- Create: `semi/cli/menu_loop.py`
- Test: `tests/cli/__init__.py`
- Test: `tests/cli/test_menu_loop.py`

**Interfaces:**
- Consumes: `semi.services.exceptions.DomainError`, `semi.storage.exceptions.NotFoundError`.
- Produces: `MenuController` Protocol (attrs: `label: str`, method `run() -> None`) and `main_loop(controllers: list[MenuController], render_main_menu: Callable[[list[str]], int | str]) -> None`. Task 6-10 controllers structurally satisfy this Protocol (duck typing, no inheritance needed). Task 11 (`app.py`) calls `main_loop(controllers, render_main_menu=render_main_menu)`.

- [ ] **Step 1: Write the failing test**

Create `tests/cli/__init__.py` (empty file).

```python
# tests/cli/test_menu_loop.py
import pytest

from semi.cli.menu_loop import main_loop
from semi.services.exceptions import DomainError
from semi.storage.exceptions import NotFoundError


class _FakeController:
    def __init__(self, label, action=None):
        self.label = label
        self._action = action
        self.run_calls = 0

    def run(self) -> None:
        self.run_calls += 1
        if self._action is not None:
            self._action()


def test_main_loop_exits_immediately_when_render_returns_exit():
    controller = _FakeController("시료 관리")

    main_loop([controller], render_main_menu=lambda labels: "exit")

    assert controller.run_calls == 0


def test_main_loop_dispatches_to_selected_controller_then_exits():
    controller_a = _FakeController("시료 관리")
    controller_b = _FakeController("주문 접수")
    choices = iter([1, "exit"])

    main_loop([controller_a, controller_b], render_main_menu=lambda labels: next(choices))

    assert controller_a.run_calls == 0
    assert controller_b.run_calls == 1


def test_main_loop_passes_controller_labels_to_render_main_menu():
    controller_a = _FakeController("시료 관리")
    controller_b = _FakeController("주문 접수")
    seen_labels = []

    def render(labels):
        seen_labels.append(list(labels))
        return "exit"

    main_loop([controller_a, controller_b], render_main_menu=render)

    assert seen_labels == [["시료 관리", "주문 접수"]]


def test_main_loop_catches_domain_error_and_continues(capsys):
    def raise_domain_error():
        raise DomainError("bad quantity")

    controller = _FakeController("주문 접수", action=raise_domain_error)
    choices = iter([0, "exit"])

    main_loop([controller], render_main_menu=lambda labels: next(choices))

    assert controller.run_calls == 1
    assert "[오류] bad quantity" in capsys.readouterr().out


def test_main_loop_catches_not_found_error_and_continues(capsys):
    def raise_not_found():
        raise NotFoundError("order_id=99 not found")

    controller = _FakeController("출고 처리", action=raise_not_found)
    choices = iter([0, "exit"])

    main_loop([controller], render_main_menu=lambda labels: next(choices))

    assert controller.run_calls == 1
    assert "[조회 실패] order_id=99 not found" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_menu_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# semi/cli/__init__.py
```
(empty file)

```python
# semi/cli/menu_loop.py
from typing import Callable, Protocol

from semi.services.exceptions import DomainError
from semi.storage.exceptions import NotFoundError


class MenuController(Protocol):
    label: str

    def run(self) -> None: ...


def main_loop(
    controllers: list[MenuController],
    render_main_menu: Callable[[list[str]], int | str],
) -> None:
    while True:
        choice = render_main_menu([c.label for c in controllers])
        if choice == "exit":
            break
        try:
            controllers[choice].run()
        except DomainError as e:
            print(f"[오류] {e}")
        except NotFoundError as e:
            print(f"[조회 실패] {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_menu_loop.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add semi/cli/__init__.py semi/cli/menu_loop.py tests/cli/__init__.py tests/cli/test_menu_loop.py
git commit -m "feat(cli): add MenuController protocol and main_loop dispatch"
```

---

### Task 3: `semi/cli/views.py` — main menu + sample views

**Files:**
- Create: `semi/cli/views.py`
- Test: `tests/cli/test_views_sample.py`

**Interfaces:**
- Consumes: `semi.domain.models.Sample` (fields: `sample_id, name, avg_production_seconds, yield_rate, stock_quantity`).
- Produces: `render_main_menu(labels: list[str]) -> int | str`, `render_sample_menu() -> str` (`"register"|"list"|"search"|"back"`), `prompt_sample_registration() -> dict` (keys `sample_id, name, avg_production_seconds, yield_rate`), `prompt_search_query() -> str`, `render_sample_list(samples: list[Sample]) -> None`, `render_sample_registered(sample: Sample) -> None`. Consumed by Task 2 (`render_main_menu`, via `app.py`) and Task 6 (`SampleMenuController`).

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_views_sample.py
from semi.cli import views
from semi.domain.models import Sample


def test_render_main_menu_returns_zero_based_index_for_valid_choice(mocker, capsys):
    mocker.patch("builtins.input", return_value="2")

    result = views.render_main_menu(["시료 관리", "주문 접수"])

    assert result == 1
    out = capsys.readouterr().out
    assert "1. 시료 관리" in out
    assert "2. 주문 접수" in out


def test_render_main_menu_returns_exit_for_zero():
    import builtins

    original_input = builtins.input
    builtins.input = lambda *_: "0"
    try:
        assert views.render_main_menu(["시료 관리"]) == "exit"
    finally:
        builtins.input = original_input


def test_render_main_menu_reprompts_on_non_numeric_then_out_of_range_then_valid(mocker, capsys):
    mocker.patch("builtins.input", side_effect=["abc", "9", "1"])

    result = views.render_main_menu(["시료 관리"])

    assert result == 0
    out = capsys.readouterr().out
    assert out.count("[오류]") == 2


def test_render_sample_menu_maps_known_inputs(mocker):
    mocker.patch("builtins.input", return_value="1")
    assert views.render_sample_menu() == "register"

    mocker.patch("builtins.input", return_value="2")
    assert views.render_sample_menu() == "list"

    mocker.patch("builtins.input", return_value="3")
    assert views.render_sample_menu() == "search"

    mocker.patch("builtins.input", return_value="0")
    assert views.render_sample_menu() == "back"


def test_render_sample_menu_maps_unrecognized_input_to_back(mocker):
    mocker.patch("builtins.input", return_value="garbage")
    assert views.render_sample_menu() == "back"


def test_prompt_sample_registration_collects_all_fields(mocker):
    mocker.patch(
        "builtins.input", side_effect=["S1", "Wafer A", "12.5", "0.9"]
    )

    data = views.prompt_sample_registration()

    assert data == {
        "sample_id": "S1",
        "name": "Wafer A",
        "avg_production_seconds": 12.5,
        "yield_rate": 0.9,
    }


def test_prompt_sample_registration_reprompts_on_invalid_number(mocker, capsys):
    mocker.patch(
        "builtins.input",
        side_effect=["S1", "Wafer A", "not-a-number", "12.5", "0.9"],
    )

    data = views.prompt_sample_registration()

    assert data["avg_production_seconds"] == 12.5
    assert "[오류]" in capsys.readouterr().out


def test_prompt_search_query_returns_stripped_input(mocker):
    mocker.patch("builtins.input", return_value="  Wafer  ")
    assert views.prompt_search_query() == "Wafer"


def test_render_sample_list_prints_each_sample(capsys):
    samples = [Sample("S1", "Wafer A", 10.0, 0.9, 5)]

    views.render_sample_list(samples)

    out = capsys.readouterr().out
    assert "S1" in out
    assert "Wafer A" in out
    assert "5" in out


def test_render_sample_registered_prints_sample_id(capsys):
    sample = Sample("S1", "Wafer A", 10.0, 0.9, 0)

    views.render_sample_registered(sample)

    assert "S1" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_views_sample.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.cli.views'`

- [ ] **Step 3: Write minimal implementation**

```python
# semi/cli/views.py
from semi.domain.models import Sample


def _prompt_float(prompt: str) -> float:
    while True:
        raw = input(prompt).strip()
        try:
            return float(raw)
        except ValueError:
            print("[오류] 숫자를 입력하세요.")


def render_main_menu(labels: list[str]) -> int | str:
    while True:
        print("\n=== 메인 메뉴 ===")
        for i, label in enumerate(labels, start=1):
            print(f"{i}. {label}")
        print("0. 종료")
        raw = input("선택: ").strip()
        if raw == "0":
            return "exit"
        try:
            choice = int(raw)
        except ValueError:
            print("[오류] 숫자를 입력하세요.")
            continue
        if 1 <= choice <= len(labels):
            return choice - 1
        print("[오류] 올바른 번호를 입력하세요.")


def render_sample_menu() -> str:
    print("\n--- 시료 관리 ---")
    print("1. 시료 등록")
    print("2. 시료 목록 조회")
    print("3. 이름 검색")
    print("0. 뒤로가기")
    raw = input("선택: ").strip()
    return {"1": "register", "2": "list", "3": "search"}.get(raw, "back")


def prompt_sample_registration() -> dict:
    sample_id = input("시료 ID: ").strip()
    name = input("이름: ").strip()
    avg_production_seconds = _prompt_float("평균 생산시간(초): ")
    yield_rate = _prompt_float("수율 (0~1): ")
    return {
        "sample_id": sample_id,
        "name": name,
        "avg_production_seconds": avg_production_seconds,
        "yield_rate": yield_rate,
    }


def prompt_search_query() -> str:
    return input("검색할 이름: ").strip()


def render_sample_list(samples: list[Sample]) -> None:
    print("\n--- 시료 목록 ---")
    if not samples:
        print("등록된 시료가 없습니다.")
        return
    for sample in samples:
        print(
            f"[{sample.sample_id}] {sample.name} | 평균생산시간={sample.avg_production_seconds}s "
            f"| 수율={sample.yield_rate} | 재고={sample.stock_quantity}"
        )


def render_sample_registered(sample: Sample) -> None:
    print(f"시료 등록 완료: {sample.sample_id} ({sample.name})")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_views_sample.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add semi/cli/views.py tests/cli/test_views_sample.py
git commit -m "feat(cli): add main menu and sample management views"
```

---

### Task 4: `semi/cli/views.py` — order views

**Files:**
- Modify: `semi/cli/views.py` (append)
- Test: `tests/cli/test_views_order.py`

**Interfaces:**
- Consumes: `semi.domain.models.Order` (fields: `order_id, sample_id, customer_name, quantity, status, created_at`).
- Produces: `render_order_menu() -> str` (`"create"|"approve_reject"|"back"`), `prompt_order_creation() -> dict` (keys `sample_id, customer_name, quantity`), `render_order_created(order: Order) -> None`, `render_reserved_orders(orders: list[Order]) -> None`, `prompt_order_action(orders: list[Order]) -> tuple[int, str] | None` (returns `(order_id, "approve"|"reject")` or `None` for "back"/invalid), `render_order_result(order: Order) -> None`. Consumed by Task 7 (`OrderMenuController`).

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_views_order.py
from datetime import datetime

from semi.cli import views
from semi.domain.models import Order, OrderStatus


def _order(order_id=1, status=OrderStatus.RESERVED, quantity=5):
    return Order(order_id, "S1", "ACME", quantity, status, datetime.now())


def test_render_order_menu_maps_known_inputs(mocker):
    mocker.patch("builtins.input", return_value="1")
    assert views.render_order_menu() == "create"

    mocker.patch("builtins.input", return_value="2")
    assert views.render_order_menu() == "approve_reject"

    mocker.patch("builtins.input", return_value="0")
    assert views.render_order_menu() == "back"


def test_render_order_menu_maps_unrecognized_input_to_back(mocker):
    mocker.patch("builtins.input", return_value="xyz")
    assert views.render_order_menu() == "back"


def test_prompt_order_creation_collects_fields(mocker):
    mocker.patch("builtins.input", side_effect=["S1", "ACME", "5"])

    data = views.prompt_order_creation()

    assert data == {"sample_id": "S1", "customer_name": "ACME", "quantity": 5}


def test_prompt_order_creation_reprompts_on_invalid_quantity(mocker, capsys):
    mocker.patch("builtins.input", side_effect=["S1", "ACME", "not-a-number", "5"])

    data = views.prompt_order_creation()

    assert data["quantity"] == 5
    assert "[오류]" in capsys.readouterr().out


def test_render_order_created_prints_order_id(capsys):
    views.render_order_created(_order(order_id=7))
    assert "7" in capsys.readouterr().out


def test_render_reserved_orders_prints_each_order(capsys):
    orders = [_order(order_id=1), _order(order_id=2, quantity=3)]

    views.render_reserved_orders(orders)

    out = capsys.readouterr().out
    assert "1" in out and "2" in out


def test_render_reserved_orders_handles_empty_list(capsys):
    views.render_reserved_orders([])
    assert "없습니다" in capsys.readouterr().out


def test_prompt_order_action_returns_approve_for_valid_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", side_effect=["3", "a"])

    result = views.prompt_order_action(orders)

    assert result == (3, "approve")


def test_prompt_order_action_returns_reject_for_valid_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", side_effect=["3", "r"])

    result = views.prompt_order_action(orders)

    assert result == (3, "reject")


def test_prompt_order_action_returns_none_for_back_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", return_value="0")

    assert views.prompt_order_action(orders) is None


def test_prompt_order_action_returns_none_for_unknown_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", return_value="99")

    assert views.prompt_order_action(orders) is None


def test_prompt_order_action_returns_none_for_non_numeric_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", return_value="abc")

    assert views.prompt_order_action(orders) is None


def test_prompt_order_action_returns_none_for_unrecognized_action(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", side_effect=["3", "z"])

    assert views.prompt_order_action(orders) is None


def test_render_order_result_prints_status(capsys):
    views.render_order_result(_order(order_id=3, status=OrderStatus.CONFIRMED))
    out = capsys.readouterr().out
    assert "3" in out
    assert "CONFIRMED" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_views_order.py -v`
Expected: FAIL with `AttributeError: module 'semi.cli.views' has no attribute 'render_order_menu'`

- [ ] **Step 3: Write minimal implementation**

Append to `semi/cli/views.py` (add `Order` to the existing `from semi.domain.models import Sample` import line, changing it to `from semi.domain.models import Order, Sample`):

```python
def _prompt_int(prompt: str) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            return int(raw)
        except ValueError:
            print("[오류] 숫자를 입력하세요.")


def render_order_menu() -> str:
    print("\n--- 주문 접수 / 승인 / 거절 ---")
    print("1. 주문 접수")
    print("2. 승인/거절 대상 조회 및 처리")
    print("0. 뒤로가기")
    raw = input("선택: ").strip()
    return {"1": "create", "2": "approve_reject"}.get(raw, "back")


def prompt_order_creation() -> dict:
    sample_id = input("시료 ID: ").strip()
    customer_name = input("고객명: ").strip()
    quantity = _prompt_int("주문 수량: ")
    return {"sample_id": sample_id, "customer_name": customer_name, "quantity": quantity}


def render_order_created(order: Order) -> None:
    print(f"주문 접수 완료: 주문ID={order.order_id} (상태={order.status})")


def render_reserved_orders(orders: list[Order]) -> None:
    print("\n--- 접수 대기(RESERVED) 주문 ---")
    if not orders:
        print("대기 중인 주문이 없습니다.")
        return
    for order in orders:
        print(
            f"주문ID={order.order_id} | 시료={order.sample_id} "
            f"| 고객={order.customer_name} | 수량={order.quantity}"
        )


def prompt_order_action(orders: list[Order]) -> tuple[int, str] | None:
    valid_ids = {order.order_id for order in orders}
    raw_id = input("처리할 주문 ID (0: 뒤로가기): ").strip()
    try:
        order_id = int(raw_id)
    except ValueError:
        return None
    if order_id == 0 or order_id not in valid_ids:
        return None
    raw_action = input("승인(a) / 거절(r): ").strip().lower()
    action = {"a": "approve", "r": "reject"}.get(raw_action)
    if action is None:
        return None
    return order_id, action


def render_order_result(order: Order) -> None:
    print(f"주문 {order.order_id} 처리 완료: 상태={order.status}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_views_order.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add semi/cli/views.py tests/cli/test_views_order.py
git commit -m "feat(cli): add order creation and approve/reject views"
```

---

### Task 5: `semi/cli/views.py` — monitoring, production, release views

**Files:**
- Modify: `semi/cli/views.py` (append)
- Test: `tests/cli/test_views_monitoring_production_release.py`

**Interfaces:**
- Consumes: `semi.services.monitoring_service.SampleStockStatus`, `semi.services.monitoring_service.StockStatus`, `semi.services.production_service.ProductionJobStatus`, `semi.domain.models.OrderStatus`, `semi.domain.models.Order`.
- Produces: `render_monitoring_menu() -> str` (`"order_counts"|"stock_status"|"back"`), `render_order_counts(counts: dict[OrderStatus, int]) -> None`, `render_stock_status(statuses: list[SampleStockStatus]) -> None`, `render_production_menu() -> str` (`"current"|"queue"|"back"`), `render_current_production(status: ProductionJobStatus | None) -> None`, `render_production_queue(statuses: list[ProductionJobStatus]) -> None`, `render_release_menu` is not needed (release flow has no submenu — see Task 10), `render_confirmed_orders(orders: list[Order]) -> None`, `prompt_release_selection(orders: list[Order]) -> int | None`, `render_release_result(order: Order) -> None`. Consumed by Task 8 (`MonitoringMenuController`), Task 9 (`ProductionMenuController`), Task 10 (`ReleaseMenuController`).

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_views_monitoring_production_release.py
from datetime import datetime, timedelta

from semi.cli import views
from semi.domain.models import JobStatus, Order, OrderStatus, ProductionJob
from semi.services.monitoring_service import SampleStockStatus, StockStatus
from semi.services.production_service import ProductionJobStatus


def _sample_stock_status(status, outstanding=5):
    from semi.domain.models import Sample

    return SampleStockStatus(
        sample=Sample("S1", "Wafer A", 10.0, 0.9, 3), outstanding=outstanding, status=status
    )


def _job_status(job_id=1):
    job = ProductionJob(
        job_id=job_id,
        order_id=1,
        sample_id="S1",
        shortfall_quantity=2,
        actual_quantity=3,
        total_duration_seconds=30.0,
        status=JobStatus.IN_PROGRESS,
        enqueued_at=datetime.now(),
        started_at=datetime.now(),
    )
    return ProductionJobStatus(
        job=job,
        progress_ratio=0.5,
        produced_so_far=1,
        estimated_completion_at=datetime.now() + timedelta(seconds=15),
    )


def test_render_monitoring_menu_maps_known_inputs(mocker):
    mocker.patch("builtins.input", return_value="1")
    assert views.render_monitoring_menu() == "order_counts"

    mocker.patch("builtins.input", return_value="2")
    assert views.render_monitoring_menu() == "stock_status"

    mocker.patch("builtins.input", return_value="0")
    assert views.render_monitoring_menu() == "back"


def test_render_monitoring_menu_maps_unrecognized_input_to_back(mocker):
    mocker.patch("builtins.input", return_value="nope")
    assert views.render_monitoring_menu() == "back"


def test_render_order_counts_prints_each_status(capsys):
    counts = {
        OrderStatus.RESERVED: 2,
        OrderStatus.CONFIRMED: 1,
        OrderStatus.PRODUCING: 0,
        OrderStatus.RELEASE: 4,
    }

    views.render_order_counts(counts)

    out = capsys.readouterr().out
    assert "접수" in out
    assert "출고완료" in out
    assert "4" in out


def test_render_stock_status_maps_korean_labels(capsys):
    statuses = [
        _sample_stock_status(StockStatus.SUFFICIENT),
        _sample_stock_status(StockStatus.SHORT),
        _sample_stock_status(StockStatus.DEPLETED),
    ]

    views.render_stock_status(statuses)

    out = capsys.readouterr().out
    assert "여유" in out
    assert "부족" in out
    assert "고갈" in out


def test_render_production_menu_maps_known_inputs(mocker):
    mocker.patch("builtins.input", return_value="1")
    assert views.render_production_menu() == "current"

    mocker.patch("builtins.input", return_value="2")
    assert views.render_production_menu() == "queue"

    mocker.patch("builtins.input", return_value="0")
    assert views.render_production_menu() == "back"


def test_render_current_production_handles_none(capsys):
    views.render_current_production(None)
    assert "없습니다" in capsys.readouterr().out


def test_render_current_production_prints_progress(capsys):
    views.render_current_production(_job_status(job_id=9))

    out = capsys.readouterr().out
    assert "9" in out
    assert "50" in out or "0.5" in out


def test_render_production_queue_handles_empty(capsys):
    views.render_production_queue([])
    assert "없습니다" in capsys.readouterr().out


def test_render_production_queue_prints_each_job(capsys):
    views.render_production_queue([_job_status(job_id=5), _job_status(job_id=6)])

    out = capsys.readouterr().out
    assert "5" in out and "6" in out


def test_render_confirmed_orders_handles_empty(capsys):
    views.render_confirmed_orders([])
    assert "없습니다" in capsys.readouterr().out


def test_render_confirmed_orders_prints_each_order(capsys):
    orders = [Order(1, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]

    views.render_confirmed_orders(orders)

    out = capsys.readouterr().out
    assert "1" in out
    assert "ACME" in out


def test_prompt_release_selection_returns_id_for_valid_choice(mocker):
    orders = [Order(4, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]
    mocker.patch("builtins.input", return_value="4")

    assert views.prompt_release_selection(orders) == 4


def test_prompt_release_selection_returns_none_for_back():
    import builtins

    orders = [Order(4, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]
    original_input = builtins.input
    builtins.input = lambda *_: "0"
    try:
        assert views.prompt_release_selection(orders) is None
    finally:
        builtins.input = original_input


def test_prompt_release_selection_returns_none_for_unknown_id(mocker):
    orders = [Order(4, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]
    mocker.patch("builtins.input", return_value="99")

    assert views.prompt_release_selection(orders) is None


def test_prompt_release_selection_returns_none_for_non_numeric(mocker):
    orders = [Order(4, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]
    mocker.patch("builtins.input", return_value="abc")

    assert views.prompt_release_selection(orders) is None


def test_render_release_result_prints_order_id(capsys):
    order = Order(4, "S1", "ACME", 5, OrderStatus.RELEASE, datetime.now())

    views.render_release_result(order)

    out = capsys.readouterr().out
    assert "4" in out
    assert "RELEASE" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_views_monitoring_production_release.py -v`
Expected: FAIL with `AttributeError: module 'semi.cli.views' has no attribute 'render_monitoring_menu'`

- [ ] **Step 3: Write minimal implementation**

Append to `semi/cli/views.py`. Add these imports at the top alongside the existing ones:

```python
from semi.domain.models import Order, OrderStatus, Sample
from semi.services.monitoring_service import StockStatus
```

(`Order`/`Sample` already imported from Tasks 3-4 — merge into one `from semi.domain.models import Order, OrderStatus, Sample` line.)

```python
_ORDER_STATUS_LABELS = {
    OrderStatus.RESERVED: "접수",
    OrderStatus.CONFIRMED: "출고대기",
    OrderStatus.PRODUCING: "생산중",
    OrderStatus.RELEASE: "출고완료",
}

_STOCK_STATUS_LABELS = {
    StockStatus.SUFFICIENT: "여유",
    StockStatus.SHORT: "부족",
    StockStatus.DEPLETED: "고갈",
}


def render_monitoring_menu() -> str:
    print("\n--- 모니터링 ---")
    print("1. 상태별 주문 수 확인")
    print("2. 재고 현황 확인")
    print("0. 뒤로가기")
    raw = input("선택: ").strip()
    return {"1": "order_counts", "2": "stock_status"}.get(raw, "back")


def render_order_counts(counts: dict) -> None:
    print("\n--- 상태별 주문 수 ---")
    for status, count in counts.items():
        print(f"{_ORDER_STATUS_LABELS[status]}: {count}")


def render_stock_status(statuses: list) -> None:
    print("\n--- 재고 현황 ---")
    for entry in statuses:
        label = _STOCK_STATUS_LABELS[entry.status]
        print(
            f"[{entry.sample.sample_id}] {entry.sample.name} | 재고={entry.sample.stock_quantity} "
            f"| 미완료주문={entry.outstanding} | 상태={label}"
        )


def render_production_menu() -> str:
    print("\n--- 생산 라인 ---")
    print("1. 현재 생산 현황")
    print("2. 생산 큐 조회")
    print("0. 뒤로가기")
    raw = input("선택: ").strip()
    return {"1": "current", "2": "queue"}.get(raw, "back")


def render_current_production(status) -> None:
    print("\n--- 현재 생산 현황 ---")
    if status is None:
        print("현재 생산 중인 작업이 없습니다.")
        return
    job = status.job
    print(
        f"작업ID={job.job_id} | 주문ID={job.order_id} | 시료={job.sample_id} "
        f"| 부족분={job.shortfall_quantity} | 실생산량={job.actual_quantity} "
        f"| 진행률={status.progress_ratio:.0%} | 현재생산량={status.produced_so_far} "
        f"| 예상완료={status.estimated_completion_at}"
    )


def render_production_queue(statuses: list) -> None:
    print("\n--- 생산 대기열(FIFO) ---")
    if not statuses:
        print("대기 중인 생산 작업이 없습니다.")
        return
    for status in statuses:
        job = status.job
        print(
            f"작업ID={job.job_id} | 주문ID={job.order_id} | 시료={job.sample_id} "
            f"| 실생산량={job.actual_quantity} | 예상완료={status.estimated_completion_at}"
        )


def render_confirmed_orders(orders: list) -> None:
    print("\n--- 출고 대기(CONFIRMED) 주문 ---")
    if not orders:
        print("출고 대기 중인 주문이 없습니다.")
        return
    for order in orders:
        print(
            f"주문ID={order.order_id} | 시료={order.sample_id} "
            f"| 고객={order.customer_name} | 수량={order.quantity}"
        )


def prompt_release_selection(orders: list) -> int | None:
    valid_ids = {order.order_id for order in orders}
    raw_id = input("출고 처리할 주문 ID (0: 뒤로가기): ").strip()
    try:
        order_id = int(raw_id)
    except ValueError:
        return None
    if order_id == 0 or order_id not in valid_ids:
        return None
    return order_id


def render_release_result(order) -> None:
    print(f"주문 {order.order_id} 출고 완료: 상태={order.status}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_views_monitoring_production_release.py -v`
Expected: PASS (17 passed)

- [ ] **Step 5: Commit**

```bash
git add semi/cli/views.py tests/cli/test_views_monitoring_production_release.py
git commit -m "feat(cli): add monitoring, production, and release views"
```

---

### Task 6: `semi/cli/controllers.py` — `SampleMenuController`

**Files:**
- Create: `semi/cli/controllers.py`
- Test: `tests/cli/test_sample_menu_controller.py`

**Interfaces:**
- Consumes: `semi.services.sample_service.SampleService` (`.register(sample_id, name, avg_production_seconds, yield_rate) -> Sample`, `.list_all() -> list[Sample]`, `.search_by_name(query) -> list[Sample]`), `semi.cli.views` module (`render_sample_menu`, `prompt_sample_registration`, `render_sample_registered`, `render_sample_list`, `prompt_search_query`).
- Produces: `SampleMenuController` with `label = "시료 관리"` and `run() -> None`, satisfying the `MenuController` Protocol from Task 2. Consumed by Task 11 (`app.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_sample_menu_controller.py
from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import SampleMenuController
from semi.domain.models import Sample


def test_label_is_sample_management():
    assert SampleMenuController(MagicMock()).label == "시료 관리"


def test_run_registers_sample_then_exits_on_back(mocker):
    service = MagicMock()
    registered = Sample("S1", "Wafer A", 10.0, 0.9, 0)
    service.register.return_value = registered
    mocker.patch.object(views, "render_sample_menu", side_effect=["register", "back"])
    mocker.patch.object(
        views,
        "prompt_sample_registration",
        return_value={
            "sample_id": "S1",
            "name": "Wafer A",
            "avg_production_seconds": 10.0,
            "yield_rate": 0.9,
        },
    )
    render_registered = mocker.patch.object(views, "render_sample_registered")

    SampleMenuController(service).run()

    service.register.assert_called_once_with(
        sample_id="S1", name="Wafer A", avg_production_seconds=10.0, yield_rate=0.9
    )
    render_registered.assert_called_once_with(registered)


def test_run_lists_samples_then_exits_on_back(mocker):
    service = MagicMock()
    samples = [Sample("S1", "Wafer A", 10.0, 0.9, 5)]
    service.list_all.return_value = samples
    mocker.patch.object(views, "render_sample_menu", side_effect=["list", "back"])
    render_list = mocker.patch.object(views, "render_sample_list")

    SampleMenuController(service).run()

    render_list.assert_called_once_with(samples)


def test_run_searches_samples_then_exits_on_back(mocker):
    service = MagicMock()
    service.search_by_name.return_value = []
    mocker.patch.object(views, "render_sample_menu", side_effect=["search", "back"])
    mocker.patch.object(views, "prompt_search_query", return_value="Wafer")
    render_list = mocker.patch.object(views, "render_sample_list")

    SampleMenuController(service).run()

    service.search_by_name.assert_called_once_with("Wafer")
    render_list.assert_called_once_with([])


def test_run_returns_immediately_on_back(mocker):
    service = MagicMock()
    mocker.patch.object(views, "render_sample_menu", return_value="back")

    SampleMenuController(service).run()

    service.register.assert_not_called()
    service.list_all.assert_not_called()
    service.search_by_name.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_sample_menu_controller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.cli.controllers'`

- [ ] **Step 3: Write minimal implementation**

```python
# semi/cli/controllers.py
from semi.cli import views


class SampleMenuController:
    label = "시료 관리"

    def __init__(self, sample_service) -> None:
        self._service = sample_service

    def run(self) -> None:
        while True:
            choice = views.render_sample_menu()
            if choice == "back":
                return
            elif choice == "register":
                data = views.prompt_sample_registration()
                sample = self._service.register(**data)
                views.render_sample_registered(sample)
            elif choice == "list":
                views.render_sample_list(self._service.list_all())
            elif choice == "search":
                query = views.prompt_search_query()
                views.render_sample_list(self._service.search_by_name(query))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_sample_menu_controller.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add semi/cli/controllers.py tests/cli/test_sample_menu_controller.py
git commit -m "feat(cli): add SampleMenuController"
```

---

### Task 7: `semi/cli/controllers.py` — `OrderMenuController`

**Files:**
- Modify: `semi/cli/controllers.py` (append)
- Test: `tests/cli/test_order_menu_controller.py`

**Interfaces:**
- Consumes: `semi.services.order_service.OrderService` (`.create_order(sample_id, customer_name, quantity) -> Order`, `.approve(order_id) -> Order`, `.reject(order_id) -> Order`), `semi.services.monitoring_service.MonitoringService` (`.list_by_status(status) -> list[Order]`), `semi.domain.models.OrderStatus.RESERVED`, `views` (`render_order_menu`, `prompt_order_creation`, `render_order_created`, `render_reserved_orders`, `prompt_order_action`, `render_order_result`).
- Produces: `OrderMenuController(order_service, monitoring_service)` with `label = "주문 접수 / 승인 / 거절"` and `run() -> None`. Consumed by Task 11 (`app.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_order_menu_controller.py
from datetime import datetime
from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import OrderMenuController
from semi.domain.models import Order, OrderStatus


def _order(order_id=1, status=OrderStatus.RESERVED):
    return Order(order_id, "S1", "ACME", 5, status, datetime.now())


def test_label_is_order_menu():
    assert OrderMenuController(MagicMock(), MagicMock()).label == "주문 접수 / 승인 / 거절"


def test_run_creates_order_then_exits_on_back(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    created = _order(order_id=9)
    order_service.create_order.return_value = created
    mocker.patch.object(views, "render_order_menu", side_effect=["create", "back"])
    mocker.patch.object(
        views,
        "prompt_order_creation",
        return_value={"sample_id": "S1", "customer_name": "ACME", "quantity": 5},
    )
    render_created = mocker.patch.object(views, "render_order_created")

    OrderMenuController(order_service, monitoring_service).run()

    order_service.create_order.assert_called_once_with(
        sample_id="S1", customer_name="ACME", quantity=5
    )
    render_created.assert_called_once_with(created)


def test_run_approves_selected_reserved_order(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    reserved = _order(order_id=3)
    monitoring_service.list_by_status.return_value = [reserved]
    approved = _order(order_id=3, status=OrderStatus.CONFIRMED)
    order_service.approve.return_value = approved
    mocker.patch.object(views, "render_order_menu", side_effect=["approve_reject", "back"])
    mocker.patch.object(views, "render_reserved_orders")
    mocker.patch.object(views, "prompt_order_action", return_value=(3, "approve"))
    render_result = mocker.patch.object(views, "render_order_result")

    OrderMenuController(order_service, monitoring_service).run()

    monitoring_service.list_by_status.assert_called_once_with(OrderStatus.RESERVED)
    order_service.approve.assert_called_once_with(3)
    order_service.reject.assert_not_called()
    render_result.assert_called_once_with(approved)


def test_run_rejects_selected_reserved_order(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    reserved = _order(order_id=4)
    monitoring_service.list_by_status.return_value = [reserved]
    rejected = _order(order_id=4, status=OrderStatus.REJECTED)
    order_service.reject.return_value = rejected
    mocker.patch.object(views, "render_order_menu", side_effect=["approve_reject", "back"])
    mocker.patch.object(views, "render_reserved_orders")
    mocker.patch.object(views, "prompt_order_action", return_value=(4, "reject"))
    render_result = mocker.patch.object(views, "render_order_result")

    OrderMenuController(order_service, monitoring_service).run()

    order_service.reject.assert_called_once_with(4)
    order_service.approve.assert_not_called()
    render_result.assert_called_once_with(rejected)


def test_run_does_nothing_when_action_selection_is_none(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    monitoring_service.list_by_status.return_value = [_order(order_id=5)]
    mocker.patch.object(views, "render_order_menu", side_effect=["approve_reject", "back"])
    mocker.patch.object(views, "render_reserved_orders")
    mocker.patch.object(views, "prompt_order_action", return_value=None)

    OrderMenuController(order_service, monitoring_service).run()

    order_service.approve.assert_not_called()
    order_service.reject.assert_not_called()


def test_run_does_not_prompt_for_action_when_no_reserved_orders(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    monitoring_service.list_by_status.return_value = []
    mocker.patch.object(views, "render_order_menu", side_effect=["approve_reject", "back"])
    mocker.patch.object(views, "render_reserved_orders")
    prompt_action = mocker.patch.object(views, "prompt_order_action")

    OrderMenuController(order_service, monitoring_service).run()

    prompt_action.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_order_menu_controller.py -v`
Expected: FAIL with `ImportError: cannot import name 'OrderMenuController' from 'semi.cli.controllers'`

- [ ] **Step 3: Write minimal implementation**

Append to `semi/cli/controllers.py`, adding `from semi.domain.models import OrderStatus` to the imports:

```python
class OrderMenuController:
    label = "주문 접수 / 승인 / 거절"

    def __init__(self, order_service, monitoring_service) -> None:
        self._order_service = order_service
        self._monitoring_service = monitoring_service

    def run(self) -> None:
        while True:
            choice = views.render_order_menu()
            if choice == "back":
                return
            elif choice == "create":
                data = views.prompt_order_creation()
                order = self._order_service.create_order(**data)
                views.render_order_created(order)
            elif choice == "approve_reject":
                self._approve_or_reject()

    def _approve_or_reject(self) -> None:
        orders = self._monitoring_service.list_by_status(OrderStatus.RESERVED)
        views.render_reserved_orders(orders)
        if not orders:
            return
        selection = views.prompt_order_action(orders)
        if selection is None:
            return
        order_id, action = selection
        if action == "approve":
            order = self._order_service.approve(order_id)
        else:
            order = self._order_service.reject(order_id)
        views.render_order_result(order)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_order_menu_controller.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add semi/cli/controllers.py tests/cli/test_order_menu_controller.py
git commit -m "feat(cli): add OrderMenuController"
```

---

### Task 8: `semi/cli/controllers.py` — `MonitoringMenuController`

**Files:**
- Modify: `semi/cli/controllers.py` (append)
- Test: `tests/cli/test_monitoring_menu_controller.py`

**Interfaces:**
- Consumes: `semi.services.monitoring_service.MonitoringService` (`.count_by_status() -> dict`, `.stock_status() -> list`), `views` (`render_monitoring_menu`, `render_order_counts`, `render_stock_status`).
- Produces: `MonitoringMenuController(monitoring_service)` with `label = "모니터링"` and `run() -> None`. Consumed by Task 11.

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_monitoring_menu_controller.py
from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import MonitoringMenuController


def test_label_is_monitoring():
    assert MonitoringMenuController(MagicMock()).label == "모니터링"


def test_run_renders_order_counts_then_exits_on_back(mocker):
    service = MagicMock()
    counts = {"RESERVED": 2}
    service.count_by_status.return_value = counts
    mocker.patch.object(views, "render_monitoring_menu", side_effect=["order_counts", "back"])
    render_counts = mocker.patch.object(views, "render_order_counts")

    MonitoringMenuController(service).run()

    render_counts.assert_called_once_with(counts)


def test_run_renders_stock_status_then_exits_on_back(mocker):
    service = MagicMock()
    statuses = [MagicMock()]
    service.stock_status.return_value = statuses
    mocker.patch.object(views, "render_monitoring_menu", side_effect=["stock_status", "back"])
    render_stock = mocker.patch.object(views, "render_stock_status")

    MonitoringMenuController(service).run()

    render_stock.assert_called_once_with(statuses)


def test_run_returns_immediately_on_back(mocker):
    service = MagicMock()
    mocker.patch.object(views, "render_monitoring_menu", return_value="back")

    MonitoringMenuController(service).run()

    service.count_by_status.assert_not_called()
    service.stock_status.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_monitoring_menu_controller.py -v`
Expected: FAIL with `ImportError: cannot import name 'MonitoringMenuController' from 'semi.cli.controllers'`

- [ ] **Step 3: Write minimal implementation**

Append to `semi/cli/controllers.py`:

```python
class MonitoringMenuController:
    label = "모니터링"

    def __init__(self, monitoring_service) -> None:
        self._service = monitoring_service

    def run(self) -> None:
        while True:
            choice = views.render_monitoring_menu()
            if choice == "back":
                return
            elif choice == "order_counts":
                views.render_order_counts(self._service.count_by_status())
            elif choice == "stock_status":
                views.render_stock_status(self._service.stock_status())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_monitoring_menu_controller.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add semi/cli/controllers.py tests/cli/test_monitoring_menu_controller.py
git commit -m "feat(cli): add MonitoringMenuController"
```

---

### Task 9: `semi/cli/controllers.py` — `ProductionMenuController`

**Files:**
- Modify: `semi/cli/controllers.py` (append)
- Test: `tests/cli/test_production_menu_controller.py`

**Interfaces:**
- Consumes: `semi.services.production_service.ProductionService` (`.get_current_status() -> ProductionJobStatus | None`, `.list_queue_status() -> list[ProductionJobStatus]`), `views` (`render_production_menu`, `render_current_production`, `render_production_queue`).
- Produces: `ProductionMenuController(production_service)` with `label = "생산 라인"` and `run() -> None`. Consumed by Task 11.

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_production_menu_controller.py
from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import ProductionMenuController


def test_label_is_production_line():
    assert ProductionMenuController(MagicMock()).label == "생산 라인"


def test_run_renders_current_status_then_exits_on_back(mocker):
    service = MagicMock()
    current = MagicMock()
    service.get_current_status.return_value = current
    mocker.patch.object(views, "render_production_menu", side_effect=["current", "back"])
    render_current = mocker.patch.object(views, "render_current_production")

    ProductionMenuController(service).run()

    render_current.assert_called_once_with(current)


def test_run_renders_queue_then_exits_on_back(mocker):
    service = MagicMock()
    queue = [MagicMock()]
    service.list_queue_status.return_value = queue
    mocker.patch.object(views, "render_production_menu", side_effect=["queue", "back"])
    render_queue = mocker.patch.object(views, "render_production_queue")

    ProductionMenuController(service).run()

    render_queue.assert_called_once_with(queue)


def test_run_returns_immediately_on_back(mocker):
    service = MagicMock()
    mocker.patch.object(views, "render_production_menu", return_value="back")

    ProductionMenuController(service).run()

    service.get_current_status.assert_not_called()
    service.list_queue_status.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_production_menu_controller.py -v`
Expected: FAIL with `ImportError: cannot import name 'ProductionMenuController' from 'semi.cli.controllers'`

- [ ] **Step 3: Write minimal implementation**

Append to `semi/cli/controllers.py`:

```python
class ProductionMenuController:
    label = "생산 라인"

    def __init__(self, production_service) -> None:
        self._service = production_service

    def run(self) -> None:
        while True:
            choice = views.render_production_menu()
            if choice == "back":
                return
            elif choice == "current":
                views.render_current_production(self._service.get_current_status())
            elif choice == "queue":
                views.render_production_queue(self._service.list_queue_status())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_production_menu_controller.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add semi/cli/controllers.py tests/cli/test_production_menu_controller.py
git commit -m "feat(cli): add ProductionMenuController"
```

---

### Task 10: `semi/cli/controllers.py` — `ReleaseMenuController`

**Files:**
- Modify: `semi/cli/controllers.py` (append)
- Test: `tests/cli/test_release_menu_controller.py`

**Interfaces:**
- Consumes: `semi.services.order_service.OrderService` (`.release(order_id) -> Order`), `semi.services.monitoring_service.MonitoringService` (`.list_by_status(OrderStatus.CONFIRMED) -> list[Order]`), `views` (`render_confirmed_orders`, `prompt_release_selection`, `render_release_result`).
- Produces: `ReleaseMenuController(order_service, monitoring_service)` with `label = "출고 처리"` and `run() -> None`. Consumed by Task 11.

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_release_menu_controller.py
from datetime import datetime
from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import ReleaseMenuController
from semi.domain.models import Order, OrderStatus


def _order(order_id=1, status=OrderStatus.CONFIRMED):
    return Order(order_id, "S1", "ACME", 5, status, datetime.now())


def test_label_is_release_processing():
    assert ReleaseMenuController(MagicMock(), MagicMock()).label == "출고 처리"


def test_run_returns_immediately_when_no_confirmed_orders(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    monitoring_service.list_by_status.return_value = []
    mocker.patch.object(views, "render_confirmed_orders")
    prompt_selection = mocker.patch.object(views, "prompt_release_selection")

    ReleaseMenuController(order_service, monitoring_service).run()

    monitoring_service.list_by_status.assert_called_once_with(OrderStatus.CONFIRMED)
    prompt_selection.assert_not_called()
    order_service.release.assert_not_called()


def test_run_releases_selected_order_then_stops_when_none_left(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    confirmed = _order(order_id=6)
    monitoring_service.list_by_status.side_effect = [[confirmed], []]
    released = _order(order_id=6, status=OrderStatus.RELEASE)
    order_service.release.return_value = released
    mocker.patch.object(views, "render_confirmed_orders")
    mocker.patch.object(views, "prompt_release_selection", return_value=6)
    render_result = mocker.patch.object(views, "render_release_result")

    ReleaseMenuController(order_service, monitoring_service).run()

    order_service.release.assert_called_once_with(6)
    render_result.assert_called_once_with(released)
    assert monitoring_service.list_by_status.call_count == 2


def test_run_returns_immediately_when_selection_is_none(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    monitoring_service.list_by_status.return_value = [_order(order_id=7)]
    mocker.patch.object(views, "render_confirmed_orders")
    mocker.patch.object(views, "prompt_release_selection", return_value=None)

    ReleaseMenuController(order_service, monitoring_service).run()

    order_service.release.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_release_menu_controller.py -v`
Expected: FAIL with `ImportError: cannot import name 'ReleaseMenuController' from 'semi.cli.controllers'`

- [ ] **Step 3: Write minimal implementation**

Append to `semi/cli/controllers.py`:

```python
class ReleaseMenuController:
    label = "출고 처리"

    def __init__(self, order_service, monitoring_service) -> None:
        self._order_service = order_service
        self._monitoring_service = monitoring_service

    def run(self) -> None:
        while True:
            orders = self._monitoring_service.list_by_status(OrderStatus.CONFIRMED)
            views.render_confirmed_orders(orders)
            if not orders:
                return
            order_id = views.prompt_release_selection(orders)
            if order_id is None:
                return
            order = self._order_service.release(order_id)
            views.render_release_result(order)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_release_menu_controller.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add semi/cli/controllers.py tests/cli/test_release_menu_controller.py
git commit -m "feat(cli): add ReleaseMenuController"
```

---

### Task 11: `semi/cli/app.py` — entrypoint and wiring

**Files:**
- Create: `semi/cli/app.py`
- Test: `tests/cli/test_app.py`

**Interfaces:**
- Consumes: everything built in Tasks 1-10 — `start_worker` (Task 1), `main_loop` (Task 2), `render_main_menu` (Task 3), all five controllers (Tasks 6-10), plus `connect_db` and the three repositories/four services from the pre-existing `semi.storage`/`semi.services` layers.
- Produces: `main(db_path: Path = Path("semi.db")) -> None` — the process entrypoint (also runnable via `if __name__ == "__main__": main()`).

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_app.py
import threading

from semi.cli.app import main
from semi.storage.db import connect_db


def test_main_initializes_db_starts_worker_and_exits_cleanly_on_zero(tmp_path, mocker):
    db_path = tmp_path / "app.db"
    mocker.patch("builtins.input", return_value="0")
    threads_before = set(threading.enumerate())

    main(db_path=db_path)

    new_daemon_threads = [
        t for t in set(threading.enumerate()) - threads_before if t.daemon
    ]
    assert len(new_daemon_threads) == 1
    assert new_daemon_threads[0].is_alive()

    conn = connect_db(db_path)
    assert conn.execute("SELECT * FROM samples").fetchall() == []
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.cli.app'`

- [ ] **Step 3: Write minimal implementation**

```python
# semi/cli/app.py
import threading
from pathlib import Path

from semi.cli.controllers import (
    MonitoringMenuController,
    OrderMenuController,
    ProductionMenuController,
    ReleaseMenuController,
    SampleMenuController,
)
from semi.cli.menu_loop import main_loop
from semi.cli.views import render_main_menu
from semi.scheduler.background_worker import start_worker
from semi.services.monitoring_service import MonitoringService
from semi.services.order_service import OrderService
from semi.services.production_service import ProductionService
from semi.services.sample_service import SampleService
from semi.storage.db import connect_db
from semi.storage.order_repository import OrderRepository
from semi.storage.production_job_repository import ProductionJobRepository
from semi.storage.sample_repository import SampleRepository


def main(db_path: Path = Path("semi.db")) -> None:
    conn = connect_db(db_path)
    lock = threading.Lock()

    sample_repo = SampleRepository(conn)
    order_repo = OrderRepository(conn)
    job_repo = ProductionJobRepository(conn)

    sample_service = SampleService(sample_repo)
    order_service = OrderService(order_repo, job_repo, sample_repo, lock)
    production_service = ProductionService(order_repo, job_repo, sample_repo, lock)
    monitoring_service = MonitoringService(order_repo, sample_repo)

    controllers = [
        SampleMenuController(sample_service),
        OrderMenuController(order_service, monitoring_service),
        MonitoringMenuController(monitoring_service),
        ProductionMenuController(production_service),
        ReleaseMenuController(order_service, monitoring_service),
    ]

    start_worker(db_path, lock)

    try:
        main_loop(controllers, render_main_menu=render_main_menu)
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_app.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass (existing domain/storage/services tests plus all new scheduler/cli tests).

- [ ] **Step 6: Commit**

```bash
git add semi/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): add app.py entrypoint wiring services, controllers, and worker"
```

---

## Final Verification

- [ ] Run `ruff check --fix .` and `ruff format .` from the repo root; fix any lint findings introduced by this plan.
- [ ] Run `pytest -v` and confirm the full suite (existing + new) passes.
- [ ] Manually smoke-test the console app: `python -m semi.cli.app`, register a sample, place an order that exceeds current stock (0), approve it (should go `PRODUCING`), wait a few seconds, check "생산 라인 → 현재 생산 현황" shows progress, then after completion check "모니터링" shows it `CONFIRMED`, then release it via "출고 처리" and confirm stock decreases and status becomes `RELEASE`. Delete the resulting `semi.db` file afterward if it was a throwaway manual test (or keep it, per project preference — flag either way to the user; per `CLAUDE.md`, prefer using `dummydatagen`/`datamonitor` dev tools over hand-seeding for this kind of manual verification when available).
</content>
