from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import ProductionMenuController


def test_label_is_production_line():
    assert ProductionMenuController(MagicMock()).label == "생산 라인"


def test_run_renders_current_status_then_exits_on_back(mocker):
    service = MagicMock()
    current = MagicMock()
    service.get_current_status.return_value = current
    mocker.patch.object(views, "render_production_menu", side_effect=["current", "back"])
    render_current = mocker.patch.object(views, "render_current_production")

    ProductionMenuController(service).run()

    render_current.assert_called_once_with(current)


def test_run_renders_queue_then_exits_on_back(mocker):
    service = MagicMock()
    queue = [MagicMock()]
    service.list_queue_status.return_value = queue
    mocker.patch.object(views, "render_production_menu", side_effect=["queue", "back"])
    render_queue = mocker.patch.object(views, "render_production_queue")

    ProductionMenuController(service).run()

    render_queue.assert_called_once_with(queue)


def test_run_returns_immediately_on_back(mocker):
    service = MagicMock()
    mocker.patch.object(views, "render_production_menu", return_value="back")

    ProductionMenuController(service).run()

    service.get_current_status.assert_not_called()
    service.list_queue_status.assert_not_called()
