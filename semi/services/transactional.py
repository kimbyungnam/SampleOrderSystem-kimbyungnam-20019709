from contextlib import contextmanager


class TransactionalMixin:
    @contextmanager
    def _transaction(self):
        with self._lock:
            try:
                yield
                self._order_repo.conn.commit()
            except Exception:
                self._order_repo.conn.rollback()
                raise
