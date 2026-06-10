from apps.skills.services import OllamaExtractor

from apps.imports.models import PipelineLog

from .monitoring_service import MonitoringService


class SkillExtractionService:
    def __init__(self, extractor=None):
        self.extractor = extractor or OllamaExtractor()

    def extract_from_job_data(self, job_data):
        source_job_identifier = (
            job_data.get("external_id")
            or job_data.get("source_url")
            or job_data.get("id")
            or ""
        )
        return self._extract(
            title=job_data.get("title", ""),
            description=job_data.get("description", ""),
            raw_text=job_data.get("raw_text", "") or job_data.get("raw_content", ""),
            normalized_text=job_data.get("normalized_text", ""),
            source_fragments=job_data.get("source_fragments", []),
            source_job_identifier=str(source_job_identifier),
        )

    def extract_from_job_post(self, job_post, raw_text=""):
        return self._extract(
            title=job_post.title,
            description=job_post.description,
            raw_text=raw_text,
            source_job_identifier=str(job_post.pk or ""),
            job_id=job_post.pk,
            company_id=job_post.company_id,
        )

    def _extract(
        self,
        title,
        description,
        raw_text="",
        normalized_text="",
        source_fragments=None,
        source_job_identifier="",
        job_id=None,
        company_id=None,
    ):
        MonitoringService.log_event(
            step_name="ollama_extract",
            status=PipelineLog.StatusChoices.STARTED,
            message="Ollama skill extraction started.",
            service_name=self.__class__.__name__,
            job_id=job_id,
            company_id=company_id,
            metadata={"source_job_identifier": source_job_identifier},
        )
        try:
            result = self.extractor.extract(
                title=title,
                description=description,
                raw_text=raw_text,
                normalized_text=normalized_text,
                source_fragments=source_fragments or [],
                source_job_identifier=source_job_identifier,
            )
        except Exception as exc:
            MonitoringService.log_failure(
                step_name="ollama_extract",
                message="Ollama skill extraction failed.",
                service_name=self.__class__.__name__,
                job_id=job_id,
                company_id=company_id,
                metadata={"source_job_identifier": source_job_identifier},
                error=exc,
            )
            raise

        MonitoringService.log_event(
            step_name="ollama_extract",
            status=PipelineLog.StatusChoices.SUCCESS,
            message="Ollama skill extraction finished.",
            service_name=self.__class__.__name__,
            job_id=job_id,
            company_id=company_id,
            metadata={
                "source_job_identifier": source_job_identifier,
                "candidate_skill_count": len(result.candidate_skills),
            },
        )
        return result
