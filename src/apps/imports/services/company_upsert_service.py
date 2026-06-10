from apps.companies.models import Company

from apps.imports.models import PipelineLog

from .monitoring_service import MonitoringService
from .sync_result import CompanyUpsertResult


class CompanyUpsertService:
    @classmethod
    def upsert(cls, company_name, website=""):
        normalized_name = cls._normalize_name(company_name)
        normalized_website = (website or "").strip()
        if not normalized_name:
            raise ValueError("company_name is required.")

        company = Company.objects.filter(name__iexact=normalized_name).first()
        if company is None:
            company = Company.objects.create(
                name=normalized_name,
                website=normalized_website,
            )
            MonitoringService.log_success(
                step_name="company_upsert",
                message="Created company during sync.",
                service_name=cls.__name__,
                company=company,
                metadata={"company_name": normalized_name, "created": True},
            )
            return CompanyUpsertResult(
                company=company,
                created=True,
            )

        changed_fields = []
        if company.name != normalized_name:
            company.name = normalized_name
            changed_fields.append("name")
        if normalized_website and company.website != normalized_website:
            company.website = normalized_website
            changed_fields.append("website")

        if changed_fields:
            company.save(update_fields=[*changed_fields, "updated_at"])

        MonitoringService.log_event(
            step_name="company_upsert",
            status=PipelineLog.StatusChoices.SUCCESS,
            message="Reused existing company during sync.",
            service_name=cls.__name__,
            company=company,
            metadata={
                "company_name": normalized_name,
                "created": False,
                "updated_fields": changed_fields,
            },
        )
        return CompanyUpsertResult(company=company, created=False)

    @staticmethod
    def _normalize_name(company_name):
        return " ".join((company_name or "").split())
