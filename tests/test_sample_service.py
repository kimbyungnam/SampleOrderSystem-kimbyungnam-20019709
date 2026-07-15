import pytest

from semi.services.exceptions import DomainError
from semi.services.sample_service import SampleService


def test_register_creates_sample_with_zero_initial_stock(sample_repo):
    service = SampleService(sample_repo)
    sample = service.register("S1", "Wafer A", 10.0, 0.9)
    assert sample.sample_id == "S1"
    assert sample.stock_quantity == 0
    assert sample_repo.conn.committed is True


def test_register_rejects_non_positive_avg_production_seconds(sample_repo):
    service = SampleService(sample_repo)
    with pytest.raises(DomainError):
        service.register("S1", "Wafer A", 0, 0.9)
    with pytest.raises(DomainError):
        service.register("S1", "Wafer A", -1.0, 0.9)


@pytest.mark.parametrize("yield_rate", [0, -0.1, 1.1])
def test_register_rejects_yield_rate_out_of_range(sample_repo, yield_rate):
    service = SampleService(sample_repo)
    with pytest.raises(DomainError):
        service.register("S1", "Wafer A", 10.0, yield_rate)


def test_register_accepts_yield_rate_boundary_of_one(sample_repo):
    service = SampleService(sample_repo)
    sample = service.register("S1", "Wafer A", 10.0, 1.0)
    assert sample.yield_rate == 1.0


def test_register_rejects_duplicate_sample_id(sample_repo):
    service = SampleService(sample_repo)
    service.register("S1", "Wafer A", 10.0, 0.9)
    with pytest.raises(DomainError):
        service.register("S1", "Wafer B", 5.0, 0.8)


def test_list_all_and_search_by_name(sample_repo):
    service = SampleService(sample_repo)
    service.register("S1", "Wafer A", 10.0, 0.9)
    service.register("S2", "Die B", 5.0, 0.8)
    assert {s.sample_id for s in service.list_all()} == {"S1", "S2"}
    assert [s.sample_id for s in service.search_by_name("Wafer")] == ["S1"]
