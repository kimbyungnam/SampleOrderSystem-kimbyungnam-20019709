from semi.cli import views
from semi.domain.models import Sample


def test_render_main_menu_returns_zero_based_index_for_valid_choice(mocker, capsys):
    mocker.patch("builtins.input", return_value="2")

    result = views.render_main_menu(["시료 관리", "주문 접수"])

    assert result == 1
    out = capsys.readouterr().out
    assert "1. 시료 관리" in out
    assert "2. 주문 접수" in out


def test_render_main_menu_returns_exit_for_zero():
    import builtins

    original_input = builtins.input
    builtins.input = lambda *_: "0"
    try:
        assert views.render_main_menu(["시료 관리"]) == "exit"
    finally:
        builtins.input = original_input


def test_render_main_menu_reprompts_on_non_numeric_then_out_of_range_then_valid(mocker, capsys):
    mocker.patch("builtins.input", side_effect=["abc", "9", "1"])

    result = views.render_main_menu(["시료 관리"])

    assert result == 0
    out = capsys.readouterr().out
    assert out.count("[오류]") == 2


def test_render_sample_menu_maps_known_inputs(mocker):
    mocker.patch("builtins.input", return_value="1")
    assert views.render_sample_menu() == "register"

    mocker.patch("builtins.input", return_value="2")
    assert views.render_sample_menu() == "list"

    mocker.patch("builtins.input", return_value="3")
    assert views.render_sample_menu() == "search"

    mocker.patch("builtins.input", return_value="0")
    assert views.render_sample_menu() == "back"


def test_render_sample_menu_maps_unrecognized_input_to_back(mocker):
    mocker.patch("builtins.input", return_value="garbage")
    assert views.render_sample_menu() == "back"


def test_prompt_sample_registration_collects_all_fields(mocker):
    mocker.patch(
        "builtins.input", side_effect=["S1", "Wafer A", "12.5", "0.9"]
    )

    data = views.prompt_sample_registration()

    assert data == {
        "sample_id": "S1",
        "name": "Wafer A",
        "avg_production_seconds": 12.5,
        "yield_rate": 0.9,
    }


def test_prompt_sample_registration_reprompts_on_invalid_number(mocker, capsys):
    mocker.patch(
        "builtins.input",
        side_effect=["S1", "Wafer A", "not-a-number", "12.5", "0.9"],
    )

    data = views.prompt_sample_registration()

    assert data["avg_production_seconds"] == 12.5
    assert "[오류]" in capsys.readouterr().out


def test_prompt_search_query_returns_stripped_input(mocker):
    mocker.patch("builtins.input", return_value="  Wafer  ")
    assert views.prompt_search_query() == "Wafer"


def test_render_sample_list_prints_each_sample(capsys):
    samples = [Sample("S1", "Wafer A", 10.0, 0.9, 5)]

    views.render_sample_list(samples)

    out = capsys.readouterr().out
    assert "S1" in out
    assert "Wafer A" in out
    assert "5" in out


def test_render_sample_registered_prints_sample_id(capsys):
    sample = Sample("S1", "Wafer A", 10.0, 0.9, 0)

    views.render_sample_registered(sample)

    assert "S1" in capsys.readouterr().out
