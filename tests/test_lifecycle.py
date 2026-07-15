from datetime import datetime, timedelta

from semi.domain.models import OrderStatus
from semi.services.order_service import OrderService
from semi.services.production_service import ProductionService


def test_order_lifecycle_reserved_producing_confirmed_release(
    sample_repo, order_repo, job_repo, lock
):
    # Sample starts with 0 stock, so approving the order will always take the
    # PRODUCING branch (available stock = 0 < any positive quantity).
    sample_repo.create(
        "S1", "Wafer A", 10.0, 0.9
    )  # avg_production_seconds=10, yield_rate=0.9

    order_service = OrderService(order_repo, job_repo, sample_repo, lock)
    production_service = ProductionService(order_repo, job_repo, sample_repo, lock)

    # 1. create_order -> RESERVED
    order = order_service.create_order("S1", "ACME", 5)
    assert order.status == OrderStatus.RESERVED

    # 2. approve -> PRODUCING (available = 0 < 5 -> shortfall = 5)
    approved = order_service.approve(order.order_id)
    assert approved.status == OrderStatus.PRODUCING

    job = job_repo.get_by_order_id(order.order_id)
    assert job.shortfall_quantity == 5
    assert job.actual_quantity == 6  # ceil(5 / 0.9) == 6
    assert job.total_duration_seconds == 60.0  # 10 * 6

    # 3. tick() promotes QUEUED -> IN_PROGRESS (first tick is a no-op completion-wise)
    production_service.tick()
    in_progress_job = job_repo.get_by_order_id(order.order_id)
    assert in_progress_job.started_at is not None
    # Order is still PRODUCING; job hasn't had time to complete yet.
    assert order_repo.get_by_id(order.order_id).status == OrderStatus.PRODUCING

    # Force the job to look like it started long enough ago to be complete.
    job_repo.mark_in_progress(
        in_progress_job.job_id,
        datetime.now() - timedelta(seconds=in_progress_job.total_duration_seconds + 1),
    )

    # 4. second tick() completes the job -> stock incremented, order CONFIRMED
    production_service.tick()
    confirmed = order_repo.get_by_id(order.order_id)
    assert confirmed.status == OrderStatus.CONFIRMED

    stock_after_production = sample_repo.get_by_id("S1").stock_quantity
    assert stock_after_production == job.actual_quantity == 6

    # 5. release -> RELEASE, stock decremented by order quantity
    released = order_service.release(order.order_id)
    assert released.status == OrderStatus.RELEASE

    final_stock = sample_repo.get_by_id("S1").stock_quantity
    assert final_stock == stock_after_production - order.quantity
    assert final_stock == 1  # 6 - 5 = 1
    assert final_stock >= 0  # anti-oversell invariant holds end-to-end
