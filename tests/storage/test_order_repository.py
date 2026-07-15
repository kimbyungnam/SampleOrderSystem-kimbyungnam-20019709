from datetime import datetime

import pytest

from semi.storage.exceptions import NotFoundError
from semi.storage.order_repository import OrderRepository


def test_create_inserts_row_and_returns_mapped_order(mock_conn, mocker) -> None:
    order_cls = mocker.patch("semi.storage.order_repository.Order")
    order_status = mocker.patch("semi.storage.order_repository.OrderStatus")
    fixed_now = datetime(2026, 1, 1, 12, 0, 0)
    mock_datetime = mocker.patch("semi.storage.order_repository.datetime")
    mock_datetime.now.return_value = fixed_now
    mock_conn.execute.return_value.lastrowid = 7
    mock_conn.execute.return_value.fetchone.return_value = {
        "order_id": 7,
        "sample_id": "S1",
        "customer_name": "acme corp",
        "quantity": 5,
        "status": "RESERVED",
        "created_at": fixed_now.isoformat(),
    }

    repo = OrderRepository(mock_conn)
    result = repo.create("S1", "acme corp", 5)

    mock_conn.execute.assert_any_call(
        "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("S1", "acme corp", 5, order_status.RESERVED, fixed_now.isoformat()),
    )
    order_cls.assert_called_once_with(
        order_id=7,
        sample_id="S1",
        customer_name="acme corp",
        quantity=5,
        status=order_status.return_value,
        created_at=fixed_now,
    )
    assert result is order_cls.return_value


def test_get_by_id_raises_not_found_when_row_missing(mock_conn, mocker) -> None:
    mocker.patch("semi.storage.order_repository.Order")
    mocker.patch("semi.storage.order_repository.OrderStatus")
    mock_conn.execute.return_value.fetchone.return_value = None

    repo = OrderRepository(mock_conn)
    with pytest.raises(NotFoundError):
        repo.get_by_id(999)


def test_list_by_status_maps_every_row(mock_conn, mocker) -> None:
    order_cls = mocker.patch("semi.storage.order_repository.Order")
    mocker.patch("semi.storage.order_repository.OrderStatus")
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "order_id": 1,
            "sample_id": "S1",
            "customer_name": "acme",
            "quantity": 5,
            "status": "CONFIRMED",
            "created_at": "2026-01-01T00:00:00",
        },
    ]

    repo = OrderRepository(mock_conn)
    result = repo.list_by_status("CONFIRMED")

    mock_conn.execute.assert_called_once_with(
        "SELECT * FROM orders WHERE status = ?", ("CONFIRMED",)
    )
    assert result == [order_cls.return_value]


def test_update_status_executes_update(mock_conn) -> None:
    repo = OrderRepository(mock_conn)
    repo.update_status(1, "CONFIRMED")
    mock_conn.execute.assert_called_once_with(
        "UPDATE orders SET status = ? WHERE order_id = ?", ("CONFIRMED", 1)
    )


def test_sum_quantity_by_status_returns_total(mock_conn) -> None:
    mock_conn.execute.return_value.fetchone.return_value = {"total": 12}
    repo = OrderRepository(mock_conn)
    result = repo.sum_quantity_by_status("S1", "CONFIRMED")
    assert result == 12
    mock_conn.execute.assert_called_once_with(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
        "WHERE sample_id = ? AND status IN (?)",
        ("S1", "CONFIRMED"),
    )


def test_sum_quantity_by_statuses_returns_total(mock_conn) -> None:
    mock_conn.execute.return_value.fetchone.return_value = {"total": 15}
    repo = OrderRepository(mock_conn)
    result = repo.sum_quantity_by_statuses("S1", ["RESERVED", "CONFIRMED", "PRODUCING"])
    assert result == 15
    mock_conn.execute.assert_called_once_with(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
        "WHERE sample_id = ? AND status IN (?,?,?)",
        ("S1", "RESERVED", "CONFIRMED", "PRODUCING"),
    )
