from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import MonitoringMenuController


def test_label_is_monitoring():
    assert MonitoringMenuController(MagicMock()).label == "모니터링"


def test_run_renders_order_counts_then_exits_on_back(mocker):
    service = MagicMock()
    counts = {"RESERVED": 2}
    service.count_by_status.return_value = counts
    mocker.patch.object(
        views, "render_monitoring_menu", side_effect=["order_counts", "back"]
    )
    render_counts = mocker.patch.object(views, "render_order_counts")

    MonitoringMenuController(service).run()

    render_counts.assert_called_once_with(counts)


def test_run_renders_stock_status_then_exits_on_back(mocker):
    service = MagicMock()
    statuses = [MagicMock()]
    service.stock_status.return_value = statuses
    mocker.patch.object(
        views, "render_monitoring_menu", side_effect=["stock_status", "back"]
    )
    render_stock = mocker.patch.object(views, "render_stock_status")

    MonitoringMenuController(service).run()

    render_stock.assert_called_once_with(statuses)


def test_run_returns_immediately_on_back(mocker):
    service = MagicMock()
    mocker.patch.object(views, "render_monitoring_menu", return_value="back")

    MonitoringMenuController(service).run()

    service.count_by_status.assert_not_called()
    service.stock_status.assert_not_called()
