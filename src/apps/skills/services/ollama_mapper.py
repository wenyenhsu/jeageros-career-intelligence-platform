import json
import logging
from dataclasses import dataclass
from urllib import error, request

from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaSkillMappingError(ValueError):
    """Raised when Ollama cannot produce a usable skill mapping response."""

    pass


@dataclass(frozen=True)
class OllamaSkillMapping:
    """Parsed Ollama response for mapping one raw skill to a canonical option."""

    original: str
    canonical: str | None
    confidence: float
    reason: str

    def as_dict(self):
        return {
            "original": self.original,
            "canonical": self.canonical,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class OllamaSkillMapper:
    """Ask Ollama to map a raw skill to an existing canonical SkillSet name.

    The prompt constrains Ollama to pick from the supplied canonical SkillSet
    names, so unresolved raw skills remain unmapped instead of creating ad hoc
    skill labels.
    """

    def __init__(self, model=None, base_url=None, timeout=None):
        self.model = model or settings.OLLAMA_SKILL_MODEL
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.OLLAMA_TIMEOUT_SECONDS

    def map(self, raw_skill, canonical_options=None):
        prompt = self._build_prompt(raw_skill, canonical_options or [])
        logger.info(
            "Starting Ollama skill mapping: model=%s raw_skill=%s",
            self.model,
            raw_skill,
        )
        payload = self._call_ollama(prompt)
        result = self.parse_response(payload, original=raw_skill)
        logger.info(
            "Finished Ollama skill mapping: "
            "model=%s raw_skill=%s canonical=%s confidence=%s",
            self.model,
            raw_skill,
            result.canonical or "",
            result.confidence,
        )
        return result

    def parse_response(self, payload, original=""):
        data = self._coerce_payload(payload)
        canonical = self._clean_optional_text(data.get("canonical"))
        confidence = self._normalize_confidence(data.get("confidence", 0.0))
        reason = self._clean_optional_text(data.get("reason")) or ""
        original_value = self._clean_optional_text(data.get("original")) or str(
            original or ""
        )
        return OllamaSkillMapping(
            original=original_value,
            canonical=canonical,
            confidence=confidence,
            reason=reason,
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
            raise OllamaSkillMappingError(
                f"Ollama skill mapping request failed: {exc}"
            ) from exc

        return response_payload.get("response", response_payload)

    @staticmethod
    def _build_prompt(raw_skill, canonical_options):
        options_json = json.dumps(list(canonical_options), ensure_ascii=True)
        return (
            "You are verifying whether a raw extracted skill maps to one known "
            "canonical skill.\n\n"
            f"Known Candidate Skills:\n{options_json}\n\n"
            f"Input Skill:\n{raw_skill}\n\n"
            "Rules:\n"
            "- Select only from Known Candidate Skills.\n"
            "- Do not invent new canonical skills.\n"
            "- Return valid JSON only.\n"
            "- If confidence is low, return canonical as null.\n\n"
            "Expected JSON shape:\n"
            '{"original": "...", "canonical": "...", '
            '"confidence": 0.0, "reason": "..."}'
        )

    @staticmethod
    def _coerce_payload(payload):
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise OllamaSkillMappingError(
                    "Ollama skill mapping response was malformed JSON."
                ) from exc
        if not isinstance(payload, dict):
            raise OllamaSkillMappingError(
                "Ollama skill mapping response must be a JSON object."
            )
        return payload

    @staticmethod
    def _clean_optional_text(value):
        if value is None:
            return None
        text = " ".join(str(value).split()).strip()
        return text or None

    @staticmethod
    def _normalize_confidence(value):
        try:
            confidence = float(value)
        except (TypeError, ValueError) as exc:
            raise OllamaSkillMappingError(
                "Ollama skill mapping confidence must be numeric."
            ) from exc
        return max(0.0, min(1.0, confidence))
