from semi.domain.models import Order, OrderStatus, Sample
from semi.services.monitoring_service import StockStatus


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
    return {
        "sample_id": sample_id,
        "customer_name": customer_name,
        "quantity": quantity,
    }


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


_ORDER_STATUS_LABELS = {
    OrderStatus.RESERVED: "접수",
    OrderStatus.CONFIRMED: "출고대기",
    OrderStatus.PRODUCING: "생산중",
    OrderStatus.RELEASE: "출고완료",
}

_STOCK_STATUS_LABELS = {
    StockStatus.SUFFICIENT: "여유",
    StockStatus.SHORT: "부족",
    StockStatus.DEPLETED: "고갈",
}


def render_monitoring_menu() -> str:
    print("\n--- 모니터링 ---")
    print("1. 상태별 주문 수 확인")
    print("2. 재고 현황 확인")
    print("0. 뒤로가기")
    raw = input("선택: ").strip()
    return {"1": "order_counts", "2": "stock_status"}.get(raw, "back")


def render_order_counts(counts: dict) -> None:
    print("\n--- 상태별 주문 수 ---")
    for status, count in counts.items():
        print(f"{_ORDER_STATUS_LABELS[status]}: {count}")


def render_stock_status(statuses: list) -> None:
    print("\n--- 재고 현황 ---")
    for entry in statuses:
        label = _STOCK_STATUS_LABELS[entry.status]
        print(
            f"[{entry.sample.sample_id}] {entry.sample.name} | 재고={entry.sample.stock_quantity} "
            f"| 미완료주문={entry.outstanding} | 상태={label}"
        )


def render_production_menu() -> str:
    print("\n--- 생산 라인 ---")
    print("1. 현재 생산 현황")
    print("2. 생산 큐 조회")
    print("0. 뒤로가기")
    raw = input("선택: ").strip()
    return {"1": "current", "2": "queue"}.get(raw, "back")


def render_current_production(status) -> None:
    print("\n--- 현재 생산 현황 ---")
    if status is None:
        print("현재 생산 중인 작업이 없습니다.")
        return
    job = status.job
    print(
        f"작업ID={job.job_id} | 주문ID={job.order_id} | 시료={job.sample_id} "
        f"| 부족분={job.shortfall_quantity} | 실생산량={job.actual_quantity} "
        f"| 진행률={status.progress_ratio:.0%} | 현재생산량={status.produced_so_far} "
        f"| 예상완료={status.estimated_completion_at}"
    )


def render_production_queue(statuses: list) -> None:
    print("\n--- 생산 대기열(FIFO) ---")
    if not statuses:
        print("대기 중인 생산 작업이 없습니다.")
        return
    for status in statuses:
        job = status.job
        print(
            f"작업ID={job.job_id} | 주문ID={job.order_id} | 시료={job.sample_id} "
            f"| 실생산량={job.actual_quantity} | 예상완료={status.estimated_completion_at}"
        )


def render_confirmed_orders(orders: list) -> None:
    print("\n--- 출고 대기(CONFIRMED) 주문 ---")
    if not orders:
        print("출고 대기 중인 주문이 없습니다.")
        return
    for order in orders:
        print(
            f"주문ID={order.order_id} | 시료={order.sample_id} "
            f"| 고객={order.customer_name} | 수량={order.quantity}"
        )


def prompt_release_selection(orders: list) -> int | None:
    valid_ids = {order.order_id for order in orders}
    raw_id = input("출고 처리할 주문 ID (0: 뒤로가기): ").strip()
    try:
        order_id = int(raw_id)
    except ValueError:
        return None
    if order_id == 0 or order_id not in valid_ids:
        return None
    return order_id


def render_release_result(order) -> None:
    print(f"주문 {order.order_id} 출고 완료: 상태={order.status}")
