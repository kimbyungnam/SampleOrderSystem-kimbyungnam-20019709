# 상세 아키텍처 설계 — `semi/services`

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | `PRD.md`/`DESIGN.md`가 상위 수준에서 확정한 내용을 `semi/services` 레이어의 실제 구현 가능한 수준(서비스 메서드 시그니처, 예외 체계, Lock/트랜잭션 소유권)까지 구체화 |
| 근거 문서 | `PRD.md`, `DESIGN.md`, [`2026-07-15-domain-design.md`](2026-07-15-domain-design.md), [`2026-07-15-storage-design.md`](2026-07-15-storage-design.md) |
| 작성일 | 2026-07-15 |

---

## 1. 예외 — `services/exceptions.py`

```python
class DomainError(Exception):
    """PRD/DESIGN이 명시한 도메인 규칙(검증 또는 상태 전이) 위반 시 raise."""
```

검증 실패(`yield_rate` 범위 위반, `quantity <= 0`, 존재하지 않는 `sample_id` 등)와 상태 전이 오류(`RESERVED`가 아닌 주문 승인/거절 시도, `CONFIRMED`가 아닌 주문 출고 시도 등)를 하나의 `DomainError`로 표현한다 — 둘 다 PRD/DESIGN이 명시한 "도메인 규칙" 위반이라는 점에서 같은 범주이기 때문이다.

`storage.NotFoundError`는 도메인 규칙 위반이 아닌 단순 조회 실패이므로 변환 없이 그대로 전파된다.

services의 검증(예: `quantity > 0`, `0 < yield_rate <= 1`)은 DB의 `CHECK` 제약(storage 설계 문서 스키마)과 내용상 겹치지만 역할이 다르다: services 검증은 친절한 `DomainError` 메시지를 사용자에게 보여주기 위한 1차 방어선이고, DB `CHECK`는 구현 버그로 그 검증이 우회되더라도 잘못된 값이 조용히 저장되지 않도록 하는 최종 방어선(defense-in-depth)이다. 두 계층 모두 유지한다.

## 2. Lock 공유

쓰기 트랜잭션(승인/거절/출고/tick)을 직렬화하는 `threading.Lock`은 `cli/app.py`(진입점)가 단 하나만 생성해, 메인 스레드의 `OrderService` 등과 백그라운드 워커 스레드의 `ProductionService`에 동일한 객체로 주입한다. 서비스는 생성자로 이 `Lock`을 받아 각 쓰기 메서드에서 `with self._lock:`으로 감싼다.

## 3. `sample_service.py` — `SampleService(sample_repo)`

- `register(sample_id, name, avg_production_seconds, yield_rate) -> Sample` — `avg_production_seconds > 0`, `0 < yield_rate <= 1`, 중복 `sample_id` 아님을 검증 (위반 시 `DomainError`)
- `list_all() -> list[Sample]`
- `search_by_name(query) -> list[Sample]`

## 4. `order_service.py` — `OrderService(order_repo, job_repo, sample_repo, lock)`

- `create_order(sample_id, customer_name, quantity) -> Order` — `quantity > 0`, `sample_id` 존재 검증
- `approve(order_id) -> Order` — `lock` 내부: `RESERVED` 아니면 `DomainError`; 가용재고 계산 후 `CONFIRMED` 또는 (부족분 계산 + `production_jobs` 등록 + `PRODUCING`) 분기; 커밋
- `reject(order_id) -> Order` — `RESERVED` 아니면 `DomainError`; `REJECTED`로 전환
- `release(order_id) -> Order` — `CONFIRMED` 아니면 `DomainError`; 재고 차감 + `RELEASE`로 전환

`approve`의 가용재고 계산은 전적으로 이 메서드 내부에서 조립된다 (storage 설계 문서의 repository는 원시 데이터만 제공):

```python
def _available_stock(self, sample: Sample) -> int:
    confirmed_sum = self._order_repo.sum_quantity_by_status(sample.sample_id, OrderStatus.CONFIRMED)
    producing_reserved_sum = sum(
        qty - shortfall
        for qty, shortfall in self._job_repo.list_producing_with_shortfall(sample.sample_id)
    )
    return sample.stock_quantity - confirmed_sum - producing_reserved_sum
```

## 5. `production_service.py`

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

## 6. `monitoring_service.py` — `MonitoringService(order_repo, sample_repo)`

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
