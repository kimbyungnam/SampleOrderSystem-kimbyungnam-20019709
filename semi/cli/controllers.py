from semi.cli import views
from semi.domain.models import OrderStatus


class SampleMenuController:
    label = "시료 관리"

    def __init__(self, sample_service) -> None:
        self._service = sample_service

    def run(self) -> None:
        while True:
            choice = views.render_sample_menu()
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


class OrderMenuController:
    label = "주문 접수 / 승인 / 거절"

    def __init__(self, order_service, monitoring_service) -> None:
        self._order_service = order_service
        self._monitoring_service = monitoring_service

    def run(self) -> None:
        while True:
            choice = views.render_order_menu()
            if choice == "back":
                return
            elif choice == "create":
                data = views.prompt_order_creation()
                order = self._order_service.create_order(**data)
                views.render_order_created(order)
            elif choice == "approve_reject":
                self._approve_or_reject()

    def _approve_or_reject(self) -> None:
        orders = self._monitoring_service.list_by_status(OrderStatus.RESERVED)
        views.render_reserved_orders(orders)
        if not orders:
            return
        selection = views.prompt_order_action(orders)
        if selection is None:
            return
        order_id, action = selection
        if action == "approve":
            order = self._order_service.approve(order_id)
        else:
            order = self._order_service.reject(order_id)
        views.render_order_result(order)
