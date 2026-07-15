# 인수 테스트 설계 — `semi/cli` + `semi/scheduler`

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | `semi/cli`, `semi/scheduler`가 main에 병합된 뒤 별도 세션이 이 문서를 입력으로 writing-plans → 구현에 바로 들어갈 수 있도록, 인수 테스트의 하네스/시나리오/검증 방법을 구체적으로 확정 |
| 근거 문서 | `PRD.md` §4.1~4.7, [`2026-07-15-cli-design.md`](2026-07-15-cli-design.md), [`2026-07-15-scheduler-design.md`](2026-07-15-scheduler-design.md), [`2026-07-15-services-design.md`](2026-07-15-services-design.md) |
| 작성일 | 2026-07-15 |
| 실행 시점 | **CLI/scheduler가 main에 병합된 이후.** 이 문서 작성 시점에는 `semi/cli`, `semi/scheduler` 코드가 아직 존재하지 않으므로, 여기 기술된 어떤 테스트 코드도 이 시점에는 작성/실행하지 않는다 |
| 실행 위치 | `tests/acceptance/` (신규 디렉터리) |

---

## 1. 왜 별도 인수 테스트 레이어가 필요한가

`tests/integration/`(2026-07-15-integration-acceptance-tests.md에서 추가)은 storage+services 크로스레이어를 실제 SQLite로 검증하지만, 사용자가 실제로 마주치는 표면인 콘솔 메뉴 흐름(`cli`)과 백그라운드 생산 시뮬레이션(`scheduler`)은 검증하지 않는다. 이 문서가 설계하는 `tests/acceptance/`는 PRD §4.1~4.7의 메뉴별 시나리오를 실제 Controller/View 조립을 통해 엔드투엔드로 검증하고, CLI(메인 스레드)와 스케줄러(백그라운드 데몬 스레드)가 하나의 `threading.Lock`으로 안전하게 공존하는지까지 검증한다.

## 2. 테스트 하네스 설계

### 2.1 `tests/acceptance/conftest.py` — `app_context` 픽스처

`semi/cli/app.py`의 조립 로직(2026-07-15-cli-design.md §5)을 그대로 재현하되, 두 가지를 테스트 목적으로 바꾼다:

1. DB 경로는 `tmp_path / "test.db"`로 고정 (실제 파일 시스템 SQLite, `connect_db` 사용 — `tests/integration/conftest.py`의 `real_db` 픽스처와 동일한 방식).
2. `start_worker(db_path, lock)`는 **기본적으로 호출하지 않는다.** 대부분의 CLI 시나리오 테스트는 결정론적으로 `production_service.tick()`을 테스트 코드가 직접 호출해 생산 진행을 제어해야 하므로, 실시간 1초 tick 데몬을 백그라운드에서 같이 돌리면 타이밍에 따라 결과가 흔들릴 수 있다. 워커가 실제로 필요한 테스트는 §5(동시성 인수 테스트)뿐이며, 그 테스트는 자체적으로 `start_worker`를 호출하는 별도 픽스처(`app_context_with_worker` 또는 동등한 변형)를 쓴다.

```python
@dataclass
class AppContext:
    conn: sqlite3.Connection
    db_path: Path
    lock: threading.Lock
    sample_repo: SampleRepository
    order_repo: OrderRepository
    job_repo: ProductionJobRepository
    sample_service: SampleService
    order_service: OrderService
    production_service: ProductionService
    monitoring_service: MonitoringService
    controllers: list[MenuController]  # app.py와 동일한 순서로 조립:
                                        # [SampleMenuController, OrderMenuController,
                                        #  MonitoringMenuController, ProductionMenuController,
                                        #  ReleaseMenuController]


@pytest.fixture
def app_context(tmp_path):
    conn = connect_db(tmp_path / "test.db")
    try:
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
        yield AppContext(
            conn=conn, db_path=tmp_path / "test.db", lock=lock,
            sample_repo=sample_repo, order_repo=order_repo, job_repo=job_repo,
            sample_service=sample_service, order_service=order_service,
            production_service=production_service, monitoring_service=monitoring_service,
            controllers=controllers,
        )
    finally:
        conn.close()
```

`app_context`가 `app.py`의 실제 조립 순서·인자와 어긋나면(예: `OrderMenuController`가 실제로는 다른 서비스를 받도록 병합 시점에 바뀌었다면) 이 픽스처를 그 시점의 `app.py` 소스에 맞춰 갱신하는 것이 구현 세션의 첫 번째 할 일이다.

### 2.2 사용자 입력 스크립팅 — `views.*` patch

`controllers.py`는 `views.render_sample_menu()` 형태로 `views` 모듈 함수를 직접 호출하는 구조이며 의존성 주입이 아니다(2026-07-15-cli-design.md §3). 따라서 메뉴 선택/입력 시퀀스는 `unittest.mock.patch`로 스크립팅한다:

```python
def test_sample_register_then_list_then_search(app_context, mocker):
    mocker.patch(
        "semi.cli.views.render_sample_menu",
        side_effect=["register", "list", "search", "back"],
    )
    mocker.patch(
        "semi.cli.views.prompt_sample_registration",
        return_value={
            "sample_id": "S1", "name": "Wafer A",
            "avg_production_seconds": 10.0, "yield_rate": 0.9,
        },
    )
    mocker.patch("semi.cli.views.prompt_search_query", return_value="Wafer")
    render_list = mocker.patch("semi.cli.views.render_sample_list")
    mocker.patch("semi.cli.views.render_sample_registered")

    sample_menu_controller = app_context.controllers[0]
    sample_menu_controller.run()

    # 최종 상태는 서비스/리포지토리 조회로 검증한다 — render_list의 호출 인자는
    # 화면 출력 검증이 필요한 보조 확인용으로만 사용.
    assert app_context.sample_repo.get_by_id("S1").name == "Wafer A"
    assert render_list.call_count == 2  # list 시나리오 + search 시나리오
```

- `pytest-mock`(이미 `pyproject.toml` test extra에 존재)의 `mocker` 픽스처를 사용해 `patch`가 테스트 종료 시 자동 복원되도록 한다.
- 각 Controller의 `run()`은 무한 서브메뉴 루프이므로, `side_effect` 리스트의 **마지막 값은 반드시 `"back"`**이어야 한다(그렇지 않으면 `StopIteration`이 발생하고 `run()`은 이를 그대로 전파해 테스트가 실패한다 — 이는 의도된 fail-safe이며, 테스트 스크립트 실수를 잡아내는 신호로 활용한다).
- `main_loop` 자체(루프/디스패치/예외 처리 골격)를 검증하는 테스트는 `views`를 patch하지 않고, `render_main_menu`에 순수 함수(예: `lambda labels: "exit"`, 또는 호출마다 다른 값을 내는 클로저)를 직접 인자로 넘긴다(2026-07-15-cli-design.md §2가 `render_main_menu`를 파라미터로 주입받도록 설계한 이유가 바로 이 테스트 용이성이다). 예:

```python
def test_main_loop_exits_immediately(app_context):
    main_loop(app_context.controllers, render_main_menu=lambda labels: "exit")
    # 컨트롤러가 한 번도 호출되지 않았음을 별도 spy로 확인하거나,
    # 예외 없이 반환되는 것 자체를 성공 기준으로 삼는다.
```

### 2.3 상태 검증 원칙

- **1순위**: 서비스/리포지토리 조회 (`order_repo.get_by_id(...).status`, `sample_repo.get_by_id(...).stock_quantity` 등) — 이것이 사용자가 실제로 경험하는 "결과"의 근거이며, 화면 출력 포맷 변경에 테스트가 흔들리지 않는다.
- **2순위**: 화면 출력 검증이 반드시 필요한 경우(에러 메시지가 실제로 렌더링되는지, `[오류]`/`[조회 실패]` 접두사가 붙는지 등)만 `views.render_*`를 patch해 호출 인자(`call_args`)를 캡처해 확인한다.
- `print`로 직접 출력되는 `main_loop`의 오류 메시지(`print(f"[오류] {e}")`)를 검증해야 하는 시나리오(§4)는 `capsys`(pytest 내장 픽스처)로 stdout을 캡처한다.

## 3. PRD 4.1~4.7 메뉴별 시나리오 (해피패스)

각 시나리오는 `app_context` 픽스처를 사용하고, 해당 `MenuController.run()`을 `views.*` patch로 스크립팅해 직접 호출한 뒤 리포지토리 상태로 검증한다.

### 3.1 시료 관리 (`SampleMenuController`, PRD §4.2)
1. `views.render_sample_menu` 시퀀스: `["register", "list", "search", "back"]`.
2. `register`: `prompt_sample_registration`이 `{"sample_id": "S1", "name": "Wafer A", "avg_production_seconds": 10.0, "yield_rate": 0.9}`를 반환하도록 patch → `sample_repo.get_by_id("S1")`이 방금 등록한 값과 일치하는지 검증, `views.render_sample_registered`가 등록된 `Sample`을 인자로 호출됐는지 확인.
3. `list`: `views.render_sample_list`가 `sample_service.list_all()`과 동일한 리스트를 인자로 호출됐는지 확인.
4. `search`: `prompt_search_query`가 `"Wafer"`를 반환하도록 patch → `views.render_sample_list`가 `search_by_name("Wafer")` 결과(등록된 S1 포함)로 호출됐는지 확인.

### 3.2 주문 접수/승인/거절 (`OrderMenuController`, PRD §4.3, §4.4)
사전 조건: 시료 두 개 등록 — 하나는 재고를 미리 채워(`sample_repo.increment_stock`) 승인 시 즉시 CONFIRMED가 나오는 경로, 다른 하나는 재고 0으로 두어 승인 시 PRODUCING(재고부족) 경로를 만든다.

1. 주문 접수: Controller의 주문 생성 서브메뉴를 통해 두 시료 각각에 대해 주문 1건씩 생성 → `order_repo.get_by_id(...).status == RESERVED`.
2. 미결 주문 목록 조회: `monitoring_service.list_by_status(RESERVED)`를 사용하는 서브메뉴 선택 시 `views.render_*`가 두 건 모두를 포함해 호출되는지 확인.
3. 승인(재고 충분 경로): 재고를 채워둔 시료의 주문을 승인 → `order_repo.get_by_id(...).status == CONFIRMED`, `job_repo.get_by_order_id(...)`가 `NotFoundError`를 던짐(job 미생성) 확인.
4. 승인(재고 부족 경로): 재고 0인 시료의 주문을 승인 → `status == PRODUCING`, `job_repo.get_by_order_id(...)`가 실제 `ProductionJob`을 반환하며 `shortfall_quantity`/`actual_quantity`/`total_duration_seconds`가 DESIGN.md 공식대로 계산됐는지 확인.
5. 거절: 별도 주문 1건을 생성해 거절 → `status == REJECTED`.

### 3.3 모니터링 (`MonitoringMenuController`, PRD §4.5)
1. 위 3.2에서 만든 상태(RESERVED/CONFIRMED/PRODUCING/REJECTED 각 1건 이상)를 재사용하거나 이 시나리오 전용으로 다시 구성.
2. 상태별 주문 건수 조회 서브메뉴 → `views.render_*`가 `monitoring_service.count_by_status()`와 일치하는 딕셔너리로 호출되는지 확인.
3. 재고 현황 조회 서브메뉴 → 여유(SUFFICIENT)/부족(SHORT)/고갈(DEPLETED) 세 케이스를 만들어(각각 시료 하나씩, `tests/integration/test_order_lifecycle_sqlite.py::test_monitoring_stock_status_classification`와 동일한 재고/미결 수량 조합 사용) `views.render_stock_status`가 올바른 `SampleStockStatus` 리스트로 호출되는지, 그리고 CLI 레이어가 영문 `StockStatus`를 한글("여유"/"부족"/"고갈")로 매핑해 실제로 출력하는지(§2.3의 `capsys` 또는 patch된 `render_stock_status` 호출 인자로) 확인.

### 3.4 생산 현황/큐 (`ProductionMenuController`, PRD §4.6)
1. 재고 부족 경로로 주문 2건을 PRODUCING까지 승인해 큐에 job 2개를 쌓는다(`tests/integration`의 FIFO 시나리오와 동일한 준비 단계).
2. `production_service.tick()`을 테스트 코드가 직접 1회 호출해 첫 job을 IN_PROGRESS로 승격시킨다.
3. 현재 생산 현황 조회 서브메뉴 → `views.render_*`가 `production_service.get_current_status()`와 일치하는 `ProductionJobStatus`(진행률/완료 예정 시각 포함)로 호출되는지 확인.
4. 생산 큐 조회 서브메뉴 → `production_service.list_queue_status()`와 일치하는 리스트(대기 중인 job)로 호출되는지 확인.
5. 이 컨트롤러에는 승인/거절이 없으므로(§3 cli-design.md) 서브메뉴는 조회 전용 두 갈래(`current`, `queue`)와 `back`만 존재 — `run()`이 그 외 입력에 대해 크래시하지 않고 `back`으로 처리하는지도 §4.2에서 다룬다.

### 3.5 출고 (`ReleaseMenuController`, PRD §4.7)
1. 사전 조건: 주문을 CONFIRMED까지 만든다(재고 충분 경로로 즉시 CONFIRMED, 또는 PRODUCING → tick 강제 완료 → CONFIRMED 두 경로 모두 최소 1회씩 커버).
2. CONFIRMED 목록 조회 서브메뉴 → `views.render_*`가 `monitoring_service.list_by_status(CONFIRMED)`와 일치하는 리스트로 호출되는지 확인.
3. 출고 실행 서브메뉴 → 대상 주문 선택 후 `order_repo.get_by_id(...).status == RELEASE`, `sample_repo.get_by_id(...).stock_quantity`가 정확히 `order.quantity`만큼 감소했는지 확인.

## 4. 에러/예외 경로 시나리오

### 4.1 잘못된 메인 메뉴 입력
- `render_main_menu`에 순수 함수 대신, 첫 호출엔 잘못된 값(문자열 파싱 실패 또는 범위 초과)을 반환하고 이후 호출엔 유효한 값을 반환하는 스텁을 넘겨 **`main_loop` 자체가 아니라 `views.render_main_menu`의 실제 구현**이 재입력 요구 로직(§2.1)을 갖고 있는지 검증한다. 구체적으로:
  - `views.render_main_menu`를 직접 호출하는 단위 테스트(§4는 인수 테스트지만, 이 케이스는 `input`을 patch해 `["abc", "99", "0"]` 같은 시퀀스를 주고 `views.render_main_menu(labels)`가 크래시 없이 최종적으로 유효한 인덱스 `0`을 반환하는지 확인) — `mocker.patch("builtins.input", side_effect=[...])`.
  - `main_loop` 레벨에서는 `render_main_menu`가 계약대로 항상 유효한 값만 반환한다고 가정하고 있으므로, `main_loop`이 잘못된 `choice`를 받았을 때 크래시하지 않는다는 것 자체는 위 `views.render_main_menu` 단위 테스트로 이미 보장된다. `main_loop` 인수 테스트는 대신 "controllers 리스트 범위 내의 choice만 주입되면 정상적으로 `controllers[choice].run()`이 호출된다"를 확인하는 정도로 충분하다 (계약 위반 케이스까지 `main_loop`에서 재검증하지 않는다 — 책임 소재를 명확히 하기 위함).

### 4.2 서브메뉴에서 인식 불가 입력 → `"back"` 안전 처리
- 임의의 한 Controller(예: `ProductionMenuController`)를 골라 `views.render_*_menu`(서브메뉴 선택 함수)가 인식할 수 없는 입력에 대해 `"back"`을 반환하도록 patch(`side_effect=["back"]`으로 직접 스크립팅하거나, 실제 `views` 구현을 그대로 두고 `input`을 이상한 값으로 patch)하고, `run()`이 예외 없이 반환되는지 확인.
- 이 원칙 자체(§4 cli-design.md의 입력 파싱 fail-safe)를 검증하는 더 강력한 방법은 `views.py`의 실제 서브메뉴 함수(`render_sample_menu` 등)를 patch하지 않고 `input`만 patch해, 인식 불가 문자열(`"xyz"`)을 주었을 때 함수가 예외를 던지지 않고 `"back"`을 반환하는지를 `views` 모듈 단위로 직접 확인하는 것 — 인수 테스트 스위트 안에 `tests/acceptance/test_views_fail_safe.py`로 이 케이스들을 모아 둔다(Controller 레벨 인수 테스트와는 별도 파일).

### 4.3 `DomainError`/`NotFoundError`의 단일 catch 지점 처리
- `app_context.controllers`에서 임의의 Controller 하나를 골라, `views.*` patch로 서비스가 반드시 `DomainError`를 던지는 입력을 스크립팅한다(예: 존재하지 않는 `sample_id`로 주문 생성 시도 → `OrderService.create_order`가 `DomainError` 발생).
- `main_loop(app_context.controllers, render_main_menu=lambda labels: <해당 컨트롤러 인덱스이고, 두 번째 호출부터는 "exit">)`처럼 스크립팅해 `main_loop`을 실제로 구동하고, `capsys.readouterr().out`에 `"[오류] "` 접두사가 포함된 메시지가 출력되는지, 그리고 루프가 죽지 않고 다음 반복(→ `"exit"`)까지 정상적으로 도달하는지 확인.
- 동일한 방식으로 `NotFoundError` 경로(예: 존재하지 않는 order_id로 승인 시도)도 `"[조회 실패] "` 접두사로 확인하는 별도 테스트를 둔다.
- 두 테스트 모두 "루프가 죽지 않는다"를 **다음 반복이 실제로 일어난다는 것**(예: `render_main_menu`가 2번째로 호출됨을 spy로 확인)으로 검증해, 단순히 예외가 밖으로 새지 않는 것 이상을 보장한다.

## 5. 전용 동시성(스케줄러) 인수 테스트

파일: `tests/acceptance/test_concurrency_scheduler.py` (전용 픽스처 사용, §2.1의 기본 `app_context`와 별개).

### 5.1 준비
- `app_context`와 동일하게 조립하되, 이번에는 실제로 `start_worker(db_path, lock)`를 호출해 데몬 스레드를 띄운다(2026-07-15-scheduler-design.md). `start_worker`가 반환하는 `threading.Thread`는 데몬이므로 테스트 종료 시 별도 join 없이 프로세스/세션이 끝나면 정리되지만, 테스트 자체가 끝나기 전에는 폴링으로 완료를 기다린다(아래).
- 실시간 1초 tick 루프를 그대로 기다리지 않기 위해, 시료의 `avg_production_seconds`를 작게(예: `0.05`) 설정해 job의 `total_duration_seconds`가 짧게(수십 ms~수백 ms) 나오도록 한다. 이렇게 하면 워커의 1초 간격 tick만으로도 여러 tick 안에 완료가 관측된다 — 단, 정확한 tick 횟수에 의존하지 않고 폴링으로 완료를 기다린다(아래 5.3).
- 대안으로 `job_repo.mark_in_progress`를 이용해 `started_at`을 과거로 미리 이동시키는 기법도 병행 가능하지만, 이 경우 락을 쥐고 있는 워커 스레드와 테스트 스레드가 동시에 같은 job row를 건드리게 되므로, 이 시나리오의 목적(두 스레드가 실제로 동시 접근할 때 락이 직렬화를 보장하는지)에는 "작은 `avg_production_seconds` + 워커의 자연스러운 tick"이 더 적합하다. `started_at` 과거 이동 기법은 §3.4처럼 워커 없이 결정론적으로 tick을 손으로 미는 시나리오에서만 사용한다.

### 5.2 실행
1. 재고 0인 시료 하나를 등록(`avg_production_seconds=0.05`, `yield_rate=1.0`).
2. **메인 스레드에서** CLI 컨트롤러(`OrderMenuController`, `views.*` patch로 스크립팅)를 통해 주문 3건을 생성하고 즉시 각각 승인 요청을 보낸다(모두 재고 0 → PRODUCING 경로, job 3개가 큐잉됨).
3. 워커 스레드는 이미 백그라운드에서 1초 간격으로 `tick()`을 호출 중이며, 메인 스레드의 승인(각 `approve()` 호출도 동일한 `lock`을 획득)과 교차로 실행된다.

### 5.3 검증
- 짧은 간격(0.05~0.1초)으로 폴링하며 최대 수 초(예: 5초) 동안 "3건의 주문이 모두 CONFIRMED 상태가 되었는지"를 기다린다:

```python
import time

deadline = time.monotonic() + 5.0
while time.monotonic() < deadline:
    statuses = [app_context.order_repo.get_by_id(oid).status for oid in order_ids]
    if all(s == OrderStatus.CONFIRMED for s in statuses):
        break
    time.sleep(0.05)
else:
    pytest.fail("orders did not all reach CONFIRMED within timeout")
```
- 완료 후 다음을 확인한다:
  - 각 job의 `actual_quantity` 합만큼 재고가 증가했다가, 이 시나리오에서는 출고를 하지 않았으므로 `sample_repo.get_by_id(...).stock_quantity == sum(actual_quantity for all 3 jobs)`.
  - **오버셀 방지 불변식**: 테스트 진행 중 어느 시점에도(폴링 루프 안에서 매 iteration마다 함께 관찰) `stock_quantity >= sum(quantity of un-released CONFIRMED orders)`가 위반된 순간이 없었는지 — 폴링 루프에서 매번 이 조건도 함께 체크하고, 위반되는 순간이 있으면 즉시 실패시킨다(단순히 최종 상태만 보면 레이스가 순간적으로 불변식을 깨더라도 놓칠 수 있으므로).
  - 워커가 죽지 않고 계속 동작했는지(스레드가 여전히 `is_alive()`인지) 확인 — `traceback.print_exc()`로 삼켜지는 예외가 있었다면 워커는 계속 돌아야 정상이므로, 스레드 자체의 생존만으로는 예외 발생 여부를 알 수 없다. 대신 stderr를 `capsys`(또는 `capfd`, 스레드 출력이므로 `capfd`가 더 안전)로 캡처해 `traceback.print_exc()`에 해당하는 트레이스백이 찍히지 않았는지 확인한다.
- 테스트 종료 시 워커 스레드는 데몬이므로 명시적 종료가 필수는 아니지만, 다음 테스트에 영향을 주지 않도록 `conn.close()`(픽스처의 `finally`)는 그대로 수행하고, 워커 스레드가 닫힌 연결에 대해 예외를 던지더라도 `traceback.print_exc()`로 삼켜지고 프로세스는 종료되므로 테스트 실행 자체에는 영향이 없음을 이 설계의 전제로 명시한다.

## 6. 문서 self-review 체크리스트 결과

- **TBD/placeholder 없음**: 위 모든 섹션이 구체적인 픽스처 이름, 코드 스케치, patch 대상, 검증식(폴링 루프 포함)을 담고 있다. "추후 결정" 항목 없음.
- **cli-design.md의 fail-safe 원칙과의 교차 확인**:
  - §2.1(잘못된 메인 메뉴 입력은 `views.py`가 흡수)과 본 문서 §4.1이 일치 — `main_loop`에 잘못된 입력을 직접 넣어 검증하지 않고, 계약의 소유자인 `views.render_main_menu` 레벨에서 검증하도록 설계했다.
  - §4(서브메뉴 인식 불가 입력 → `"back"`)와 본 문서 §4.2가 일치 — Controller 레벨과 `views` 단위 레벨 양쪽에서 커버.
  - §2(단일 지점 예외 처리)와 본 문서 §4.3이 일치 — `DomainError`/`NotFoundError` 각각을 `main_loop`을 통해 실제로 구동해 검증하고, 메시지 접두사(`[오류]`/`[조회 실패]`)까지 확인.
  - 모순되는 지점 없음.
- **자기완결성**: `app_context`/`AppContext`의 필드 구성이 `app.py` §5의 조립 순서·인자와 그대로 대응되도록 코드 스케치를 포함했고, 병합 시점에 `app.py`가 바뀌었을 경우의 대응 지침(§2.1 마지막 문단)도 포함했다. 별도 질문 없이 writing-plans로 진입 가능한 수준으로 판단.
