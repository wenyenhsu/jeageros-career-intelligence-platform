import logging
import re
from dataclasses import dataclass, field
from typing import Any

from django.db import IntegrityError, transaction

from apps.skills.models import SkillAlias, SkillKeyword, SkillSet

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
class MappedKeyword:
    skillset_id: int
    keyword_id: int
    raw_text: str
    normalized_text: str
    source: str
    status: str

    def as_dict(self):
        return {
            "skillset_id": self.skillset_id,
            "keyword_id": self.keyword_id,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "source": self.source,
            "status": self.status,
        }


@dataclass(frozen=True)
class SkillMappingResult:
    matched: list[MappedSkill]
    unmapped: list[UnmappedSkill]
    keywords: list[MappedKeyword] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {
            "matched": [skill.as_dict() for skill in self.matched],
            "unmapped": [skill.as_dict() for skill in self.unmapped],
            "keywords": [keyword.as_dict() for keyword in self.keywords],
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
        keywords = []
        seen = set()
        seen_keyword_ids = set()

        for candidate in candidates:
            normalized_name = SkillSet.normalize_name(candidate["name"])
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)

            match = skill_index.get(normalized_name)
            skillset = match["skillset"] if match else None
            created = False
            if skillset is None and should_auto_create:
                skillset, created = self._create_skillset(candidate["name"])
                match = self._match_payload(
                    skillset=skillset,
                    match_type="auto_created",
                    keyword=skillset.keywords.filter(
                        normalized_text=skillset.normalized_name
                    ).first(),
                )
                for keyword in SkillKeyword.objects.filter(skill_set=skillset):
                    skill_index.setdefault(
                        keyword.normalized_text,
                        self._match_payload(
                            skillset=skillset,
                            match_type="keyword",
                            keyword=keyword,
                        ),
                    )
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
            keyword = match.get("keyword") if match else None
            if keyword and keyword.id not in seen_keyword_ids:
                keywords.append(self._mapped_keyword(keyword))
                seen_keyword_ids.add(keyword.id)

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
            keywords=keywords,
            metadata={
                "mapper": "skillset",
                "auto_create": should_auto_create,
                "source_job_identifier": source_job_identifier or "",
                "model": model_name or "",
                "created_skillset_ids": [
                    skill.skillset_id for skill in matched if skill.created
                ],
                "created_skillset_names": [
                    skill.name for skill in matched if skill.created
                ],
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
            for name in cls._names_from_skill(item):
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
            for name in cls._names_from_skill(item):
                names.append(name)
        return names

    @classmethod
    def _name_from_skill(cls, item):
        names = cls._names_from_skill(item)
        return names[0] if names else ""

    @classmethod
    def _names_from_skill(cls, item):
        raw_name = cls._raw_name_from_skill(item)
        return cls._expand_compound_skill_names(raw_name)

    @staticmethod
    def _raw_name_from_skill(item):
        if isinstance(item, (VerifiedSkill,)):
            return item.name
        elif hasattr(item, "name"):
            return item.name
        elif isinstance(item, dict):
            return item.get("name") or item.get("skill") or ""
        return item

    @classmethod
    def _expand_compound_skill_names(cls, name):
        normalized = re.sub(r"\s+", " ", str(name or "")).strip()
        normalized = normalized.strip(".,;:|/\\<>")
        if not normalized:
            return []

        raw_parts = []
        parenthetical_values = re.findall(r"\(([^()]*)\)", normalized)
        outside_parentheses = re.sub(r"\([^()]*\)", " ", normalized).strip()
        if outside_parentheses:
            raw_parts.append(outside_parentheses)

        for value in parenthetical_values:
            if cls._is_standalone_parenthetical_skill(value):
                raw_parts.append(value)

        if not raw_parts:
            raw_parts = [normalized]

        names = []
        seen = set()
        for part in raw_parts:
            display_name = cls._normalize_display_name(part)
            key = SkillSet.normalize_name(display_name)
            if not key or key in seen:
                continue
            seen.add(key)
            names.append(display_name)
        return names

    @staticmethod
    def _is_standalone_parenthetical_skill(value):
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        normalized = normalized.strip(".,;:|/\\<>")
        if not normalized or not re.search(r"[A-Za-z0-9]", normalized):
            return False
        if "," in normalized or ":" in normalized:
            return False
        return len(normalized.split()) <= 4

    @staticmethod
    def _normalize_display_name(name):
        normalized = re.sub(r"\s+", " ", str(name or "")).strip()
        normalized = normalized.strip(".,;:|/\\<>")
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
            "mysql": "MySQL",
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
        records = (
            skillsets
            if skillsets is not None
            else SkillSet.objects.prefetch_related("keywords")
        )
        for skillset in records:
            canonical_keyword = None
            for keyword in skillset.keywords.all():
                if (
                    keyword.status == SkillKeyword.StatusChoices.ACTIVE
                    and keyword.normalized_text == skillset.normalized_name
                ):
                    canonical_keyword = keyword
                    break
            index[skillset.normalized_name] = SkillSetMapper._match_payload(
                skillset=skillset,
                match_type="normalized_name",
                keyword=canonical_keyword,
            )
            for keyword in skillset.keywords.all():
                if keyword.status == SkillKeyword.StatusChoices.ACTIVE:
                    index.setdefault(
                        keyword.normalized_text,
                        SkillSetMapper._match_payload(
                            skillset=skillset,
                            match_type="keyword",
                            keyword=keyword,
                        ),
                    )
            for alias in skillset.normalized_aliases:
                index.setdefault(
                    alias,
                    SkillSetMapper._match_payload(
                        skillset=skillset,
                        match_type="alias",
                    ),
                )
        for alias_record in SkillAlias.objects.select_related("skill").all():
            normalized_alias = SkillSet.normalize_name(alias_record.alias)
            if not normalized_alias:
                continue
            index.setdefault(
                normalized_alias,
                SkillSetMapper._match_payload(
                    skillset=alias_record.skill,
                    match_type="skill_alias",
                ),
            )
        return index

    @staticmethod
    def _match_payload(skillset, match_type, keyword=None):
        return {
            "skillset": skillset,
            "match_type": match_type,
            "keyword": keyword,
        }

    @staticmethod
    def _mapped_keyword(keyword):
        return MappedKeyword(
            skillset_id=keyword.skill_set_id,
            keyword_id=keyword.id,
            raw_text=keyword.raw_text,
            normalized_text=keyword.normalized_text,
            source=keyword.source,
            status=keyword.status,
        )

    @staticmethod
    def _create_skillset(name):
        normalized_name = SkillSet.normalize_name(name)
        display_name = SkillSetMapper._normalize_display_name(name)
        try:
            with transaction.atomic():
                return (
                    SkillSet.objects.create(
                        name=display_name,
                        normalized_name=normalized_name,
                        auto_created=True,
                    ),
                    True,
                )
        except IntegrityError:
            return SkillSet.objects.get(normalized_name=normalized_name), False
