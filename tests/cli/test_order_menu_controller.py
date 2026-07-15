from datetime import datetime
from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import OrderMenuController
from semi.domain.models import Order, OrderStatus


def _order(order_id=1, status=OrderStatus.RESERVED):
    return Order(order_id, "S1", "ACME", 5, status, datetime.now())


def test_label_is_order_menu():
    assert OrderMenuController(MagicMock(), MagicMock()).label == "주문 접수 / 승인 / 거절"


def test_run_creates_order_then_exits_on_back(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    created = _order(order_id=9)
    order_service.create_order.return_value = created
    mocker.patch.object(views, "render_order_menu", side_effect=["create", "back"])
    mocker.patch.object(
        views,
        "prompt_order_creation",
        return_value={"sample_id": "S1", "customer_name": "ACME", "quantity": 5},
    )
    render_created = mocker.patch.object(views, "render_order_created")

    OrderMenuController(order_service, monitoring_service).run()

    order_service.create_order.assert_called_once_with(
        sample_id="S1", customer_name="ACME", quantity=5
    )
    render_created.assert_called_once_with(created)


def test_run_approves_selected_reserved_order(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    reserved = _order(order_id=3)
    monitoring_service.list_by_status.return_value = [reserved]
    approved = _order(order_id=3, status=OrderStatus.CONFIRMED)
    order_service.approve.return_value = approved
    mocker.patch.object(views, "render_order_menu", side_effect=["approve_reject", "back"])
    mocker.patch.object(views, "render_reserved_orders")
    mocker.patch.object(views, "prompt_order_action", return_value=(3, "approve"))
    render_result = mocker.patch.object(views, "render_order_result")

    OrderMenuController(order_service, monitoring_service).run()

    monitoring_service.list_by_status.assert_called_once_with(OrderStatus.RESERVED)
    order_service.approve.assert_called_once_with(3)
    order_service.reject.assert_not_called()
    render_result.assert_called_once_with(approved)


def test_run_rejects_selected_reserved_order(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    reserved = _order(order_id=4)
    monitoring_service.list_by_status.return_value = [reserved]
    rejected = _order(order_id=4, status=OrderStatus.REJECTED)
    order_service.reject.return_value = rejected
    mocker.patch.object(views, "render_order_menu", side_effect=["approve_reject", "back"])
    mocker.patch.object(views, "render_reserved_orders")
    mocker.patch.object(views, "prompt_order_action", return_value=(4, "reject"))
    render_result = mocker.patch.object(views, "render_order_result")

    OrderMenuController(order_service, monitoring_service).run()

    order_service.reject.assert_called_once_with(4)
    order_service.approve.assert_not_called()
    render_result.assert_called_once_with(rejected)


def test_run_does_nothing_when_action_selection_is_none(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    monitoring_service.list_by_status.return_value = [_order(order_id=5)]
    mocker.patch.object(views, "render_order_menu", side_effect=["approve_reject", "back"])
    mocker.patch.object(views, "render_reserved_orders")
    mocker.patch.object(views, "prompt_order_action", return_value=None)

    OrderMenuController(order_service, monitoring_service).run()

    order_service.approve.assert_not_called()
    order_service.reject.assert_not_called()


def test_run_does_not_prompt_for_action_when_no_reserved_orders(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    monitoring_service.list_by_status.return_value = []
    mocker.patch.object(views, "render_order_menu", side_effect=["approve_reject", "back"])
    mocker.patch.object(views, "render_reserved_orders")
    prompt_action = mocker.patch.object(views, "prompt_order_action")

    OrderMenuController(order_service, monitoring_service).run()

    prompt_action.assert_not_called()
