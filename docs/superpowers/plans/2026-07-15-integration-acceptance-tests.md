# 통합/인수 테스트 추가 계획

## Context

`semi/domain`, `semi/storage`, `semi/services` 레이어는 구현/테스트가 끝났지만, 현재 유일한 크로스-레이어 테스트인 `tests/test_lifecycle.py`는 실제 SQLite가 아니라 `tests/test_fakes.py`의 in-memory fake 리포지토리를 사용한다. `semi/cli`, `semi/scheduler`는 아직 코드가 없고 설계 문서(`docs/superpowers/specs/2026-07-15-cli-design.md`, `2026-07-15-scheduler-design.md`)만 존재하며, 다른 세션이 병렬로 구현 중이다(이 저장소는 레이어별 동시 세션 작업 패턴을 쓴다).

사용자는 통합/인수 테스트를 원했고, 브레인스토밍 결과 다음 두 갈래로 진행하기로 확정했다:
- **Part A** (지금 실행): fake 대신 실제 SQLite로 storage+services 크로스레이어를 검증하는 통합 테스트를 지금 작성하고 통과시킨다.
- **Part B** (계획만): CLI/scheduler가 아직 없으므로 실행 불가. 병합 후 실행할 인수 테스트의 설계를 스펙 문서로 남겨 다른 세션이 CLI/scheduler를 끝냈을 때 바로 구현에 들어갈 수 있게 한다.

## Part A — 실제 SQLite 통합 테스트 (지금 구현)

### 위치 및 픽스처

- 신규 디렉터리 `tests/integration/` (`__init__.py` 추가)
- `tests/integration/conftest.py`에 `real_db` 픽스처 추가:
  - `connect_db(tmp_path / "test.db")` (`semi/storage/db.py:37`)로 실제 커넥션 생성 (WAL, schema init 포함)
  - `SampleRepository`/`OrderRepository`/`ProductionJobRepository`를 이 커넥션으로 생성
  - `threading.Lock()` 생성
  - `SampleService`, `OrderService`, `ProductionService`, `MonitoringService`를 실제로 조립해 dataclass 또는 namedtuple(`RealDB`)로 묶어 반환 — 각 테스트는 여기서 필요한 컴포넌트만 꺼내 쓴다

### 테스트 파일 및 시나리오

`tests/integration/test_order_lifecycle_sqlite.py` (파일 하나로 시작, 필요하면 이후 분리):

1. **해피패스 전체 라이프사이클** — `tests/test_lifecycle.py`의 시나리오를 실제 DB로 이관: RESERVED → approve(재고부족→PRODUCING) → tick()×2(강제로 `started_at`을 과거로 밀어 즉시 완료 처리, 기존 테스트와 동일 기법) → CONFIRMED → release() → RELEASE. 재고가 매 단계 기대값과 일치하는지 검증.
2. **재고 충분 시 즉시 CONFIRMED** — 사전에 `sample_repo.increment_stock`으로 충분한 재고를 만든 뒤 approve → CONFIRMED 즉시 전이, `job_repo.get_by_order_id`가 `NotFoundError`를 던짐(=job 미생성) 검증.
3. **거절 후 상태 잠금** — reject() → REJECTED. 이후 approve()/release() 호출 시 `DomainError` 발생, `samples.stock_quantity` 불변 검증.
4. **FIFO 큐 처리 순서** — 재고 0인 샘플에 대해 주문 2건을 모두 approve(둘 다 PRODUCING/큐잉). tick()으로 job1만 IN_PROGRESS로 승격됨을 확인 → job1을 완료 처리 → 다음 tick()에서 job2가 승격됨을 검증 (`enqueued_at`/`job_id` 순서 보장, `production_service.py:50` `_promote_if_idle`).
5. **available 재고 불변식** — 같은 샘플에 CONFIRMED 1건 + PRODUCING 1건이 공존하는 상태를 만들고, `stock_quantity >= sum(미출고 CONFIRMED 수량)`이 각 단계(승인 전/후, tick 전/후)에서 항상 유지되는지 검증 (`order_service.py:92` `_available_stock` 로직 자체가 아니라, 그 결과로 유지되는 DESIGN.md 핵심 불변식을 실제 DB 상태로 검증).
6. **큐잉된 job은 재계산되지 않음** — job이 QUEUED인 동안 다른 주문의 완료로 재고가 바뀌어도, 해당 job의 `actual_quantity`/`total_duration_seconds`가 최초 계산값 그대로인지 검증.
7. **재고 상태 분류(모니터링 연동)** — 실제 DB 위에서 `MonitoringService.stock_status()`가 `stock_quantity == 0` → DEPLETED, `stock_quantity >= outstanding` → SUFFICIENT, 그 외 → SHORT 순서로 정확히 분류하는지 각 케이스 별로 검증 (`monitoring_service.py:46`).

### 실행 및 검증

- `pip install -e ".[dev,test]"` 후 `pytest tests/integration -v`로 새 테스트만 우선 확인
- 이어서 `pytest`(전체) 및 `ruff check --fix . && ruff format .`로 회귀 없는지 확인
- 커밋 메시지는 Conventional Commits (`test: add real-SQLite integration tests for order lifecycle`)

## Part B — CLI/scheduler 인수 테스트 설계 문서 (실행은 CLI/scheduler 병합 후)

`docs/superpowers/specs/2026-07-15-acceptance-test-design.md`로 신규 스펙 문서를 작성하고 커밋한다 (근거 문서: `PRD.md`, `2026-07-15-cli-design.md`, `2026-07-15-scheduler-design.md`). 문서에는 다음 내용을 담는다 — **코드는 작성하지 않고, CLI/scheduler가 main에 병합된 뒤 별도 세션에서 이 문서를 기반으로 writing-plans를 거쳐 구현**:

### 테스트 하네스 설계

- `tests/acceptance/conftest.py`에 `app_context` 픽스처: `semi/cli/app.py`의 조립 로직(실제 SQLite + 4개 서비스 + 5개 Controller)을 그대로 재현하되, 백그라운드 워커(`start_worker`)는 대부분의 테스트에서 실행하지 않고 `production_service.tick()`을 테스트 코드가 직접 호출해 결정론적으로 제어한다.
- 사용자 입력 스크립팅: `controllers.py`가 `views.*` 함수를 모듈 속성으로 직접 호출하는 구조이므로(`views.render_sample_menu()` 형태, 의존성 주입 아님), `unittest.mock.patch("semi.cli.views.<함수명>", side_effect=[...])`로 메뉴 선택/입력 시퀀스를 스크립팅한다. `main_loop`의 `render_main_menu`만 파라미터로 주입되므로(`menu_loop.py`), 메인 루프 자체를 검증하는 테스트는 순수 함수(`lambda labels: "exit"` 등)를 직접 넘긴다.
- 최종 상태 검증은 원칙적으로 서비스/리포지토리 조회로 하고(예: `order_repo.get_by_id(...).status`), 화면 출력 검증이 필요한 경우(에러 메시지 등)만 `views.render_*`를 patch해 호출 인자를 캡처한다.

### PRD 4.1~4.7 메뉴별 시나리오 (해피패스)

1. 시료 등록 → 목록 조회 → 이름 검색 (`SampleMenuController`)
2. 주문 접수(RESERVED) → 미결 주문 목록 조회 → 승인(재고 충분/부족 두 경로 모두) (`OrderMenuController`)
3. 모니터링: 상태별 주문 건수, 재고 현황(여유/부족/고갈) 조회 (`MonitoringMenuController`)
4. 생산 현황(진행률/완료 예정 시각) 및 큐 조회 (`ProductionMenuController`)
5. CONFIRMED 목록 조회 → 출고 실행 (`ReleaseMenuController`)

### 에러/예외 경로 시나리오

- 잘못된 메인 메뉴 입력(숫자 아님/범위 초과) → 크래시 없이 재입력 요구 (`menu_loop.py` §2.1 fail-safe)
- 서브메뉴에서 인식 불가 입력 → `"back"`으로 안전 처리
- `DomainError`/`NotFoundError`가 `main_loop`의 단일 catch 지점에서 잡혀 각각 `[오류]`/`[조회 실패]` 메시지로 출력되고 루프가 죽지 않고 계속됨을 검증

### 전용 동시성(스케줄러) 인수 테스트 1건

- 실제 `start_worker(db_path, lock)` 데몬 스레드를 띄우고, 메인 스레드에서는 CLI 컨트롤러를 통해 주문 생성/승인을 수행한다.
- 실시간 1초 대기 대신, 기존 서비스 테스트에서 쓰인 기법(`avg_production_seconds`를 작게 설정하거나 `job_repo.mark_in_progress`로 `started_at`을 과거로 미리 이동)을 활용하고, 완료 여부는 짧은 간격(예: 0.05~0.1초)으로 최대 수 초까지 폴링해 확인한다 — 실제 sleep(1) 루프를 그대로 기다리는 테스트는 피한다.
- 검증 목표: 메인 스레드(CLI)와 백그라운드 워커가 같은 `threading.Lock`으로 쓰기를 직렬화해, 두 스레드가 동시에 같은 주문/재고를 건드려도 DESIGN.md의 오버셀 방지 불변식이 깨지지 않는다.

### 문서 self-review 체크리스트 (작성 시 반영)

- TBD/placeholder 없이 전부 구체적으로 기술
- CLI 설계 문서(§2, §2.1, §4)의 fail-safe 원칙과 모순되지 않는지 교차 확인
- 이 스펙만으로 별도 질문 없이 구현 계획(writing-plans)에 들어갈 수 있는 수준인지 확인

## 실행 순서 요약

1. Part A 테스트 코드 작성 → 실행 통과 확인 → 커밋
2. Part B 스펙 문서 작성 → 커밋 (CLI/scheduler 병합 전이므로 코드 작성 없음)
3. (이후 별도 세션) CLI/scheduler가 main에 병합되면, Part B 스펙을 입력으로 writing-plans → 구현
