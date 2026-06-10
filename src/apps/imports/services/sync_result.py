from dataclasses import dataclass


@dataclass(frozen=True)
class CompanyUpsertResult:
    company: object
    created: bool


@dataclass(frozen=True)
class JobUpsertResult:
    job: object
    created: bool


@dataclass(frozen=True)
class SyncResult:
    success: bool = True
    jobs_created: int = 0
    jobs_updated: int = 0
    jobs_closed: int = 0

    def as_dict(self):
        return {
            "success": self.success,
            "jobs_created": self.jobs_created,
            "jobs_updated": self.jobs_updated,
            "jobs_closed": self.jobs_closed,
        }
