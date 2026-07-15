def test_register_then_list_then_search(app_context, mocker):
    mocker.patch(
        "semi.cli.views.render_sample_menu",
        side_effect=["register", "list", "search", "back"],
    )
    mocker.patch(
        "semi.cli.views.prompt_sample_registration",
        return_value={
            "sample_id": "S1",
            "name": "Wafer A",
            "avg_production_seconds": 10.0,
            "yield_rate": 0.9,
        },
    )
    mocker.patch("semi.cli.views.prompt_search_query", return_value="Wafer")
    render_registered = mocker.patch("semi.cli.views.render_sample_registered")
    render_list = mocker.patch("semi.cli.views.render_sample_list")

    sample_menu_controller = app_context.controllers[0]
    sample_menu_controller.run()

    registered = app_context.sample_repo.get_by_id("S1")
    assert registered.name == "Wafer A"
    assert registered.avg_production_seconds == 10.0
    assert registered.yield_rate == 0.9

    render_registered.assert_called_once_with(registered)

    assert render_list.call_count == 2
    list_call_args = render_list.call_args_list[0].args[0]
    assert list_call_args == app_context.sample_service.list_all()
    search_call_args = render_list.call_args_list[1].args[0]
    assert search_call_args == app_context.sample_service.search_by_name("Wafer")
    assert [s.sample_id for s in search_call_args] == ["S1"]
