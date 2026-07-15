import threading
import time

import pytest

from semi.domain.models import JobStatus, OrderStatus
from semi.scheduler.background_worker import start_worker
from semi.services.order_service import OrderService
from semi.storage.db import connect_db
from semi.storage.order_repository import OrderRepository
from semi.storage.production_job_repository import ProductionJobRepository
from semi.storage.sample_repository import SampleRepository


def test_start_worker_returns_running_daemon_thread(tmp_path):
    db_path = tmp_path / "worker_smoke.db"
    lock = threading.Lock()

    thread = start_worker(db_path, lock)

    assert isinstance(thread, threading.Thread)
    assert thread.daemon is True
    assert thread.is_alive()


def test_start_worker_ticks_and_completes_queued_production(tmp_path):
    db_path = tmp_path / "worker_completion.db"
    conn = connect_db(db_path)
    sample_repo = SampleRepository(conn)
    order_repo = OrderRepository(conn)
    job_repo = ProductionJobRepository(conn)
    lock = threading.Lock()
    order_service = OrderService(order_repo, job_repo, sample_repo, lock)

    sample_repo.create("S1", "Wafer A", 0.05, 1.0)
    conn.commit()
    order = order_service.create_order("S1", "ACME", 3)
    order_service.approve(order.order_id)  # stock=0 < 3 -> PRODUCING, actual_quantity=3

    start_worker(db_path, lock)

    deadline = time.monotonic() + 3.0
    updated_status = None
    while time.monotonic() < deadline:
        updated_status = order_repo.get_by_id(order.order_id).status
        if updated_status == OrderStatus.CONFIRMED:
            break
        time.sleep(0.05)
    else:
        pytest.fail(
            f"production job did not complete in time, last status={updated_status}"
        )

    assert sample_repo.get_by_id("S1").stock_quantity == 3
    assert job_repo.get_by_order_id(order.order_id).status == JobStatus.DONE

    conn.close()
