import logging
from dataclasses import dataclass, field
from typing import Any

from apps.imports.models import PipelineLog
from apps.skills.models import (
    ApplicationSkill,
    JobPostSkill,
    SkillAttachmentSource,
)
from apps.skills.services.skill_scoring_service import (
    ScoredSkill,
    SkillScoringResult,
    SkillScoringService,
)

from .monitoring_service import MonitoringService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillAttachResult:
    target_type: str
    target_id: int
    attached_count: int
    created_count: int
    updated_count: int
    skillset_ids: list[int]
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "attached_count": self.attached_count,
            "created_count": self.created_count,
            "updated_count": self.updated_count,
            "skillset_ids": self.skillset_ids,
            "metadata": self.metadata,
        }


class SkillAttachService:
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

    def __init__(self, scoring_service=None):
        self.scoring_service = scoring_service or SkillScoringService()

    def score_and_attach_job_post_from_payload(
        self,
        job_post,
        canonical_job_payload,
        mapped_skills,
        verified_skills=None,
        source_type=SkillAttachmentSource.OLLAMA_PIPELINE,
        extraction_metadata=None,
    ):
        scoring_result = self._score_canonical_payload(
            canonical_job_payload=canonical_job_payload,
            mapped_skills=mapped_skills,
            verified_skills=verified_skills,
            job_id=job_post.pk,
            company_id=job_post.company_id,
        )
        attach_result = self.attach_to_job_post(
            job_post=job_post,
            scored_skills=scoring_result,
            source_type=source_type,
            extraction_metadata=self._attachment_metadata(
                canonical_job_payload,
                extraction_metadata,
            ),
        )
        return {
            "scoring": scoring_result.as_dict(),
            "attachment": attach_result.as_dict(),
        }

    def score_and_attach_application_from_payload(
        self,
        application,
        canonical_job_payload,
        mapped_skills,
        verified_skills=None,
        source_type=SkillAttachmentSource.OLLAMA_PIPELINE,
        extraction_metadata=None,
    ):
        scoring_result = self._score_canonical_payload(
            canonical_job_payload=canonical_job_payload,
            mapped_skills=mapped_skills,
            verified_skills=verified_skills,
            job_id=application.job_post_id,
            company_id=application.job_post.company_id,
        )
        attach_result = self.attach_to_application(
            application=application,
            scored_skills=scoring_result,
            source_type=source_type,
            extraction_metadata=self._attachment_metadata(
                canonical_job_payload,
                extraction_metadata,
            ),
        )
        return {
            "scoring": scoring_result.as_dict(),
            "attachment": attach_result.as_dict(),
        }

    def score_and_attach_job_post(
        self,
        job_post,
        mapped_skills,
        verified_skills=None,
        normalized_text="",
        source_fragments=None,
        source_type=SkillAttachmentSource.OLLAMA_PIPELINE,
        extraction_metadata=None,
    ):
        scoring_result = self._score(
            mapped_skills=mapped_skills,
            verified_skills=verified_skills,
            title=job_post.title,
            description=job_post.description,
            normalized_text=normalized_text,
            source_fragments=source_fragments or [],
            source_job_identifier=str(job_post.pk or ""),
            job_id=job_post.pk,
            company_id=job_post.company_id,
        )
        attach_result = self.attach_to_job_post(
            job_post=job_post,
            scored_skills=scoring_result,
            source_type=source_type,
            extraction_metadata=extraction_metadata,
        )
        return {
            "scoring": scoring_result.as_dict(),
            "attachment": attach_result.as_dict(),
        }

    def score_and_attach_application(
        self,
        application,
        mapped_skills,
        verified_skills=None,
        normalized_text="",
        source_fragments=None,
        source_type=SkillAttachmentSource.OLLAMA_PIPELINE,
        extraction_metadata=None,
    ):
        scoring_result = self._score(
            mapped_skills=mapped_skills,
            verified_skills=verified_skills,
            title=application.job_post.title,
            description=application.job_post.description,
            normalized_text=normalized_text,
            source_fragments=source_fragments or [],
            source_job_identifier=str(application.job_post_id or ""),
            job_id=application.job_post_id,
            company_id=application.job_post.company_id,
        )
        attach_result = self.attach_to_application(
            application=application,
            scored_skills=scoring_result,
            source_type=source_type,
            extraction_metadata=extraction_metadata,
        )
        return {
            "scoring": scoring_result.as_dict(),
            "attachment": attach_result.as_dict(),
        }

    def attach_to_job_post(
        self,
        job_post,
        scored_skills,
        source_type=SkillAttachmentSource.OLLAMA_PIPELINE,
        extraction_metadata=None,
    ):
        return self._attach(
            model=JobPostSkill,
            lookup={"job_post": job_post},
            target_type="job_post",
            target_id=job_post.id,
            scored_skills=scored_skills,
            source_type=source_type,
            extraction_metadata=extraction_metadata,
        )

    def attach_to_application(
        self,
        application,
        scored_skills,
        source_type=SkillAttachmentSource.OLLAMA_PIPELINE,
        extraction_metadata=None,
    ):
        return self._attach(
            model=ApplicationSkill,
            lookup={"application": application},
            target_type="application",
            target_id=application.id,
            scored_skills=scored_skills,
            source_type=source_type,
            extraction_metadata=extraction_metadata,
        )

    def _attach(
        self,
        model,
        lookup,
        target_type,
        target_id,
        scored_skills,
        source_type,
        extraction_metadata,
    ):
        skills = self._coerce_scored_skills(scored_skills)
        metadata = extraction_metadata or {}

        logger.info(
            "Starting skill attachment: target_type=%s target_id=%s skills=%s",
            target_type,
            target_id,
            len(skills),
        )
        MonitoringService.log_event(
            step_name="skill_attach",
            status=PipelineLog.StatusChoices.STARTED,
            message="Skill attachment started.",
            service_name=self.__class__.__name__,
            job_id=lookup.get("job_post").id if lookup.get("job_post") else None,
            metadata={
                "target_type": target_type,
                "target_id": target_id,
                "skill_count": len(skills),
            },
        )

        created_count = 0
        updated_count = 0
        skillset_ids = []

        try:
            for skill in skills:
                defaults = {
                    "score": skill["score"],
                    "source_type": source_type,
                    "extraction_metadata": {
                        **metadata,
                        "skill_name": skill["name"],
                        "reasons": skill["reasons"],
                    },
                }
                _, created = model.objects.update_or_create(
                    **lookup,
                    skill_set_id=skill["skillset_id"],
                    defaults=defaults,
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                skillset_ids.append(skill["skillset_id"])
        except Exception as exc:
            MonitoringService.log_failure(
                step_name="skill_attach",
                message="Skill attachment failed.",
                service_name=self.__class__.__name__,
                job_id=lookup.get("job_post").id if lookup.get("job_post") else None,
                metadata={"target_type": target_type, "target_id": target_id},
                error=exc,
            )
            raise

        logger.info(
            "Finished skill attachment: target_type=%s target_id=%s attached=%s created=%s updated=%s",
            target_type,
            target_id,
            len(skillset_ids),
            created_count,
            updated_count,
        )
        MonitoringService.log_event(
            step_name="skill_attach",
            status=PipelineLog.StatusChoices.SUCCESS,
            message="Skill attachment finished.",
            service_name=self.__class__.__name__,
            job_id=lookup.get("job_post").id if lookup.get("job_post") else None,
            metadata={
                "target_type": target_type,
                "target_id": target_id,
                "attached_count": len(skillset_ids),
                "created_count": created_count,
                "updated_count": updated_count,
            },
        )
        return SkillAttachResult(
            target_type=target_type,
            target_id=target_id,
            attached_count=len(skillset_ids),
            created_count=created_count,
            updated_count=updated_count,
            skillset_ids=skillset_ids,
            metadata={"source_type": source_type},
        )

    def _score(
        self,
        mapped_skills,
        verified_skills,
        title,
        description,
        normalized_text,
        source_fragments,
        source_job_identifier,
        job_id=None,
        company_id=None,
    ):
        MonitoringService.log_event(
            step_name="skill_scoring",
            status=PipelineLog.StatusChoices.STARTED,
            message="Skill scoring started.",
            service_name=self.__class__.__name__,
            job_id=job_id,
            company_id=company_id,
            metadata={"source_job_identifier": source_job_identifier},
        )
        try:
            result = self.scoring_service.score_mapped_skills(
                mapped_skills=mapped_skills,
                verified_skills=verified_skills,
                title=title,
                description=description,
                normalized_text=normalized_text,
                source_fragments=source_fragments,
                source_job_identifier=source_job_identifier,
            )
        except Exception as exc:
            MonitoringService.log_failure(
                step_name="skill_scoring",
                message="Skill scoring failed.",
                service_name=self.__class__.__name__,
                job_id=job_id,
                company_id=company_id,
                metadata={"source_job_identifier": source_job_identifier},
                error=exc,
            )
            raise

        MonitoringService.log_event(
            step_name="skill_scoring",
            status=PipelineLog.StatusChoices.SUCCESS,
            message="Skill scoring finished.",
            service_name=self.__class__.__name__,
            job_id=job_id,
            company_id=company_id,
            metadata={
                "source_job_identifier": source_job_identifier,
                "scored_count": len(result.scored_skills),
                "scores": [
                    {
                        "skillset_id": skill.skillset_id,
                        "score": skill.score,
                    }
                    for skill in result.scored_skills
                ],
            },
        )
        return result

    def _score_canonical_payload(
        self,
        canonical_job_payload,
        mapped_skills,
        verified_skills,
        job_id=None,
        company_id=None,
    ):
        data = self._canonical_job_data(canonical_job_payload)
        source_job_identifier = data.get("external_id") or data.get("source_url") or ""
        MonitoringService.log_event(
            step_name="skill_scoring",
            status=PipelineLog.StatusChoices.STARTED,
            message="Skill scoring started.",
            service_name=self.__class__.__name__,
            job_id=job_id,
            company_id=company_id,
            metadata={
                "source_job_identifier": source_job_identifier,
                "canonical_payload": True,
            },
        )
        try:
            result = self.scoring_service.score_canonical_payload(
                canonical_job_payload=canonical_job_payload,
                mapped_skills=mapped_skills,
                verified_skills=verified_skills,
            )
        except Exception as exc:
            MonitoringService.log_failure(
                step_name="skill_scoring",
                message="Skill scoring failed.",
                service_name=self.__class__.__name__,
                job_id=job_id,
                company_id=company_id,
                metadata={
                    "source_job_identifier": source_job_identifier,
                    "canonical_payload": True,
                },
                error=exc,
            )
            raise

        MonitoringService.log_event(
            step_name="skill_scoring",
            status=PipelineLog.StatusChoices.SUCCESS,
            message="Skill scoring finished.",
            service_name=self.__class__.__name__,
            job_id=job_id,
            company_id=company_id,
            metadata={
                "source_job_identifier": source_job_identifier,
                "canonical_payload": True,
                "scored_count": len(result.scored_skills),
                "scores": [
                    {
                        "skillset_id": skill.skillset_id,
                        "score": skill.score,
                    }
                    for skill in result.scored_skills
                ],
            },
        )
        return result

    @staticmethod
    def _coerce_scored_skills(scored_skills):
        if isinstance(scored_skills, SkillScoringResult):
            scored_skills = scored_skills.scored_skills
        elif isinstance(scored_skills, dict):
            scored_skills = scored_skills.get("scored_skills", [])

        if isinstance(scored_skills, ScoredSkill):
            scored_skills = [scored_skills]

        skills = []
        seen = set()
        for item in scored_skills or []:
            if isinstance(item, ScoredSkill):
                name = item.name
                skillset_id = item.skillset_id
                score = item.score
                reasons = item.reasons
            else:
                name = item.get("name", "")
                skillset_id = item.get("skillset_id")
                score = item.get("score", 0)
                reasons = item.get("reasons", [])
            if not skillset_id or skillset_id in seen:
                continue
            seen.add(skillset_id)
            skills.append(
                {
                    "name": str(name),
                    "skillset_id": int(skillset_id),
                    "score": max(0, min(100, int(score))),
                    "reasons": list(reasons or []),
                }
            )
        return skills

    @classmethod
    def _canonical_job_data(cls, canonical_job_payload):
        if hasattr(canonical_job_payload, "as_dict"):
            canonical_job_payload = canonical_job_payload.as_dict()
        if not isinstance(canonical_job_payload, dict):
            raise TypeError(
                "skill attach requires a CanonicalJobPayload or canonical dict."
            )

        unexpected_keys = set(canonical_job_payload) - cls.CANONICAL_KEYS
        if unexpected_keys:
            raise ValueError(
                "skill attach requires canonical job payload fields only; "
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
        cls._validate_canonical_payload(data)
        return data

    @staticmethod
    def _validate_canonical_payload(data):
        missing = []
        if not data.get("title"):
            missing.append("title")
        if not data.get("company_name"):
            missing.append("company_name")
        if not (data.get("source_url") or data.get("external_id")):
            missing.append("source_url_or_external_id")
        if missing:
            raise ValueError(
                "Canonical job payload missing required field(s): " + ", ".join(missing)
            )

    @classmethod
    def _attachment_metadata(cls, canonical_job_payload, extraction_metadata=None):
        data = cls._canonical_job_data(canonical_job_payload)
        metadata = dict(extraction_metadata or {})
        metadata.setdefault("source", data.get("source") or "")
        metadata.setdefault("source_url", data.get("source_url") or "")
        metadata.setdefault("external_id", data.get("external_id") or "")
        metadata.setdefault("posted_at", data.get("posted_at") or "")
        return metadata
