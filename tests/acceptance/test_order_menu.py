import math

import pytest

from semi.domain.models import OrderStatus
from semi.storage.exceptions import NotFoundError


@pytest.fixture
def two_samples(app_context):
    """S-STOCK has enough stock to confirm immediately; S-SHORT has none."""
    app_context.sample_service.register("S-STOCK", "Stocked Wafer", 10.0, 0.9)
    app_context.sample_repo.increment_stock("S-STOCK", 100)
    app_context.sample_repo.conn.commit()
    app_context.sample_service.register("S-SHORT", "Short Wafer", 10.0, 0.5)
    return app_context


def test_create_order_reserved(two_samples, mocker):
    app_context = two_samples
    mocker.patch(
        "semi.cli.views.render_order_menu",
        side_effect=["create", "create", "back"],
    )
    mocker.patch(
        "semi.cli.views.prompt_order_creation",
        side_effect=[
            {"sample_id": "S-STOCK", "customer_name": "Alice", "quantity": 5},
            {"sample_id": "S-SHORT", "customer_name": "Bob", "quantity": 5},
        ],
    )
    mocker.patch("semi.cli.views.render_order_created")

    order_menu_controller = app_context.controllers[1]
    order_menu_controller.run()

    orders = app_context.order_repo.list_by_status(OrderStatus.RESERVED)
    assert len(orders) == 2
    assert {o.sample_id for o in orders} == {"S-STOCK", "S-SHORT"}
    assert all(o.status == OrderStatus.RESERVED for o in orders)


def test_approve_sufficient_stock_confirms_immediately(two_samples, mocker):
    app_context = two_samples
    order = app_context.order_service.create_order("S-STOCK", "Alice", 5)

    mocker.patch(
        "semi.cli.views.render_order_menu", side_effect=["approve_reject", "back"]
    )
    mocker.patch("semi.cli.views.render_reserved_orders")
    mocker.patch(
        "semi.cli.views.prompt_order_action",
        return_value=(order.order_id, "approve"),
    )
    mocker.patch("semi.cli.views.render_order_result")

    order_menu_controller = app_context.controllers[1]
    order_menu_controller.run()

    updated = app_context.order_repo.get_by_id(order.order_id)
    assert updated.status == OrderStatus.CONFIRMED
    with pytest.raises(NotFoundError):
        app_context.job_repo.get_by_order_id(order.order_id)


def test_approve_insufficient_stock_queues_production_job(two_samples, mocker):
    app_context = two_samples
    order = app_context.order_service.create_order("S-SHORT", "Bob", 5)
    sample = app_context.sample_repo.get_by_id("S-SHORT")

    mocker.patch(
        "semi.cli.views.render_order_menu", side_effect=["approve_reject", "back"]
    )
    mocker.patch("semi.cli.views.render_reserved_orders")
    mocker.patch(
        "semi.cli.views.prompt_order_action",
        return_value=(order.order_id, "approve"),
    )
    mocker.patch("semi.cli.views.render_order_result")

    order_menu_controller = app_context.controllers[1]
    order_menu_controller.run()

    updated = app_context.order_repo.get_by_id(order.order_id)
    assert updated.status == OrderStatus.PRODUCING

    job = app_context.job_repo.get_by_order_id(order.order_id)
    expected_shortfall = order.quantity - 0  # available stock was 0
    expected_actual_quantity = math.ceil(expected_shortfall / sample.yield_rate)
    expected_duration = sample.avg_production_seconds * expected_actual_quantity
    assert job.shortfall_quantity == expected_shortfall
    assert job.actual_quantity == expected_actual_quantity
    assert job.total_duration_seconds == expected_duration


def test_reject_order(two_samples, mocker):
    app_context = two_samples
    order = app_context.order_service.create_order("S-STOCK", "Carol", 3)

    mocker.patch(
        "semi.cli.views.render_order_menu", side_effect=["approve_reject", "back"]
    )
    mocker.patch("semi.cli.views.render_reserved_orders")
    mocker.patch(
        "semi.cli.views.prompt_order_action",
        return_value=(order.order_id, "reject"),
    )
    mocker.patch("semi.cli.views.render_order_result")

    order_menu_controller = app_context.controllers[1]
    order_menu_controller.run()

    updated = app_context.order_repo.get_by_id(order.order_id)
    assert updated.status == OrderStatus.REJECTED


def test_approve_reject_lists_reserved_orders(two_samples, mocker):
    app_context = two_samples
    order1 = app_context.order_service.create_order("S-STOCK", "Alice", 1)
    order2 = app_context.order_service.create_order("S-SHORT", "Bob", 1)

    mocker.patch(
        "semi.cli.views.render_order_menu", side_effect=["approve_reject", "back"]
    )
    render_reserved = mocker.patch("semi.cli.views.render_reserved_orders")
    mocker.patch("semi.cli.views.prompt_order_action", return_value=None)

    order_menu_controller = app_context.controllers[1]
    order_menu_controller.run()

    listed = render_reserved.call_args.args[0]
    assert {o.order_id for o in listed} == {order1.order_id, order2.order_id}
