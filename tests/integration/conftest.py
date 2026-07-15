import threading
from dataclasses import dataclass

import pytest

from semi.services.monitoring_service import MonitoringService
from semi.services.order_service import OrderService
from semi.services.production_service import ProductionService
from semi.services.sample_service import SampleService
from semi.storage.db import connect_db
from semi.storage.order_repository import OrderRepository
from semi.storage.production_job_repository import ProductionJobRepository
from semi.storage.sample_repository import SampleRepository


@dataclass
class RealDB:
    sample_repo: SampleRepository
    order_repo: OrderRepository
    job_repo: ProductionJobRepository
    lock: threading.Lock
    sample_service: SampleService
    order_service: OrderService
    production_service: ProductionService
    monitoring_service: MonitoringService


@pytest.fixture
def real_db(tmp_path):
    conn = connect_db(tmp_path / "test.db")
    try:
        sample_repo = SampleRepository(conn)
        order_repo = OrderRepository(conn)
        job_repo = ProductionJobRepository(conn)
        lock = threading.Lock()

        yield RealDB(
            sample_repo=sample_repo,
            order_repo=order_repo,
            job_repo=job_repo,
            lock=lock,
            sample_service=SampleService(sample_repo),
            order_service=OrderService(order_repo, job_repo, sample_repo, lock),
            production_service=ProductionService(
                order_repo, job_repo, sample_repo, lock
            ),
            monitoring_service=MonitoringService(order_repo, sample_repo),
        )
    finally:
        conn.close()
