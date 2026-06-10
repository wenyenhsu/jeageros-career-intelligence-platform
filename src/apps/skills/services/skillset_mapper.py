import logging
import re
from dataclasses import dataclass, field
from typing import Any

from django.db import IntegrityError, transaction

from apps.skills.models import SkillSet

from .ollama_verifier import SkillVerificationResult, VerifiedSkill

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MappedSkill:
    name: str
    skillset_id: int
    created: bool = False

    def as_dict(self):
        return {
            "name": self.name,
            "skillset_id": self.skillset_id,
            "created": self.created,
        }


@dataclass(frozen=True)
class UnmappedSkill:
    name: str
    reason: str

    def as_dict(self):
        return {
            "name": self.name,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SkillMappingResult:
    matched: list[MappedSkill]
    unmapped: list[UnmappedSkill]
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {
            "matched": [skill.as_dict() for skill in self.matched],
            "unmapped": [skill.as_dict() for skill in self.unmapped],
            "metadata": self.metadata,
        }


class SkillSetMapper:
    def __init__(self, auto_create=False):
        self.auto_create = auto_create

    def map_verified_skills(
        self,
        verified_skills,
        rejected_skills=None,
        auto_create=None,
        source_job_identifier="",
        model_name="",
        skillsets=None,
    ):
        should_auto_create = self.auto_create if auto_create is None else auto_create
        candidates = self._coerce_verified_skills(verified_skills)
        rejected_names = self._coerce_rejected_names(rejected_skills)
        skill_index = self._build_skill_index(skillsets)

        logger.info(
            "Starting SkillSet mapping: source_job=%s model=%s candidates=%s auto_create=%s",
            source_job_identifier or "",
            model_name or "",
            len(candidates),
            should_auto_create,
        )

        matched = []
        unmapped = []
        seen = set()

        for candidate in candidates:
            normalized_name = SkillSet.normalize_name(candidate["name"])
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)

            skillset = skill_index.get(normalized_name)
            created = False
            if skillset is None and should_auto_create:
                skillset, created = self._create_skillset(candidate["name"])
                skill_index[skillset.normalized_name] = skillset
                for alias in skillset.normalized_aliases:
                    skill_index.setdefault(alias, skillset)
                if created:
                    logger.info(
                        "Created SkillSet during mapping: name=%s source_job=%s",
                        skillset.name,
                        source_job_identifier or "",
                    )

            if skillset is None:
                unmapped.append(
                    UnmappedSkill(
                        name=candidate["name"],
                        reason="no matching SkillSet",
                    )
                )
                continue

            matched.append(
                MappedSkill(
                    name=skillset.name,
                    skillset_id=skillset.id,
                    created=created,
                )
            )

        for rejected_name in rejected_names:
            normalized_name = SkillSet.normalize_name(rejected_name)
            if normalized_name in seen:
                continue
            seen.add(normalized_name)
            unmapped.append(
                UnmappedSkill(
                    name=rejected_name,
                    reason="rejected during verification",
                )
            )

        logger.info(
            "Finished SkillSet mapping: source_job=%s model=%s matched=%s unmapped=%s created=%s",
            source_job_identifier or "",
            model_name or "",
            len(matched),
            len(unmapped),
            sum(1 for skill in matched if skill.created),
        )
        return SkillMappingResult(
            matched=matched,
            unmapped=unmapped,
            metadata={
                "mapper": "skillset",
                "auto_create": should_auto_create,
                "source_job_identifier": source_job_identifier or "",
                "model": model_name or "",
            },
        )

    @classmethod
    def _coerce_verified_skills(cls, verified_skills):
        if isinstance(verified_skills, SkillVerificationResult):
            verified_skills = verified_skills.verified_skills
        elif isinstance(verified_skills, dict):
            verified_skills = verified_skills.get("verified_skills", [])

        if isinstance(verified_skills, (str, VerifiedSkill)):
            verified_skills = [verified_skills]

        candidates = []
        for item in verified_skills or []:
            name = cls._name_from_skill(item)
            if not name:
                continue
            candidates.append({"name": name})
        return candidates

    @classmethod
    def _coerce_rejected_names(cls, rejected_skills):
        if isinstance(rejected_skills, SkillVerificationResult):
            rejected_skills = rejected_skills.rejected_skills
        elif isinstance(rejected_skills, dict):
            rejected_skills = rejected_skills.get("rejected_skills", [])

        if isinstance(rejected_skills, str):
            rejected_skills = [rejected_skills]

        names = []
        for item in rejected_skills or []:
            name = cls._name_from_skill(item)
            if name:
                names.append(name)
        return names

    @classmethod
    def _name_from_skill(cls, item):
        if isinstance(item, (VerifiedSkill,)):
            raw_name = item.name
        elif hasattr(item, "name"):
            raw_name = item.name
        elif isinstance(item, dict):
            raw_name = item.get("name") or item.get("skill") or ""
        else:
            raw_name = item
        return cls._normalize_display_name(raw_name)

    @staticmethod
    def _normalize_display_name(name):
        normalized = re.sub(r"\s+", " ", str(name or "")).strip()
        normalized = normalized.strip(".,;:|/\\")
        known_spellings = {
            "aws": "AWS",
            "api": "API",
            "apis": "APIs",
            "css": "CSS",
            "django": "Django",
            "docker": "Docker",
            "graphql": "GraphQL",
            "html": "HTML",
            "javascript": "JavaScript",
            "kubernetes": "Kubernetes",
            "machine learning": "Machine Learning",
            "node.js": "Node.js",
            "postgresql": "PostgreSQL",
            "python": "Python",
            "react": "React",
            "rest": "REST",
            "sql": "SQL",
            "typescript": "TypeScript",
        }
        known = known_spellings.get(normalized.casefold())
        if known:
            return known
        if normalized.islower() or normalized.isupper():
            return " ".join(
                word[:1].upper() + word[1:].lower() for word in normalized.split()
            )
        return normalized

    @staticmethod
    def _build_skill_index(skillsets=None):
        index = {}
        records = skillsets if skillsets is not None else SkillSet.objects.all()
        for skillset in records:
            index[skillset.normalized_name] = skillset
            for alias in skillset.normalized_aliases:
                index.setdefault(alias, skillset)
        return index

    @staticmethod
    def _create_skillset(name):
        normalized_name = SkillSet.normalize_name(name)
        display_name = SkillSetMapper._normalize_display_name(name)
        try:
            with transaction.atomic():
                return SkillSet.objects.create(
                    name=display_name,
                    normalized_name=normalized_name,
                    auto_created=True,
                ), True
        except IntegrityError:
            return SkillSet.objects.get(normalized_name=normalized_name), False
