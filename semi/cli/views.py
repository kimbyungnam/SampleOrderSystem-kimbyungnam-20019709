from semi.domain.models import Order, Sample


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


def _prompt_int(prompt: str) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            return int(raw)
        except ValueError:
            print("[오류] 숫자를 입력하세요.")


def render_order_menu() -> str:
    print("\n--- 주문 접수 / 승인 / 거절 ---")
    print("1. 주문 접수")
    print("2. 승인/거절 대상 조회 및 처리")
    print("0. 뒤로가기")
    raw = input("선택: ").strip()
    return {"1": "create", "2": "approve_reject"}.get(raw, "back")


def prompt_order_creation() -> dict:
    sample_id = input("시료 ID: ").strip()
    customer_name = input("고객명: ").strip()
    quantity = _prompt_int("주문 수량: ")
    return {"sample_id": sample_id, "customer_name": customer_name, "quantity": quantity}


def render_order_created(order: Order) -> None:
    print(f"주문 접수 완료: 주문ID={order.order_id} (상태={order.status})")


def render_reserved_orders(orders: list[Order]) -> None:
    print("\n--- 접수 대기(RESERVED) 주문 ---")
    if not orders:
        print("대기 중인 주문이 없습니다.")
        return
    for order in orders:
        print(
            f"주문ID={order.order_id} | 시료={order.sample_id} "
            f"| 고객={order.customer_name} | 수량={order.quantity}"
        )


def prompt_order_action(orders: list[Order]) -> tuple[int, str] | None:
    valid_ids = {order.order_id for order in orders}
    raw_id = input("처리할 주문 ID (0: 뒤로가기): ").strip()
    try:
        order_id = int(raw_id)
    except ValueError:
        return None
    if order_id == 0 or order_id not in valid_ids:
        return None
    raw_action = input("승인(a) / 거절(r): ").strip().lower()
    action = {"a": "approve", "r": "reject"}.get(raw_action)
    if action is None:
        return None
    return order_id, action


def render_order_result(order: Order) -> None:
    print(f"주문 {order.order_id} 처리 완료: 상태={order.status}")
