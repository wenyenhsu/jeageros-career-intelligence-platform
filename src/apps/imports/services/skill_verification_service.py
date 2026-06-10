from apps.skills.services import OllamaVerifier

from apps.imports.models import PipelineLog

from .monitoring_service import MonitoringService


class SkillVerificationService:
    def __init__(self, verifier=None):
        self.verifier = verifier or OllamaVerifier()

    def verify_from_job_data(self, job_data, candidate_skills):
        source_job_identifier = (
            job_data.get("external_id")
            or job_data.get("source_url")
            or job_data.get("id")
            or ""
        )
        return self._verify(
            title=job_data.get("title", ""),
            description=job_data.get("description", ""),
            candidate_skills=candidate_skills,
            raw_text=job_data.get("raw_text", "") or job_data.get("raw_content", ""),
            normalized_text=job_data.get("normalized_text", ""),
            source_fragments=job_data.get("source_fragments", []),
            source_job_identifier=str(source_job_identifier),
        )

    def verify_extraction_result(self, job_data, extraction_result):
        return self.verify_from_job_data(
            job_data=job_data,
            candidate_skills=extraction_result,
        )

    def verify_from_job_post(
        self,
        job_post,
        candidate_skills,
        raw_text="",
        normalized_text="",
        source_fragments=None,
    ):
        return self._verify(
            title=job_post.title,
            description=job_post.description,
            candidate_skills=candidate_skills,
            raw_text=raw_text,
            normalized_text=normalized_text,
            source_fragments=source_fragments or [],
            source_job_identifier=str(job_post.pk or ""),
            job_id=job_post.pk,
            company_id=job_post.company_id,
        )

    def _verify(
        self,
        title,
        description,
        candidate_skills,
        raw_text="",
        normalized_text="",
        source_fragments=None,
        source_job_identifier="",
        job_id=None,
        company_id=None,
    ):
        MonitoringService.log_event(
            step_name="ollama_verify",
            status=PipelineLog.StatusChoices.STARTED,
            message="Ollama skill verification started.",
            service_name=self.__class__.__name__,
            job_id=job_id,
            company_id=company_id,
            metadata={"source_job_identifier": source_job_identifier},
        )
        try:
            result = self.verifier.verify(
                title=title,
                description=description,
                candidate_skills=candidate_skills,
                raw_text=raw_text,
                normalized_text=normalized_text,
                source_fragments=source_fragments or [],
                source_job_identifier=source_job_identifier,
            )
        except Exception as exc:
            MonitoringService.log_failure(
                step_name="ollama_verify",
                message="Ollama skill verification failed.",
                service_name=self.__class__.__name__,
                job_id=job_id,
                company_id=company_id,
                metadata={"source_job_identifier": source_job_identifier},
                error=exc,
            )
            raise

        MonitoringService.log_event(
            step_name="ollama_verify",
            status=PipelineLog.StatusChoices.SUCCESS,
            message="Ollama skill verification finished.",
            service_name=self.__class__.__name__,
            job_id=job_id,
            company_id=company_id,
            metadata={
                "source_job_identifier": source_job_identifier,
                "accepted_count": len(result.verified_skills),
                "rejected_count": len(result.rejected_skills),
            },
        )
        return result
