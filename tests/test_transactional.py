import pytest

from semi.services.transactional import TransactionalMixin


class _FakeRepo:
    def __init__(self, conn):
        self.conn = conn


class _FakeService(TransactionalMixin):
    def __init__(self, conn, lock):
        self._order_repo = _FakeRepo(conn)
        self._lock = lock


def test_transaction_commits_on_success(conn, lock):
    service = _FakeService(conn, lock)
    with service._transaction():
        pass
    assert conn.committed is True
    assert conn.rolled_back is False


def test_transaction_rolls_back_and_reraises_on_exception(conn, lock):
    service = _FakeService(conn, lock)
    with pytest.raises(ValueError):
        with service._transaction():
            raise ValueError("boom")
    assert conn.committed is False
    assert conn.rolled_back is True
