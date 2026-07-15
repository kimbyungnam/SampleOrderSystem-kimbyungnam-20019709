# 상세 아키텍처 설계 — `semi/storage`

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | `PRD.md`/`DESIGN.md`가 상위 수준에서 확정한 내용을 `semi/storage` 레이어의 실제 구현 가능한 수준(연결 관리, repository 메서드 시그니처, 예외, 트랜잭션 경계)까지 구체화 |
| 근거 문서 | `PRD.md`, `DESIGN.md`, [`2026-07-15-domain-design.md`](2026-07-15-domain-design.md) |
| 작성일 | 2026-07-15 |

---

## 1. 연결 관리 — 명시적 DI, 스레드당 1세트

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

## 2. 예외 — `storage/exceptions.py`

```python
class NotFoundError(Exception):
    """id로 조회했으나 대상 row가 없을 때 발생."""
```

`get_by_id` 계열은 `None`을 반환하지 않고 항상 도메인 객체를 반환하거나 `NotFoundError`를 raise한다 (호출부에서 None 체크가 사라짐).

## 3. Repository별 메서드

각 repository는 `conn.execute()`만 수행하고 **절대 commit/rollback하지 않는다** — 트랜잭션 경계는 전적으로 호출하는 Service가 소유한다 (4절 참조). 집계 쿼리는 순수 데이터 조회만 담당하며, "가용 재고" 같은 비즈니스 공식은 전혀 포함하지 않는다 (services 레이어 100% 소유).

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

## 4. 트랜잭션 커밋 — Service 책임

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
