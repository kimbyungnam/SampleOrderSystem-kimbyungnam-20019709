import threading
import time
import traceback
from pathlib import Path

from semi.services.production_service import ProductionService
from semi.storage.db import connect_db
from semi.storage.order_repository import OrderRepository
from semi.storage.production_job_repository import ProductionJobRepository
from semi.storage.sample_repository import SampleRepository


def start_worker(db_path: Path, lock: threading.Lock) -> threading.Thread:
    def _run() -> None:
        conn = connect_db(db_path)
        prod_svc = ProductionService(
            OrderRepository(conn),
            ProductionJobRepository(conn),
            SampleRepository(conn),
            lock,
        )
        while True:
            try:
                prod_svc.tick()
            except Exception:
                traceback.print_exc()
            time.sleep(1)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
