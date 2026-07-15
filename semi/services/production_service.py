from datetime import datetime

from semi.domain.models import OrderStatus


class ProductionService:
    def __init__(self, order_repo, job_repo, sample_repo, lock):
        assert order_repo.conn is sample_repo.conn, (
            "OrderRepository and SampleRepository must share the same connection"
        )
        assert order_repo.conn is job_repo.conn, (
            "OrderRepository and ProductionJobRepository must share the same connection"
        )
        self._order_repo = order_repo
        self._job_repo = job_repo
        self._sample_repo = sample_repo
        self._lock = lock

    def tick(self) -> None:
        with self._lock:
            try:
                self._promote_if_idle()
                current = self._job_repo.get_current_in_progress()
                if current is not None:
                    elapsed = (datetime.now() - current.started_at).total_seconds()
                    if elapsed >= current.total_duration_seconds:
                        self._sample_repo.increment_stock(
                            current.sample_id, current.actual_quantity
                        )
                        self._order_repo.update_status(
                            current.order_id, OrderStatus.CONFIRMED
                        )
                        self._job_repo.mark_done(current.job_id)
                        self._promote_if_idle()
                self._order_repo.conn.commit()
            except Exception:
                self._order_repo.conn.rollback()
                raise

    def _promote_if_idle(self) -> None:
        if self._job_repo.get_current_in_progress() is not None:
            return
        queue = self._job_repo.list_queued_fifo()
        if queue:
            self._job_repo.mark_in_progress(queue[0].job_id, datetime.now())
