from datetime import timedelta

import pytest


def _assert_close_status(actual, expected):
    """ProductionJobStatus.progress_ratio/produced_so_far are computed from
    datetime.now() at call time, so two independent calls (one inside run(),
    one in the test for comparison) will differ by whatever wall-clock time
    elapsed between them. Compare the deterministic fields exactly and the
    time-derived fields with a generous tolerance instead of exact equality."""
    assert actual.job == expected.job
    assert actual.estimated_completion_at == expected.estimated_completion_at
    assert abs(actual.progress_ratio - expected.progress_ratio) < 0.5
    assert abs(actual.produced_so_far - expected.produced_so_far) <= 1


@pytest.fixture
def two_queued_jobs(app_context):
    app_context.sample_service.register("S1", "Wafer A", 10.0, 1.0)
    order1 = app_context.order_service.create_order("S1", "Alice", 3)
    order2 = app_context.order_service.create_order("S1", "Bob", 2)
    app_context.order_service.approve(order1.order_id)
    app_context.order_service.approve(order2.order_id)
    app_context.production_service.tick()
    return app_context


def test_current_production_status(two_queued_jobs, mocker):
    app_context = two_queued_jobs
    mocker.patch(
        "semi.cli.views.render_production_menu", side_effect=["current", "back"]
    )
    render_current = mocker.patch("semi.cli.views.render_current_production")

    production_menu_controller = app_context.controllers[3]
    production_menu_controller.run()

    assert render_current.call_count == 1
    actual = render_current.call_args.args[0]
    expected = app_context.production_service.get_current_status()
    _assert_close_status(actual, expected)


def test_production_queue(two_queued_jobs, mocker):
    app_context = two_queued_jobs
    mocker.patch("semi.cli.views.render_production_menu", side_effect=["queue", "back"])
    render_queue = mocker.patch("semi.cli.views.render_production_queue")

    production_menu_controller = app_context.controllers[3]
    production_menu_controller.run()

    assert render_queue.call_count == 1
    actual_list = render_queue.call_args.args[0]
    expected_list = app_context.production_service.list_queue_status()
    assert len(actual_list) == len(expected_list) == 1
    actual, expected = actual_list[0], expected_list[0]
    assert actual.job == expected.job
    assert (
        abs(
            (actual.estimated_completion_at - expected.estimated_completion_at)
            / timedelta(seconds=1)
        )
        < 1.0
    )


def test_unrecognized_choice_is_safe(app_context, mocker):
    mocker.patch("builtins.input", return_value="xyz")

    production_menu_controller = app_context.controllers[3]
    production_menu_controller.run()  # should return via "back" without crashing
