from semi.domain.models import Sample


def _prompt_float(prompt: str) -> float:
    while True:
        raw = input(prompt).strip()
        try:
            return float(raw)
        except ValueError:
            print("[오류] 숫자를 입력하세요.")


def render_main_menu(labels: list[str]) -> int | str:
    while True:
        print("\n=== 메인 메뉴 ===")
        for i, label in enumerate(labels, start=1):
            print(f"{i}. {label}")
        print("0. 종료")
        raw = input("선택: ").strip()
        if raw == "0":
            return "exit"
        try:
            choice = int(raw)
        except ValueError:
            print("[오류] 숫자를 입력하세요.")
            continue
        if 1 <= choice <= len(labels):
            return choice - 1
        print("[오류] 올바른 번호를 입력하세요.")


def render_sample_menu() -> str:
    print("\n--- 시료 관리 ---")
    print("1. 시료 등록")
    print("2. 시료 목록 조회")
    print("3. 이름 검색")
    print("0. 뒤로가기")
    raw = input("선택: ").strip()
    return {"1": "register", "2": "list", "3": "search"}.get(raw, "back")


def prompt_sample_registration() -> dict:
    sample_id = input("시료 ID: ").strip()
    name = input("이름: ").strip()
    avg_production_seconds = _prompt_float("평균 생산시간(초): ")
    yield_rate = _prompt_float("수율 (0~1): ")
    return {
        "sample_id": sample_id,
        "name": name,
        "avg_production_seconds": avg_production_seconds,
        "yield_rate": yield_rate,
    }


def prompt_search_query() -> str:
    return input("검색할 이름: ").strip()


def render_sample_list(samples: list[Sample]) -> None:
    print("\n--- 시료 목록 ---")
    if not samples:
        print("등록된 시료가 없습니다.")
        return
    for sample in samples:
        print(
            f"[{sample.sample_id}] {sample.name} | 평균생산시간={sample.avg_production_seconds}s "
            f"| 수율={sample.yield_rate} | 재고={sample.stock_quantity}"
        )


def render_sample_registered(sample: Sample) -> None:
    print(f"시료 등록 완료: {sample.sample_id} ({sample.name})")
