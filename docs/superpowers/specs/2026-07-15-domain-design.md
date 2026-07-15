# 상세 아키텍처 설계 — `semi/domain`

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | `PRD.md`/`DESIGN.md`가 상위 수준에서 확정한 내용을 `semi/domain` 레이어의 실제 구현 가능한 수준(데이터클래스 필드, 타입, 설계 결정)까지 구체화 |
| 근거 문서 | `PRD.md`, `DESIGN.md` |
| 작성일 | 2026-07-15 |

---

## 1. Enum

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

## 2. 데이터클래스

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

## 3. 설계 결정

- **불변(frozen)**: 상태 전이는 services가 DB에서 새로 읽은 값으로 새 객체를 만들거나 `dataclasses.replace()`로 처리한다. 멀티스레드 환경에서 공유 객체를 실수로 무통제 수정하는 버그를 구조적으로 차단하기 위함.
- **시각 필드는 `datetime` 객체**: DB에는 ISO8601 TEXT로 저장되지만, 도메인/서비스 레이어는 `datetime`을 사용해 날짜 연산(경과시간, 비교)을 타입 안전하게 다룬다. 문자열 ↔ `datetime` 변환은 `storage` 레이어(repository)가 전담한다.
- **`order_id`/`job_id`는 항상 필수(`int`, Optional 아님)**: 아직 DB에 없는 미저장 객체를 표현할 필요가 없도록, repository가 INSERT 후 자동 채번된 id를 포함한 완전한 도메인 객체만 반환한다. 호출부는 id 없는 반쪽 객체를 다루지 않는다.
