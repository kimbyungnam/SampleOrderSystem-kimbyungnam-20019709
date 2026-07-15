from datetime import datetime

import pytest

from semi.storage.exceptions import NotFoundError
from semi.storage.production_job_repository import ProductionJobRepository


def test_create_inserts_row_and_returns_mapped_job(mock_conn, mocker) -> None:
    job_cls = mocker.patch("semi.storage.production_job_repository.ProductionJob")
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")
    fixed_now = datetime(2026, 1, 1, 12, 0, 0)
    mock_datetime = mocker.patch("semi.storage.production_job_repository.datetime")
    mock_datetime.now.return_value = fixed_now
    mock_conn.execute.return_value.fetchone.return_value = {
        "job_id": 1,
        "order_id": 7,
        "sample_id": "S1",
        "shortfall_quantity": 3,
        "actual_quantity": 4,
        "total_duration_seconds": 40.0,
        "status": "QUEUED",
        "enqueued_at": fixed_now.isoformat(),
        "started_at": None,
    }

    repo = ProductionJobRepository(mock_conn)
    result = repo.create(
        7, "S1", shortfall_quantity=3, actual_quantity=4, total_duration_seconds=40.0
    )

    mock_conn.execute.assert_any_call(
        "INSERT INTO production_jobs "
        "(order_id, sample_id, shortfall_quantity, actual_quantity, "
        "total_duration_seconds, status, enqueued_at, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
        (7, "S1", 3, 4, 40.0, job_status.QUEUED, fixed_now.isoformat()),
    )
    job_cls.assert_called_once_with(
        job_id=1,
        order_id=7,
        sample_id="S1",
        shortfall_quantity=3,
        actual_quantity=4,
        total_duration_seconds=40.0,
        status=job_status.return_value,
        enqueued_at=fixed_now,
        started_at=None,
    )
    assert result is job_cls.return_value


def test_get_by_order_id_raises_not_found_when_row_missing(mock_conn, mocker) -> None:
    mocker.patch("semi.storage.production_job_repository.ProductionJob")
    mocker.patch("semi.storage.production_job_repository.JobStatus")
    mock_conn.execute.return_value.fetchone.return_value = None

    repo = ProductionJobRepository(mock_conn)
    with pytest.raises(NotFoundError):
        repo.get_by_order_id(999)


def test_list_producing_with_shortfall_returns_raw_pairs(mock_conn, mocker) -> None:
    order_status = mocker.patch("semi.storage.production_job_repository.OrderStatus")
    mock_conn.execute.return_value.fetchall.return_value = [
        {"quantity": 5, "shortfall_quantity": 3},
    ]

    repo = ProductionJobRepository(mock_conn)
    result = repo.list_producing_with_shortfall("S1")

    mock_conn.execute.assert_called_once_with(
        "SELECT o.quantity, pj.shortfall_quantity FROM production_jobs pj "
        "JOIN orders o ON o.order_id = pj.order_id "
        "WHERE o.sample_id = ? AND o.status = ?",
        ("S1", order_status.PRODUCING),
    )
    assert result == [(5, 3)]


def test_get_current_in_progress_returns_none_when_empty(mock_conn, mocker) -> None:
    mocker.patch("semi.storage.production_job_repository.JobStatus")
    mock_conn.execute.return_value.fetchone.return_value = None

    repo = ProductionJobRepository(mock_conn)
    assert repo.get_current_in_progress() is None


def test_get_current_in_progress_maps_row_when_present(mock_conn, mocker) -> None:
    job_cls = mocker.patch("semi.storage.production_job_repository.ProductionJob")
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")
    mock_conn.execute.return_value.fetchone.return_value = {
        "job_id": 1,
        "order_id": 7,
        "sample_id": "S1",
        "shortfall_quantity": 3,
        "actual_quantity": 4,
        "total_duration_seconds": 40.0,
        "status": "IN_PROGRESS",
        "enqueued_at": "2026-01-01T00:00:00",
        "started_at": "2026-01-01T00:05:00",
    }

    repo = ProductionJobRepository(mock_conn)
    result = repo.get_current_in_progress()

    mock_conn.execute.assert_called_once_with(
        "SELECT * FROM production_jobs WHERE status = ?", (job_status.IN_PROGRESS,)
    )
    assert result is job_cls.return_value


def test_list_queued_fifo_orders_by_enqueued_at_then_job_id(mock_conn, mocker) -> None:
    job_cls = mocker.patch("semi.storage.production_job_repository.ProductionJob")
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "job_id": 1,
            "order_id": 1,
            "sample_id": "S1",
            "shortfall_quantity": 1,
            "actual_quantity": 2,
            "total_duration_seconds": 20.0,
            "status": "QUEUED",
            "enqueued_at": "2026-01-01T00:00:00",
            "started_at": None,
        },
        {
            "job_id": 2,
            "order_id": 2,
            "sample_id": "S1",
            "shortfall_quantity": 1,
            "actual_quantity": 2,
            "total_duration_seconds": 20.0,
            "status": "QUEUED",
            "enqueued_at": "2026-01-01T00:01:00",
            "started_at": None,
        },
    ]

    repo = ProductionJobRepository(mock_conn)
    result = repo.list_queued_fifo()

    mock_conn.execute.assert_called_once_with(
        "SELECT * FROM production_jobs WHERE status = ? ORDER BY enqueued_at, job_id",
        (job_status.QUEUED,),
    )
    assert result == [job_cls.return_value, job_cls.return_value]


def test_mark_in_progress_executes_update(mock_conn, mocker) -> None:
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")
    started_at = datetime(2026, 1, 1, 12, 0, 0)

    repo = ProductionJobRepository(mock_conn)
    repo.mark_in_progress(1, started_at)

    mock_conn.execute.assert_called_once_with(
        "UPDATE production_jobs SET status = ?, started_at = ? WHERE job_id = ?",
        (job_status.IN_PROGRESS, started_at.isoformat(), 1),
    )


def test_mark_done_executes_update(mock_conn, mocker) -> None:
    job_status = mocker.patch("semi.storage.production_job_repository.JobStatus")

    repo = ProductionJobRepository(mock_conn)
    repo.mark_done(1)

    mock_conn.execute.assert_called_once_with(
        "UPDATE production_jobs SET status = ? WHERE job_id = ?",
        (job_status.DONE, 1),
    )
