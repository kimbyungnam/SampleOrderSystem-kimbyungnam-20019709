from datetime import datetime, timedelta

from semi.domain.models import OrderStatus


def _force_job_complete(app_context, job):
    """Same technique as tests/integration/test_order_lifecycle_sqlite.py:
    push started_at far enough into the past that tick() treats it as done."""
    app_context.job_repo.mark_in_progress(
        job.job_id,
        datetime.now() - timedelta(seconds=job.total_duration_seconds + 1),
    )


def _make_two_confirmed_orders(app_context):
    # Order 1: sufficient stock -> confirmed immediately on approval.
    app_context.sample_service.register("S-STOCK", "Stocked Wafer", 10.0, 0.9)
    app_context.sample_repo.increment_stock("S-STOCK", 100)
    app_context.sample_repo.conn.commit()
    order1 = app_context.order_service.create_order("S-STOCK", "Alice", 5)
    app_context.order_service.approve(order1.order_id)

    # Order 2: insufficient stock -> PRODUCING -> tick (forced complete) -> CONFIRMED.
    app_context.sample_service.register("S-SHORT", "Short Wafer", 10.0, 1.0)
    order2 = app_context.order_service.create_order("S-SHORT", "Bob", 4)
    app_context.order_service.approve(order2.order_id)
    app_context.production_service.tick()
    job2 = app_context.job_repo.get_by_order_id(order2.order_id)
    _force_job_complete(app_context, job2)
    app_context.production_service.tick()

    return order1, order2


def test_confirmed_orders_listed(app_context, mocker):
    order1, order2 = _make_two_confirmed_orders(app_context)

    render_confirmed = mocker.patch("semi.cli.views.render_confirmed_orders")
    mocker.patch("semi.cli.views.prompt_release_selection", return_value=None)

    release_menu_controller = app_context.controllers[4]
    release_menu_controller.run()

    listed = render_confirmed.call_args.args[0]
    assert {o.order_id for o in listed} == {order1.order_id, order2.order_id}
    assert all(o.status == OrderStatus.CONFIRMED for o in listed)


def test_release_decrements_stock(app_context, mocker):
    order1, order2 = _make_two_confirmed_orders(app_context)
    stock_before_1 = app_context.sample_repo.get_by_id("S-STOCK").stock_quantity
    stock_before_2 = app_context.sample_repo.get_by_id("S-SHORT").stock_quantity

    mocker.patch("semi.cli.views.render_confirmed_orders")
    mocker.patch(
        "semi.cli.views.prompt_release_selection",
        side_effect=[order1.order_id, order2.order_id],
    )
    mocker.patch("semi.cli.views.render_release_result")

    release_menu_controller = app_context.controllers[4]
    release_menu_controller.run()  # loop ends naturally once no CONFIRMED orders remain

    updated1 = app_context.order_repo.get_by_id(order1.order_id)
    updated2 = app_context.order_repo.get_by_id(order2.order_id)
    assert updated1.status == OrderStatus.RELEASE
    assert updated2.status == OrderStatus.RELEASE

    stock_after_1 = app_context.sample_repo.get_by_id("S-STOCK").stock_quantity
    stock_after_2 = app_context.sample_repo.get_by_id("S-SHORT").stock_quantity
    assert stock_after_1 == stock_before_1 - order1.quantity
    assert stock_after_2 == stock_before_2 - order2.quantity
