# CLI Layer (`semi/cli`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `semi/cli` (`menu_loop.py`, `views.py`, `controllers.py`, `app.py`) per `docs/superpowers/specs/2026-07-15-cli-design.md` — an MVC-shaped console layer covering PRD 4.1~4.7 (시료 관리, 주문 접수/승인/거절, 모니터링, 생산 라인, 출고 처리).

**Architecture:** `menu_loop.py` holds the `MenuController` Protocol and the single-catch `main_loop`. `views.py` is pure `print`/`input` — no service/domain logic beyond rendering and safe parsing. `controllers.py` has one class per PRD menu section, each calling its injected service(s) and delegating all rendering to `views.*`. `app.py` wires repositories → services → controllers → worker → `main_loop`. Built bottom-up: `menu_loop.py` first (no dependencies), then `views.py` functions grouped by menu section paired with their controller, ending with `app.py`.

**Tech Stack:** Python 3.14+, `pytest` + `pytest-mock` (`mocker` fixture, `test` extra already installed), `ruff` for lint/format. Views are tested via `mocker.patch("builtins.input", side_effect=[...])` plus `capsys` for output assertions — no real stdin/stdout needed.

## Prerequisite (read before Task 1)

`semi/cli` imports `semi.services.*` (`SampleService`, `OrderService`, `ProductionService`, `MonitoringService`, `DomainError`) and `semi.scheduler.background_worker.start_worker`. As of this writing, only `semi/domain` and `semi/storage` exist on disk — `semi/services` and `semi/scheduler` do not, even though their plans (`docs/superpowers/plans/2026-07-15-services-design.md`, `docs/superpowers/plans/2026-07-15-scheduler-worker.md`) are already written. **Task 1 Step 0 is a hard gate**: if it fails, stop and execute both of those plans in full first, then return here.

## Global Constraints

- Python 3.14+ (`pyproject.toml` `requires-python = ">=3.14"`), `StrEnum`/PEP 604 unions where relevant.
- `pip install -e ".[dev,test]"` must already be done; no reinstall needed unless the environment is fresh.
- Before every commit: `ruff check --fix .` then `ruff format .`.
- Commit messages follow Conventional Commits (`commitizen` `commit-msg` hook).
- No code comments except where the WHY is non-obvious (per project style).
- `views.py` never imports from `semi.services` or `semi.storage` for anything other than the plain data types it renders (`Sample`, `Order`, `ProductionJob`, `OrderStatus`, `ProductionJobStatus`, `SampleStockStatus`, `StockStatus`) — it never calls a service method or repository method. This is the MVC boundary the spec (§0, §4) requires.
- **Input fail-safe principle (spec §2.1, §4):** every `views.py` input-parsing function returns a valid value instead of raising on unrecognized input.
  - Submenu selectors (`render_sample_menu`, `render_order_menu`, `render_monitoring_menu`, `render_production_menu`, `prompt_approve_or_reject`) map any input they don't recognize to `"back"`.
  - `render_main_menu` retries on a non-numeric or out-of-range choice instead of raising (spec §2.1) — it only ever returns a valid index or `"exit"`.
  - Numeric field prompts (`prompt_sample_registration`'s `avg_production_seconds`/`yield_rate`, `prompt_order_creation`'s `quantity`) use a shared `_parse_float`/`_parse_int` helper that falls back to a value **guaranteed to fail the corresponding service-layer `DomainError` check** (`0.0` for `avg_production_seconds`/`yield_rate`, `0` for `quantity`) rather than crashing on non-numeric input. This turns a bad keystroke into a friendly `[오류]` message (via `main_loop`'s existing `DomainError` catch) instead of an uncaught `ValueError`.
  - `prompt_order_id` falls back to `-1` on non-numeric input (an `order_id` that can never exist), which surfaces as `NotFoundError` → `main_loop`'s `[조회 실패]` message — the same reasoning as above, just routed through the lookup-miss path instead of the validation path.
- Controllers never catch `DomainError`/`NotFoundError` themselves — they propagate to `main_loop`'s single catch point (spec §2, §3).
- Each controller's constructor takes only the service(s) its menu section needs (spec §3) — no controller depends on a service it doesn't call.

---

### Task 1: `menu_loop.py` — `MenuController` Protocol and `main_loop`

**Files:**
- Create: `semi/cli/__init__.py`
- Create: `semi/cli/menu_loop.py`
- Create: `tests/cli/__init__.py`
- Test: `tests/cli/test_menu_loop.py`

**Interfaces:**
- Consumes: `semi.services.exceptions.DomainError`, `semi.storage.exceptions.NotFoundError` (both from the services-layer plan — see Prerequisite above).
- Produces: `semi.cli.menu_loop.MenuController` (Protocol: `label: str`, `run() -> None`), `semi.cli.menu_loop.main_loop(controllers: list[MenuController], render_main_menu: Callable[[list[str]], int | str]) -> None`. Every later controller class implements this Protocol; `app.py` calls `main_loop` directly.

- [ ] **Step 0: Verify the prerequisite is met**

Run: `python -c "from semi.services.exceptions import DomainError; from semi.storage.exceptions import NotFoundError"`
Expected: no output, exit code 0. If this raises `ModuleNotFoundError: No module named 'semi.services'`, **stop** — execute `docs/superpowers/plans/2026-07-15-services-design.md` first, then restart this task.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/__init__.py` (empty file).

Create `tests/cli/test_menu_loop.py`:

```python
from semi.cli.menu_loop import main_loop
from semi.services.exceptions import DomainError
from semi.storage.exceptions import NotFoundError


class _FakeController:
    def __init__(self, label, run_fn):
        self.label = label
        self._run_fn = run_fn
        self.run_calls = 0

    def run(self):
        self.run_calls += 1
        self._run_fn()


def test_main_loop_exits_immediately_when_render_returns_exit():
    controllers = [_FakeController("A", lambda: None)]
    main_loop(controllers, render_main_menu=lambda labels: "exit")


def test_main_loop_dispatches_to_chosen_controller_by_index():
    calls = []
    controllers = [
        _FakeController("A", lambda: calls.append("A")),
        _FakeController("B", lambda: calls.append("B")),
    ]
    choices = iter([1, "exit"])
    main_loop(controllers, render_main_menu=lambda labels: next(choices))
    assert calls == ["B"]
    assert controllers[1].run_calls == 1
    assert controllers[0].run_calls == 0


def test_main_loop_passes_controller_labels_to_render_main_menu():
    received = []
    controllers = [_FakeController("시료 관리", lambda: None)]

    def fake_render(labels):
        received.append(list(labels))
        return "exit"

    main_loop(controllers, render_main_menu=fake_render)
    assert received == [["시료 관리"]]


def test_main_loop_catches_domain_error_and_continues(capsys):
    def raise_domain_error():
        raise DomainError("수율은 0보다 커야 합니다")

    controllers = [_FakeController("A", raise_domain_error)]
    choices = iter([0, "exit"])
    main_loop(controllers, render_main_menu=lambda labels: next(choices))
    out = capsys.readouterr().out
    assert "[오류] 수율은 0보다 커야 합니다" in out


def test_main_loop_catches_not_found_error_and_continues(capsys):
    def raise_not_found():
        raise NotFoundError("order_id=99 not found")

    controllers = [_FakeController("A", raise_not_found)]
    choices = iter([0, "exit"])
    main_loop(controllers, render_main_menu=lambda labels: next(choices))
    out = capsys.readouterr().out
    assert "[조회 실패] order_id=99 not found" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_menu_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.cli'`

- [ ] **Step 3: Implement `menu_loop.py`**

`semi/cli/__init__.py` (empty file).

`semi/cli/menu_loop.py`:

```python
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_menu_loop.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/__init__.py semi/cli/menu_loop.py tests/cli/__init__.py tests/cli/test_menu_loop.py
git commit -m "feat(cli): add MenuController protocol and main_loop"
```

---

### Task 2: `views.py` — main menu rendering + shared parse helpers

**Files:**
- Create: `semi/cli/views.py`
- Test: `tests/cli/test_views_main_menu.py`

**Interfaces:**
- Consumes: nothing beyond stdlib.
- Produces: `semi.cli.views.render_main_menu(labels: list[str]) -> int | Literal["exit"]`, `semi.cli.views._parse_int(raw: str, default: int) -> int`, `semi.cli.views._parse_float(raw: str, default: float) -> float`. Later view functions in Tasks 3/5/7/9/11 use `_parse_int`/`_parse_float`; `app.py` (Task 13) imports `render_main_menu`.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_views_main_menu.py`:

```python
from semi.cli.views import _parse_float, _parse_int, render_main_menu


def test_parse_int_returns_value_on_valid_input():
    assert _parse_int("5", default=0) == 5


def test_parse_int_returns_default_on_invalid_input():
    assert _parse_int("abc", default=-1) == -1


def test_parse_float_returns_value_on_valid_input():
    assert _parse_float("1.5", default=0.0) == 1.5


def test_parse_float_returns_default_on_invalid_input():
    assert _parse_float("nope", default=0.0) == 0.0


def test_render_main_menu_returns_index_for_valid_choice(mocker):
    mocker.patch("builtins.input", side_effect=["2"])
    result = render_main_menu(["시료 관리", "주문 접수", "모니터링"])
    assert result == 1


def test_render_main_menu_returns_exit_for_exit_choice(mocker):
    mocker.patch("builtins.input", side_effect=["4"])
    result = render_main_menu(["시료 관리", "주문 접수", "모니터링"])
    assert result == "exit"


def test_render_main_menu_retries_on_non_numeric_input(mocker, capsys):
    mocker.patch("builtins.input", side_effect=["abc", "1"])
    result = render_main_menu(["시료 관리"])
    assert result == 0
    out = capsys.readouterr().out
    assert "[오류]" in out


def test_render_main_menu_retries_on_out_of_range_input(mocker, capsys):
    mocker.patch("builtins.input", side_effect=["99", "1"])
    result = render_main_menu(["시료 관리"])
    assert result == 0
    out = capsys.readouterr().out
    assert "[오류]" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_views_main_menu.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.cli.views'`

- [ ] **Step 3: Implement `views.py` (main menu section)**

`semi/cli/views.py`:

```python
from typing import Literal


def _parse_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_float(raw: str, default: float) -> float:
    try:
        return float(raw)
    except ValueError:
        return default


def render_main_menu(labels: list[str]) -> int | Literal["exit"]:
    while True:
        print("\n=== S-Semi 메인 메뉴 ===")
        for i, label in enumerate(labels, start=1):
            print(f"{i}. {label}")
        print(f"{len(labels) + 1}. 종료")
        raw = input("선택> ")
        choice = _parse_int(raw, default=-1)
        if choice == len(labels) + 1:
            return "exit"
        if 1 <= choice <= len(labels):
            return choice - 1
        print("[오류] 올바른 번호를 입력하세요.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_views_main_menu.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/views.py tests/cli/test_views_main_menu.py
git commit -m "feat(cli): add render_main_menu and shared parse helpers"
```

---

### Task 3: `views.py` — sample menu views (PRD 4.2)

**Files:**
- Modify: `semi/cli/views.py`
- Test: `tests/cli/test_views_sample.py`

**Interfaces:**
- Consumes: `semi.domain.models.Sample`, `_parse_float` (Task 2).
- Produces: `render_sample_menu() -> Literal["register", "list", "search", "back"]`, `prompt_sample_registration() -> dict`, `prompt_search_query() -> str`, `render_sample_list(samples: list[Sample]) -> None`, `render_sample_registered(sample: Sample) -> None`. Task 4's `SampleMenuController` calls all five.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_views_sample.py`:

```python
from semi.cli.views import (
    prompt_sample_registration,
    prompt_search_query,
    render_sample_list,
    render_sample_menu,
    render_sample_registered,
)
from semi.domain.models import Sample


def _sample(**overrides):
    defaults = dict(
        sample_id="S1",
        name="Wafer A",
        avg_production_seconds=10.0,
        yield_rate=0.9,
        stock_quantity=5,
    )
    defaults.update(overrides)
    return Sample(**defaults)


def test_render_sample_menu_maps_known_choices(mocker):
    mocker.patch("builtins.input", side_effect=["1"])
    assert render_sample_menu() == "register"


def test_render_sample_menu_maps_unknown_input_to_back(mocker):
    mocker.patch("builtins.input", side_effect=["nonsense"])
    assert render_sample_menu() == "back"


def test_prompt_sample_registration_parses_valid_numeric_fields(mocker):
    mocker.patch("builtins.input", side_effect=["S1", "Wafer A", "10.5", "0.9"])
    data = prompt_sample_registration()
    assert data == {
        "sample_id": "S1",
        "name": "Wafer A",
        "avg_production_seconds": 10.5,
        "yield_rate": 0.9,
    }


def test_prompt_sample_registration_falls_back_to_domain_invalid_defaults(mocker):
    mocker.patch("builtins.input", side_effect=["S1", "Wafer A", "oops", "oops"])
    data = prompt_sample_registration()
    assert data["avg_production_seconds"] == 0.0
    assert data["yield_rate"] == 0.0


def test_prompt_search_query_returns_raw_string(mocker):
    mocker.patch("builtins.input", side_effect=["wafer"])
    assert prompt_search_query() == "wafer"


def test_render_sample_list_prints_each_sample(capsys):
    render_sample_list([_sample(sample_id="S1"), _sample(sample_id="S2")])
    out = capsys.readouterr().out
    assert "S1" in out
    assert "S2" in out


def test_render_sample_list_handles_empty_list(capsys):
    render_sample_list([])
    out = capsys.readouterr().out
    assert "없음" in out


def test_render_sample_registered_prints_sample_id(capsys):
    render_sample_registered(_sample(sample_id="S1"))
    out = capsys.readouterr().out
    assert "S1" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_views_sample.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_sample_menu' from 'semi.cli.views'`

- [ ] **Step 3: Append sample views to `views.py`**

Add to `semi/cli/views.py` (below the Task 2 code, add `from semi.domain.models import Sample` to the top imports):

```python
def render_sample_menu() -> Literal["register", "list", "search", "back"]:
    print("\n--- 시료 관리 ---")
    print("1. 시료 등록")
    print("2. 시료 목록 조회")
    print("3. 시료 검색")
    print("4. 뒤로가기")
    raw = input("선택> ")
    return {"1": "register", "2": "list", "3": "search"}.get(raw, "back")


def prompt_sample_registration() -> dict:
    sample_id = input("시료 ID: ")
    name = input("이름: ")
    avg_production_seconds = _parse_float(input("평균 생산시간(초): "), default=0.0)
    yield_rate = _parse_float(input("수율(0~1): "), default=0.0)
    return {
        "sample_id": sample_id,
        "name": name,
        "avg_production_seconds": avg_production_seconds,
        "yield_rate": yield_rate,
    }


def prompt_search_query() -> str:
    return input("검색어(이름): ")


def render_sample_list(samples: list[Sample]) -> None:
    print("\n--- 시료 목록 ---")
    if not samples:
        print("(등록된 시료 없음)")
        return
    for sample in samples:
        print(
            f"[{sample.sample_id}] {sample.name} 평균생산시간={sample.avg_production_seconds}s "
            f"수율={sample.yield_rate} 재고={sample.stock_quantity}"
        )


def render_sample_registered(sample: Sample) -> None:
    print(f"시료가 등록되었습니다. [{sample.sample_id}] {sample.name}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_views_sample.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/views.py tests/cli/test_views_sample.py
git commit -m "feat(cli): add sample menu views"
```

---

### Task 4: `controllers.py` — `SampleMenuController` (PRD 4.2)

**Files:**
- Create: `semi/cli/controllers.py`
- Test: `tests/cli/test_controllers_sample.py`

**Interfaces:**
- Consumes: `semi.cli.views` (Tasks 2–3), `semi.services.sample_service.SampleService` (`register`, `list_all`, `search_by_name` — from the services-layer plan).
- Produces: `semi.cli.controllers.SampleMenuController(sample_service)` satisfying `MenuController` (`label = "시료 관리"`, `run() -> None`). `app.py` (Task 13) instantiates it.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_controllers_sample.py`:

```python
from semi.cli.controllers import SampleMenuController


def test_label_is_sample_management():
    controller = SampleMenuController(sample_service=object())
    assert controller.label == "시료 관리"


def test_run_returns_on_back(mocker):
    mocker.patch("semi.cli.controllers.views.render_sample_menu", return_value="back")
    service = mocker.MagicMock()
    controller = SampleMenuController(sample_service=service)
    controller.run()
    service.register.assert_not_called()


def test_run_registers_sample_on_register_choice(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_sample_menu",
        side_effect=["register", "back"],
    )
    mocker.patch(
        "semi.cli.controllers.views.prompt_sample_registration",
        return_value={
            "sample_id": "S1",
            "name": "Wafer A",
            "avg_production_seconds": 10.0,
            "yield_rate": 0.9,
        },
    )
    render_registered = mocker.patch(
        "semi.cli.controllers.views.render_sample_registered"
    )
    service = mocker.MagicMock()
    controller = SampleMenuController(sample_service=service)
    controller.run()
    service.register.assert_called_once_with(
        sample_id="S1", name="Wafer A", avg_production_seconds=10.0, yield_rate=0.9
    )
    render_registered.assert_called_once_with(service.register.return_value)


def test_run_lists_samples_on_list_choice(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_sample_menu", side_effect=["list", "back"]
    )
    render_list = mocker.patch("semi.cli.controllers.views.render_sample_list")
    service = mocker.MagicMock()
    service.list_all.return_value = ["sample-stub"]
    controller = SampleMenuController(sample_service=service)
    controller.run()
    service.list_all.assert_called_once_with()
    render_list.assert_called_once_with(["sample-stub"])


def test_run_searches_samples_on_search_choice(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_sample_menu",
        side_effect=["search", "back"],
    )
    mocker.patch(
        "semi.cli.controllers.views.prompt_search_query", return_value="wafer"
    )
    render_list = mocker.patch("semi.cli.controllers.views.render_sample_list")
    service = mocker.MagicMock()
    service.search_by_name.return_value = ["sample-stub"]
    controller = SampleMenuController(sample_service=service)
    controller.run()
    service.search_by_name.assert_called_once_with("wafer")
    render_list.assert_called_once_with(["sample-stub"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_controllers_sample.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.cli.controllers'`

- [ ] **Step 3: Implement `controllers.py` (sample section)**

`semi/cli/controllers.py`:

```python
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_controllers_sample.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/controllers.py tests/cli/test_controllers_sample.py
git commit -m "feat(cli): add SampleMenuController"
```

---

### Task 5: `views.py` — order menu views (PRD 4.3, 4.4)

**Files:**
- Modify: `semi/cli/views.py`
- Test: `tests/cli/test_views_order.py`

**Interfaces:**
- Consumes: `semi.domain.models.Order`, `_parse_int` (Task 2).
- Produces: `render_order_menu() -> Literal["create", "approve_reject", "back"]`, `prompt_order_creation() -> dict`, `render_order_created(order: Order) -> None`, `render_order_list(title: str, orders: list[Order]) -> None`, `prompt_order_id(prompt_label: str) -> int | Literal["back"]`, `prompt_approve_or_reject() -> Literal["approve", "reject", "back"]`, `render_order_approved(order: Order) -> None`, `render_order_rejected(order: Order) -> None`. Task 6's `OrderMenuController` uses all eight; `render_order_list` and `prompt_order_id` are reused by Task 12's `ReleaseMenuController`.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_views_order.py`:

```python
from datetime import datetime

from semi.cli.views import (
    prompt_approve_or_reject,
    prompt_order_creation,
    prompt_order_id,
    render_order_approved,
    render_order_created,
    render_order_list,
    render_order_menu,
    render_order_rejected,
)
from semi.domain.models import Order, OrderStatus


def _order(**overrides):
    defaults = dict(
        order_id=1,
        sample_id="S1",
        customer_name="ACME",
        quantity=3,
        status=OrderStatus.RESERVED,
        created_at=datetime(2026, 7, 15, 12, 0, 0),
    )
    defaults.update(overrides)
    return Order(**defaults)


def test_render_order_menu_maps_known_choices(mocker):
    mocker.patch("builtins.input", side_effect=["1"])
    assert render_order_menu() == "create"


def test_render_order_menu_maps_unknown_input_to_back(mocker):
    mocker.patch("builtins.input", side_effect=["?"])
    assert render_order_menu() == "back"


def test_prompt_order_creation_parses_valid_quantity(mocker):
    mocker.patch("builtins.input", side_effect=["S1", "ACME", "5"])
    data = prompt_order_creation()
    assert data == {"sample_id": "S1", "customer_name": "ACME", "quantity": 5}


def test_prompt_order_creation_falls_back_to_zero_quantity_on_invalid_input(mocker):
    mocker.patch("builtins.input", side_effect=["S1", "ACME", "oops"])
    data = prompt_order_creation()
    assert data["quantity"] == 0


def test_render_order_created_prints_order_id(capsys):
    render_order_created(_order(order_id=42))
    assert "42" in capsys.readouterr().out


def test_render_order_list_prints_each_order(capsys):
    render_order_list("대기 주문", [_order(order_id=1), _order(order_id=2)])
    out = capsys.readouterr().out
    assert "대기 주문" in out
    assert "[1]" in out
    assert "[2]" in out


def test_render_order_list_handles_empty_list(capsys):
    render_order_list("대기 주문", [])
    assert "없음" in capsys.readouterr().out


def test_prompt_order_id_returns_parsed_int(mocker):
    mocker.patch("builtins.input", side_effect=["7"])
    assert prompt_order_id("주문 ID") == 7


def test_prompt_order_id_returns_back_on_b(mocker):
    mocker.patch("builtins.input", side_effect=["b"])
    assert prompt_order_id("주문 ID") == "back"


def test_prompt_order_id_falls_back_to_sentinel_on_invalid_input(mocker):
    mocker.patch("builtins.input", side_effect=["oops"])
    assert prompt_order_id("주문 ID") == -1


def test_prompt_approve_or_reject_maps_choices(mocker):
    mocker.patch("builtins.input", side_effect=["1"])
    assert prompt_approve_or_reject() == "approve"


def test_prompt_approve_or_reject_maps_unknown_to_back(mocker):
    mocker.patch("builtins.input", side_effect=["9"])
    assert prompt_approve_or_reject() == "back"


def test_render_order_approved_and_rejected_print_order_id(capsys):
    render_order_approved(_order(order_id=5))
    render_order_rejected(_order(order_id=6))
    out = capsys.readouterr().out
    assert "5" in out
    assert "6" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_views_order.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_order_menu' from 'semi.cli.views'`

- [ ] **Step 3: Append order views to `views.py`**

Add to `semi/cli/views.py` (add `from semi.domain.models import Order` to the top imports, alongside `Sample`):

```python
def render_order_menu() -> Literal["create", "approve_reject", "back"]:
    print("\n--- 주문 접수 / 승인 / 거절 ---")
    print("1. 주문 접수")
    print("2. 승인/거절 대상 조회 및 처리")
    print("3. 뒤로가기")
    raw = input("선택> ")
    return {"1": "create", "2": "approve_reject"}.get(raw, "back")


def prompt_order_creation() -> dict:
    sample_id = input("시료 ID: ")
    customer_name = input("고객명: ")
    quantity = _parse_int(input("주문 수량: "), default=0)
    return {"sample_id": sample_id, "customer_name": customer_name, "quantity": quantity}


def render_order_created(order: Order) -> None:
    print(f"주문이 접수되었습니다. [주문 ID={order.order_id}] 상태={order.status}")


def render_order_list(title: str, orders: list[Order]) -> None:
    print(f"\n--- {title} ---")
    if not orders:
        print("(해당 주문 없음)")
        return
    for order in orders:
        print(
            f"[{order.order_id}] 시료={order.sample_id} 고객={order.customer_name} "
            f"수량={order.quantity} 상태={order.status}"
        )


def prompt_order_id(prompt_label: str) -> int | Literal["back"]:
    raw = input(f"{prompt_label} (뒤로가기: b): ")
    if raw.strip().lower() == "b":
        return "back"
    return _parse_int(raw, default=-1)


def prompt_approve_or_reject() -> Literal["approve", "reject", "back"]:
    raw = input("처리 선택 (1=승인, 2=거절, 그 외=취소): ")
    return {"1": "approve", "2": "reject"}.get(raw, "back")


def render_order_approved(order: Order) -> None:
    print(f"주문이 승인되었습니다. [주문 ID={order.order_id}] 상태={order.status}")


def render_order_rejected(order: Order) -> None:
    print(f"주문이 거절되었습니다. [주문 ID={order.order_id}] 상태={order.status}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_views_order.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/views.py tests/cli/test_views_order.py
git commit -m "feat(cli): add order menu views"
```

---

### Task 6: `controllers.py` — `OrderMenuController` (PRD 4.3, 4.4)

**Files:**
- Modify: `semi/cli/controllers.py`
- Test: `tests/cli/test_controllers_order.py`

**Interfaces:**
- Consumes: `semi.cli.views` (Task 5), `semi.services.order_service.OrderService` (`create_order`, `approve`, `reject`), `semi.services.monitoring_service.MonitoringService.list_by_status`, `semi.domain.models.OrderStatus`.
- Produces: `semi.cli.controllers.OrderMenuController(order_service, monitoring_service)` satisfying `MenuController` (`label = "주문 접수 / 승인 / 거절"`). `app.py` (Task 13) instantiates it.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_controllers_order.py`:

```python
from semi.cli.controllers import OrderMenuController
from semi.domain.models import OrderStatus


def test_label_is_order_menu_label():
    controller = OrderMenuController(order_service=object(), monitoring_service=object())
    assert controller.label == "주문 접수 / 승인 / 거절"


def test_run_returns_on_back(mocker):
    mocker.patch("semi.cli.controllers.views.render_order_menu", return_value="back")
    order_service = mocker.MagicMock()
    controller = OrderMenuController(order_service, monitoring_service=mocker.MagicMock())
    controller.run()
    order_service.create_order.assert_not_called()


def test_run_creates_order_on_create_choice(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_order_menu", side_effect=["create", "back"]
    )
    mocker.patch(
        "semi.cli.controllers.views.prompt_order_creation",
        return_value={"sample_id": "S1", "customer_name": "ACME", "quantity": 3},
    )
    render_created = mocker.patch("semi.cli.controllers.views.render_order_created")
    order_service = mocker.MagicMock()
    controller = OrderMenuController(order_service, monitoring_service=mocker.MagicMock())
    controller.run()
    order_service.create_order.assert_called_once_with(
        sample_id="S1", customer_name="ACME", quantity=3
    )
    render_created.assert_called_once_with(order_service.create_order.return_value)


def test_approve_reject_flow_returns_early_when_no_reserved_orders(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_order_menu",
        side_effect=["approve_reject", "back"],
    )
    render_list = mocker.patch("semi.cli.controllers.views.render_order_list")
    monitoring_service = mocker.MagicMock()
    monitoring_service.list_by_status.return_value = []
    order_service = mocker.MagicMock()
    controller = OrderMenuController(order_service, monitoring_service)
    controller.run()
    monitoring_service.list_by_status.assert_called_once_with(OrderStatus.RESERVED)
    render_list.assert_called_once_with("승인/거절 대기 주문 (RESERVED)", [])
    order_service.approve.assert_not_called()
    order_service.reject.assert_not_called()


def test_approve_reject_flow_approves_selected_order(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_order_menu",
        side_effect=["approve_reject", "back"],
    )
    mocker.patch("semi.cli.controllers.views.render_order_list")
    mocker.patch("semi.cli.controllers.views.prompt_order_id", return_value=7)
    mocker.patch(
        "semi.cli.controllers.views.prompt_approve_or_reject", return_value="approve"
    )
    render_approved = mocker.patch("semi.cli.controllers.views.render_order_approved")
    monitoring_service = mocker.MagicMock()
    monitoring_service.list_by_status.return_value = ["order-stub"]
    order_service = mocker.MagicMock()
    controller = OrderMenuController(order_service, monitoring_service)
    controller.run()
    order_service.approve.assert_called_once_with(7)
    render_approved.assert_called_once_with(order_service.approve.return_value)


def test_approve_reject_flow_rejects_selected_order(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_order_menu",
        side_effect=["approve_reject", "back"],
    )
    mocker.patch("semi.cli.controllers.views.render_order_list")
    mocker.patch("semi.cli.controllers.views.prompt_order_id", return_value=7)
    mocker.patch(
        "semi.cli.controllers.views.prompt_approve_or_reject", return_value="reject"
    )
    render_rejected = mocker.patch("semi.cli.controllers.views.render_order_rejected")
    monitoring_service = mocker.MagicMock()
    monitoring_service.list_by_status.return_value = ["order-stub"]
    order_service = mocker.MagicMock()
    controller = OrderMenuController(order_service, monitoring_service)
    controller.run()
    order_service.reject.assert_called_once_with(7)
    render_rejected.assert_called_once_with(order_service.reject.return_value)


def test_approve_reject_flow_does_nothing_when_order_id_is_back(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_order_menu",
        side_effect=["approve_reject", "back"],
    )
    mocker.patch("semi.cli.controllers.views.render_order_list")
    mocker.patch("semi.cli.controllers.views.prompt_order_id", return_value="back")
    monitoring_service = mocker.MagicMock()
    monitoring_service.list_by_status.return_value = ["order-stub"]
    order_service = mocker.MagicMock()
    controller = OrderMenuController(order_service, monitoring_service)
    controller.run()
    order_service.approve.assert_not_called()
    order_service.reject.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_controllers_order.py -v`
Expected: FAIL with `ImportError: cannot import name 'OrderMenuController' from 'semi.cli.controllers'`

- [ ] **Step 3: Append `OrderMenuController` to `controllers.py`**

Add to `semi/cli/controllers.py` (add `from semi.domain.models import OrderStatus` to the top imports):

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
                self._approve_reject_flow()

    def _approve_reject_flow(self) -> None:
        orders = self._monitoring_service.list_by_status(OrderStatus.RESERVED)
        views.render_order_list("승인/거절 대기 주문 (RESERVED)", orders)
        if not orders:
            return
        order_id = views.prompt_order_id("승인/거절할 주문 ID")
        if order_id == "back":
            return
        action = views.prompt_approve_or_reject()
        if action == "approve":
            order = self._order_service.approve(order_id)
            views.render_order_approved(order)
        elif action == "reject":
            order = self._order_service.reject(order_id)
            views.render_order_rejected(order)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_controllers_order.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/controllers.py tests/cli/test_controllers_order.py
git commit -m "feat(cli): add OrderMenuController"
```

---

### Task 7: `views.py` — monitoring views (PRD 4.5)

**Files:**
- Modify: `semi/cli/views.py`
- Test: `tests/cli/test_views_monitoring.py`

**Interfaces:**
- Consumes: `semi.domain.models.OrderStatus`, `semi.services.monitoring_service.StockStatus`, `semi.services.monitoring_service.SampleStockStatus`, `semi.domain.models.Sample` (from the services-layer plan).
- Produces: `render_monitoring_menu() -> Literal["counts", "stock", "back"]`, `render_order_counts(counts: dict[OrderStatus, int]) -> None`, `render_stock_status(statuses: list[SampleStockStatus]) -> None`. Task 8's `MonitoringMenuController` uses all three.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_views_monitoring.py`:

```python
from semi.cli.views import render_monitoring_menu, render_order_counts, render_stock_status
from semi.domain.models import OrderStatus, Sample
from semi.services.monitoring_service import SampleStockStatus, StockStatus


def test_render_monitoring_menu_maps_known_choices(mocker):
    mocker.patch("builtins.input", side_effect=["1"])
    assert render_monitoring_menu() == "counts"


def test_render_monitoring_menu_maps_unknown_input_to_back(mocker):
    mocker.patch("builtins.input", side_effect=["?"])
    assert render_monitoring_menu() == "back"


def test_render_order_counts_prints_all_tracked_statuses(capsys):
    counts = {
        OrderStatus.RESERVED: 2,
        OrderStatus.CONFIRMED: 1,
        OrderStatus.PRODUCING: 0,
        OrderStatus.RELEASE: 5,
    }
    render_order_counts(counts)
    out = capsys.readouterr().out
    assert "RESERVED" in out
    assert "CONFIRMED" in out
    assert "PRODUCING" in out
    assert "RELEASE" in out
    assert "REJECTED" not in out


def test_render_stock_status_maps_each_status_to_korean_label(capsys):
    sample = Sample(
        sample_id="S1",
        name="Wafer A",
        avg_production_seconds=10.0,
        yield_rate=0.9,
        stock_quantity=0,
    )
    statuses = [SampleStockStatus(sample=sample, outstanding=3, status=StockStatus.DEPLETED)]
    render_stock_status(statuses)
    out = capsys.readouterr().out
    assert "고갈" in out


def test_render_stock_status_handles_empty_list(capsys):
    render_stock_status([])
    assert "없음" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_views_monitoring.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_monitoring_menu' from 'semi.cli.views'`

- [ ] **Step 3: Append monitoring views to `views.py`**

Add to `semi/cli/views.py` (add `from semi.domain.models import OrderStatus` and `from semi.services.monitoring_service import SampleStockStatus, StockStatus` to the top imports):

```python
def render_monitoring_menu() -> Literal["counts", "stock", "back"]:
    print("\n--- 모니터링 ---")
    print("1. 상태별 주문 수 조회")
    print("2. 재고 현황 조회")
    print("3. 뒤로가기")
    raw = input("선택> ")
    return {"1": "counts", "2": "stock"}.get(raw, "back")


def render_order_counts(counts: dict[OrderStatus, int]) -> None:
    print("\n--- 상태별 주문 수 ---")
    for status in (
        OrderStatus.RESERVED,
        OrderStatus.CONFIRMED,
        OrderStatus.PRODUCING,
        OrderStatus.RELEASE,
    ):
        print(f"{status}: {counts.get(status, 0)}건")


_STOCK_STATUS_LABELS = {
    StockStatus.SUFFICIENT: "여유",
    StockStatus.SHORT: "부족",
    StockStatus.DEPLETED: "고갈",
}


def render_stock_status(statuses: list[SampleStockStatus]) -> None:
    print("\n--- 재고 현황 ---")
    if not statuses:
        print("(등록된 시료 없음)")
        return
    for s in statuses:
        label = _STOCK_STATUS_LABELS[s.status]
        print(
            f"[{s.sample.sample_id}] {s.sample.name} 재고={s.sample.stock_quantity} "
            f"미완료주문={s.outstanding} 상태={label}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_views_monitoring.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/views.py tests/cli/test_views_monitoring.py
git commit -m "feat(cli): add monitoring views"
```

---

### Task 8: `controllers.py` — `MonitoringMenuController` (PRD 4.5)

**Files:**
- Modify: `semi/cli/controllers.py`
- Test: `tests/cli/test_controllers_monitoring.py`

**Interfaces:**
- Consumes: `semi.cli.views` (Task 7), `semi.services.monitoring_service.MonitoringService` (`count_by_status`, `stock_status`).
- Produces: `semi.cli.controllers.MonitoringMenuController(monitoring_service)` satisfying `MenuController` (`label = "모니터링"`). `app.py` (Task 13) instantiates it.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_controllers_monitoring.py`:

```python
from semi.cli.controllers import MonitoringMenuController


def test_label_is_monitoring():
    controller = MonitoringMenuController(monitoring_service=object())
    assert controller.label == "모니터링"


def test_run_returns_on_back(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_monitoring_menu", return_value="back"
    )
    service = mocker.MagicMock()
    controller = MonitoringMenuController(service)
    controller.run()
    service.count_by_status.assert_not_called()
    service.stock_status.assert_not_called()


def test_run_shows_counts_on_counts_choice(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_monitoring_menu",
        side_effect=["counts", "back"],
    )
    render_counts = mocker.patch("semi.cli.controllers.views.render_order_counts")
    service = mocker.MagicMock()
    service.count_by_status.return_value = {"stub": 1}
    controller = MonitoringMenuController(service)
    controller.run()
    service.count_by_status.assert_called_once_with()
    render_counts.assert_called_once_with({"stub": 1})


def test_run_shows_stock_status_on_stock_choice(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_monitoring_menu",
        side_effect=["stock", "back"],
    )
    render_stock = mocker.patch("semi.cli.controllers.views.render_stock_status")
    service = mocker.MagicMock()
    service.stock_status.return_value = ["stub"]
    controller = MonitoringMenuController(service)
    controller.run()
    service.stock_status.assert_called_once_with()
    render_stock.assert_called_once_with(["stub"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_controllers_monitoring.py -v`
Expected: FAIL with `ImportError: cannot import name 'MonitoringMenuController' from 'semi.cli.controllers'`

- [ ] **Step 3: Append `MonitoringMenuController` to `controllers.py`**

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
            elif choice == "counts":
                views.render_order_counts(self._service.count_by_status())
            elif choice == "stock":
                views.render_stock_status(self._service.stock_status())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_controllers_monitoring.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/controllers.py tests/cli/test_controllers_monitoring.py
git commit -m "feat(cli): add MonitoringMenuController"
```

---

### Task 9: `views.py` — production line views (PRD 4.6)

**Files:**
- Modify: `semi/cli/views.py`
- Test: `tests/cli/test_views_production.py`

**Interfaces:**
- Consumes: `semi.services.production_service.ProductionJobStatus`, `semi.domain.models.ProductionJob` (from the services-layer plan).
- Produces: `render_production_menu() -> Literal["current", "queue", "back"]`, `render_current_production(status: ProductionJobStatus | None) -> None`, `render_production_queue(statuses: list[ProductionJobStatus]) -> None`. Task 10's `ProductionMenuController` uses all three.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_views_production.py`:

```python
from datetime import datetime

from semi.cli.views import (
    render_current_production,
    render_production_menu,
    render_production_queue,
)
from semi.domain.models import JobStatus, ProductionJob
from semi.services.production_service import ProductionJobStatus


def _job_status(**overrides):
    job = ProductionJob(
        job_id=1,
        order_id=10,
        sample_id="S1",
        shortfall_quantity=4,
        actual_quantity=5,
        total_duration_seconds=50.0,
        status=JobStatus.IN_PROGRESS,
        enqueued_at=datetime(2026, 7, 15, 12, 0, 0),
        started_at=datetime(2026, 7, 15, 12, 0, 0),
    )
    defaults = dict(
        job=job,
        progress_ratio=0.4,
        produced_so_far=2,
        estimated_completion_at=datetime(2026, 7, 15, 12, 1, 0),
    )
    defaults.update(overrides)
    return ProductionJobStatus(**defaults)


def test_render_production_menu_maps_known_choices(mocker):
    mocker.patch("builtins.input", side_effect=["1"])
    assert render_production_menu() == "current"


def test_render_production_menu_maps_unknown_input_to_back(mocker):
    mocker.patch("builtins.input", side_effect=["?"])
    assert render_production_menu() == "back"


def test_render_current_production_handles_none(capsys):
    render_current_production(None)
    assert "없음" in capsys.readouterr().out


def test_render_current_production_prints_job_details(capsys):
    render_current_production(_job_status())
    out = capsys.readouterr().out
    assert "10" in out
    assert "S1" in out


def test_render_production_queue_prints_each_job(capsys):
    render_production_queue([_job_status(), _job_status()])
    out = capsys.readouterr().out
    assert out.count("S1") == 2


def test_render_production_queue_handles_empty_list(capsys):
    render_production_queue([])
    assert "없음" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_views_production.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_production_menu' from 'semi.cli.views'`

- [ ] **Step 3: Append production views to `views.py`**

Add to `semi/cli/views.py` (add `from semi.services.production_service import ProductionJobStatus` to the top imports):

```python
def render_production_menu() -> Literal["current", "queue", "back"]:
    print("\n--- 생산 라인 ---")
    print("1. 현재 생산 현황 조회")
    print("2. 생산 대기열 조회")
    print("3. 뒤로가기")
    raw = input("선택> ")
    return {"1": "current", "2": "queue"}.get(raw, "back")


def render_current_production(status: ProductionJobStatus | None) -> None:
    print("\n--- 현재 생산 중 ---")
    if status is None:
        print("(현재 진행 중인 생산 작업 없음)")
        return
    job = status.job
    print(
        f"[Job {job.job_id}] 주문ID={job.order_id} 시료={job.sample_id} "
        f"부족분={job.shortfall_quantity} 실생산량={job.actual_quantity} "
        f"진행률={status.progress_ratio:.0%} 현재생산량={status.produced_so_far} "
        f"예상완료={status.estimated_completion_at.isoformat()}"
    )


def render_production_queue(statuses: list[ProductionJobStatus]) -> None:
    print("\n--- 생산 대기열 (FIFO) ---")
    if not statuses:
        print("(대기 중인 작업 없음)")
        return
    for status in statuses:
        job = status.job
        print(
            f"[Job {job.job_id}] 주문ID={job.order_id} 시료={job.sample_id} "
            f"실생산량={job.actual_quantity} 예상완료={status.estimated_completion_at.isoformat()}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_views_production.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/views.py tests/cli/test_views_production.py
git commit -m "feat(cli): add production line views"
```

---

### Task 10: `controllers.py` — `ProductionMenuController` (PRD 4.6)

**Files:**
- Modify: `semi/cli/controllers.py`
- Test: `tests/cli/test_controllers_production.py`

**Interfaces:**
- Consumes: `semi.cli.views` (Task 9), `semi.services.production_service.ProductionService` (`get_current_status`, `list_queue_status`).
- Produces: `semi.cli.controllers.ProductionMenuController(production_service)` satisfying `MenuController` (`label = "생산 라인"`). `app.py` (Task 13) instantiates it.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_controllers_production.py`:

```python
from semi.cli.controllers import ProductionMenuController


def test_label_is_production_line():
    controller = ProductionMenuController(production_service=object())
    assert controller.label == "생산 라인"


def test_run_returns_on_back(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_production_menu", return_value="back"
    )
    service = mocker.MagicMock()
    controller = ProductionMenuController(service)
    controller.run()
    service.get_current_status.assert_not_called()
    service.list_queue_status.assert_not_called()


def test_run_shows_current_status_on_current_choice(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_production_menu",
        side_effect=["current", "back"],
    )
    render_current = mocker.patch(
        "semi.cli.controllers.views.render_current_production"
    )
    service = mocker.MagicMock()
    service.get_current_status.return_value = "stub"
    controller = ProductionMenuController(service)
    controller.run()
    service.get_current_status.assert_called_once_with()
    render_current.assert_called_once_with("stub")


def test_run_shows_queue_on_queue_choice(mocker):
    mocker.patch(
        "semi.cli.controllers.views.render_production_menu",
        side_effect=["queue", "back"],
    )
    render_queue = mocker.patch("semi.cli.controllers.views.render_production_queue")
    service = mocker.MagicMock()
    service.list_queue_status.return_value = ["stub"]
    controller = ProductionMenuController(service)
    controller.run()
    service.list_queue_status.assert_called_once_with()
    render_queue.assert_called_once_with(["stub"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_controllers_production.py -v`
Expected: FAIL with `ImportError: cannot import name 'ProductionMenuController' from 'semi.cli.controllers'`

- [ ] **Step 3: Append `ProductionMenuController` to `controllers.py`**

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_controllers_production.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/controllers.py tests/cli/test_controllers_production.py
git commit -m "feat(cli): add ProductionMenuController"
```

---

### Task 11: `views.py` — release view (PRD 4.7)

**Files:**
- Modify: `semi/cli/views.py`
- Test: `tests/cli/test_views_release.py`

**Interfaces:**
- Consumes: `semi.domain.models.Order`, `render_order_list`/`prompt_order_id` (Task 5, reused as-is).
- Produces: `render_order_released(order: Order) -> None`. Task 12's `ReleaseMenuController` uses it plus the Task 5 functions.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_views_release.py`:

```python
from datetime import datetime

from semi.cli.views import render_order_released
from semi.domain.models import Order, OrderStatus


def test_render_order_released_prints_order_id(capsys):
    order = Order(
        order_id=9,
        sample_id="S1",
        customer_name="ACME",
        quantity=3,
        status=OrderStatus.RELEASE,
        created_at=datetime(2026, 7, 15, 12, 0, 0),
    )
    render_order_released(order)
    assert "9" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_views_release.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_order_released' from 'semi.cli.views'`

- [ ] **Step 3: Append `render_order_released` to `views.py`**

```python
def render_order_released(order: Order) -> None:
    print(f"출고가 완료되었습니다. [주문 ID={order.order_id}] 상태={order.status}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_views_release.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/views.py tests/cli/test_views_release.py
git commit -m "feat(cli): add release view"
```

---

### Task 12: `controllers.py` — `ReleaseMenuController` (PRD 4.7)

**Files:**
- Modify: `semi/cli/controllers.py`
- Test: `tests/cli/test_controllers_release.py`

**Interfaces:**
- Consumes: `semi.cli.views` (Tasks 5, 11), `semi.services.order_service.OrderService.release`, `semi.services.monitoring_service.MonitoringService.list_by_status`, `semi.domain.models.OrderStatus`.
- Produces: `semi.cli.controllers.ReleaseMenuController(order_service, monitoring_service)` satisfying `MenuController` (`label = "출고 처리"`). `app.py` (Task 13) instantiates it.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_controllers_release.py`:

```python
from semi.cli.controllers import ReleaseMenuController
from semi.domain.models import OrderStatus


def test_label_is_release():
    controller = ReleaseMenuController(order_service=object(), monitoring_service=object())
    assert controller.label == "출고 처리"


def test_run_returns_when_no_confirmed_orders(mocker):
    render_list = mocker.patch("semi.cli.controllers.views.render_order_list")
    monitoring_service = mocker.MagicMock()
    monitoring_service.list_by_status.return_value = []
    order_service = mocker.MagicMock()
    controller = ReleaseMenuController(order_service, monitoring_service)
    controller.run()
    monitoring_service.list_by_status.assert_called_once_with(OrderStatus.CONFIRMED)
    render_list.assert_called_once_with("출고 대상 주문 (CONFIRMED)", [])
    order_service.release.assert_not_called()


def test_run_returns_when_order_id_is_back(mocker):
    mocker.patch("semi.cli.controllers.views.render_order_list")
    mocker.patch("semi.cli.controllers.views.prompt_order_id", return_value="back")
    monitoring_service = mocker.MagicMock()
    monitoring_service.list_by_status.return_value = ["order-stub"]
    order_service = mocker.MagicMock()
    controller = ReleaseMenuController(order_service, monitoring_service)
    controller.run()
    order_service.release.assert_not_called()


def test_run_releases_selected_order_then_loops(mocker):
    mocker.patch("semi.cli.controllers.views.render_order_list")
    mocker.patch(
        "semi.cli.controllers.views.prompt_order_id", side_effect=[3, "back"]
    )
    render_released = mocker.patch("semi.cli.controllers.views.render_order_released")
    monitoring_service = mocker.MagicMock()
    monitoring_service.list_by_status.return_value = ["order-stub"]
    order_service = mocker.MagicMock()
    controller = ReleaseMenuController(order_service, monitoring_service)
    controller.run()
    order_service.release.assert_called_once_with(3)
    render_released.assert_called_once_with(order_service.release.return_value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_controllers_release.py -v`
Expected: FAIL with `ImportError: cannot import name 'ReleaseMenuController' from 'semi.cli.controllers'`

- [ ] **Step 3: Append `ReleaseMenuController` to `controllers.py`**

```python
class ReleaseMenuController:
    label = "출고 처리"

    def __init__(self, order_service, monitoring_service) -> None:
        self._order_service = order_service
        self._monitoring_service = monitoring_service

    def run(self) -> None:
        while True:
            orders = self._monitoring_service.list_by_status(OrderStatus.CONFIRMED)
            views.render_order_list("출고 대상 주문 (CONFIRMED)", orders)
            if not orders:
                return
            order_id = views.prompt_order_id("출고할 주문 ID")
            if order_id == "back":
                return
            order = self._order_service.release(order_id)
            views.render_order_released(order)
```

Note: this reuses the `OrderStatus` import already added in Task 6 — no new import needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_controllers_release.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/controllers.py tests/cli/test_controllers_release.py
git commit -m "feat(cli): add ReleaseMenuController"
```

---

### Task 13: `app.py` — entrypoint and assembly (§5)

**Files:**
- Create: `semi/cli/app.py`
- Test: `tests/cli/test_app.py`

**Interfaces:**
- Consumes: everything from Tasks 1–12, plus `semi.storage.db.connect_db`, `semi.storage.sample_repository.SampleRepository`, `semi.storage.order_repository.OrderRepository`, `semi.storage.production_job_repository.ProductionJobRepository`, `semi.services.sample_service.SampleService`, `semi.services.order_service.OrderService`, `semi.services.production_service.ProductionService`, `semi.services.monitoring_service.MonitoringService`, `semi.scheduler.background_worker.start_worker`.
- Produces: `semi.cli.app.main(db_path: Path = DB_PATH) -> None`, `semi.cli.app.DB_PATH`. `db_path` defaults to the module constant but is overridable — this is what lets the test below inject a stub path without touching a real file, since every collaborator that would use it (`connect_db`, `start_worker`) is mocked. Nothing beyond this module depends on `app.py`; it's the composition root.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_app.py`:

```python
from pathlib import Path

from semi.cli.app import main


def _patch_all_collaborators(mocker):
    mock_conn = mocker.MagicMock(name="conn")
    connect_db = mocker.patch("semi.cli.app.connect_db", return_value=mock_conn)
    lock = mocker.MagicMock(name="lock")
    mocker.patch("semi.cli.app.threading.Lock", return_value=lock)

    sample_repo_cls = mocker.patch("semi.cli.app.SampleRepository")
    order_repo_cls = mocker.patch("semi.cli.app.OrderRepository")
    job_repo_cls = mocker.patch("semi.cli.app.ProductionJobRepository")

    sample_service_cls = mocker.patch("semi.cli.app.SampleService")
    order_service_cls = mocker.patch("semi.cli.app.OrderService")
    production_service_cls = mocker.patch("semi.cli.app.ProductionService")
    monitoring_service_cls = mocker.patch("semi.cli.app.MonitoringService")

    sample_ctrl_cls = mocker.patch("semi.cli.app.SampleMenuController")
    order_ctrl_cls = mocker.patch("semi.cli.app.OrderMenuController")
    monitoring_ctrl_cls = mocker.patch("semi.cli.app.MonitoringMenuController")
    production_ctrl_cls = mocker.patch("semi.cli.app.ProductionMenuController")
    release_ctrl_cls = mocker.patch("semi.cli.app.ReleaseMenuController")

    start_worker = mocker.patch("semi.cli.app.start_worker")
    main_loop = mocker.patch("semi.cli.app.main_loop")

    return {
        "conn": mock_conn,
        "connect_db": connect_db,
        "lock": lock,
        "sample_repo_cls": sample_repo_cls,
        "order_repo_cls": order_repo_cls,
        "job_repo_cls": job_repo_cls,
        "sample_service_cls": sample_service_cls,
        "order_service_cls": order_service_cls,
        "production_service_cls": production_service_cls,
        "monitoring_service_cls": monitoring_service_cls,
        "sample_ctrl_cls": sample_ctrl_cls,
        "order_ctrl_cls": order_ctrl_cls,
        "monitoring_ctrl_cls": monitoring_ctrl_cls,
        "production_ctrl_cls": production_ctrl_cls,
        "release_ctrl_cls": release_ctrl_cls,
        "start_worker": start_worker,
        "main_loop": main_loop,
    }


def test_main_wires_repositories_services_and_controllers(mocker):
    collab = _patch_all_collaborators(mocker)
    db_path = Path("stub.db")

    main(db_path)

    collab["connect_db"].assert_called_once_with(db_path)
    collab["sample_repo_cls"].assert_called_once_with(collab["conn"])
    collab["order_repo_cls"].assert_called_once_with(collab["conn"])
    collab["job_repo_cls"].assert_called_once_with(collab["conn"])

    collab["sample_service_cls"].assert_called_once_with(
        collab["sample_repo_cls"].return_value
    )
    collab["order_service_cls"].assert_called_once_with(
        collab["order_repo_cls"].return_value,
        collab["job_repo_cls"].return_value,
        collab["sample_repo_cls"].return_value,
        collab["lock"],
    )
    collab["production_service_cls"].assert_called_once_with(
        collab["order_repo_cls"].return_value,
        collab["job_repo_cls"].return_value,
        collab["sample_repo_cls"].return_value,
        collab["lock"],
    )
    collab["monitoring_service_cls"].assert_called_once_with(
        collab["order_repo_cls"].return_value, collab["sample_repo_cls"].return_value
    )

    collab["sample_ctrl_cls"].assert_called_once_with(
        collab["sample_service_cls"].return_value
    )
    collab["order_ctrl_cls"].assert_called_once_with(
        collab["order_service_cls"].return_value,
        collab["monitoring_service_cls"].return_value,
    )
    collab["monitoring_ctrl_cls"].assert_called_once_with(
        collab["monitoring_service_cls"].return_value
    )
    collab["production_ctrl_cls"].assert_called_once_with(
        collab["production_service_cls"].return_value
    )
    collab["release_ctrl_cls"].assert_called_once_with(
        collab["order_service_cls"].return_value,
        collab["monitoring_service_cls"].return_value,
    )


def test_main_starts_worker_with_same_lock_and_db_path(mocker):
    collab = _patch_all_collaborators(mocker)
    db_path = Path("stub.db")

    main(db_path)

    collab["start_worker"].assert_called_once_with(db_path, collab["lock"])


def test_main_runs_main_loop_with_all_five_controllers_and_render_main_menu(mocker):
    collab = _patch_all_collaborators(mocker)
    from semi.cli.views import render_main_menu

    main(Path("stub.db"))

    args, kwargs = collab["main_loop"].call_args
    assert len(args[0]) == 5
    assert args[0] == [
        collab["sample_ctrl_cls"].return_value,
        collab["order_ctrl_cls"].return_value,
        collab["monitoring_ctrl_cls"].return_value,
        collab["production_ctrl_cls"].return_value,
        collab["release_ctrl_cls"].return_value,
    ]
    assert kwargs["render_main_menu"] is render_main_menu


def test_main_closes_connection_even_when_main_loop_raises_keyboard_interrupt(mocker):
    collab = _patch_all_collaborators(mocker)
    collab["main_loop"].side_effect = KeyboardInterrupt()

    main(Path("stub.db"))

    collab["conn"].close.assert_called_once_with()


def test_main_closes_connection_on_normal_exit(mocker):
    collab = _patch_all_collaborators(mocker)

    main(Path("stub.db"))

    collab["conn"].close.assert_called_once_with()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semi.cli.app'`

- [ ] **Step 3: Implement `app.py`**

```python
import threading
from pathlib import Path

from semi.cli.controllers import (
    MonitoringMenuController,
    OrderMenuController,
    ProductionMenuController,
    ReleaseMenuController,
    SampleMenuController,
)
from semi.cli.menu_loop import MenuController, main_loop
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

DB_PATH = Path("semi_order_system.db")


def main(db_path: Path = DB_PATH) -> None:
    conn = connect_db(db_path)
    lock = threading.Lock()

    sample_repo = SampleRepository(conn)
    order_repo = OrderRepository(conn)
    job_repo = ProductionJobRepository(conn)

    sample_service = SampleService(sample_repo)
    order_service = OrderService(order_repo, job_repo, sample_repo, lock)
    production_service = ProductionService(order_repo, job_repo, sample_repo, lock)
    monitoring_service = MonitoringService(order_repo, sample_repo)

    controllers: list[MenuController] = [
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_app.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest -v`
Expected: all tests across `tests/domain`, `tests/storage`, `tests/scheduler`, `tests/cli` (and services tests, if that plan has already run) PASS.

- [ ] **Step 6: Lint, format, commit**

```bash
ruff check --fix .
ruff format .
git add semi/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): add app entrypoint wiring repositories, services, controllers, and worker"
```

---

## Out of scope

- `semi/services/*` and `semi/scheduler/background_worker.py` — covered by `docs/superpowers/plans/2026-07-15-services-design.md` and `docs/superpowers/plans/2026-07-15-scheduler-worker.md` (see Prerequisite above).
- Packaging an actual console-script entry point (e.g. a `[project.scripts]` `pyproject.toml` entry calling `semi.cli.app:main`) — not requested by the spec; `python -m semi.cli.app` or a direct `main()` call both work as-is.
- Manual/interactive verification of the running console app against `dummydatagen`/`datamonitor` — recommended before considering this feature "done" end-to-end, but it is a manual QA step, not a plan task.

## Self-Review Notes

- **Spec coverage:** `2026-07-15-cli-design.md` §1 (module layout) → Tasks 1–13 create exactly `menu_loop.py`, `views.py`, `controllers.py`, `app.py`. §2 (`MenuController`/`main_loop`, single-catch dispatch, injected `render_main_menu`) → Task 1. §2.1 (fail-safe main menu input) → Task 2. §3 (five controllers, each with only its needed services) → Tasks 4/6/8/10/12, one per PRD 4.2–4.7 section exactly as the spec's bullet list names them. §4 (pure `views.py`, fail-safe submenu input, `StockStatus` Korean mapping in `cli`) → Tasks 2/3/5/7/9/11. §5 (`app.py` assembly, exact wiring order/args) → Task 13, code copied verbatim from the spec. §6 (two change points for new menus) → satisfied structurally: `menu_loop.py` is untouched by Tasks 4–13. §7 (KeyboardInterrupt → `finally: conn.close()`) → Task 13's tests explicitly cover both normal exit and `KeyboardInterrupt`.
- **Placeholder scan:** every step has full runnable code, concrete `pytest` commands, and stated expected pass counts; no "TBD"/"add validation"/"similar to Task N" placeholders.
- **Type consistency:** `render_main_menu(labels: list[str]) -> int | Literal["exit"]` (Task 2) matches what `main_loop` (Task 1) expects and what `app.py` (Task 13) passes in. Every controller constructor signature in Tasks 4/6/8/10/12 matches the exact instantiation calls in Task 13's `app.py` code and its test's `assert_called_once_with` checks. `prompt_order_id`/`render_order_list` (Task 5) are reused unchanged by `ReleaseMenuController` (Task 12) rather than redefined.
