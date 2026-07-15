import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from semi.cli.controllers import (
    MonitoringMenuController,
    OrderMenuController,
    ProductionMenuController,
    ReleaseMenuController,
    SampleMenuController,
)
from semi.cli.menu_loop import MenuController
from semi.services.monitoring_service import MonitoringService
from semi.services.order_service import OrderService
from semi.services.production_service import ProductionService
from semi.services.sample_service import SampleService
from semi.storage.db import connect_db
from semi.storage.order_repository import OrderRepository
from semi.storage.production_job_repository import ProductionJobRepository
from semi.storage.sample_repository import SampleRepository


@dataclass
class AppContext:
    db_path: Path
    lock: threading.Lock
    sample_repo: SampleRepository
    order_repo: OrderRepository
    job_repo: ProductionJobRepository
    sample_service: SampleService
    order_service: OrderService
    production_service: ProductionService
    monitoring_service: MonitoringService
    controllers: list[MenuController]


@pytest.fixture
def app_context(tmp_path):
    db_path = tmp_path / "test.db"
    conn = connect_db(db_path)
    try:
        lock = threading.Lock()
        sample_repo = SampleRepository(conn)
        order_repo = OrderRepository(conn)
        job_repo = ProductionJobRepository(conn)

        sample_service = SampleService(sample_repo)
        order_service = OrderService(order_repo, job_repo, sample_repo, lock)
        production_service = ProductionService(order_repo, job_repo, sample_repo, lock)
        monitoring_service = MonitoringService(order_repo, sample_repo)

        controllers = [
            SampleMenuController(sample_service),
            OrderMenuController(order_service, monitoring_service),
            MonitoringMenuController(monitoring_service),
            ProductionMenuController(production_service),
            ReleaseMenuController(order_service, monitoring_service),
        ]
        yield AppContext(
            db_path=db_path,
            lock=lock,
            sample_repo=sample_repo,
            order_repo=order_repo,
            job_repo=job_repo,
            sample_service=sample_service,
            order_service=order_service,
            production_service=production_service,
            monitoring_service=monitoring_service,
            controllers=controllers,
        )
    finally:
        conn.close()
