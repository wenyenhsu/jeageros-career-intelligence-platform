import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib import error, request

from django.conf import settings

logger = logging.getLogger(__name__)


class SkillExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateSkill:
    name: str
    source: str = "description"
    confidence: float | None = None
    source_fragment: str = ""

    def as_dict(self):
        data = {"name": self.name, "source": self.source}
        if self.confidence is not None:
            data["confidence"] = self.confidence
        if self.source_fragment:
            data["source_fragment"] = self.source_fragment
        return data


@dataclass(frozen=True)
class SkillExtractionResult:
    candidate_skills: list[CandidateSkill]
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {
            "skills": [skill.as_dict() for skill in self.candidate_skills],
            "metadata": self.metadata,
        }


class OllamaExtractor:
    def __init__(self, model=None, base_url=None, timeout=None, max_skills=None):
        self.model = model or settings.OLLAMA_SKILL_MODEL
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.OLLAMA_TIMEOUT_SECONDS
        self.max_skills = max_skills or settings.OLLAMA_MAX_CANDIDATE_SKILLS

    def extract(
        self,
        title,
        description,
        raw_text="",
        normalized_text="",
        source_fragments=None,
        source_job_identifier="",
    ):
        content = self._build_content(
            title=title,
            description=description,
            raw_text=raw_text,
            normalized_text=normalized_text,
            source_fragments=source_fragments,
        )
        if not content:
            raise SkillExtractionError("Job content is required for skill extraction.")

        logger.info(
            "Starting Ollama skill extraction: model=%s source_job=%s",
            self.model,
            source_job_identifier or "",
        )
        try:
            payload = self._call_ollama(self._build_prompt(content))
            result = self.parse_response(
                payload,
                source_job_identifier=source_job_identifier,
            )
        except SkillExtractionError:
            logger.exception(
                "Ollama skill extraction failed: model=%s source_job=%s",
                self.model,
                source_job_identifier or "",
            )
            raise

        logger.info(
            "Finished Ollama skill extraction: model=%s source_job=%s skills=%s",
            self.model,
            source_job_identifier or "",
            len(result.candidate_skills),
        )
        return result

    def parse_response(self, payload, source_job_identifier=""):
        data = self._coerce_payload(payload)
        skills_payload = data.get("candidate_skills") or data.get("skills")
        if not isinstance(skills_payload, list) or not skills_payload:
            raise SkillExtractionError(
                "Ollama response did not include candidate skills."
            )

        skills = []
        seen = set()
        for item in skills_payload:
            candidate = self._candidate_from_payload(item)
            key = candidate.name.casefold()
            if key in seen:
                continue
            seen.add(key)
            skills.append(candidate)
            if len(skills) >= self.max_skills:
                break

        if not skills:
            raise SkillExtractionError("Ollama response did not include usable skills.")

        return SkillExtractionResult(
            candidate_skills=skills,
            metadata={
                "model": data.get("model", self.model),
                "extractor": "ollama",
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
            raise SkillExtractionError(f"Ollama request failed: {exc}") from exc

        return response_payload.get("response", response_payload)

    def _build_prompt(self, content):
        return (
            "Extract candidate technical skills from this job content. "
            "Return only JSON with a skills array. "
            "Each item must include name and source. "
            "Source must be one of title, description, normalized_text, source_fragment, or raw_text. "
            "Each item may include confidence and source_fragment. "
            "Do not include personal notes, tags, soft skills, or unrelated keywords. "
            f"Limit to {self.max_skills} normalized technical skills.\n\n"
            f"{content}"
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
            OllamaExtractor._format_source_fragments(source_fragments),
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
                raise SkillExtractionError(
                    "Ollama response was malformed JSON."
                ) from exc
        if not isinstance(payload, dict):
            raise SkillExtractionError("Ollama response must be a JSON object.")
        return payload

    def _candidate_from_payload(self, item):
        if isinstance(item, str):
            name = item
            confidence = None
            source_fragment = ""
        elif isinstance(item, dict):
            name = item.get("name") or item.get("skill") or ""
            source = self._normalize_source(item.get("source", "description"))
            confidence = self._normalize_confidence(item.get("confidence"))
            source_fragment = self._normalize_fragment(item.get("source_fragment", ""))
        else:
            raise SkillExtractionError(
                "Candidate skill entries must be objects or strings."
            )
        if isinstance(item, str):
            source = "description"

        normalized_name = self._normalize_skill_name(name)
        if not normalized_name:
            raise SkillExtractionError("Candidate skill name cannot be empty.")
        return CandidateSkill(
            name=normalized_name,
            source=source,
            confidence=confidence,
            source_fragment=source_fragment,
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
            return " ".join(word[:1].upper() + word[1:].lower() for word in normalized.split())
        return normalized

    @staticmethod
    def _normalize_source(source):
        normalized = re.sub(r"\s+", "_", str(source or "")).strip().lower()
        allowed_sources = {
            "title",
            "description",
            "normalized_text",
            "source_fragment",
            "raw_text",
        }
        return normalized if normalized in allowed_sources else "description"

    @staticmethod
    def _normalize_confidence(confidence):
        if confidence is None or confidence == "":
            return None
        try:
            value = float(confidence)
        except (TypeError, ValueError) as exc:
            raise SkillExtractionError("Skill confidence must be numeric.") from exc
        return max(0.0, min(1.0, value))

    @staticmethod
    def _normalize_fragment(fragment):
        return re.sub(r"\s+", " ", str(fragment or "")).strip()[:240]
