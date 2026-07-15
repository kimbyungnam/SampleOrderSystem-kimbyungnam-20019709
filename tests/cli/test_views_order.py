from datetime import datetime

from semi.cli import views
from semi.domain.models import Order, OrderStatus


def _order(order_id=1, status=OrderStatus.RESERVED, quantity=5):
    return Order(order_id, "S1", "ACME", quantity, status, datetime.now())


def test_render_order_menu_maps_known_inputs(mocker):
    mocker.patch("builtins.input", return_value="1")
    assert views.render_order_menu() == "create"

    mocker.patch("builtins.input", return_value="2")
    assert views.render_order_menu() == "approve_reject"

    mocker.patch("builtins.input", return_value="0")
    assert views.render_order_menu() == "back"


def test_render_order_menu_maps_unrecognized_input_to_back(mocker):
    mocker.patch("builtins.input", return_value="xyz")
    assert views.render_order_menu() == "back"


def test_prompt_order_creation_collects_fields(mocker):
    mocker.patch("builtins.input", side_effect=["S1", "ACME", "5"])

    data = views.prompt_order_creation()

    assert data == {"sample_id": "S1", "customer_name": "ACME", "quantity": 5}


def test_prompt_order_creation_reprompts_on_invalid_quantity(mocker, capsys):
    mocker.patch("builtins.input", side_effect=["S1", "ACME", "not-a-number", "5"])

    data = views.prompt_order_creation()

    assert data["quantity"] == 5
    assert "[오류]" in capsys.readouterr().out


def test_render_order_created_prints_order_id(capsys):
    views.render_order_created(_order(order_id=7))
    assert "7" in capsys.readouterr().out


def test_render_reserved_orders_prints_each_order(capsys):
    orders = [_order(order_id=1), _order(order_id=2, quantity=3)]

    views.render_reserved_orders(orders)

    out = capsys.readouterr().out
    assert "1" in out and "2" in out


def test_render_reserved_orders_handles_empty_list(capsys):
    views.render_reserved_orders([])
    assert "없습니다" in capsys.readouterr().out


def test_prompt_order_action_returns_approve_for_valid_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", side_effect=["3", "a"])

    result = views.prompt_order_action(orders)

    assert result == (3, "approve")


def test_prompt_order_action_returns_reject_for_valid_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", side_effect=["3", "r"])

    result = views.prompt_order_action(orders)

    assert result == (3, "reject")


def test_prompt_order_action_returns_none_for_back_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", return_value="0")

    assert views.prompt_order_action(orders) is None


def test_prompt_order_action_returns_none_for_unknown_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", return_value="99")

    assert views.prompt_order_action(orders) is None


def test_prompt_order_action_returns_none_for_non_numeric_id(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", return_value="abc")

    assert views.prompt_order_action(orders) is None


def test_prompt_order_action_returns_none_for_unrecognized_action(mocker):
    orders = [_order(order_id=3)]
    mocker.patch("builtins.input", side_effect=["3", "z"])

    assert views.prompt_order_action(orders) is None


def test_render_order_result_prints_status(capsys):
    views.render_order_result(_order(order_id=3, status=OrderStatus.CONFIRMED))
    out = capsys.readouterr().out
    assert "3" in out
    assert "CONFIRMED" in out
