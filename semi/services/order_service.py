from semi.domain.models import Order, OrderStatus
from semi.services.exceptions import DomainError


class OrderService:
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

    def create_order(self, sample_id, customer_name, quantity) -> Order:
        if quantity <= 0:
            raise DomainError(f"quantity must be > 0, got {quantity}")
        if not self._sample_repo.exists(sample_id):
            raise DomainError(f"unknown sample_id: {sample_id}")
        order = self._order_repo.create(sample_id, customer_name, quantity)
        self._order_repo.conn.commit()
        return order

    def reject(self, order_id) -> Order:
        with self._lock:
            try:
                order = self._order_repo.get_by_id(order_id)
                if order.status != OrderStatus.RESERVED:
                    raise DomainError(
                        f"order {order_id} is not RESERVED (status={order.status})"
                    )
                self._order_repo.update_status(order_id, OrderStatus.REJECTED)
                self._order_repo.conn.commit()
                return self._order_repo.get_by_id(order_id)
            except Exception:
                self._order_repo.conn.rollback()
                raise
