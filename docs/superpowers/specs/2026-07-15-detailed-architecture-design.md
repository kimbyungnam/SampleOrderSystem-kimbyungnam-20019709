# 상세 소프트웨어 아키텍처 설계

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | `PRD.md`/`DESIGN.md`가 상위 수준에서 확정한 내용을 실제 구현 가능한 수준(모듈 API, 함수 시그니처, 예외 처리 등)까지 구체화 |
| 근거 문서 | `PRD.md`, `DESIGN.md` |
| 작성일 | 2026-07-15 |
| 범위 | `semi/domain`, `semi/storage`, `semi/services`, `semi/scheduler`, `semi/cli` 레이어를 의존성 순서(domain → storage → services → scheduler → cli)로 설계 |

---

## 1. `semi/domain` — 도메인 모델

### 1.1 Enum

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

`StrEnum`(Python 3.14+)을 사용해 DB의 `CHECK (status IN (...))` 문자열 값과 1:1로 매칭시킨다 (`str, Enum` 다중 상속 대신).

### 1.2 데이터클래스

모두 `@dataclass(frozen=True)`이며 필드 외의 어떤 로직(검증, 상태 전이 규칙)도 갖지 않는 순수 데이터(anemic) 컨테이너다. 검증/전이 규칙은 전부 `services` 레이어 책임이다.

```python
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

### 1.3 설계 결정

- **불변(frozen)**: 상태 전이는 services가 DB에서 새로 읽은 값으로 새 객체를 만들거나 `dataclasses.replace()`로 처리한다. 멀티스레드 환경에서 공유 객체를 실수로 무통제 수정하는 버그를 구조적으로 차단하기 위함.
- **시각 필드는 `datetime` 객체**: DB에는 ISO8601 TEXT로 저장되지만, 도메인/서비스 레이어는 `datetime`을 사용해 날짜 연산(경과시간, 비교)을 타입 안전하게 다룬다. 문자열 ↔ `datetime` 변환은 `storage` 레이어(repository)가 전담한다.
- **`order_id`/`job_id`는 항상 필수(`int`, Optional 아님)**: 아직 DB에 없는 미저장 객체를 표현할 필요가 없도록, repository가 INSERT 후 자동 채번된 id를 포함한 완전한 도메인 객체만 반환한다. 호출부는 id 없는 반쪽 객체를 다루지 않는다.

---

## 2. `semi/storage` — 저장소 레이어

### 2.1 연결 관리 — 명시적 DI, 스레드당 1세트

```python
def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA_SQL)  # CREATE TABLE IF NOT EXISTS ...
    return conn
```

`threading.local` 같은 전역 상태 없이, 각 스레드(메인 스레드, 백그라운드 워커 스레드)가 시작 시점에 직접 `connect_db()`를 호출해 자신만의 `Connection`을 만들고, 그 위에 자신만의 Repository/Service 인스턴스 세트를 구성한다. `cli/app.py`는 메인용 서비스 세트를, `scheduler/background_worker.py`는 자체 `ProductionService` 세트를 구성한다.

### 2.2 예외 — `storage/exceptions.py`

```python
class NotFoundError(Exception):
    """id로 조회했으나 대상 row가 없을 때 발생."""
```

`get_by_id` 계열은 `None`을 반환하지 않고 항상 도메인 객체를 반환하거나 `NotFoundError`를 raise한다 (호출부에서 None 체크가 사라짐).

### 2.3 Repository별 메서드

각 repository는 `conn.execute()`만 수행하고 **절대 commit/rollback하지 않는다** — 트랜잭션 경계는 전적으로 호출하는 Service가 소유한다 (2.4절 참조). 집계 쿼리는 순수 데이터 조회만 담당하며, "가용 재고" 같은 비즈니스 공식은 전혀 포함하지 않는다 (services 레이어 100% 소유).

**`sample_repository.py` — `SampleRepository(conn)`**
- `create(sample_id, name, avg_production_seconds, yield_rate) -> Sample` (초기 재고 0으로 INSERT)
- `get_by_id(sample_id) -> Sample` (없으면 `NotFoundError`)
- `exists(sample_id) -> bool`
- `list_all() -> list[Sample]`
- `search_by_name(query) -> list[Sample]`
- `increment_stock(sample_id, amount) -> None` (생산 완료 시)
- `decrement_stock(sample_id, amount) -> None` (출고 시)

**`order_repository.py` — `OrderRepository(conn)`**
- `create(sample_id, customer_name, quantity) -> Order` (status=RESERVED, created_at=now)
- `get_by_id(order_id) -> Order` (없으면 `NotFoundError`)
- `list_by_status(status) -> list[Order]`
- `update_status(order_id, status) -> None`
- `sum_quantity_by_status(sample_id, status) -> int` (단일 상태 합계 — CONFIRMED 합계 계산용)
- `sum_quantity_by_statuses(sample_id, statuses) -> int` (다중 상태 합계 — 모니터링 outstanding 계산용)

**`production_job_repository.py` — `ProductionJobRepository(conn)`**
- `create(order_id, sample_id, shortfall_quantity, actual_quantity, total_duration_seconds) -> ProductionJob` (status=QUEUED, enqueued_at=now)
- `get_by_order_id(order_id) -> ProductionJob`
- `list_producing_with_shortfall(sample_id) -> list[tuple[int, int]]` (해당 시료의 PRODUCING 주문들의 `(quantity, shortfall_quantity)` 원시 쌍 — `orders` JOIN, 가공 없음)
- `get_current_in_progress() -> ProductionJob | None`
- `list_queued_fifo() -> list[ProductionJob]` (`enqueued_at`, tie-break `job_id`)
- `mark_in_progress(job_id, started_at) -> None`
- `mark_done(job_id) -> None`

### 2.4 트랜잭션 커밋 — Service 책임

Repository 메서드는 `conn.execute()`만 하고 커밋하지 않는다. 여러 repository 호출로 구성된 하나의 비즈니스 트랜잭션(예: `OrderService.approve()`의 상태 변경 + 생산 작업 INSERT)은 Service가 `threading.Lock`으로 감싼 뒤 마지막에 단 한 번 `conn.commit()`을 호출해 원자성을 보장한다. 예외 발생 시 `conn.rollback()`.

```python
def approve(self, order_id: int) -> Order:
    with self._lock:
        try:
            ...  # 여러 repository 호출
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
    return self._order_repo.get_by_id(order_id)
```

---

## 3. `semi/services` — 도메인 서비스 레이어

### 3.1 예외 — `services/exceptions.py`

```python
class DomainError(Exception):
    """PRD/DESIGN이 명시한 도메인 규칙(검증 또는 상태 전이) 위반 시 raise."""
```

검증 실패(`yield_rate` 범위 위반, `quantity <= 0`, 존재하지 않는 `sample_id` 등)와 상태 전이 오류(`RESERVED`가 아닌 주문 승인/거절 시도, `CONFIRMED`가 아닌 주문 출고 시도 등)를 하나의 `DomainError`로 표현한다 — 둘 다 PRD/DESIGN이 명시한 "도메인 규칙" 위반이라는 점에서 같은 범주이기 때문이다.

`storage.NotFoundError`는 도메인 규칙 위반이 아닌 단순 조회 실패이므로 변환 없이 그대로 전파된다.

services의 검증(예: `quantity > 0`, `0 < yield_rate <= 1`)은 DB의 `CHECK` 제약(2절 스키마)과 내용상 겹치지만 역할이 다르다: services 검증은 친절한 `DomainError` 메시지를 사용자에게 보여주기 위한 1차 방어선이고, DB `CHECK`는 구현 버그로 그 검증이 우회되더라도 잘못된 값이 조용히 저장되지 않도록 하는 최종 방어선(defense-in-depth)이다. 두 계층 모두 유지한다.

### 3.2 Lock 공유

쓰기 트랜잭션(승인/거절/출고/tick)을 직렬화하는 `threading.Lock`은 `cli/app.py`(진입점)가 단 하나만 생성해, 메인 스레드의 `OrderService` 등과 백그라운드 워커 스레드의 `ProductionService`에 동일한 객체로 주입한다. 서비스는 생성자로 이 `Lock`을 받아 각 쓰기 메서드에서 `with self._lock:`으로 감싼다.

### 3.3 `sample_service.py` — `SampleService(sample_repo)`

- `register(sample_id, name, avg_production_seconds, yield_rate) -> Sample` — `avg_production_seconds > 0`, `0 < yield_rate <= 1`, 중복 `sample_id` 아님을 검증 (위반 시 `DomainError`)
- `list_all() -> list[Sample]`
- `search_by_name(query) -> list[Sample]`

### 3.4 `order_service.py` — `OrderService(order_repo, job_repo, sample_repo, lock)`

- `create_order(sample_id, customer_name, quantity) -> Order` — `quantity > 0`, `sample_id` 존재 검증
- `approve(order_id) -> Order` — `lock` 내부: `RESERVED` 아니면 `DomainError`; 가용재고 계산 후 `CONFIRMED` 또는 (부족분 계산 + `production_jobs` 등록 + `PRODUCING`) 분기; 커밋
- `reject(order_id) -> Order` — `RESERVED` 아니면 `DomainError`; `REJECTED`로 전환
- `release(order_id) -> Order` — `CONFIRMED` 아니면 `DomainError`; 재고 차감 + `RELEASE`로 전환

`approve`의 가용재고 계산은 전적으로 이 메서드 내부에서 조립된다 (2.3절 repository는 원시 데이터만 제공):

```python
def _available_stock(self, sample: Sample) -> int:
    confirmed_sum = self._order_repo.sum_quantity_by_status(sample.sample_id, OrderStatus.CONFIRMED)
    producing_reserved_sum = sum(
        qty - shortfall
        for qty, shortfall in self._job_repo.list_producing_with_shortfall(sample.sample_id)
    )
    return sample.stock_quantity - confirmed_sum - producing_reserved_sum
```

### 3.5 `production_service.py`

```python
@dataclass(frozen=True)
class ProductionJobStatus:
    job: ProductionJob
    progress_ratio: float           # min(1, elapsed / total_duration_seconds)
    produced_so_far: int            # floor(progress_ratio * actual_quantity)
    estimated_completion_at: datetime
```

`ProductionService(order_repo, job_repo, sample_repo, lock)`
- `tick() -> None` — DESIGN.md 4.2절 그대로: `QUEUED`→`IN_PROGRESS` 승격, 완료 판정 시 재고 증가 + 주문 `CONFIRMED` 전환 + 다음 작업 승격
- `get_current_status() -> ProductionJobStatus | None`
- `list_queue_status() -> list[ProductionJobStatus]` — 대기열은 앞선 작업들의 남은 시간을 누적해 `estimated_completion_at` 계산

### 3.6 `monitoring_service.py` — `MonitoringService(order_repo, sample_repo)`

```python
class StockStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    SHORT = "SHORT"
    DEPLETED = "DEPLETED"

@dataclass(frozen=True)
class SampleStockStatus:
    sample: Sample
    outstanding: int
    status: StockStatus
```

- `count_by_status() -> dict[OrderStatus, int]` — `RESERVED`/`CONFIRMED`/`PRODUCING`/`RELEASE`만 집계 (`REJECTED` 제외, PRD 4.5)
- `list_by_status(status) -> list[Order]`
- `stock_status() -> list[SampleStockStatus]` — 시료별 `outstanding` 계산 후 규칙 14 순서(재고=0 → 고갈, 재고>=outstanding → 여유, 그 외 → 부족)로 판정

`StockStatus`는 영문 멤버로 두고, 한글 표시("여유"/"부족"/"고갈")는 `cli` 레이어가 매핑한다 — services는 로케일에 독립적으로 유지한다.

---

## 4. `semi/scheduler` — 백그라운드 워커

**`background_worker.py`**

```python
def start_worker(db_path: Path, lock: threading.Lock) -> threading.Thread:
    def _run() -> None:
        conn = connect_db(db_path)  # 이 스레드 전용 연결
        prod_svc = ProductionService(
            OrderRepository(conn), ProductionJobRepository(conn), SampleRepository(conn), lock
        )
        while True:
            try:
                prod_svc.tick()
            except Exception:
                traceback.print_exc()  # 로깅 후 계속 진행 — 일시적 오류로 생산 시뮬레이션 전체가 멈추지 않게 함
            time.sleep(1)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
```

`start_worker`는 `cli/app.py`가 생성한 `Lock`을 그대로 전달받아, `OrderService`(메인 스레드)와 동일한 락으로 쓰기 트랜잭션을 직렬화한다. daemon 스레드이므로 프로세스 종료 시 자동으로 정리된다.

---

## 5. `semi/cli` — 콘솔 UI

### 5.1 `app.py` — 진입점

```python
def main() -> None:
    conn = connect_db(db_path)
    lock = threading.Lock()

    sample_repo = SampleRepository(conn)
    order_repo = OrderRepository(conn)
    job_repo = ProductionJobRepository(conn)

    services = {
        "sample": SampleService(sample_repo),
        "order": OrderService(order_repo, job_repo, sample_repo, lock),
        "production": ProductionService(order_repo, job_repo, sample_repo, lock),
        "monitoring": MonitoringService(order_repo, sample_repo),
    }

    start_worker(db_path, lock)

    try:
        main_loop(services)  # 메뉴에서 '종료' 선택 시 루프 break
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        conn.close()
```

### 5.2 `menus.py` — 메뉴 렌더링 및 입력 처리

```python
def main_loop(services: dict) -> None:
    while True:
        choice = render_main_menu()  # 시료관리 / 주문접수·승인·거절 / 모니터링 / 출고처리 / 생산라인 / 종료
        if choice == "exit":
            break
        try:
            dispatch(choice, services)
        except DomainError as e:
            print(f"[오류] {e}")
        except NotFoundError as e:
            print(f"[조회 실패] {e}")


def dispatch(choice: str, services: dict) -> None:
    ...  # PRD 4.1~4.7 각 메뉴 핸들러로 라우팅
```

### 5.3 예외 처리 지점 — 단일 지점 catch

`DomainError`/`storage.NotFoundError`는 개별 메뉴 핸들러(`handle_sample_menu`, `handle_order_menu`, `handle_monitoring_menu`, `handle_release_menu`, `handle_production_menu`)가 아니라 `main_loop`의 `dispatch()` 호출 지점 **한 곳**에서만 잡는다. 각 핸들러는 서비스 메서드를 호출하고 결과를 렌더링할 뿐, 에러 처리 코드를 반복해서 갖지 않는다.

### 5.4 종료 처리

콘솔 앱은 메인 메뉴의 "종료" 항목으로 정상 종료한다 (`main_loop`가 break). `Ctrl+C`(`KeyboardInterrupt`)도 동일하게 처리해 깨끗이 종료되도록 한다. 두 경우 모두 `finally` 블록에서 메인 스레드의 `conn.close()`를 명시적으로 호출한다. 백그라운드 워커 스레드는 daemon이므로 별도 종료 처리 없이 프로세스 종료와 함께 정리된다.
