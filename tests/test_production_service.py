from datetime import datetime, timedelta

import pytest

from semi.domain.models import JobStatus, OrderStatus
from semi.services.production_service import ProductionService


@pytest.fixture
def production_service(order_repo, job_repo, sample_repo, lock):
    return ProductionService(order_repo, job_repo, sample_repo, lock)


def test_constructor_asserts_shared_connection(job_repo, sample_repo, lock):
    from tests.conftest import FakeConnection, FakeOrderRepository

    mismatched_order_repo = FakeOrderRepository(FakeConnection())
    with pytest.raises(AssertionError):
        ProductionService(mismatched_order_repo, job_repo, sample_repo, lock)


def test_tick_promotes_oldest_queued_job_to_in_progress_when_idle(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(order.order_id, OrderStatus.PRODUCING)
    job = job_repo.create(
        order.order_id,
        "S1",
        shortfall_quantity=5,
        actual_quantity=6,
        total_duration_seconds=60.0,
    )

    production_service.tick()

    in_progress = job_repo.get_current_in_progress()
    assert in_progress.job_id == job.job_id
    assert in_progress.status == JobStatus.IN_PROGRESS
    assert in_progress.started_at is not None


def test_tick_does_nothing_when_in_progress_job_not_yet_complete(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(order.order_id, OrderStatus.PRODUCING)
    job = job_repo.create(order.order_id, "S1", 5, 6, total_duration_seconds=999.0)
    job_repo.mark_in_progress(job.job_id, datetime.now())

    production_service.tick()

    assert job_repo.get_current_in_progress().status == JobStatus.IN_PROGRESS
    assert sample_repo.get_by_id("S1").stock_quantity == 0
    assert order_repo.get_by_id(order.order_id).status == OrderStatus.PRODUCING


def test_tick_completes_job_increments_stock_confirms_order_and_promotes_next(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    finishing_order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(finishing_order.order_id, OrderStatus.PRODUCING)
    finishing_job = job_repo.create(
        finishing_order.order_id, "S1", 5, 6, total_duration_seconds=30.0
    )
    job_repo.mark_in_progress(
        finishing_job.job_id, datetime.now() - timedelta(seconds=31)
    )

    next_order = order_repo.create("S1", "ACME", 2)
    order_repo.update_status(next_order.order_id, OrderStatus.PRODUCING)
    next_job = job_repo.create(
        next_order.order_id, "S1", 2, 3, total_duration_seconds=20.0
    )

    production_service.tick()

    assert job_repo.get_by_order_id(finishing_order.order_id).status == JobStatus.DONE
    assert sample_repo.get_by_id("S1").stock_quantity == 6
    assert (
        order_repo.get_by_id(finishing_order.order_id).status == OrderStatus.CONFIRMED
    )

    promoted = job_repo.get_current_in_progress()
    assert promoted.job_id == next_job.job_id
    assert promoted.started_at is not None


def test_tick_with_no_queued_or_in_progress_jobs_is_a_no_op(production_service):
    production_service.tick()  # must not raise


def test_get_current_status_returns_none_when_nothing_in_progress(production_service):
    assert production_service.get_current_status() is None


def test_get_current_status_reports_progress_ratio_and_produced_so_far(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(order.order_id, OrderStatus.PRODUCING)
    job = job_repo.create(order.order_id, "S1", 5, 6, total_duration_seconds=60.0)
    started_at = datetime.now() - timedelta(seconds=30)
    job_repo.mark_in_progress(job.job_id, started_at)

    status = production_service.get_current_status()

    assert status.job.job_id == job.job_id
    assert status.progress_ratio == pytest.approx(0.5, abs=0.05)
    assert status.produced_so_far == 3  # floor(0.5 * 6)
    assert status.estimated_completion_at == started_at + timedelta(seconds=60.0)


def test_get_current_status_caps_progress_ratio_at_one_when_overdue(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(order.order_id, OrderStatus.PRODUCING)
    job = job_repo.create(order.order_id, "S1", 5, 6, total_duration_seconds=10.0)
    job_repo.mark_in_progress(job.job_id, datetime.now() - timedelta(seconds=100))

    status = production_service.get_current_status()

    assert status.progress_ratio == 1.0
    assert status.produced_so_far == 6


def test_list_queue_status_is_empty_when_no_queued_jobs(production_service):
    assert production_service.list_queue_status() == []


def test_list_queue_status_accumulates_remaining_time_of_current_and_preceding_jobs(
    production_service, sample_repo, order_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)

    current_order = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(current_order.order_id, OrderStatus.PRODUCING)
    current_job = job_repo.create(
        current_order.order_id, "S1", 1, 1, total_duration_seconds=100.0
    )
    job_repo.mark_in_progress(
        current_job.job_id, datetime.now() - timedelta(seconds=40)
    )
    # current job has ~60s remaining

    first_queued_order = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(first_queued_order.order_id, OrderStatus.PRODUCING)
    first_queued_job = job_repo.create(
        first_queued_order.order_id, "S1", 1, 1, total_duration_seconds=20.0
    )

    second_queued_order = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(second_queued_order.order_id, OrderStatus.PRODUCING)
    second_queued_job = job_repo.create(
        second_queued_order.order_id, "S1", 1, 1, total_duration_seconds=30.0
    )

    statuses = production_service.list_queue_status()

    assert [s.job.job_id for s in statuses] == [
        first_queued_job.job_id,
        second_queued_job.job_id,
    ]
    first_remaining_seconds = (
        statuses[0].estimated_completion_at - datetime.now()
    ).total_seconds()
    assert first_remaining_seconds == pytest.approx(60 + 20, abs=2)
    second_remaining_seconds = (
        statuses[1].estimated_completion_at - datetime.now()
    ).total_seconds()
    assert second_remaining_seconds == pytest.approx(60 + 20 + 30, abs=2)
    assert statuses[0].progress_ratio == 0.0
    assert statuses[0].produced_so_far == 0
