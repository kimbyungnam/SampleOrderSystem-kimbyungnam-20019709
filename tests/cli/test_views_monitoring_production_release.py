from datetime import datetime, timedelta

from semi.cli import views
from semi.domain.models import JobStatus, Order, OrderStatus, ProductionJob
from semi.services.monitoring_service import SampleStockStatus, StockStatus
from semi.services.production_service import ProductionJobStatus


def _sample_stock_status(status, outstanding=5):
    from semi.domain.models import Sample

    return SampleStockStatus(
        sample=Sample("S1", "Wafer A", 10.0, 0.9, 3),
        outstanding=outstanding,
        status=status,
    )


def _job_status(job_id=1):
    job = ProductionJob(
        job_id=job_id,
        order_id=1,
        sample_id="S1",
        shortfall_quantity=2,
        actual_quantity=3,
        total_duration_seconds=30.0,
        status=JobStatus.IN_PROGRESS,
        enqueued_at=datetime.now(),
        started_at=datetime.now(),
    )
    return ProductionJobStatus(
        job=job,
        progress_ratio=0.5,
        produced_so_far=1,
        estimated_completion_at=datetime.now() + timedelta(seconds=15),
    )


def test_render_monitoring_menu_maps_known_inputs(mocker):
    mocker.patch("builtins.input", return_value="1")
    assert views.render_monitoring_menu() == "order_counts"

    mocker.patch("builtins.input", return_value="2")
    assert views.render_monitoring_menu() == "stock_status"

    mocker.patch("builtins.input", return_value="0")
    assert views.render_monitoring_menu() == "back"


def test_render_monitoring_menu_maps_unrecognized_input_to_back(mocker):
    mocker.patch("builtins.input", return_value="nope")
    assert views.render_monitoring_menu() == "back"


def test_render_order_counts_prints_each_status(capsys):
    counts = {
        OrderStatus.RESERVED: 2,
        OrderStatus.CONFIRMED: 1,
        OrderStatus.PRODUCING: 0,
        OrderStatus.RELEASE: 4,
    }

    views.render_order_counts(counts)

    out = capsys.readouterr().out
    assert "접수" in out
    assert "출고완료" in out
    assert "4" in out


def test_render_stock_status_maps_korean_labels(capsys):
    statuses = [
        _sample_stock_status(StockStatus.SUFFICIENT),
        _sample_stock_status(StockStatus.SHORT),
        _sample_stock_status(StockStatus.DEPLETED),
    ]

    views.render_stock_status(statuses)

    out = capsys.readouterr().out
    assert "여유" in out
    assert "부족" in out
    assert "고갈" in out


def test_render_production_menu_maps_known_inputs(mocker):
    mocker.patch("builtins.input", return_value="1")
    assert views.render_production_menu() == "current"

    mocker.patch("builtins.input", return_value="2")
    assert views.render_production_menu() == "queue"

    mocker.patch("builtins.input", return_value="0")
    assert views.render_production_menu() == "back"


def test_render_current_production_handles_none(capsys):
    views.render_current_production(None)
    assert "없습니다" in capsys.readouterr().out


def test_render_current_production_prints_progress(capsys):
    views.render_current_production(_job_status(job_id=9))

    out = capsys.readouterr().out
    assert "9" in out
    assert "50" in out or "0.5" in out


def test_render_production_queue_handles_empty(capsys):
    views.render_production_queue([])
    assert "없습니다" in capsys.readouterr().out


def test_render_production_queue_prints_each_job(capsys):
    views.render_production_queue([_job_status(job_id=5), _job_status(job_id=6)])

    out = capsys.readouterr().out
    assert "5" in out and "6" in out


def test_render_confirmed_orders_handles_empty(capsys):
    views.render_confirmed_orders([])
    assert "없습니다" in capsys.readouterr().out


def test_render_confirmed_orders_prints_each_order(capsys):
    orders = [Order(1, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]

    views.render_confirmed_orders(orders)

    out = capsys.readouterr().out
    assert "1" in out
    assert "ACME" in out


def test_prompt_release_selection_returns_id_for_valid_choice(mocker):
    orders = [Order(4, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]
    mocker.patch("builtins.input", return_value="4")

    assert views.prompt_release_selection(orders) == 4


def test_prompt_release_selection_returns_none_for_back():
    import builtins

    orders = [Order(4, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]
    original_input = builtins.input
    builtins.input = lambda *_: "0"
    try:
        assert views.prompt_release_selection(orders) is None
    finally:
        builtins.input = original_input


def test_prompt_release_selection_returns_none_for_unknown_id(mocker):
    orders = [Order(4, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]
    mocker.patch("builtins.input", return_value="99")

    assert views.prompt_release_selection(orders) is None


def test_prompt_release_selection_returns_none_for_non_numeric(mocker):
    orders = [Order(4, "S1", "ACME", 5, OrderStatus.CONFIRMED, datetime.now())]
    mocker.patch("builtins.input", return_value="abc")

    assert views.prompt_release_selection(orders) is None


def test_render_release_result_prints_order_id(capsys):
    order = Order(4, "S1", "ACME", 5, OrderStatus.RELEASE, datetime.now())

    views.render_release_result(order)

    out = capsys.readouterr().out
    assert "4" in out
    assert "RELEASE" in out
