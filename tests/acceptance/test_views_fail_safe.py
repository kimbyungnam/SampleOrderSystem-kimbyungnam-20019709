import pytest

from semi.cli import views


def test_render_main_menu_reprompts_on_invalid_input_then_exits(mocker):
    mocker.patch("builtins.input", side_effect=["abc", "99", "0"])
    result = views.render_main_menu(["A", "B"])
    assert result == "exit"


def test_render_main_menu_reprompts_on_invalid_input_then_returns_valid_index(mocker):
    mocker.patch("builtins.input", side_effect=["abc", "99", "1"])
    result = views.render_main_menu(["A", "B"])
    assert result == 0


@pytest.mark.parametrize(
    "render_func",
    [
        views.render_sample_menu,
        views.render_order_menu,
        views.render_monitoring_menu,
        views.render_production_menu,
    ],
)
def test_submenu_unrecognized_input_returns_back(render_func, mocker):
    mocker.patch("builtins.input", return_value="xyz")
    assert render_func() == "back"
