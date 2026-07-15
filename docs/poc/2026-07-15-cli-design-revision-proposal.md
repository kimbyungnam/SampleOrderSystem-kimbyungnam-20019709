# `2026-07-15-cli-design.md` 개정 제안

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 목적 | PoC(`poc/`) 구현 및 테스트(`poc/tests/`) 작성 과정에서 드러난, 원 설계 문서(`2026-07-15-cli-design.md`)에 반영하면 좋을 지점을 정리한다. 이 문서 자체는 설계를 변경하지 않으며, 원 문서 수정 시 참고할 제안 목록이다. |
| 근거 | `poc/menu_loop.py`, `poc/controllers.py`, `poc/views.py`, `poc/tests/*` (실제 구현/테스트 코드) |
| 작성일 | 2026-07-15 |

---

## 1. `main_loop`이 `render_main_menu`를 직접 import하지 않고 파라미터로 주입받음

원 문서 §2의 의사코드는 `main_loop` 내부에서 `render_main_menu(...)`를 (views.py에서 import한 함수로) 직접 호출하는 형태다:

```python
def main_loop(controllers: list[MenuController]) -> None:
    while True:
        choice = render_main_menu([c.label for c in controllers])  # views.py 호출
        ...
```

PoC(`poc/menu_loop.py:12-25`)는 대신 `render_main_menu`를 인자로 받는다:

```python
def main_loop(
    controllers: list[MenuController],
    render_main_menu: Callable[[list[str]], int | str],
) -> None:
```

**이유**: `menu_loop.py`가 `views` 모듈을 직접 import하면 `main_loop`을 테스트할 때 실제 `print`/`input`을 우회하기 위해 `views` 모듈 전체를 몽키패치해야 한다. 함수를 인자로 주입하면 `poc/tests/test_menu_loop.py`처럼 순수 함수(`lambda labels: "exit"` 등)로 대체해 루프/디스패치/예외 처리 로직만 독립적으로 검증할 수 있었다.

**제안**: §2의 `main_loop` 시그니처를 `main_loop(controllers, render_main_menu)` 형태로 수정하고, "테스트 시 `render_main_menu`를 페이크로 주입해 stdin/stdout 없이 루프 로직을 검증한다"는 근거를 함께 명시한다. §5 `app.py` 조립 예시도 `main_loop(controllers, render_main_menu=render_main_menu)` 호출로 갱신한다.

## 2. 잘못된 메뉴 입력에 대한 처리가 설계에 없음

원 문서 §2의 `main_loop`과 §4의 `render_main_menu`는 사용자가 숫자가 아닌 값을 입력하거나(`int(raw)`가 `ValueError` 발생) 범위를 벗어난 번호를 입력하는 경우(`controllers[choice]`가 `IndexError` 발생)를 다루지 않는다. PoC 구현도 동일한 상태로 이 부분을 그대로 재현했고, 테스트(`test_menu_loop.py`) 역시 유효한 선택지만 다룬다 — 즉 이 경로는 설계·구현·테스트 어디에서도 다뤄지지 않은 채로 PoC가 완성되었다.

`main_loop`의 예외 처리는 `DomainError`/`NotFoundError`만 잡으므로, 위 두 예외는 그대로 콘솔 앱을 크래시시킨다.

**제안**: §2 또는 §4에 "잘못된 메뉴 입력" 처리 원칙을 추가한다. 예:
- `render_main_menu`가 파싱 실패/범위 초과 시 재입력을 요구하도록 views 레이어에서 처리 (권장 — 서브메뉴의 기존 fail-safe 패턴과 일관성을 가짐, 아래 §3 참고)
- 또는 `main_loop`이 `ValueError`/`IndexError`를 잡아 "잘못된 선택입니다" 안내 후 메뉴를 다시 그리도록 명시

## 3. 서브메뉴(`render_sample_menu`)의 fail-safe 동작이 설계에 명문화되어 있지 않음

PoC의 `render_sample_menu`(`poc/views.py:15-22`)는 인식하지 못한 입력을 `"back"`으로 매핑한다 (`{"1": ..., "0": "back"}.get(raw, "back")`). 즉 서브메뉴는 잘못된 입력에도 크래시하지 않고 안전하게 상위 메뉴로 복귀한다 — 반면 메인 메뉴(`render_main_menu`)는 위 §2에서 지적한 대로 동일 상황에서 크래시한다.

**제안**: §4에 "서브메뉴 입력 파싱은 인식할 수 없는 입력을 안전한 기본값(뒤로가기)으로 처리한다"는 원칙을 명시하고, §2의 메인 메뉴도 동일한 원칙을 따르도록 통일한다 (§2 참고).

---

## 요약

| # | 제안 | 대상 절 |
|---|---|---|
| 1 | `main_loop`이 `render_main_menu`를 파라미터로 주입받도록 시그니처 변경 (테스트 용이성) | §2, §5 |
| 2 | 잘못된 메인 메뉴 입력(비숫자/범위 초과) 처리 원칙 추가 | §2, §4 |
| 3 | 서브메뉴 fail-safe(인식 불가 입력 → 뒤로가기) 원칙을 메인 메뉴에도 통일 적용 | §4 |
