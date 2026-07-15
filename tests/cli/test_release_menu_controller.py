from datetime import datetime
from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import ReleaseMenuController
from semi.domain.models import Order, OrderStatus


def _order(order_id=1, status=OrderStatus.CONFIRMED):
    return Order(order_id, "S1", "ACME", 5, status, datetime.now())


def test_label_is_release_processing():
    assert ReleaseMenuController(MagicMock(), MagicMock()).label == "출고 처리"


def test_run_returns_immediately_when_no_confirmed_orders(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    monitoring_service.list_by_status.return_value = []
    mocker.patch.object(views, "render_confirmed_orders")
    prompt_selection = mocker.patch.object(views, "prompt_release_selection")

    ReleaseMenuController(order_service, monitoring_service).run()

    monitoring_service.list_by_status.assert_called_once_with(OrderStatus.CONFIRMED)
    prompt_selection.assert_not_called()
    order_service.release.assert_not_called()


def test_run_releases_selected_order_then_stops_when_none_left(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    confirmed = _order(order_id=6)
    monitoring_service.list_by_status.side_effect = [[confirmed], []]
    released = _order(order_id=6, status=OrderStatus.RELEASE)
    order_service.release.return_value = released
    mocker.patch.object(views, "render_confirmed_orders")
    mocker.patch.object(views, "prompt_release_selection", return_value=6)
    render_result = mocker.patch.object(views, "render_release_result")

    ReleaseMenuController(order_service, monitoring_service).run()

    order_service.release.assert_called_once_with(6)
    render_result.assert_called_once_with(released)
    assert monitoring_service.list_by_status.call_count == 2


def test_run_returns_immediately_when_selection_is_none(mocker):
    order_service = MagicMock()
    monitoring_service = MagicMock()
    monitoring_service.list_by_status.return_value = [_order(order_id=7)]
    mocker.patch.object(views, "render_confirmed_orders")
    mocker.patch.object(views, "prompt_release_selection", return_value=None)

    ReleaseMenuController(order_service, monitoring_service).run()

    order_service.release.assert_not_called()
