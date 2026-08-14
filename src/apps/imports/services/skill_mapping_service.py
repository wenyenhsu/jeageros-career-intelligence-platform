from apps.skills.services import SkillSetMapper

from apps.imports.models import PipelineLog

from .job_normalizer import CanonicalJobPayload
from .monitoring_service import MonitoringService


class SkillMappingService:
    def __init__(self, mapper=None):
        self.mapper = mapper or SkillSetMapper()

    def map_verification_result(
        self,
        verification_result,
        auto_create=None,
        source_job_identifier="",
    ):
        metadata = getattr(verification_result, "metadata", {}) or {}
        source_job_identifier = source_job_identifier or metadata.get(
            "source_job_identifier", ""
        )
        MonitoringService.log_event(
            step_name="skillset_mapping",
            status=PipelineLog.StatusChoices.STARTED,
            message="SkillSet mapping started.",
            service_name=self.__class__.__name__,
            metadata={
                "source_job_identifier": source_job_identifier,
                "model": metadata.get("model", ""),
                "auto_create": auto_create,
            },
        )
        try:
            result = self.mapper.map_verified_skills(
                verified_skills=verification_result,
                rejected_skills=verification_result,
                auto_create=auto_create,
                source_job_identifier=source_job_identifier,
                model_name=metadata.get("model", ""),
            )
        except Exception as exc:
            MonitoringService.log_failure(
                step_name="skillset_mapping",
                message="SkillSet mapping failed.",
                service_name=self.__class__.__name__,
                metadata={"source_job_identifier": source_job_identifier},
                error=exc,
            )
            raise

        MonitoringService.log_event(
            step_name="skillset_mapping",
            status=PipelineLog.StatusChoices.SUCCESS,
            message="SkillSet mapping finished.",
            service_name=self.__class__.__name__,
            metadata={
                "source_job_identifier": source_job_identifier,
                "model": metadata.get("model", ""),
                "matched_count": len(result.matched),
                "unmapped_count": len(result.unmapped),
                "created_count": sum(1 for skill in result.matched if skill.created),
                "created_skillset_ids": result.metadata.get("created_skillset_ids", []),
            },
        )
        try:
            from apps.analytics.services.skill_candidate_service import (
                SkillCandidateService,
            )

            SkillCandidateService().record_unmapped_skills(result.unmapped)
        except Exception:
            pass
        return result

    def map_from_job_data(
        self, canonical_job_payload, verification_result, auto_create=None
    ):
        job_data = self._canonical_job_data(canonical_job_payload)
        source_job_identifier = (
            job_data.get("external_id") or job_data.get("source_url") or ""
        )
        return self.map_verification_result(
            verification_result=verification_result,
            auto_create=auto_create,
            source_job_identifier=str(source_job_identifier),
        )

    @classmethod
    def _canonical_job_data(cls, canonical_job_payload):
        return CanonicalJobPayload.coerce_dict(canonical_job_payload)
