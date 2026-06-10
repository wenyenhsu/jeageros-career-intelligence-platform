import logging
import re
from dataclasses import dataclass, field
from typing import Any

from apps.skills.models import SkillSet

from .ollama_verifier import SkillVerificationResult
from .skillset_mapper import MappedSkill, SkillMappingResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoredSkill:
    name: str
    skillset_id: int
    score: int
    reasons: list[str]

    def as_dict(self):
        return {
            "name": self.name,
            "skillset_id": self.skillset_id,
            "score": self.score,
            "reasons": self.reasons,
        }


@dataclass(frozen=True)
class SkillScoringResult:
    scored_skills: list[ScoredSkill]
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {
            "scored_skills": [skill.as_dict() for skill in self.scored_skills],
            "metadata": self.metadata,
        }


class SkillScoringService:
    def score_mapped_skills(
        self,
        mapped_skills,
        verified_skills=None,
        title="",
        description="",
        normalized_text="",
        source_fragments=None,
        source_job_identifier="",
    ):
        mapped = self._coerce_mapped_skills(mapped_skills)
        verified_index = self._build_verified_index(verified_skills)
        skillsets = self._load_skillsets(mapped)

        logger.info(
            "Starting skill scoring: source_job=%s mapped=%s",
            source_job_identifier or "",
            len(mapped),
        )

        scored = []
        for item in mapped:
            skillset = skillsets.get(item["skillset_id"])
            names = self._skill_terms(item, skillset)
            score, reasons = self._score_one(
                item=item,
                names=names,
                verified=self._verified_for_names(names, verified_index),
                title=title,
                description=description,
                normalized_text=normalized_text,
                source_fragments=source_fragments or [],
            )
            scored.append(
                ScoredSkill(
                    name=skillset.name if skillset else item["name"],
                    skillset_id=item["skillset_id"],
                    score=score,
                    reasons=reasons,
                )
            )

        scored.sort(key=lambda skill: (-skill.score, skill.name.casefold()))

        logger.info(
            "Finished skill scoring: source_job=%s scored=%s scores=%s",
            source_job_identifier or "",
            len(scored),
            [(skill.skillset_id, skill.score) for skill in scored],
        )
        return SkillScoringResult(
            scored_skills=scored,
            metadata={
                "scorer": "deterministic_evidence_v1",
                "source_job_identifier": source_job_identifier or "",
            },
        )

    @classmethod
    def _coerce_mapped_skills(cls, mapped_skills):
        if isinstance(mapped_skills, SkillMappingResult):
            mapped_skills = mapped_skills.matched
        elif isinstance(mapped_skills, dict):
            mapped_skills = mapped_skills.get("matched", [])

        if isinstance(mapped_skills, MappedSkill):
            mapped_skills = [mapped_skills]

        mapped = []
        seen = set()
        for item in mapped_skills or []:
            if isinstance(item, MappedSkill):
                name = item.name
                skillset_id = item.skillset_id
                created = item.created
            else:
                name = item.get("name", "")
                skillset_id = item.get("skillset_id")
                created = item.get("created", False)

            if not skillset_id or skillset_id in seen:
                continue
            seen.add(skillset_id)
            mapped.append(
                {
                    "name": cls._normalize_display_name(name),
                    "skillset_id": int(skillset_id),
                    "created": bool(created),
                }
            )
        return mapped

    @classmethod
    def _build_verified_index(cls, verified_skills):
        if isinstance(verified_skills, SkillVerificationResult):
            verified_skills = verified_skills.verified_skills
        elif isinstance(verified_skills, dict):
            verified_skills = verified_skills.get("verified_skills", [])

        index = {}
        for item in verified_skills or []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("skill") or ""
                reason = item.get("reason", "")
            else:
                name = getattr(item, "name", "")
                reason = getattr(item, "reason", "")
            normalized = cls._normalize_name(name)
            if normalized:
                index[normalized] = {"reason": cls._normalize_reason(reason)}
        return index

    @staticmethod
    def _load_skillsets(mapped):
        ids = [item["skillset_id"] for item in mapped]
        return SkillSet.objects.in_bulk(ids)

    @classmethod
    def _skill_terms(cls, item, skillset):
        terms = [item["name"]]
        if skillset:
            terms.append(skillset.name)
            terms.extend(skillset.aliases or [])

        normalized_terms = []
        seen = set()
        for term in terms:
            normalized = cls._normalize_display_name(term)
            key = cls._normalize_name(normalized)
            if not key or key in seen:
                continue
            seen.add(key)
            normalized_terms.append(normalized)
        return normalized_terms

    @classmethod
    def _verified_for_names(cls, names, verified_index):
        for name in names:
            verified = verified_index.get(cls._normalize_name(name))
            if verified:
                return verified
        return {}

    @classmethod
    def _score_one(
        cls,
        item,
        names,
        verified,
        title,
        description,
        normalized_text,
        source_fragments,
    ):
        score = 0
        reasons = []

        if cls._contains_any(title, names):
            score += 30
            reasons.append("title match")

        requirements_text = cls._requirements_text(source_fragments)
        if cls._contains_any(requirements_text, names):
            score += 25
            reasons.append("requirements match")

        if cls._contains_any(description, names):
            score += 20
            reasons.append("description match")

        if cls._contains_any(normalized_text, names):
            score += 15
            reasons.append("normalized text match")

        if verified:
            score += 20
            reason = verified.get("reason")
            reasons.append(
                f"verification support: {reason}" if reason else "verification support"
            )

        if item["created"]:
            score += 5
            reasons.append("auto-created SkillSet")
        else:
            score += 10
            reasons.append("canonical SkillSet match")

        frequency = cls._count_occurrences(
            " ".join(
                [
                    str(title or ""),
                    str(description or ""),
                    str(normalized_text or ""),
                    cls._all_fragments_text(source_fragments),
                ]
            ),
            names,
        )
        if frequency > 1:
            score += min(10, (frequency - 1) * 2)
            reasons.append("repeated evidence")

        if not reasons:
            reasons.append("mapped skill")

        return min(score, 100), reasons

    @classmethod
    def _contains_any(cls, text, terms):
        normalized_text = cls._normalize_text(text)
        return any(cls._normalize_name(term) in normalized_text for term in terms)

    @classmethod
    def _count_occurrences(cls, text, terms):
        normalized_text = cls._normalize_text(text)
        count = 0
        for term in terms:
            normalized_term = re.escape(cls._normalize_name(term))
            if not normalized_term:
                continue
            count += len(re.findall(normalized_term, normalized_text))
        return count

    @classmethod
    def _requirements_text(cls, source_fragments):
        fragments = []
        for fragment in source_fragments or []:
            if isinstance(fragment, dict):
                label = str(fragment.get("source") or fragment.get("label") or "")
                text = fragment.get("text") or fragment.get("content") or ""
                label_key = cls._normalize_text(label)
                if any(
                    key in label_key
                    for key in (
                        "requirement",
                        "qualification",
                        "preferred",
                        "minimum",
                    )
                ):
                    fragments.append(str(text))
            else:
                fragments.append(str(fragment))
        return " ".join(fragments)

    @staticmethod
    def _all_fragments_text(source_fragments):
        fragments = []
        for fragment in source_fragments or []:
            if isinstance(fragment, dict):
                fragments.append(str(fragment.get("text") or fragment.get("content") or ""))
            else:
                fragments.append(str(fragment))
        return " ".join(fragments)

    @staticmethod
    def _normalize_display_name(name):
        return re.sub(r"\s+", " ", str(name or "")).strip().strip(".,;:|/\\")

    @classmethod
    def _normalize_name(cls, name):
        return cls._normalize_text(name).strip(".,;:|/\\")

    @staticmethod
    def _normalize_text(text):
        return re.sub(r"\s+", " ", str(text or "")).strip().casefold()

    @staticmethod
    def _normalize_reason(reason):
        return re.sub(r"\s+", " ", str(reason or "")).strip()[:160]
