# 상세 아키텍처 설계 — `semi/cli`

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | `PRD.md`/`DESIGN.md`가 상위 수준에서 확정한 내용을 `semi/cli` 레이어의 실제 구현 가능한 수준(진입점, 메뉴 루프, 에러 처리, 종료 처리)까지 구체화 |
| 근거 문서 | `PRD.md`, `DESIGN.md`, [`2026-07-15-services-design.md`](2026-07-15-services-design.md), [`2026-07-15-scheduler-design.md`](2026-07-15-scheduler-design.md) |
| 작성일 | 2026-07-15 |

---

## 1. `app.py` — 진입점

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

## 2. `menus.py` — 메뉴 렌더링 및 입력 처리

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

## 3. 예외 처리 지점 — 단일 지점 catch

`DomainError`/`storage.NotFoundError`는 개별 메뉴 핸들러(`handle_sample_menu`, `handle_order_menu`, `handle_monitoring_menu`, `handle_release_menu`, `handle_production_menu`)가 아니라 `main_loop`의 `dispatch()` 호출 지점 **한 곳**에서만 잡는다. 각 핸들러는 서비스 메서드를 호출하고 결과를 렌더링할 뿐, 에러 처리 코드를 반복해서 갖지 않는다.

## 4. 종료 처리

콘솔 앱은 메인 메뉴의 "종료" 항목으로 정상 종료한다 (`main_loop`가 break). `Ctrl+C`(`KeyboardInterrupt`)도 동일하게 처리해 깨끗이 종료되도록 한다. 두 경우 모두 `finally` 블록에서 메인 스레드의 `conn.close()`를 명시적으로 호출한다. 백그라운드 워커 스레드는 daemon이므로 별도 종료 처리 없이 프로세스 종료와 함께 정리된다.
