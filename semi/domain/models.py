from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OrderStatus(StrEnum):
    RESERVED = "RESERVED"
    REJECTED = "REJECTED"
    PRODUCING = "PRODUCING"
    CONFIRMED = "CONFIRMED"
    RELEASE = "RELEASE"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


@dataclass(frozen=True)
class Sample:
    sample_id: str
    name: str
    avg_production_seconds: float
    yield_rate: float
    stock_quantity: int


@dataclass(frozen=True)
class Order:
    order_id: int
    sample_id: str
    customer_name: str
    quantity: int
    status: OrderStatus
    created_at: datetime
