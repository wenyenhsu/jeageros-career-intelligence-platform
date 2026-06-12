from apps.skills.services import OllamaVerifier

from apps.imports.models import PipelineLog

from .job_normalizer import CanonicalJobPayload
from .monitoring_service import MonitoringService


class SkillVerificationService:
    CANONICAL_KEYS = {
        "source",
        "source_url",
        "external_id",
        "company_name",
        "title",
        "job_type",
        "employment_type",
        "remote_type",
        "location",
        "description",
        "sections",
        "posted_at",
        "metadata",
    }

    def __init__(self, verifier=None):
        self.verifier = verifier or OllamaVerifier()

    def verify_from_job_data(self, canonical_job_payload, candidate_skills):
        job_data = self._canonical_job_data(canonical_job_payload)
        source_job_identifier = (
            job_data.get("external_id") or job_data.get("source_url") or ""
        )
        return self._verify(
            title=job_data.get("title", ""),
            description=job_data.get("description", ""),
            candidate_skills=candidate_skills,
            source_fragments=self._source_fragments_from_sections(
                job_data.get("sections")
            ),
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
        canonical_payload = CanonicalJobPayload(
            source="job_post",
            source_url=job_post.source_url or "",
            external_id=job_post.external_id or str(job_post.pk or ""),
            company_name=job_post.company.name,
            title=job_post.title,
            job_type=job_post.job_type,
            employment_type=job_post.employment_type,
            remote_type=job_post.remote_type,
            location=job_post.location,
            description=job_post.description,
            sections=(
                source_fragments
                if isinstance(source_fragments, dict)
                else (
                    {"description": job_post.description}
                    if job_post.description
                    else {}
                )
            ),
            posted_at=None,
            metadata=(
                {
                    "job_post_id": job_post.pk,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                }
                if raw_text or normalized_text
                else {}
            ),
        )
        return self._verify(
            title=canonical_payload.title,
            description=canonical_payload.description,
            candidate_skills=candidate_skills,
            source_fragments=self._source_fragments_from_sections(
                canonical_payload.sections
            ),
            source_job_identifier=str(
                canonical_payload.external_id or canonical_payload.source_url or ""
            ),
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
            metadata={
                "source_job_identifier": source_job_identifier,
                "model": getattr(self.verifier, "model", ""),
            },
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
                metadata={
                    "source_job_identifier": source_job_identifier,
                    "model": getattr(self.verifier, "model", ""),
                },
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
                "model": getattr(self.verifier, "model", ""),
            },
        )
        return result

    @classmethod
    def _canonical_job_data(cls, canonical_job_payload):
        if isinstance(canonical_job_payload, CanonicalJobPayload):
            return canonical_job_payload.validate().as_dict()
        if not isinstance(canonical_job_payload, dict):
            raise TypeError(
                "skill verification requires a CanonicalJobPayload or canonical dict."
            )

        unexpected_keys = set(canonical_job_payload) - cls.CANONICAL_KEYS
        if unexpected_keys:
            raise ValueError(
                "skill verification requires canonical job payload fields only; "
                f"unexpected field(s): {', '.join(sorted(unexpected_keys))}"
            )

        data = {
            "source": canonical_job_payload.get("source"),
            "source_url": canonical_job_payload.get("source_url"),
            "external_id": canonical_job_payload.get("external_id"),
            "company_name": canonical_job_payload.get("company_name"),
            "title": canonical_job_payload.get("title"),
            "job_type": canonical_job_payload.get("job_type"),
            "employment_type": canonical_job_payload.get("employment_type"),
            "remote_type": canonical_job_payload.get("remote_type"),
            "location": canonical_job_payload.get("location"),
            "description": canonical_job_payload.get("description"),
            "sections": canonical_job_payload.get("sections") or {},
            "posted_at": canonical_job_payload.get("posted_at"),
            "metadata": canonical_job_payload.get("metadata") or {},
        }
        CanonicalJobPayload(**data).validate()
        return data

    @staticmethod
    def _source_fragments_from_sections(sections):
        if not isinstance(sections, dict):
            return []
        return [
            {"source": section_name, "text": text}
            for section_name, text in sections.items()
            if text
        ]
