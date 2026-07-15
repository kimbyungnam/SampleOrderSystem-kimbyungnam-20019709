from semi.domain.models import Sample
from semi.services.exceptions import DomainError


class SampleService:
    def __init__(self, sample_repo):
        self._sample_repo = sample_repo

    def register(self, sample_id, name, avg_production_seconds, yield_rate) -> Sample:
        if avg_production_seconds <= 0:
            raise DomainError(
                f"avg_production_seconds must be > 0, got {avg_production_seconds}"
            )
        if not (0 < yield_rate <= 1):
            raise DomainError(f"yield_rate must be in (0, 1], got {yield_rate}")
        if self._sample_repo.exists(sample_id):
            raise DomainError(f"sample_id already exists: {sample_id}")
        sample = self._sample_repo.create(
            sample_id, name, avg_production_seconds, yield_rate
        )
        self._sample_repo.conn.commit()
        return sample

    def list_all(self) -> list[Sample]:
        return self._sample_repo.list_all()

    def search_by_name(self, query) -> list[Sample]:
        return self._sample_repo.search_by_name(query)
