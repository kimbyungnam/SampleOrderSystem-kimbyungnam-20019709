import math


def compute_shortfall_job(
    order_quantity: int,
    available: int,
    yield_rate: float,
    avg_production_seconds: float,
) -> tuple[int, int, float]:
    shortfall = order_quantity - available
    actual_quantity = math.ceil(shortfall / yield_rate)
    total_duration_seconds = avg_production_seconds * actual_quantity
    return shortfall, actual_quantity, total_duration_seconds
