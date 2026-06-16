from dataclasses import dataclass, field


@dataclass(frozen=True)
class CompanyUpsertResult:
    company: object
    created: bool


@dataclass(frozen=True)
class JobUpsertResult:
    job: object
    created: bool
    canonical_job_payload: dict | None = None


@dataclass(frozen=True)
class SyncResult:
    success: bool = True
    jobs_created: int = 0
    jobs_updated: int = 0
    jobs_closed: int = 0
    job_results: list[JobUpsertResult] = field(default_factory=list)

    def as_dict(self):
        return {
            "success": self.success,
            "jobs_created": self.jobs_created,
            "jobs_updated": self.jobs_updated,
            "jobs_closed": self.jobs_closed,
        }
