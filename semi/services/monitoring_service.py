from dataclasses import dataclass
from enum import StrEnum

from semi.domain.models import Order, OrderStatus, Sample


class StockStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    SHORT = "SHORT"
    DEPLETED = "DEPLETED"


@dataclass(frozen=True)
class SampleStockStatus:
    sample: Sample
    outstanding: int
    status: StockStatus


class MonitoringService:
    _COUNTED_STATUSES = (
        OrderStatus.RESERVED,
        OrderStatus.CONFIRMED,
        OrderStatus.PRODUCING,
        OrderStatus.RELEASE,
    )
    _OUTSTANDING_STATUSES = (
        OrderStatus.RESERVED,
        OrderStatus.CONFIRMED,
        OrderStatus.PRODUCING,
    )

    def __init__(self, order_repo, sample_repo):
        self._order_repo = order_repo
        self._sample_repo = sample_repo

    def count_by_status(self) -> dict[OrderStatus, int]:
        return {
            status: len(self._order_repo.list_by_status(status))
            for status in self._COUNTED_STATUSES
        }

    def list_by_status(self, status) -> list[Order]:
        return self._order_repo.list_by_status(status)

    def stock_status(self) -> list[SampleStockStatus]:
        results = []
        for sample in self._sample_repo.list_all():
            outstanding = self._order_repo.sum_quantity_by_statuses(
                sample.sample_id, self._OUTSTANDING_STATUSES
            )
            if sample.stock_quantity == 0:
                status = StockStatus.DEPLETED
            elif sample.stock_quantity >= outstanding:
                status = StockStatus.SUFFICIENT
            else:
                status = StockStatus.SHORT
            results.append(SampleStockStatus(sample, outstanding, status))
        return results
