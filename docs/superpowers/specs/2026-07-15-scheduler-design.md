# 상세 아키텍처 설계 — `semi/scheduler`

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | `PRD.md`/`DESIGN.md`가 상위 수준에서 확정한 내용을 `semi/scheduler` 레이어의 실제 구현 가능한 수준(백그라운드 워커 API, 예외 처리)까지 구체화 |
| 근거 문서 | `PRD.md`, `DESIGN.md`, [`2026-07-15-storage-design.md`](2026-07-15-storage-design.md), [`2026-07-15-services-design.md`](2026-07-15-services-design.md) |
| 작성일 | 2026-07-15 |

---

## `background_worker.py`

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
