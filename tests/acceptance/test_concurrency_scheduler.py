"""Concurrency acceptance test: real background worker thread + CLI-driven
order creation/approval racing on the main thread, guarding the anti-oversell
invariant throughout."""

import time

from semi.domain.models import OrderStatus
from semi.scheduler.background_worker import start_worker


def test_worker_and_cli_never_violate_oversell_invariant(app_context, mocker, capfd):
    # Small avg_production_seconds so jobs complete within a handful of the
    # worker's 1s ticks, without depending on an exact tick count.
    app_context.sample_service.register("S1", "Wafer A", 0.05, 1.0)

    thread = start_worker(app_context.db_path, app_context.lock)
    assert thread.is_alive()

    order_menu_controller = app_context.controllers[1]

    # 1. Create 3 orders on the main thread via the real CLI controller.
    mocker.patch(
        "semi.cli.views.render_order_menu",
        side_effect=["create", "create", "create", "back"],
    )
    mocker.patch(
        "semi.cli.views.prompt_order_creation",
        side_effect=[
            {"sample_id": "S1", "customer_name": "Alice", "quantity": 2},
            {"sample_id": "S1", "customer_name": "Bob", "quantity": 3},
            {"sample_id": "S1", "customer_name": "Carol", "quantity": 1},
        ],
    )
    mocker.patch("semi.cli.views.render_order_created")
    order_menu_controller.run()

    reserved = app_context.order_repo.list_by_status(OrderStatus.RESERVED)
    assert len(reserved) == 3
    order_ids = [o.order_id for o in reserved]
    expected_quantities = {o.order_id: o.quantity for o in reserved}

    # 2. Approve all 3 on the main thread (all take the PRODUCING path
    # since stock is 0), racing against the worker's ticks.
    mocker.patch(
        "semi.cli.views.render_order_menu",
        side_effect=["approve_reject", "approve_reject", "approve_reject", "back"],
    )
    mocker.patch("semi.cli.views.render_reserved_orders")
    mocker.patch(
        "semi.cli.views.prompt_order_action",
        side_effect=[(order_id, "approve") for order_id in order_ids],
    )
    mocker.patch("semi.cli.views.render_order_result")
    order_menu_controller.run()

    jobs = [app_context.job_repo.get_by_order_id(order_id) for order_id in order_ids]
    expected_total_stock = sum(job.actual_quantity for job in jobs)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        statuses = [
            app_context.order_repo.get_by_id(order_id).status for order_id in order_ids
        ]
        stock_quantity = app_context.sample_repo.get_by_id("S1").stock_quantity
        confirmed_unreleased = app_context.order_repo.sum_quantity_by_status(
            "S1", OrderStatus.CONFIRMED
        )
        assert stock_quantity >= confirmed_unreleased, (
            f"anti-oversell invariant violated: stock={stock_quantity} "
            f"< confirmed_unreleased={confirmed_unreleased}"
        )
        if all(s == OrderStatus.CONFIRMED for s in statuses):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("orders did not all reach CONFIRMED within timeout")

    final_stock = app_context.sample_repo.get_by_id("S1").stock_quantity
    assert final_stock == expected_total_stock
    assert sum(expected_quantities.values()) == 6  # sanity check on setup

    assert thread.is_alive()
    stderr = capfd.readouterr().err
    assert "Traceback" not in stderr
