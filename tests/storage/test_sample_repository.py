import pytest

from semi.storage.exceptions import NotFoundError
from semi.storage.sample_repository import SampleRepository


def test_create_inserts_row_and_returns_mapped_sample(mock_conn, mocker) -> None:
    sample_cls = mocker.patch("semi.storage.sample_repository.Sample")
    mock_conn.execute.return_value.fetchone.return_value = {
        "sample_id": "S1",
        "name": "wafer",
        "avg_production_seconds": 10.0,
        "yield_rate": 0.9,
        "stock_quantity": 0,
    }

    repo = SampleRepository(mock_conn)
    result = repo.create("S1", "wafer", 10.0, 0.9)

    mock_conn.execute.assert_any_call(
        "INSERT INTO samples "
        "(sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
        "VALUES (?, ?, ?, ?, 0)",
        ("S1", "wafer", 10.0, 0.9),
    )
    sample_cls.assert_called_once_with(
        sample_id="S1",
        name="wafer",
        avg_production_seconds=10.0,
        yield_rate=0.9,
        stock_quantity=0,
    )
    assert result is sample_cls.return_value


def test_get_by_id_raises_not_found_when_row_missing(mock_conn, mocker) -> None:
    mocker.patch("semi.storage.sample_repository.Sample")
    mock_conn.execute.return_value.fetchone.return_value = None

    repo = SampleRepository(mock_conn)
    with pytest.raises(NotFoundError):
        repo.get_by_id("missing")


def test_exists_true_when_row_found(mock_conn) -> None:
    mock_conn.execute.return_value.fetchone.return_value = {"1": 1}
    repo = SampleRepository(mock_conn)
    assert repo.exists("S1") is True
    mock_conn.execute.assert_called_once_with(
        "SELECT 1 FROM samples WHERE sample_id = ?", ("S1",)
    )


def test_exists_false_when_row_missing(mock_conn) -> None:
    mock_conn.execute.return_value.fetchone.return_value = None
    repo = SampleRepository(mock_conn)
    assert repo.exists("S1") is False


def test_list_all_maps_every_row(mock_conn, mocker) -> None:
    sample_cls = mocker.patch("semi.storage.sample_repository.Sample")
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "sample_id": "S1",
            "name": "a",
            "avg_production_seconds": 1.0,
            "yield_rate": 0.5,
            "stock_quantity": 1,
        },
        {
            "sample_id": "S2",
            "name": "b",
            "avg_production_seconds": 2.0,
            "yield_rate": 0.6,
            "stock_quantity": 2,
        },
    ]

    repo = SampleRepository(mock_conn)
    result = repo.list_all()

    mock_conn.execute.assert_called_once_with("SELECT * FROM samples")
    assert sample_cls.call_count == 2
    assert result == [sample_cls.return_value, sample_cls.return_value]


def test_search_by_name_uses_like_query(mock_conn, mocker) -> None:
    sample_cls = mocker.patch("semi.storage.sample_repository.Sample")
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "sample_id": "S1",
            "name": "wafer-a",
            "avg_production_seconds": 1.0,
            "yield_rate": 0.5,
            "stock_quantity": 1,
        },
    ]

    repo = SampleRepository(mock_conn)
    result = repo.search_by_name("wafer")

    mock_conn.execute.assert_called_once_with(
        "SELECT * FROM samples WHERE name LIKE ?", ("%wafer%",)
    )
    assert result == [sample_cls.return_value]


def test_increment_stock_executes_update(mock_conn) -> None:
    repo = SampleRepository(mock_conn)
    repo.increment_stock("S1", 5)
    mock_conn.execute.assert_called_once_with(
        "UPDATE samples SET stock_quantity = stock_quantity + ? WHERE sample_id = ?",
        (5, "S1"),
    )


def test_decrement_stock_executes_update(mock_conn) -> None:
    repo = SampleRepository(mock_conn)
    repo.decrement_stock("S1", 2)
    mock_conn.execute.assert_called_once_with(
        "UPDATE samples SET stock_quantity = stock_quantity - ? WHERE sample_id = ?",
        (2, "S1"),
    )
