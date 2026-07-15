# 상세 아키텍처 설계 — `semi/cli`

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | `PRD.md`/`DESIGN.md`가 상위 수준에서 확정한 내용을 `semi/cli` 레이어의 실제 구현 가능한 수준(진입점, 메뉴 루프, 에러 처리, 종료 처리)까지 구체화. 이번 개정에서는 향후 메뉴/기능 확장을 쉽게 하기 위해 MVC(Model-View-Controller) 패턴으로 레이어를 재구성한다 |
| 근거 문서 | `PRD.md`, `DESIGN.md`, [`2026-07-15-services-design.md`](2026-07-15-services-design.md), [`2026-07-15-scheduler-design.md`](2026-07-15-scheduler-design.md) |
| 작성일 | 2026-07-15 |

---

## 0. MVC 적용 범위

Model은 이미 `semi/domain`(엔티티/enum)과 `semi/services`(도메인 규칙, 트랜잭션)가 담당하고 있으므로 그대로 둔다. 이번 재구성은 `semi/cli` 내부에서만 View와 Controller를 분리하는 것으로 범위를 한정한다:

- **Model**: `semi/services`, `semi/domain` (변경 없음)
- **View**: `cli/views.py` — 화면 출력/입력 파싱만 담당, 서비스나 도메인 로직을 호출하지 않음
- **Controller**: `cli/controllers.py` — 메뉴별 클래스. 서비스 호출과 흐름 제어(어떤 View를 언제 부를지)만 담당하고, 출력 서식은 View에 위임

## 1. 모듈 레이아웃

```
semi/cli/
├── app.py          # 진입점: DB/서비스/워커 초기화, Controller 조립, main_loop 호출
├── menu_loop.py    # MenuController Protocol, main_loop/dispatch, 단일 지점 예외 처리
├── controllers.py  # 메뉴별 Controller 클래스 (SampleMenuController 등)
└── views.py        # 렌더링/입력 함수 (Controller가 호출, print/input 캡슐화)
```

기존 설계의 `menus.py`(메뉴 렌더링 + 입력 처리를 한 파일에서 담당)는 이 개정에서 책임에 따라 `menu_loop.py`(루프/디스패치 골격)와 `views.py`(순수 출력/입력)로 분리된다.

## 2. `menu_loop.py` — `MenuController` Protocol과 메인 루프

```python
from typing import Callable, Protocol

class MenuController(Protocol):
    label: str                  # 메인 메뉴에 표시될 이름 (예: "시료 관리")
    def run(self) -> None: ...  # 서브메뉴 루프 진입점


def main_loop(
    controllers: list[MenuController],
    render_main_menu: Callable[[list[str]], int | str],
) -> None:
    while True:
        choice = render_main_menu([c.label for c in controllers])
        if choice == "exit":
            break
        try:
            controllers[choice].run()
        except DomainError as e:
            print(f"[오류] {e}")
        except NotFoundError as e:
            print(f"[조회 실패] {e}")
```

- `MenuController`는 `Protocol`(덕 타이핑)이다 — `label` 속성과 `run()` 메서드만 있으면 명시적 상속 없이 리스트에 넣을 수 있다.
- `controllers`는 `app.py`가 조립해 넘기는 **명시적 리스트**다. 새 메뉴 추가 시 변경 지점은 `controllers.py`에 클래스 하나 추가, `app.py`의 이 리스트에 인스턴스 한 줄 추가, 단 두 곳뿐이다. `menu_loop.py`는 손대지 않는다.
- 예외 처리는 기존 설계와 동일하게 **`main_loop`의 dispatch 지점(`controllers[choice].run()` 호출부) 한 곳**에서만 잡는다. 각 Controller의 `run()`은 서브메뉴 루프를 돌며 서비스 호출 도중 발생한 `DomainError`/`NotFoundError`를 잡지 않고 그대로 전파한다.
- `main_loop`은 `render_main_menu`를 `views.py`에서 직접 import하지 않고 **파라미터로 주입받는다**. `menu_loop.py`가 `views` 모듈을 직접 참조하면, `main_loop`의 루프/디스패치/예외 처리 로직만 검증하려 해도 실제 `print`/`input`을 우회하기 위해 `views` 모듈 전체를 몽키패치해야 한다. 함수를 인자로 주입하면 테스트 시 `render_main_menu`에 순수 함수(예: `lambda labels: "exit"`)를 대체해 넣어 stdin/stdout 없이 루프 로직만 독립적으로 검증할 수 있다. `app.py`에서는 `main_loop(controllers, render_main_menu=render_main_menu)` 형태로 호출한다 (§5).

### 2.1 잘못된 메인 메뉴 입력 처리

`render_main_menu`가 반환하는 `choice`가 유효한 인덱스라는 보장은 없다 — 사용자가 숫자가 아닌 값을 입력하거나(파싱 실패) 목록 범위를 벗어난 번호를 입력할 수 있다. 이 두 경우는 `controllers[choice].run()`에서 각각 파싱 단계 또는 인덱싱 단계의 예외로 나타나지만, `main_loop`이 캐치하는 예외는 `DomainError`/`NotFoundError`뿐이므로 그대로 두면 콘솔 앱 전체가 크래시한다.

**원칙**: 잘못된 메인 메뉴 입력은 §4의 서브메뉴 fail-safe 원칙과 동일하게 **`views.py` 레이어에서 흡수**한다 — `render_main_menu`는 파싱 실패나 범위 초과 입력에 대해 예외를 던지는 대신 재입력을 요구하고, 유효한 인덱스 또는 `"exit"`만을 반환값으로 보장한다. 이로써 `main_loop`은 `choice`가 항상 유효하다고 가정할 수 있고, dispatch 지점의 예외 처리는 `DomainError`/`NotFoundError`만 다루면 된다.

## 3. `controllers.py` — 메뉴별 Controller 클래스

```python
class SampleMenuController:
    label = "시료 관리"

    def __init__(self, sample_service: SampleService) -> None:
        self._service = sample_service

    def run(self) -> None:
        while True:
            choice = views.render_sample_menu()  # 등록/조회/검색/뒤로가기
            if choice == "back":
                return
            elif choice == "register":
                data = views.prompt_sample_registration()
                sample = self._service.register(**data)
                views.render_sample_registered(sample)
            elif choice == "list":
                views.render_sample_list(self._service.list_all())
            elif choice == "search":
                query = views.prompt_search_query()
                views.render_sample_list(self._service.search_by_name(query))
```

- Controller는 서비스 호출과 흐름 제어만 담당하고, 출력/입력 서식은 전부 `views.*` 함수에 위임한다.
- 예외(`DomainError` 등)는 `run()` 내부에서 잡지 않고 `main_loop`까지 전파시킨다 — §2의 단일 지점 catch 원칙을 그대로 따른다.
- PRD 4.1~4.7에 대응하는 Controller는 다음과 같이 구성한다:
  - `SampleMenuController(sample_service)` — 시료 등록/조회/검색 (PRD 4.2)
  - `OrderMenuController(order_service, monitoring_service)` — 주문 접수 + `RESERVED` 목록 조회 후 승인/거절 (PRD 4.3, 4.4). 승인/거절 대상 조회를 위해 `monitoring_service.list_by_status(RESERVED)`를 사용한다
  - `MonitoringMenuController(monitoring_service)` — 상태별 주문 수, 재고 현황 (PRD 4.5)
  - `ProductionMenuController(production_service)` — 현재 생산 현황, 생산 큐 조회 전용 (PRD 4.6). 승인/거절이 없어 `run()`이 더 단순하다
  - `ReleaseMenuController(order_service, monitoring_service)` — `CONFIRMED` 목록 조회 후 출고 실행 (PRD 4.7)
- 각 Controller는 생성자로 자신이 필요로 하는 service만 주입받는다 (필요 이상으로 넓은 의존성을 갖지 않는다).

## 4. `views.py` — 순수 렌더링/입력 함수

```python
def render_main_menu(labels: list[str]) -> int | Literal["exit"]:
    ...  # 번호 목록 출력, 입력 파싱/범위 검증 후 유효한 인덱스 또는 "exit" 반환 (실패 시 재입력 요구, §2.1)

def render_sample_menu() -> str: ...          # "register" | "list" | "search" | "back"
def prompt_sample_registration() -> dict: ... # sample_id, name, avg_production_seconds, yield_rate 입력받아 dict로 반환
def render_sample_list(samples: list[Sample]) -> None: ...
def render_sample_registered(sample: Sample) -> None: ...

def render_stock_status(statuses: list[SampleStockStatus]) -> None:
    ...  # StockStatus(SUFFICIENT/SHORT/DEPLETED) -> "여유"/"부족"/"고갈" 매핑은 여기서 수행
```

- `views.py`의 함수는 서비스나 도메인 로직을 호출하지 않는다 — 오직 `print`/`input`과 도메인 객체(`Sample`, `Order`, `SampleStockStatus` 등) 렌더링만 담당한다. 이 경계 덕분에 출력 포맷 변경(표 형식 개선, 다국어화 등)이 Controller/서비스 코드에 영향을 주지 않는다.
- services 설계 문서(§6)에서 "`StockStatus`는 영문 멤버로 두고 한글 표시는 cli 레이어가 매핑한다"고 명시한 바에 따라, 이 매핑은 `views.py`에 위치한다.
- **입력 파싱 fail-safe 원칙**: `views.py`의 모든 입력 파싱 함수는 인식할 수 없는 입력에 대해 예외를 던지지 않고 안전한 기본값으로 처리한다. 서브메뉴(`render_sample_menu` 등)는 인식하지 못한 입력을 `"back"`(상위 메뉴로 복귀)으로 매핑하고, 메인 메뉴(`render_main_menu`)는 숫자가 아니거나 범위를 벗어난 입력에 대해 크래시 대신 재입력을 요구한다(§2.1). 이 원칙 덕분에 Controller/`main_loop`은 잘못된 사용자 입력을 별도로 방어할 필요 없이, `views.py`가 반환하는 값이 항상 유효하다고 가정할 수 있다.

## 5. `app.py` — 진입점 및 조립

```python
def main() -> None:
    conn = connect_db(db_path)
    lock = threading.Lock()

    sample_repo = SampleRepository(conn)
    order_repo = OrderRepository(conn)
    job_repo = ProductionJobRepository(conn)

    sample_service = SampleService(sample_repo)
    order_service = OrderService(order_repo, job_repo, sample_repo, lock)
    production_service = ProductionService(order_repo, job_repo, sample_repo, lock)
    monitoring_service = MonitoringService(order_repo, sample_repo)

    controllers: list[MenuController] = [
        SampleMenuController(sample_service),
        OrderMenuController(order_service, monitoring_service),
        MonitoringMenuController(monitoring_service),
        ProductionMenuController(production_service),
        ReleaseMenuController(order_service, monitoring_service),
    ]

    start_worker(db_path, lock)

    try:
        main_loop(controllers, render_main_menu=render_main_menu)
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        conn.close()
```

## 6. 기능 확장 시 변경 지점 (요약)

새 메뉴/기능을 추가할 때 변경이 필요한 지점은 정확히 다음 두 곳으로 한정된다:

1. `controllers.py`에 `label`과 `run()`을 갖는 새 Controller 클래스 추가 (필요하면 `views.py`에 전용 렌더링/입력 함수 추가)
2. `app.py`의 `controllers` 리스트에 새 Controller 인스턴스 한 줄 추가

`menu_loop.py`(루프/디스패치/예외 처리 골격)는 신규 메뉴 추가만으로는 수정할 필요가 없다.

## 7. 종료 처리

콘솔 앱은 메인 메뉴의 "종료" 항목으로 정상 종료한다 (`main_loop`가 break). `Ctrl+C`(`KeyboardInterrupt`)도 동일하게 처리해 깨끗이 종료되도록 한다. 두 경우 모두 `finally` 블록에서 메인 스레드의 `conn.close()`를 명시적으로 호출한다. 백그라운드 워커 스레드는 daemon이므로 별도 종료 처리 없이 프로세스 종료와 함께 정리된다.
