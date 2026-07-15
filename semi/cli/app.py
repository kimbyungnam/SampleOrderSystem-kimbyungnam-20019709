import threading
from pathlib import Path

from semi.cli.controllers import (
    MonitoringMenuController,
    OrderMenuController,
    ProductionMenuController,
    ReleaseMenuController,
    SampleMenuController,
)
from semi.cli.menu_loop import main_loop
from semi.cli.views import render_main_menu
from semi.scheduler.background_worker import start_worker
from semi.services.monitoring_service import MonitoringService
from semi.services.order_service import OrderService
from semi.services.production_service import ProductionService
from semi.services.sample_service import SampleService
from semi.storage.db import connect_db
from semi.storage.order_repository import OrderRepository
from semi.storage.production_job_repository import ProductionJobRepository
from semi.storage.sample_repository import SampleRepository


def main(db_path: Path = Path("semi.db")) -> None:
    conn = connect_db(db_path)
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

    start_worker(db_path, lock)

    try:
        main_loop(controllers, render_main_menu=render_main_menu)
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
