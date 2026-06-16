from dataclasses import dataclass, field
from typing import Any

from apps.imports.models import PipelineLog

from .monitoring_service import MonitoringService
from .skill_attach_service import SkillAttachService
from .skill_extraction_service import SkillExtractionService
from .skill_mapping_service import SkillMappingService
from .skill_verification_service import SkillVerificationService


@dataclass(frozen=True)
class SkillPipelineResult:
    job_id: int
    success: bool
    attached_count: int = 0
    candidate_count: int = 0
    verified_count: int = 0
    rejected_count: int = 0
    mapped_count: int = 0
    unmapped_count: int = 0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {
            "job_id": self.job_id,
            "success": self.success,
            "attached_count": self.attached_count,
            "candidate_count": self.candidate_count,
            "verified_count": self.verified_count,
            "rejected_count": self.rejected_count,
            "mapped_count": self.mapped_count,
            "unmapped_count": self.unmapped_count,
            "error": self.error,
            "metadata": self.metadata,
        }


class SkillPipelineService:
    def __init__(
        self,
        extraction_service=None,
        verification_service=None,
        mapping_service=None,
        attach_service=None,
    ):
        self.extraction_service = extraction_service or SkillExtractionService()
        self.verification_service = verification_service or SkillVerificationService()
        self.mapping_service = mapping_service or SkillMappingService()
        self.attach_service = attach_service or SkillAttachService()

    def process_job_post(self, job_post, canonical_job_payload, auto_create=None):
        source_job_identifier = (
            canonical_job_payload.get("external_id")
            or canonical_job_payload.get("source_url")
            or str(job_post.pk)
        )
        MonitoringService.log_event(
            step_name="skill_pipeline",
            status=PipelineLog.StatusChoices.STARTED,
            message="Skill pipeline started.",
            service_name=self.__class__.__name__,
            job=job_post,
            company=job_post.company,
            metadata={
                "source_job_identifier": source_job_identifier,
                "auto_create": auto_create,
            },
        )

        try:
            extraction_result = self.extraction_service.extract_from_job_data(
                canonical_job_payload
            )
            verification_result = self.verification_service.verify_from_job_data(
                canonical_job_payload,
                extraction_result,
            )
            mapping_result = self.mapping_service.map_from_job_data(
                canonical_job_payload,
                verification_result,
                auto_create=auto_create,
            )
            attach_result = self.attach_service.score_and_attach_job_post_from_payload(
                job_post=job_post,
                canonical_job_payload=canonical_job_payload,
                mapped_skills=mapping_result,
                verified_skills=verification_result,
                extraction_metadata={
                    "pipeline": "crawl_skill_pipeline",
                    "source_job_identifier": source_job_identifier,
                },
            )
        except Exception as exc:
            MonitoringService.log_failure(
                step_name="skill_pipeline",
                message="Skill pipeline failed.",
                service_name=self.__class__.__name__,
                job=job_post,
                company=job_post.company,
                metadata={
                    "source_job_identifier": source_job_identifier,
                    "auto_create": auto_create,
                },
                error=exc,
            )
            return SkillPipelineResult(
                job_id=job_post.pk,
                success=False,
                error=str(exc),
                metadata={"source_job_identifier": source_job_identifier},
            )

        result = SkillPipelineResult(
            job_id=job_post.pk,
            success=True,
            attached_count=attach_result["attachment"]["attached_count"],
            candidate_count=len(extraction_result.candidate_skills),
            verified_count=len(verification_result.verified_skills),
            rejected_count=len(verification_result.rejected_skills),
            mapped_count=len(mapping_result.matched),
            unmapped_count=len(mapping_result.unmapped),
            metadata={
                "source_job_identifier": source_job_identifier,
                "created_skillset_ids": mapping_result.metadata.get(
                    "created_skillset_ids",
                    [],
                ),
            },
        )
        MonitoringService.log_success(
            step_name="skill_pipeline",
            message="Skill pipeline finished.",
            service_name=self.__class__.__name__,
            job=job_post,
            company=job_post.company,
            metadata=result.as_dict(),
        )
        return result
