# PoC 결과 반영 제안 — `storage-design.md` / `services-design.md` 개선점

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | `2026-07-15-persistence-poc-design.md`를 구현하며 실제로 드러난, `2026-07-15-storage-design.md`/`2026-07-15-services-design.md`에 반영하면 좋을 개선점 정리 |
| 근거 | Sample+Order PoC 구현(`domain/`, `storage/`, `services/`, `demo.py`, `tests/`) 및 task별 리뷰 + 최종 전체 브랜치 리뷰 결과 |
| 작성일 | 2026-07-15 |

---

## 1. `storage-design.md` 4절 예제 코드 자체에 트랜잭션 레이스 버그가 있음 (가장 중요)

`storage-design.md` 70~80행의 `approve()` 예제:

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

마지막 `return self._order_repo.get_by_id(order_id)`가 **`with self._lock:` 블록 밖**에 있다. PoC에서 `OrderService`를 이 패턴 그대로 구현했더니(Task 7), 최종 리뷰에서 다음 문제가 지적되어 별도 커밋(`4c66b15`)으로 수정했다:

- lock이 해제된 직후 다른 스레드가 동일 `order_id`에 대해 새 쓰기 트랜잭션을 커밋하면, 이 메서드는 자신이 방금 커밋한 상태가 아니라 그 **나중** 트랜잭션의 상태를 반환할 수 있다.
- 불필요한 DB 왕복이 매 호출마다 발생한다.

**제안:** 4절 예제의 `return`을 `try` 블록 안, `self._conn.commit()` 바로 다음으로 옮겨서 lock을 쥔 채로 반환하도록 수정.

```python
def approve(self, order_id: int) -> Order:
    with self._lock:
        try:
            ...  # 여러 repository 호출
            self._conn.commit()
            return self._order_repo.get_by_id(order_id)
        except Exception:
            self._conn.rollback()
            raise
```

이 문서가 향후 다른 서비스 메서드(예: `ProductionService.tick()`) 구현의 참조 템플릿 역할을 하므로, 예제 자체의 수정이 없으면 이 레이스가 반복적으로 복제될 위험이 있다.

## 2. `conn` 소유권이 두 문서 사이에서 불일치함

- `storage-design.md` 3절은 각 Repository가 `conn`을 생성자로 받는다고만 서술하고, 그 `conn`을 Service가 어떻게 참조해 commit/rollback을 호출하는지는 명시하지 않는다.
- 그런데 같은 문서 4절 예제는 `self._conn.commit()`처럼 **Service 자신이 `conn`을 직접 들고 있다**고 가정한다.
- 반면 `services-design.md` 4절의 `OrderService(order_repo, job_repo, sample_repo, lock)` 생성자 시그니처에는 `conn` 파라미터가 없다.

즉 "Service가 트랜잭션을 커밋한다"는 원칙은 두 문서 모두 명확하지만, **그 commit을 호출할 `conn`을 Service가 어디서 얻는지**가 두 문서 사이에서 서로 다르게 암시되어 있다. PoC에서는 이 간극을 메우기 위해 Repository의 `conn`을 `self.conn`(public 속성)으로 노출하고, Service가 `self._order_repo.conn.commit()` 형태로 접근하는 방식을 택했다(별도 `conn` 생성자 인자 없이 기존 시그니처 유지 가능).

**제안:** `storage-design.md` 3절에 "Repository의 `conn`은 public 속성으로 노출하며, Service는 이 속성을 통해 commit/rollback을 호출한다"는 문장과 `self.conn = conn` 한 줄을 명시적으로 추가. `services-design.md` 4절에도 "Service는 자신이 소유한 repository 중 하나의 `.conn`을 통해 커밋한다(별도 `conn` 인자를 받지 않는다)"는 문장을 추가해 두 문서가 같은 결론을 가리키도록 정합성을 맞추는 것을 제안.

## 3. "여러 repository가 동일 connection을 공유해야 한다"는 불변식이 문서화되어 있지 않음

`services-design.md` 4절의 `approve()`는 `order_repo`와 `sample_repo`를 함께 사용하고, 최종적으로 한 번만 커밋한다. 이 원자성 보장은 **두 repository가 동일한 `sqlite3.Connection` 인스턴스 위에서 생성되었을 때만** 성립하는데, 이 전제조건이 어느 문서에도 명시돼 있지 않다.

PoC에서는 이 불변식이 조용히 깨질 수 있다는 점을 최종 리뷰에서 지적받아, `OrderService.__init__`에 다음 한 줄을 추가했다(`4c66b15`):

```python
assert order_repo.conn is sample_repo.conn, "OrderRepository and SampleRepository must share the same connection"
```

**제안:** `services-design.md` 2절(Lock 공유) 또는 4절에 "같은 Service가 사용하는 모든 repository는 동일한 `conn`으로 생성되어야 하며, 생성자에서 이를 assert로 검증한다"는 규칙을 명문화.

## 4. `SCHEMA_SQL`이 실제로 정의되어 있지 않음

`storage-design.md` 16~22행의 `connect_db` 예제는 `conn.executescript(SCHEMA_SQL)`을 호출하지만, `SCHEMA_SQL`이 무엇인지(테이블 컬럼, `CHECK` 제약)는 이 문서에 없다. `services-design.md` 1절은 "DB의 `CHECK` 제약(storage 설계 문서 스키마)"을 언급하며 defense-in-depth 근거로 삼지만, 정작 그 스키마의 실제 정의는 어느 문서에도 없다.

PoC에서는 `avg_production_seconds > 0`, `yield_rate > 0 AND yield_rate <= 1`, `quantity > 0` 세 개의 `CHECK` 제약을 직접 설계해 채워 넣었다(`storage/db.py`).

**제안:** `storage-design.md`에 `SCHEMA_SQL` 전문(각 테이블의 컬럼, PK, FK, `CHECK` 제약)을 별도 섹션으로 추가해, "services 검증과 DB CHECK가 중복되지만 역할이 다르다"는 `services-design.md` 1절의 설명이 실제로 무엇을 가리키는지 확인 가능하게 할 것을 제안.

## 5. Lock/동시성 검증 전략에 대한 가이드가 없음

두 문서 모두 "쓰기 트랜잭션을 `Lock`으로 직렬화한다"는 설계는 명확히 규정하지만, 이를 어떻게 테스트로 검증하는지에 대한 언급은 없다. PoC에서 유효했던 검증 패턴 두 가지:

- **동시성 테스트**: 스레드마다 `connect_db()`로 자신만의 connection을 새로 만들고(1절의 "스레드당 1세트" 원칙 그대로), 하나의 `threading.Lock` 인스턴스만 공유하게 한 뒤, 동일 자원(재고)에 대해 경합하는 두 요청을 동시에 실행해 정확히 하나만 성공하는지 확인.
- **롤백 테스트**: 다중 repository 호출 중 두 번째 호출을 몽키패치로 실패시켜, 첫 번째 호출의 변경분까지 함께 롤백되는지(원자성) 확인.

**제안:** `services-design.md` 2절(Lock 공유) 끝에 "구현 시 위 두 시나리오(동시 요청 직렬화, 다중 repo 호출의 원자적 롤백)를 테스트로 검증할 것"이라는 짧은 검증 가이드를 추가.

## 6. `NotFoundError`가 rollback 경로에서도 그대로 전파되어야 함이 암묵적으로만 성립

`services-design.md` 1절은 "`storage.NotFoundError`는 변환 없이 그대로 전파된다"고 명시하지만, `storage-design.md` 4절의 `except Exception: rollback(); raise` 패턴과 결합했을 때 이것이 실제로 성립하는지(즉 `get_by_id`가 트랜잭션 도중 `NotFoundError`를 던져도 타입이 보존된 채 rollback 후 재전파되는지)는 명시적으로 다뤄지지 않는다. PoC에서 이 조합이 의도대로 동작함을 테스트로 직접 확인했다(`test_approve_missing_order_propagates_not_found_error`).

**제안:** `storage-design.md` 4절에 "이 `except Exception` 블록은 `NotFoundError`를 포함한 모든 예외 타입을 보존한 채 재전파한다(bare `raise` 사용, 특정 예외 타입을 잡아 변환하지 않음)"는 한 문장을 덧붙여 두 문서의 원칙이 실제 예제 코드에서 어떻게 만나는지 명확히 할 것을 제안.

---

## 요약

| # | 대상 문서 | 제안 |
|---|---|---|
| 1 | storage-design.md 4절 | 예제의 `return`을 lock 안으로 이동 (레이스 버그 수정) |
| 2 | storage-design.md 3절, services-design.md 4절 | `conn`을 Repository의 public 속성으로 노출한다고 명시, 두 문서 정합성 확보 |
| 3 | services-design.md 2절/4절 | 같은 Service의 모든 repository는 동일 `conn` 공유를 assert로 검증 |
| 4 | storage-design.md | `SCHEMA_SQL` 전문(CHECK 제약 포함) 추가 |
| 5 | services-design.md 2절 | Lock/롤백 검증을 위한 테스트 가이드 추가 |
| 6 | storage-design.md 4절 | `except Exception` 블록이 예외 타입을 보존한 채 재전파함을 명시 |
