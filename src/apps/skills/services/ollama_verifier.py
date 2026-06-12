import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib import error, request

from django.conf import settings

from .ollama_extractor import CandidateSkill, SkillExtractionResult

logger = logging.getLogger(__name__)


class SkillVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedSkill:
    name: str
    status: str = "accepted"
    reason: str = ""

    def as_dict(self):
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RejectedSkill:
    name: str
    reason: str = ""

    def as_dict(self):
        return {
            "name": self.name,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SkillVerificationResult:
    verified_skills: list[VerifiedSkill]
    rejected_skills: list[RejectedSkill]
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {
            "verified_skills": [skill.as_dict() for skill in self.verified_skills],
            "rejected_skills": [skill.as_dict() for skill in self.rejected_skills],
            "metadata": self.metadata,
        }


class OllamaVerifier:
    def __init__(self, model=None, base_url=None, timeout=None, max_skills=None):
        self.model = model or settings.OLLAMA_SKILL_MODEL
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.OLLAMA_TIMEOUT_SECONDS
        self.max_skills = (
            max_skills
            if max_skills is not None
            else settings.OLLAMA_MAX_VERIFIED_SKILLS
        )

    def verify(
        self,
        title,
        description,
        candidate_skills,
        raw_text="",
        normalized_text="",
        source_fragments=None,
        source_job_identifier="",
    ):
        candidates = self._coerce_candidate_skills(candidate_skills)
        content = self._build_content(
            title=title,
            description=description,
            raw_text=raw_text,
            normalized_text=normalized_text,
            source_fragments=source_fragments,
        )
        if not content:
            raise SkillVerificationError(
                "Job content is required for skill verification."
            )

        logger.info(
            "Starting Ollama skill verification: model=%s source_job=%s candidates=%s",
            self.model,
            source_job_identifier or "",
            len(candidates),
        )
        try:
            payload = self._call_ollama(self._build_prompt(content, candidates))
            result = self.parse_response(
                payload,
                source_job_identifier=source_job_identifier,
            )
        except SkillVerificationError:
            logger.exception(
                "Ollama skill verification failed: model=%s source_job=%s",
                self.model,
                source_job_identifier or "",
            )
            raise

        logger.info(
            "Finished Ollama skill verification: model=%s source_job=%s accepted=%s rejected=%s",
            self.model,
            source_job_identifier or "",
            len(result.verified_skills),
            len(result.rejected_skills),
        )
        return result

    def parse_response(self, payload, source_job_identifier=""):
        data = self._coerce_payload(payload)
        verified_payload = data.get("verified_skills", [])
        rejected_payload = data.get("rejected_skills", [])

        if not isinstance(verified_payload, list) or not isinstance(
            rejected_payload, list
        ):
            raise SkillVerificationError(
                "Ollama verification response must include skill lists."
            )
        if not verified_payload and not rejected_payload:
            raise SkillVerificationError(
                "Ollama verification response did not include usable results."
            )

        verified_skills = []
        rejected_skills = []
        accepted_names = set()
        rejected_names = set()

        for item in verified_payload:
            if len(verified_skills) >= self.max_skills:
                break
            skill = self._verified_from_payload(item)
            key = skill.name.casefold()
            if key in accepted_names:
                continue
            accepted_names.add(key)
            verified_skills.append(skill)

        remaining = self.max_skills - len(verified_skills)
        for item in rejected_payload:
            if len(rejected_skills) >= remaining:
                break
            skill = self._rejected_from_payload(item)
            key = skill.name.casefold()
            if key in accepted_names or key in rejected_names:
                continue
            rejected_names.add(key)
            rejected_skills.append(skill)

        if not verified_skills and not rejected_skills:
            raise SkillVerificationError(
                "Ollama verification response did not include usable skills."
            )

        return SkillVerificationResult(
            verified_skills=verified_skills,
            rejected_skills=rejected_skills,
            metadata={
                "model": data.get("model", self.model),
                "verifier": "ollama",
                "max_skills": self.max_skills,
                "source_job_identifier": source_job_identifier or "",
            },
        )

    def _call_ollama(self, prompt):
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise SkillVerificationError(f"Ollama request failed: {exc}") from exc

        return response_payload.get("response", response_payload)

    def _build_prompt(self, content, candidates):
        candidates_json = json.dumps(candidates, ensure_ascii=True)
        return (
            "Verify candidate technical skills against this job content. "
            "Use canonical job fields and sections as evidence and reject weakly supported, generic, irrelevant, or hallucinated skills. "
            "Refine skill names when the intended technical skill is clear. "
            "Return only JSON with verified_skills and rejected_skills arrays. "
            "Each verified skill must include name, status set to accepted, and reason. "
            "Each rejected skill must include name and reason. "
            f"Limit combined output to {self.max_skills} skills.\n\n"
            f"Candidate skills JSON:\n{candidates_json}\n\n"
            f"Job content:\n{content}"
        )

    @staticmethod
    def _build_content(
        title,
        description,
        raw_text="",
        normalized_text="",
        source_fragments=None,
    ):
        parts = [
            f"Title: {title}" if title else "",
            f"Description: {description}" if description else "",
            f"Normalized parser text: {normalized_text}" if normalized_text else "",
            OllamaVerifier._format_source_fragments(source_fragments),
            f"Raw parser text: {raw_text}" if raw_text else "",
        ]
        return "\n\n".join(part.strip() for part in parts if part.strip())

    @staticmethod
    def _format_source_fragments(source_fragments):
        if not source_fragments:
            return ""

        fragments = []
        for fragment in source_fragments:
            if isinstance(fragment, dict):
                label = fragment.get("source") or fragment.get("label") or "fragment"
                text = fragment.get("text") or fragment.get("content") or ""
                if text:
                    fragments.append(f"- {label}: {text}")
            else:
                text = str(fragment).strip()
                if text:
                    fragments.append(f"- fragment: {text}")

        if not fragments:
            return ""
        return "Source fragments:\n" + "\n".join(fragments)

    @staticmethod
    def _coerce_payload(payload):
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise SkillVerificationError(
                    "Ollama verification response was malformed JSON."
                ) from exc
        if not isinstance(payload, dict):
            raise SkillVerificationError(
                "Ollama verification response must be a JSON object."
            )
        return payload

    @classmethod
    def _coerce_candidate_skills(cls, candidate_skills):
        if isinstance(candidate_skills, SkillExtractionResult):
            candidate_skills = candidate_skills.candidate_skills
        elif isinstance(candidate_skills, dict):
            candidate_skills = (
                candidate_skills.get("skills")
                or candidate_skills.get("candidate_skills")
                or []
            )

        if isinstance(candidate_skills, (str, CandidateSkill)):
            candidate_skills = [candidate_skills]

        candidates = []
        seen = set()
        for item in candidate_skills or []:
            candidate = cls._candidate_to_prompt_payload(item)
            key = candidate["name"].casefold()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

        if not candidates:
            raise SkillVerificationError(
                "Candidate skills are required for skill verification."
            )
        return candidates

    @classmethod
    def _candidate_to_prompt_payload(cls, item):
        if isinstance(item, CandidateSkill):
            name = item.name
            source = item.source
        elif isinstance(item, dict):
            name = item.get("name") or item.get("skill") or ""
            source = item.get("source", "description")
        else:
            name = str(item or "")
            source = "description"

        normalized_name = cls._normalize_skill_name(name)
        if not normalized_name:
            raise SkillVerificationError("Candidate skill name cannot be empty.")

        return {
            "name": normalized_name,
            "source": cls._normalize_source(source),
        }

    @classmethod
    def _verified_from_payload(cls, item):
        if not isinstance(item, dict):
            raise SkillVerificationError("Verified skill entries must be objects.")

        name = cls._normalize_skill_name(item.get("name") or item.get("skill") or "")
        if not name:
            raise SkillVerificationError("Verified skill name cannot be empty.")
        return VerifiedSkill(
            name=name,
            status="accepted",
            reason=cls._normalize_reason(item.get("reason", "")),
        )

    @classmethod
    def _rejected_from_payload(cls, item):
        if not isinstance(item, dict):
            raise SkillVerificationError("Rejected skill entries must be objects.")

        name = cls._normalize_skill_name(item.get("name") or item.get("skill") or "")
        if not name:
            raise SkillVerificationError("Rejected skill name cannot be empty.")
        return RejectedSkill(
            name=name,
            reason=cls._normalize_reason(item.get("reason", "")),
        )

    @staticmethod
    def _normalize_skill_name(name):
        normalized = re.sub(r"\s+", " ", str(name or "")).strip()
        normalized = normalized.strip(".,;:|/\\")
        if not normalized:
            return ""
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
    def _normalize_source(source):
        normalized = re.sub(r"\s+", "_", str(source or "")).strip().lower()
        allowed_sources = {
            "title",
            "description",
            "about",
            "responsibilities",
            "requirements",
            "minimum_qualifications",
            "preferred_qualifications",
            "normalized_text",
            "source_fragment",
            "raw_text",
        }
        return normalized if normalized in allowed_sources else "description"

    @staticmethod
    def _normalize_reason(reason):
        return re.sub(r"\s+", " ", str(reason or "")).strip()[:300]
