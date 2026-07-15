from unittest.mock import MagicMock

from semi.cli import views
from semi.cli.controllers import SampleMenuController
from semi.domain.models import Sample


def test_label_is_sample_management():
    assert SampleMenuController(MagicMock()).label == "시료 관리"


def test_run_registers_sample_then_exits_on_back(mocker):
    service = MagicMock()
    registered = Sample("S1", "Wafer A", 10.0, 0.9, 0)
    service.register.return_value = registered
    mocker.patch.object(views, "render_sample_menu", side_effect=["register", "back"])
    mocker.patch.object(
        views,
        "prompt_sample_registration",
        return_value={
            "sample_id": "S1",
            "name": "Wafer A",
            "avg_production_seconds": 10.0,
            "yield_rate": 0.9,
        },
    )
    render_registered = mocker.patch.object(views, "render_sample_registered")

    SampleMenuController(service).run()

    service.register.assert_called_once_with(
        sample_id="S1", name="Wafer A", avg_production_seconds=10.0, yield_rate=0.9
    )
    render_registered.assert_called_once_with(registered)


def test_run_lists_samples_then_exits_on_back(mocker):
    service = MagicMock()
    samples = [Sample("S1", "Wafer A", 10.0, 0.9, 5)]
    service.list_all.return_value = samples
    mocker.patch.object(views, "render_sample_menu", side_effect=["list", "back"])
    render_list = mocker.patch.object(views, "render_sample_list")

    SampleMenuController(service).run()

    render_list.assert_called_once_with(samples)


def test_run_searches_samples_then_exits_on_back(mocker):
    service = MagicMock()
    service.search_by_name.return_value = []
    mocker.patch.object(views, "render_sample_menu", side_effect=["search", "back"])
    mocker.patch.object(views, "prompt_search_query", return_value="Wafer")
    render_list = mocker.patch.object(views, "render_sample_list")

    SampleMenuController(service).run()

    service.search_by_name.assert_called_once_with("Wafer")
    render_list.assert_called_once_with([])


def test_run_returns_immediately_on_back(mocker):
    service = MagicMock()
    mocker.patch.object(views, "render_sample_menu", return_value="back")

    SampleMenuController(service).run()

    service.register.assert_not_called()
    service.list_all.assert_not_called()
    service.search_by_name.assert_not_called()
