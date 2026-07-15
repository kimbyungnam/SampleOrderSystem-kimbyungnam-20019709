from semi.cli.menu_loop import main_loop


def test_main_loop_exits_immediately(app_context):
    main_loop(app_context.controllers, render_main_menu=lambda labels: "exit")


def test_main_loop_dispatches_valid_choice(app_context, mocker):
    order_menu_index = 1  # OrderMenuController, per app.py assembly order
    calls = {"n": 0}

    def render_main_menu(labels):
        calls["n"] += 1
        return order_menu_index if calls["n"] == 1 else "exit"

    run_spy = mocker.patch.object(app_context.controllers[order_menu_index], "run")

    main_loop(app_context.controllers, render_main_menu=render_main_menu)

    run_spy.assert_called_once()
    assert calls["n"] == 2


def test_main_loop_catches_domain_error_and_continues(app_context, mocker, capsys):
    order_menu_index = 1
    calls = {"n": 0}

    def render_main_menu(labels):
        calls["n"] += 1
        return order_menu_index if calls["n"] == 1 else "exit"

    mocker.patch("semi.cli.views.render_order_menu", side_effect=["create", "back"])
    mocker.patch(
        "semi.cli.views.prompt_order_creation",
        return_value={
            "sample_id": "does-not-exist",
            "customer_name": "Alice",
            "quantity": 1,
        },
    )

    main_loop(app_context.controllers, render_main_menu=render_main_menu)

    out = capsys.readouterr().out
    assert "[오류] " in out
    assert calls["n"] == 2


def test_main_loop_catches_not_found_error_and_continues(app_context, mocker, capsys):
    # A RESERVED order must exist so the controller doesn't return early,
    # but prompt_order_action is patched to target a nonexistent order_id
    # so OrderService.approve raises NotFoundError.
    app_context.sample_service.register("S1", "Wafer A", 10.0, 0.9)
    app_context.order_service.create_order("S1", "Alice", 1)

    order_menu_index = 1
    calls = {"n": 0}

    def render_main_menu(labels):
        calls["n"] += 1
        return order_menu_index if calls["n"] == 1 else "exit"

    mocker.patch(
        "semi.cli.views.render_order_menu", side_effect=["approve_reject", "back"]
    )
    mocker.patch("semi.cli.views.render_reserved_orders")
    mocker.patch("semi.cli.views.prompt_order_action", return_value=(999999, "approve"))

    main_loop(app_context.controllers, render_main_menu=render_main_menu)

    out = capsys.readouterr().out
    assert "[조회 실패] " in out
    assert calls["n"] == 2
