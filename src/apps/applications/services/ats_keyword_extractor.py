import json
import logging
from urllib import error, request

from django.conf import settings

logger = logging.getLogger(__name__)


class AtsKeywordError(ValueError):
    pass


class AtsKeywordExtractor:
    """Pull ATS screening phrases from one job posting. Not SkillSet / Market Fit."""

    max_keywords = 10

    def __init__(self, model=None, base_url=None, timeout=None):
        self.model = model or settings.OLLAMA_SKILL_MODEL
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.OLLAMA_TIMEOUT_SECONDS

    def extract_keywords(self, title, description):
        content = "\n\n".join(
            part for part in (str(title or "").strip(), str(description or "").strip()) if part
        )
        if not content:
            raise AtsKeywordError("Job description is required for ATS keyword extraction.")

        payload = self._call_ollama(self._build_prompt(content))
        keywords = self._parse_keywords(payload)
        if not keywords:
            raise AtsKeywordError("ATS keyword extraction returned no keywords.")
        return keywords

    def rewrite_draft(self, kind, job_title, company, resume_text, unmatched):
        payload = self._call_ollama(
            self._build_rewrite_prompt(kind, job_title, company, resume_text, unmatched)
        )
        return self._payload_text(payload)

    def rewrite_cover_letter(self, job_title, company, cover_letter_text, job_description):
        payload = self._call_ollama(
            self._build_cover_letter_prompt(
                job_title, company, cover_letter_text, job_description
            )
        )
        text = self._payload_text(payload)
        if not text:
            raise AtsKeywordError("Cover letter rewrite returned no text.")
        return text

    @staticmethod
    def _payload_text(payload):
        data = payload
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return payload.strip()
        if isinstance(data, dict):
            return str(data.get("text") or data.get("draft") or "").strip()
        return str(data or "").strip()

    def _parse_keywords(self, payload):
        data = payload
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"keywords": []}
        if not isinstance(data, dict):
            return []

        raw_items = data.get("keywords") or data.get("ats_keywords") or []
        keywords = []
        seen = set()
        for item in raw_items:
            if isinstance(item, dict):
                value = str(item.get("name") or item.get("keyword") or "").strip()
            else:
                value = str(item or "").strip()
            key = " ".join(value.casefold().split())
            if not key or key in seen:
                continue
            seen.add(key)
            keywords.append(value)
            if len(keywords) >= self.max_keywords:
                break
        return keywords

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
            raise AtsKeywordError(f"Ollama ATS request failed: {exc}") from exc
        return response_payload.get("response", response_payload)

    def _build_prompt(self, content):
        return (
            "Extract ATS screening keywords from this single job posting. "
            "Use wording an applicant-tracking system would scan for: tools, "
            "platforms, products, and domain phrases as they appear in the posting. "
            "Do not invent keywords that are not in the posting. "
            "Do not use market-demand or SkillSet catalogs. "
            f"Return only JSON: {{\"keywords\": [\"...\", ...]}} with at most "
            f"{self.max_keywords} items.\n\n{content}"
        )

    def _build_rewrite_prompt(self, kind, job_title, company, resume_text, unmatched):
        label = "cover letter" if kind == "cover_letter" else "resume"
        missing = ", ".join(unmatched)
        return (
            f"Rewrite this {label} for {job_title} at {company} so an ATS can "
            "find the unmatched keywords. Keep facts truthful. Do not invent "
            "employers, titles, or dates. Weave unmatched keywords into existing "
            "experience only where they reasonably fit. "
            f"Unmatched keywords: {missing}. "
            "Return only JSON: {\"text\": \"markdown draft\"}.\n\n"
            f"{resume_text[:12000]}"
        )

    def _build_cover_letter_prompt(
        self, job_title, company, cover_letter_text, job_description
    ):
        return (
            f"Rewrite this cover letter for {job_title} at {company}. "
            "Use wording from the job description where it truthfully fits. "
            "Keep facts truthful. Do not invent employers, titles, dates, or skills. "
            "Do not use a market skill catalog or synonyms that are not in the "
            "job description or the original letter. "
            "Keep a professional 3-4 paragraph cover letter. "
            "Return only JSON: {\"text\": \"cover letter\"}.\n\n"
            f"Job description:\n{str(job_description or '')[:8000]}\n\n"
            f"Original cover letter:\n{str(cover_letter_text or '')[:8000]}"
        )
