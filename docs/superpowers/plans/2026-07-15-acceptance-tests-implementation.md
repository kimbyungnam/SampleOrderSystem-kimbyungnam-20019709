# 인수 테스트(`tests/acceptance/`) 구현 계획

## Context

`docs/superpowers/specs/2026-07-15-acceptance-test-design.md`가 인수 테스트의 하네스/시나리오/검증 방법을 이미 확정했다. 이 계획 문서는 그 스펙을 실제 파일/테스트 함수 목록으로 옮기는 좁은 범위의 실행 계획이며, 스펙이 이미 정한 설계는 재검토하지 않는다.

구현 착수 전 스펙이 지시한 사전 확인을 마쳤다:
- `semi/cli/app.py`의 조립 순서·인자가 스펙 §2.1의 `AppContext`/`app_context` 픽스처 가정과 정확히 일치한다 (5개 Controller: `SampleMenuController(sample_service)`, `OrderMenuController(order_service, monitoring_service)`, `MonitoringMenuController(monitoring_service)`, `ProductionMenuController(production_service)`, `ReleaseMenuController(order_service, monitoring_service)`; 서비스 생성자 인자도 스펙과 동일).
- `SampleService.register(sample_id, name, avg_production_seconds, yield_rate)` 시그니처가 스펙 §2.2의 `prompt_sample_registration` patch 예시(`return_value={"sample_id": ..., "name": ..., "avg_production_seconds": ..., "yield_rate": ...}` → `self._service.register(**data)`)와 일치한다.
- `semi/scheduler/background_worker.py`의 `start_worker(db_path, lock) -> threading.Thread`가 데몬 스레드로 `while True: tick(); time.sleep(1)`을 돌리며 예외를 `traceback.print_exc()`로 삼킨다는 스펙 §5 가정과 일치한다.
- `views.py`/`controllers.py`/`menu_loop.py`의 실제 함수명·choice 문자열(`"register"/"list"/"search"/"back"`, `"create"/"approve_reject"`, `"order_counts"/"stock_status"`, `"current"/"queue"` 등)을 확인해 아래 테스트 스케치에 반영했다.

변경 불필요: 스펙과 실제 코드가 어긋난 부분이 없으므로 `app_context` 픽스처는 스펙 §2.1의 코드 스케치 그대로 사용한다.

## 파일 구성

```
tests/acceptance/
├── __init__.py
├── conftest.py                       # app_context 픽스처 (스펙 §2.1)
├── test_sample_menu.py               # §3.1
├── test_order_menu.py                # §3.2
├── test_monitoring_menu.py           # §3.3
├── test_production_menu.py           # §3.4
├── test_release_menu.py              # §3.5
├── test_main_loop.py                 # §4.1(main_loop 레벨 부분), §4.3
├── test_views_fail_safe.py           # §4.1(views.render_main_menu 단위), §4.2
└── test_concurrency_scheduler.py     # §5
```

## 각 파일별 구체 내용

### `conftest.py`
- 스펙 §2.1 코드 그대로: `AppContext` dataclass, `app_context` 픽스처(`connect_db(tmp_path / "test.db")`, lock, 3개 repo, 4개 service, 5개 controller). `start_worker`는 호출하지 않는다.

### `test_sample_menu.py` (§3.1)
- `test_register_then_list_then_search`: `views.render_sample_menu` side_effect `["register", "list", "search", "back"]`; `prompt_sample_registration` → `{"sample_id": "S1", "name": "Wafer A", "avg_production_seconds": 10.0, "yield_rate": 0.9}`; `prompt_search_query` → `"Wafer"`. 검증: `sample_repo.get_by_id("S1").name == "Wafer A"`, `render_sample_registered` 호출 인자가 등록된 Sample, `render_sample_list` 호출 2회(list/search 각각) 및 두 번째 호출 인자가 `search_by_name("Wafer")` 결과와 일치.

### `test_order_menu.py` (§3.2)
사전 준비: 시료 2개 등록 — `S-STOCK`(등록 후 `sample_repo.increment_stock`으로 재고 확보 → 승인 시 즉시 CONFIRMED), `S-SHORT`(재고 0 → 승인 시 PRODUCING).
- `test_create_order_reserved`: `render_order_menu` → `["create", "create", "back"]`, `prompt_order_creation` side_effect로 두 시료 각각 주문 1건씩 생성. 검증: 두 주문 모두 `status == RESERVED`.
- `test_approve_sufficient_stock_confirms_immediately`: `render_order_menu` → `["approve_reject", "back"]`, `prompt_order_action` → `(order_id, "approve")` (S-STOCK 주문). 검증: `status == CONFIRMED`, `job_repo.get_by_order_id(order_id)`가 `NotFoundError` 발생.
- `test_approve_insufficient_stock_queues_production_job`: 동일 패턴으로 S-SHORT 주문 승인. 검증: `status == PRODUCING`, `job_repo.get_by_order_id(...)`의 `shortfall_quantity`/`actual_quantity`(`math.ceil(shortfall / yield_rate)`)/`total_duration_seconds`(`avg_production_seconds * actual_quantity`)가 DESIGN.md 공식대로.
- `test_reject_order`: 별도 주문 생성 후 `prompt_order_action` → `(order_id, "reject")`. 검증: `status == REJECTED`.
- `test_approve_reject_lists_reserved_orders`: `_approve_or_reject` 진입 시 `render_reserved_orders`가 두 건(위에서 만든 RESERVED 주문들)을 포함한 리스트로 호출됐는지 확인(`prompt_order_action` → `None`으로 즉시 취소해 리스트만 확인).

### `test_monitoring_menu.py` (§3.3)
- `test_order_counts`: RESERVED/CONFIRMED/PRODUCING/REJECTED 각 1건 이상 만든 뒤 `render_monitoring_menu` → `["order_counts", "back"]`. 검증: `render_order_counts` 호출 인자 == `monitoring_service.count_by_status()`.
- `test_stock_status_classification_and_korean_labels`: 시료 3개(여유/부족/고갈 각 1개, `tests/integration/test_order_lifecycle_sqlite.py`의 재고/미결 수량 조합 재사용) 구성 후 `render_monitoring_menu` → `["stock_status", "back"]`. 검증: `render_stock_status` 호출 인자가 `monitoring_service.stock_status()`와 일치하는 `SampleStockStatus` 리스트; 실제 `views.render_stock_status`(patch하지 않고 `capsys`로 stdout 캡처)를 별도 테스트로 호출해 출력에 "여유"/"부족"/"고갈" 한글 라벨이 각각 포함되는지 확인.

### `test_production_menu.py` (§3.4)
- 사전 준비: 재고 0 시료에 주문 2건 승인(PRODUCING, job 2개 큐잉) → `production_service.tick()` 1회 직접 호출로 첫 job IN_PROGRESS 승격.
- `test_current_production_status`: `render_production_menu` → `["current", "back"]`. 검증: `render_current_production` 호출 인자 == `production_service.get_current_status()`.
- `test_production_queue`: `render_production_menu` → `["queue", "back"]`. 검증: `render_production_queue` 호출 인자 == `production_service.list_queue_status()` (대기 중인 1개 job).
- `test_unrecognized_choice_is_safe`: 이 컨트롤러가 §4.2의 "인식 불가 입력 → back" 케이스도 겸한다 — `render_production_menu`가 실제 구현 그대로 동작하도록 두고 `builtins.input`을 `"xyz"`로 patch, `run()`이 예외 없이 반환하는지 확인.

### `test_release_menu.py` (§3.5)
- 사전 준비: 주문 2건을 CONFIRMED로 — 하나는 재고충분 경로(즉시 CONFIRMED), 하나는 PRODUCING → `tick()`(스펙 §3.4 방식대로 `job_repo.mark_in_progress`의 `started_at`을 과거로 이동시켜 결정론적으로 즉시 완료 처리) → CONFIRMED.
- `test_confirmed_orders_listed`: `prompt_release_selection` → `None`(취소)으로 리스트만 확인. 검증: `render_confirmed_orders` 호출 인자 == `monitoring_service.list_by_status(CONFIRMED)` (2건).
- `test_release_decrements_stock`: 각 CONFIRMED 주문마다 `prompt_release_selection` → 해당 order_id, 이어서 남은 주문 없으면 루프 자연 종료(order 리스트가 비면 `run()`이 return). 검증: `order_repo.get_by_id(...).status == RELEASE`, `sample_repo.get_by_id(...).stock_quantity`가 정확히 `order.quantity`만큼 감소.

### `test_main_loop.py` (§4.1 main_loop 부분, §4.3)
- `test_main_loop_exits_immediately`: `main_loop(app_context.controllers, render_main_menu=lambda labels: "exit")` 예외 없이 반환.
- `test_main_loop_dispatches_valid_choice`: `render_main_menu`를 `iter(["exit"])`가 아니라, 첫 호출엔 특정 controller index, 두 번째부터는 `"exit"`를 내는 클로저로 스크립팅. 대상 컨트롤러의 `run`을 `mocker.patch.object(controller, "run")`으로 spy해 1회 호출됐는지 확인.
- `test_main_loop_catches_domain_error_and_continues`: `OrderMenuController`를 골라 `views.render_order_menu` → `"create"`, `prompt_order_creation` → 존재하지 않는 `sample_id`(→ `create_order`가 `DomainError`). `render_main_menu`를 "OrderMenuController 인덱스 1회 → 이후 exit" 클로저로 스크립팅하고 spy 부착. 검증(`capsys`): stdout에 `"[오류] "` 포함, spy가 2회 호출됨(다음 반복 도달).
- `test_main_loop_catches_not_found_error_and_continues`: 동일 패턴으로 `OrderMenuController._approve_or_reject`에서 존재하지 않는 order_id로 승인 시도 → `NotFoundError`(`order_repo.get_by_id` 실패). `prompt_order_action`을 `(9999, "approve")` 반환하도록 patch(단, `_approve_or_reject`는 `valid_ids`에 없으면 `None`을 반환하는 안전장치가 있으므로, `NotFoundError`를 실제로 유발하려면 `prompt_order_action` 자체를 직접 patch해 `valid_ids` 검사를 우회 — 스펙이 예시로 든 "존재하지 않는 order_id로 승인 시도"에 맞춰 `views.prompt_order_action`을 `(9999, "approve")` 고정 반환으로 patch). 검증: `"[조회 실패] "` 포함, spy 2회 호출.

### `test_views_fail_safe.py` (§4.1 views 단위, §4.2)
- `test_render_main_menu_reprompts_on_invalid_input`: `builtins.input` side_effect `["abc", "99", "0"]` (마지막 `"0"` → `"exit"` 반환 확인) 및 별도 케이스로 `["abc", "99", "1"]` → 유효 인덱스 `0` 반환 확인. `render_main_menu`가 크래시 없이 최종 유효값을 반환하는지 검증.
- `test_render_sample_menu_unrecognized_input_returns_back`: `input` → `"xyz"` → `render_sample_menu() == "back"`.
- 동일 패턴을 `render_order_menu`/`render_monitoring_menu`/`render_production_menu`에도 반복(테이블 기반 `pytest.mark.parametrize`로 통합 가능).

### `test_concurrency_scheduler.py` (§5)
- 전용 픽스처(`app_context`를 재사용하되 이 파일 안에서 직접 `start_worker(app_context.db_path, app_context.lock)` 호출) — 스펙이 별도 파일에 격리하라고 명시했으므로 `conftest.py`의 공용 `app_context`는 그대로 쓰고 워커 시작만 테스트 함수 내부에서 수행.
- 준비: 시료 1개 등록(`avg_production_seconds=0.05`, `yield_rate=1.0`, 재고 0).
- 실행: `OrderMenuController`를 `views.*` patch로 스크립팅해 메인 스레드에서 주문 3건 생성 + 즉시 승인(모두 PRODUCING 경로, job 3개 큐잉) — `render_order_menu` side_effect: `["create", "create", "create", "approve_reject", "approve_reject", "approve_reject", "back"]` 패턴으로 구성(생성 3회 후 승인 3회, `prompt_order_action`이 매번 다음 RESERVED 주문의 id를 반환하도록 side_effect 리스트로 미리 order_id를 알아내 구성). `start_worker`는 승인 시작 전에 이미 실행 중.
- 검증: `capfd`로 stderr 캡처 시작 → 폴링 루프(0.05s 간격, 5s 데드라인)로 (a) 3개 주문 모두 `CONFIRMED`, (b) 매 iteration마다 `sample_repo.get_by_id(...).stock_quantity >= order_repo.sum_quantity_by_status(sample_id, CONFIRMED)`(미출고 CONFIRMED 합, 이 시나리오는 release 없음) 위반 시 즉시 `pytest.fail`. 루프 종료 후: 최종 `stock_quantity == sum(actual_quantity for 3 jobs)`(job_repo에서 각 order의 job 조회), `capfd.readouterr().err`에 트레이스백 문자열(`"Traceback"`) 없음.
- side_effect 리스트는 스펙이 강조한 대로 반드시 마지막이 `"back"`으로 끝나야 하므로, 생성+승인 시퀀스 구성 시 정확한 개수를 세어 리스트를 짠다(승인은 각 승인마다 `render_order_menu`가 한 번 더 `"approve_reject"`를 반환해야 하므로 3회 반복 필요 — `_approve_or_reject`는 1회 호출당 주문 1건만 처리).

## 실행 순서

1. `docs/superpowers/plans/2026-07-15-acceptance-tests-implementation.md`(본 문서) 커밋 — `docs: add acceptance tests implementation plan`.
2. 위 파일들을 순서대로 구현.
3. `pip install -e ".[dev,test]"` (필요 시) → `py -3.14 -m pytest tests/acceptance -v` → `py -3.14 -m pytest`(전체) → `ruff check --fix .` → `ruff format .`.
4. 실패 시 폴링/타이밍 로직을 조정할지언정 불변식 검증(§5) 자체는 완화하지 않는다.
5. `test: add CLI/scheduler acceptance tests` 커밋.
6. `git fetch` 및 `git log <merge-base>..main`, `git branch -a`로 main 이동 여부 확인 후 보고(머지/리베이스/푸시는 하지 않음).
