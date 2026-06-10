from apps.skills.services import SkillSetMapper

from apps.imports.models import PipelineLog

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
                "matched_count": len(result.matched),
                "unmapped_count": len(result.unmapped),
                "created_count": sum(1 for skill in result.matched if skill.created),
            },
        )
        return result

    def map_from_job_data(self, job_data, verification_result, auto_create=None):
        source_job_identifier = (
            job_data.get("external_id")
            or job_data.get("source_url")
            or job_data.get("id")
            or ""
        )
        return self.map_verification_result(
            verification_result=verification_result,
            auto_create=auto_create,
            source_job_identifier=str(source_job_identifier),
        )
