from semi.services.production_math import compute_shortfall_job


def test_compute_shortfall_job_from_zero_available_stock():
    shortfall, actual_quantity, total_duration_seconds = compute_shortfall_job(
        order_quantity=5, available=0, yield_rate=0.9, avg_production_seconds=10.0
    )
    assert shortfall == 5
    assert actual_quantity == 6  # ceil(5 / 0.9)
    assert total_duration_seconds == 60.0


def test_compute_shortfall_job_from_partial_available_stock():
    shortfall, actual_quantity, total_duration_seconds = compute_shortfall_job(
        order_quantity=5, available=3, yield_rate=1.0, avg_production_seconds=10.0
    )
    assert shortfall == 2
    assert actual_quantity == 2
    assert total_duration_seconds == 20.0
