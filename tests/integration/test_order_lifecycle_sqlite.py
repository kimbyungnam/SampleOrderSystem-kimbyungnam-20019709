"""Cross-layer integration tests against a real (temp-file) SQLite database.

Unlike tests/test_lifecycle.py (which uses the in-memory fakes from
tests/test_fakes.py), these tests exercise the storage layer's real SQL
against an actual SQLite connection created via semi.storage.db.connect_db,
wired up to the real service layer.
"""

import math
from datetime import datetime, timedelta

import pytest

from semi.domain.models import JobStatus, OrderStatus
from semi.services.exceptions import DomainError
from semi.storage.exceptions import NotFoundError


def _force_job_complete(real_db, job):
    """Push a job's started_at far enough into the past that tick() will
    treat it as finished, using the same technique as test_lifecycle.py."""
    real_db.job_repo.mark_in_progress(
        job.job_id,
        datetime.now() - timedelta(seconds=job.total_duration_seconds + 1),
    )


def test_happy_path_full_lifecycle(real_db):
    # Sample starts with 0 stock, so approving the order will always take
    # the PRODUCING branch (available stock = 0 < any positive quantity).
    real_db.sample_repo.create("S1", "Wafer A", 10.0, 0.9)

    # 1. create_order -> RESERVED
    order = real_db.order_service.create_order("S1", "ACME", 5)
    assert order.status == OrderStatus.RESERVED

    # 2. approve -> PRODUCING (available = 0 < 5 -> shortfall = 5)
    approved = real_db.order_service.approve(order.order_id)
    assert approved.status == OrderStatus.PRODUCING

    job = real_db.job_repo.get_by_order_id(order.order_id)
    assert job.shortfall_quantity == 5
    assert job.actual_quantity == 6  # ceil(5 / 0.9) == 6
    assert job.total_duration_seconds == 60.0  # 10 * 6

    # 3. tick() promotes QUEUED -> IN_PROGRESS (first tick is a no-op
    # completion-wise)
    real_db.production_service.tick()
    in_progress_job = real_db.job_repo.get_by_order_id(order.order_id)
    assert in_progress_job.started_at is not None
    assert real_db.order_repo.get_by_id(order.order_id).status == OrderStatus.PRODUCING

    # Force the job to look like it started long enough ago to be complete.
    _force_job_complete(real_db, in_progress_job)

    # 4. second tick() completes the job -> stock incremented, order CONFIRMED
    real_db.production_service.tick()
    confirmed = real_db.order_repo.get_by_id(order.order_id)
    assert confirmed.status == OrderStatus.CONFIRMED

    stock_after_production = real_db.sample_repo.get_by_id("S1").stock_quantity
    assert stock_after_production == job.actual_quantity == 6

    # 5. release -> RELEASE, stock decremented by order quantity
    released = real_db.order_service.release(order.order_id)
    assert released.status == OrderStatus.RELEASE

    final_stock = real_db.sample_repo.get_by_id("S1").stock_quantity
    assert final_stock == stock_after_production - order.quantity
    assert final_stock == 1  # 6 - 5 = 1
    assert final_stock >= 0  # anti-oversell invariant holds end-to-end


def test_sufficient_stock_confirms_immediately_without_job(real_db):
    real_db.sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    real_db.sample_repo.increment_stock("S1", 100)

    order = real_db.order_service.create_order("S1", "ACME", 5)
    approved = real_db.order_service.approve(order.order_id)

    assert approved.status == OrderStatus.CONFIRMED
    # No production job should have been created for this order.
    with pytest.raises(NotFoundError):
        real_db.job_repo.get_by_order_id(order.order_id)

    # Stock is untouched at approval time (only released/produced stock
    # ever changes stock_quantity).
    assert real_db.sample_repo.get_by_id("S1").stock_quantity == 100


def test_reject_locks_order_and_leaves_stock_untouched(real_db):
    real_db.sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    real_db.sample_repo.increment_stock("S1", 100)

    order = real_db.order_service.create_order("S1", "ACME", 5)
    rejected = real_db.order_service.reject(order.order_id)
    assert rejected.status == OrderStatus.REJECTED

    with pytest.raises(DomainError):
        real_db.order_service.approve(order.order_id)
    with pytest.raises(DomainError):
        real_db.order_service.release(order.order_id)

    assert real_db.order_repo.get_by_id(order.order_id).status == OrderStatus.REJECTED
    assert real_db.sample_repo.get_by_id("S1").stock_quantity == 100


def test_fifo_queue_processes_jobs_in_enqueued_order(real_db):
    real_db.sample_repo.create("S1", "Wafer A", 10.0, 1.0)  # stock=0

    order1 = real_db.order_service.create_order("S1", "ACME", 3)
    order2 = real_db.order_service.create_order("S1", "ACME", 4)

    approved1 = real_db.order_service.approve(order1.order_id)
    approved2 = real_db.order_service.approve(order2.order_id)
    assert approved1.status == OrderStatus.PRODUCING
    assert approved2.status == OrderStatus.PRODUCING

    job1 = real_db.job_repo.get_by_order_id(order1.order_id)
    job2 = real_db.job_repo.get_by_order_id(order2.order_id)

    # First tick promotes only the earliest-enqueued job (job1) to
    # IN_PROGRESS; job2 stays QUEUED.
    real_db.production_service.tick()
    job1_after = real_db.job_repo.get_by_order_id(order1.order_id)
    job2_after = real_db.job_repo.get_by_order_id(order2.order_id)
    assert job1_after.status == JobStatus.IN_PROGRESS
    assert job2_after.status == JobStatus.QUEUED
    assert real_db.job_repo.get_current_in_progress().job_id == job1.job_id

    # Complete job1.
    _force_job_complete(real_db, job1_after)
    real_db.production_service.tick()

    order1_final = real_db.order_repo.get_by_id(order1.order_id)
    assert order1_final.status == OrderStatus.CONFIRMED
    assert real_db.job_repo.get_by_order_id(order1.order_id).status == JobStatus.DONE

    # job2 should now have been promoted to IN_PROGRESS by the same tick()
    # that completed job1 (production_service._promote_if_idle runs again
    # after completion).
    job2_promoted = real_db.job_repo.get_by_order_id(order2.order_id)
    assert job2_promoted.status == JobStatus.IN_PROGRESS
    assert real_db.job_repo.get_current_in_progress().job_id == job2.job_id


def test_available_stock_invariant_holds_with_confirmed_and_producing(real_db):
    real_db.sample_repo.create("S1", "Wafer A", 10.0, 1.0)

    def unreleased_confirmed_sum():
        return real_db.order_repo.sum_quantity_by_status("S1", OrderStatus.CONFIRMED)

    def invariant_holds():
        stock = real_db.sample_repo.get_by_id("S1").stock_quantity
        return stock >= unreleased_confirmed_sum()

    # Give enough stock so the first order confirms immediately.
    real_db.sample_repo.increment_stock("S1", 5)
    assert invariant_holds()

    order_confirmed = real_db.order_service.create_order("S1", "ACME", 5)
    approved_confirmed = real_db.order_service.approve(order_confirmed.order_id)
    assert approved_confirmed.status == OrderStatus.CONFIRMED
    assert invariant_holds()

    # Now stock is fully claimed by the CONFIRMED order (available == 0),
    # so a second order goes PRODUCING.
    order_producing = real_db.order_service.create_order("S1", "ACME", 3)
    approved_producing = real_db.order_service.approve(order_producing.order_id)
    assert approved_producing.status == OrderStatus.PRODUCING
    assert invariant_holds()

    job = real_db.job_repo.get_by_order_id(order_producing.order_id)
    real_db.production_service.tick()
    assert invariant_holds()

    _force_job_complete(
        real_db, real_db.job_repo.get_by_order_id(order_producing.order_id)
    )
    real_db.production_service.tick()
    assert invariant_holds()
    assert (
        real_db.order_repo.get_by_id(order_producing.order_id).status
        == OrderStatus.CONFIRMED
    )

    # Releasing the first CONFIRMED order must never fail for insufficient
    # stock, by construction of the invariant.
    released = real_db.order_service.release(order_confirmed.order_id)
    assert released.status == OrderStatus.RELEASE
    assert invariant_holds()
    assert job.actual_quantity == math.ceil(3 / 1.0)


def test_queued_job_is_never_recalculated(real_db):
    real_db.sample_repo.create("S1", "Wafer A", 10.0, 1.0)  # stock=0

    order1 = real_db.order_service.create_order("S1", "ACME", 3)
    order2 = real_db.order_service.create_order("S1", "ACME", 4)
    real_db.order_service.approve(order1.order_id)
    real_db.order_service.approve(order2.order_id)

    job2_before = real_db.job_repo.get_by_order_id(order2.order_id)
    assert job2_before.status == JobStatus.QUEUED
    original_actual_quantity = job2_before.actual_quantity
    original_total_duration = job2_before.total_duration_seconds

    # Promote and complete job1, which changes the sample's stock while
    # job2 is still sitting in the QUEUED state.
    real_db.production_service.tick()
    job1 = real_db.job_repo.get_by_order_id(order1.order_id)
    _force_job_complete(real_db, job1)
    real_db.production_service.tick()

    assert real_db.sample_repo.get_by_id("S1").stock_quantity > 0

    job2_after = real_db.job_repo.get_by_order_id(order2.order_id)
    # job2 may now be IN_PROGRESS (promoted once job1 finished) but its
    # computed quantity/duration must be untouched from when it was queued.
    assert job2_after.actual_quantity == original_actual_quantity
    assert job2_after.total_duration_seconds == original_total_duration


def test_monitoring_stock_status_classification(real_db):
    # DEPLETED: stock_quantity == 0 takes priority regardless of demand.
    real_db.sample_repo.create("DEPLETED", "Depleted Sample", 10.0, 1.0)

    # SUFFICIENT: stock_quantity >= outstanding.
    real_db.sample_repo.create("SUFFICIENT", "Sufficient Sample", 10.0, 1.0)
    real_db.sample_repo.increment_stock("SUFFICIENT", 10)
    real_db.order_service.create_order("SUFFICIENT", "ACME", 5)  # RESERVED, counts

    # SHORT: 0 < stock_quantity < outstanding.
    real_db.sample_repo.create("SHORT", "Short Sample", 10.0, 1.0)
    real_db.sample_repo.increment_stock("SHORT", 2)
    real_db.order_service.create_order("SHORT", "ACME", 5)  # RESERVED, counts

    statuses = {
        s.sample.sample_id: s for s in real_db.monitoring_service.stock_status()
    }

    from semi.services.monitoring_service import StockStatus

    assert statuses["DEPLETED"].status == StockStatus.DEPLETED
    assert statuses["SUFFICIENT"].status == StockStatus.SUFFICIENT
    assert statuses["SUFFICIENT"].outstanding == 5
    assert statuses["SHORT"].status == StockStatus.SHORT
    assert statuses["SHORT"].outstanding == 5
