import logging
from io import BytesIO
from pathlib import Path
import time
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from apps.imports.models import PipelineLog
from apps.imports.services.monitoring_service import MonitoringService
from apps.skills.models import SkillSet
from apps.skills.services.ollama_extractor import OllamaExtractor, SkillExtractionError
from apps.skills.services.ollama_verifier import OllamaVerifier
from apps.skills.services.skillset_mapper import SkillSetMapper

from .skill_analytics_service import SkillAnalyticsService

logger = logging.getLogger(__name__)


class ResumeAnalysisError(ValueError):
    pass


class ResumeAnalyticsService:
    default_job_limit = 6
    default_market_limit = 10
    max_attachment_bytes = 5 * 1024 * 1024
    text_extensions = {".txt", ".text", ".md", ".markdown"}
    supported_attachment_extensions = text_extensions | {".pdf", ".docx"}

    def __init__(self, extractor=None, verifier=None, mapper=None, skill_service=None):
        self.extractor = extractor or OllamaExtractor()
        self.verifier = verifier or OllamaVerifier()
        self.mapper = mapper or SkillSetMapper(auto_create=False)
        self.skill_service = skill_service or SkillAnalyticsService()

    def analyze_resume(
        self,
        resume_text,
        filters=None,
        job_limit=None,
        market_limit=None,
    ):
        started = time.perf_counter()
        pipeline_steps = []
        current_stage = None

        job_limit = job_limit or self.default_job_limit
        market_limit = market_limit or self.default_market_limit
        try:
            stage_started = time.perf_counter()
            current_stage = {
                "key": "text_extraction",
                "label": "Text extraction",
                "started": stage_started,
            }
            resume_text = self._clean_text(resume_text)
            if not resume_text:
                raise ResumeAnalysisError("Resume text is required.")
            resume_sections = self._resume_sections(resume_text)
            source_fragments = self._source_fragments_from_sections(resume_sections)
            self._append_pipeline_step(
                pipeline_steps,
                key="text_extraction",
                label="Text extraction",
                status="success",
                started=stage_started,
                message="Resume text prepared for analysis.",
                count=len(resume_text),
            )
            current_stage = None

            stage_started = time.perf_counter()
            current_stage = {
                "key": "ollama_extract",
                "label": "Ollama Extract",
                "started": stage_started,
            }
            extraction_result = self.extractor.extract(
                title="Resume",
                description=resume_text,
                source_fragments=source_fragments,
                source_job_identifier="resume-analysis",
                content_kind="resume",
            )
            candidate_skills = self._candidate_skills(extraction_result)
            if not candidate_skills:
                raise ResumeAnalysisError("No usable resume skills were extracted.")
            self._append_pipeline_step(
                pipeline_steps,
                key="ollama_extract",
                label="Ollama Extract",
                status="success",
                started=stage_started,
                message="Candidate resume skills extracted.",
                count=len(candidate_skills),
            )
            current_stage = None

            stage_started = time.perf_counter()
            current_stage = {
                "key": "ollama_verify",
                "label": "Ollama Verify",
                "started": stage_started,
            }
            verification_result = self.verifier.verify(
                title="Resume",
                description=resume_text,
                candidate_skills=candidate_skills,
                source_fragments=source_fragments,
                source_job_identifier="resume-analysis",
                content_kind="resume",
            )
            verified_keywords = self._verified_skills(verification_result)
            rejected_keywords = self._rejected_skills(verification_result)
            if not verified_keywords:
                raise ResumeAnalysisError("No verified resume skills were produced.")
            self._append_pipeline_step(
                pipeline_steps,
                key="ollama_verify",
                label="Ollama Verify",
                status="success",
                started=stage_started,
                message="Candidate skills verified against the resume.",
                count=len(verified_keywords),
                metadata={"rejected_count": len(rejected_keywords)},
            )
            current_stage = None

            stage_started = time.perf_counter()
            current_stage = {
                "key": "skillset_mapping",
                "label": "SkillSet mapping",
                "started": stage_started,
            }
            mapping_result = self.mapper.map_verified_skills(
                verified_keywords,
                auto_create=False,
                source_job_identifier="resume-analysis",
                model_name=getattr(self.verifier, "model", ""),
            )
            mapped_skills = self._mapped_skills(mapping_result)
            unmapped_keywords = self._unmapped_skills(mapping_result)
            resume_skill_ids = {skill["skillset_id"] for skill in mapped_skills}
            self._append_pipeline_step(
                pipeline_steps,
                key="skillset_mapping",
                label="SkillSet mapping",
                status="success",
                started=stage_started,
                message="Verified skills mapped to the SkillSet catalog.",
                count=len(mapped_skills),
                metadata={"unmapped_count": len(unmapped_keywords)},
            )
            current_stage = None

            stage_started = time.perf_counter()
            current_stage = {
                "key": "job_match",
                "label": "Job match",
                "started": stage_started,
            }
            job_matches = self._job_matches(
                resume_skill_ids=resume_skill_ids,
                filters=filters,
                limit=job_limit,
            )
            self._append_pipeline_step(
                pipeline_steps,
                key="job_match",
                label="Job match",
                status="success",
                started=stage_started,
                message="Mapped resume skills compared with tracked jobs.",
                count=len(job_matches),
            )
            current_stage = None

            stage_started = time.perf_counter()
            current_stage = {
                "key": "market_fit",
                "label": "Market fit",
                "started": stage_started,
            }
            market_fit = self._market_fit(
                resume_skill_ids=resume_skill_ids,
                filters=filters,
                limit=market_limit,
            )
            self._append_pipeline_step(
                pipeline_steps,
                key="market_fit",
                label="Market fit",
                status="success",
                started=stage_started,
                message="Mapped resume skills compared with current market demand.",
                count=len(market_fit.get("covered", [])),
                metadata={"missing_count": len(market_fit.get("missing", []))},
            )
            current_stage = None
            result = {
                "candidate_keywords": candidate_skills,
                "verified_keywords": verified_keywords,
                "rejected_keywords": rejected_keywords,
                "mapped_skills": mapped_skills,
                "unmapped_keywords": unmapped_keywords,
                "job_matches": job_matches,
                "market_fit": market_fit,
                "pipeline_steps": pipeline_steps,
                "metadata": {
                    "candidate_count": len(candidate_skills),
                    "verified_count": len(verified_keywords),
                    "rejected_count": len(rejected_keywords),
                    "mapped_count": len(mapped_skills),
                    "unmapped_count": len(unmapped_keywords),
                    "job_match_count": len(job_matches),
                },
            }
        except Exception as exc:
            if current_stage:
                self._append_pipeline_step(
                    pipeline_steps,
                    key=current_stage["key"],
                    label=current_stage["label"],
                    status="failed",
                    started=current_stage["started"],
                    message=str(exc),
                )
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._log_analysis(
                status=PipelineLog.StatusChoices.FAILED,
                severity=PipelineLog.SeverityChoices.ERROR,
                message="Resume analysis failed.",
                metadata={"pipeline_steps": pipeline_steps},
                duration_ms=duration_ms,
            )
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        self._log_analysis(
            status=PipelineLog.StatusChoices.SUCCESS,
            severity=PipelineLog.SeverityChoices.INFO,
            message="Resume analysis completed.",
            metadata=result["metadata"],
            duration_ms=duration_ms,
        )
        return result

    def analyze_resume_attachment(
        self,
        uploaded_file,
        filters=None,
        job_limit=None,
        market_limit=None,
    ):
        attachment_name, resume_text = self.extract_attachment_text(uploaded_file)
        result = self.analyze_resume(
            resume_text,
            filters=filters,
            job_limit=job_limit,
            market_limit=market_limit,
        )
        result["metadata"]["attachment_name"] = attachment_name
        return result

    def extract_attachment_text(self, uploaded_file):
        if not uploaded_file:
            raise ResumeAnalysisError("Resume attachment is required.")

        filename = Path(getattr(uploaded_file, "name", "") or "resume").name
        extension = Path(filename).suffix.casefold()
        if extension not in self.supported_attachment_extensions:
            supported = ", ".join(sorted(self.supported_attachment_extensions))
            raise ResumeAnalysisError(
                f"Unsupported resume file type. Upload one of: {supported}."
            )

        content = self._read_upload_bytes(uploaded_file)
        if extension in self.text_extensions:
            text = self._decode_text(content)
        elif extension == ".pdf":
            text = self._extract_pdf_text(content)
        else:
            text = self._extract_docx_text(content)

        text = self._clean_text(text)
        if not text:
            raise ResumeAnalysisError(
                "Could not extract readable text from the resume attachment."
            )
        return filename, text

    def _job_matches(self, resume_skill_ids, filters=None, limit=None):
        if not resume_skill_ids:
            return []

        jobs = self.skill_service.filtered_jobs(filters).select_related("company")
        matches = []
        for job in jobs.prefetch_related("skill_sets"):
            job_skills = list(job.skill_sets.all())
            job_skill_ids = {skill.id for skill in job_skills}
            if not job_skill_ids:
                continue

            matched_ids = resume_skill_ids & job_skill_ids
            if not matched_ids:
                continue

            missing_ids = job_skill_ids - resume_skill_ids
            skill_names = {skill.id: skill.name for skill in job_skills}
            match_percent = round((len(matched_ids) / len(job_skill_ids)) * 100, 1)
            matches.append(
                {
                    "job_id": job.id,
                    "title": job.title,
                    "company": job.company.name,
                    "job_type": job.job_type_display,
                    "location": job.location,
                    "source_url": job.source_url_display,
                    "match_percent": match_percent,
                    "matched_count": len(matched_ids),
                    "required_count": len(job_skill_ids),
                    "matched_skills": [
                        skill_names[skill_id] for skill_id in sorted(matched_ids)
                    ],
                    "missing_skills": [
                        skill_names[skill_id] for skill_id in sorted(missing_ids)
                    ][:6],
                }
            )

        return sorted(
            matches,
            key=lambda item: (
                -item["match_percent"],
                -item["matched_count"],
                item["company"].casefold(),
                item["title"].casefold(),
            ),
        )[:limit]

    def _market_fit(self, resume_skill_ids, filters=None, limit=None):
        market_skills = self.skill_service.top_skills(
            limit=limit or self.default_market_limit,
            filters=filters,
        )
        if not market_skills:
            return {
                "fit_percent": 0,
                "covered": [],
                "missing": [],
                "resume_only": [],
            }

        covered = [
            skill for skill in market_skills if skill["skillset_id"] in resume_skill_ids
        ]
        missing = [
            skill
            for skill in market_skills
            if skill["skillset_id"] not in resume_skill_ids
        ]
        market_skill_ids = {skill["skillset_id"] for skill in market_skills}
        resume_only = list(
            SkillSet.objects.filter(id__in=(resume_skill_ids - market_skill_ids))
            .order_by("name")
            .values("id", "name")
        )
        return {
            "fit_percent": round((len(covered) / len(market_skills)) * 100, 1),
            "covered": covered,
            "missing": missing,
            "resume_only": [
                {"skillset_id": row["id"], "name": row["name"]} for row in resume_only
            ],
        }

    @staticmethod
    def _verified_skills(verification_result):
        if hasattr(verification_result, "verified_skills"):
            payload = verification_result.verified_skills
        elif isinstance(verification_result, dict):
            payload = verification_result.get("verified_skills", [])
        else:
            payload = verification_result or []

        result = []
        seen = set()
        for item in payload:
            if isinstance(item, dict):
                name = item.get("name") or item.get("skill") or ""
                reason = item.get("reason", "")
                status = item.get("status", "accepted")
            elif hasattr(item, "name"):
                name = item.name
                reason = getattr(item, "reason", "")
                status = getattr(item, "status", "accepted")
            else:
                name = item
                reason = ""
                status = "accepted"

            for display_name in SkillSetMapper._expand_compound_skill_names(name):
                key = SkillSet.normalize_name(display_name)
                if not key or key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        "name": display_name,
                        "status": status or "accepted",
                        "reason": reason or "",
                    }
                )
        return result

    @staticmethod
    def _rejected_skills(verification_result):
        if hasattr(verification_result, "rejected_skills"):
            payload = verification_result.rejected_skills
        elif isinstance(verification_result, dict):
            payload = verification_result.get("rejected_skills", [])
        else:
            payload = []

        result = []
        seen = set()
        for item in payload:
            if isinstance(item, dict):
                name = item.get("name") or item.get("skill") or ""
                reason = item.get("reason", "")
            elif hasattr(item, "name"):
                name = item.name
                reason = getattr(item, "reason", "")
            else:
                name = item
                reason = ""

            for display_name in SkillSetMapper._expand_compound_skill_names(name):
                key = SkillSet.normalize_name(display_name)
                if not key or key in seen:
                    continue
                seen.add(key)
                result.append({"name": display_name, "reason": reason or ""})
        return result

    @staticmethod
    def _candidate_skills(extraction_result):
        if hasattr(extraction_result, "candidate_skills"):
            payload = extraction_result.candidate_skills
        elif isinstance(extraction_result, dict):
            payload = extraction_result.get("skills") or extraction_result.get(
                "candidate_skills", []
            )
        else:
            payload = extraction_result or []

        candidates = []
        seen = set()
        for item in payload:
            if isinstance(item, dict):
                name = item.get("name") or item.get("skill") or ""
                source = item.get("source") or "resume"
                confidence = item.get("confidence")
                source_fragment = item.get("source_fragment", "")
            elif hasattr(item, "name"):
                name = item.name
                source = getattr(item, "source", "resume")
                confidence = getattr(item, "confidence", None)
                source_fragment = getattr(item, "source_fragment", "")
            else:
                name = item
                source = "resume"
                confidence = None
                source_fragment = ""
            for display_name in SkillSetMapper._expand_compound_skill_names(name):
                key = SkillSet.normalize_name(display_name)
                if not key or key in seen:
                    continue
                seen.add(key)
                candidate = {"name": display_name, "source": source or "resume"}
                if confidence is not None:
                    candidate["confidence"] = confidence
                if source_fragment:
                    candidate["source_fragment"] = source_fragment
                candidates.append(candidate)
        return candidates

    @classmethod
    def _resume_sections(cls, resume_text):
        section_aliases = {
            "summary": {"summary", "profile", "objective"},
            "skills": {"skills", "technical skills", "technologies"},
            "experience": {"experience", "work experience", "employment"},
            "projects": {"projects", "project experience"},
            "education": {"education"},
            "certifications": {"certifications", "certificates"},
        }
        current = "resume"
        sections = {current: []}
        for line in resume_text.splitlines():
            heading = line.strip().strip(":").casefold()
            matched_section = None
            for canonical, aliases in section_aliases.items():
                if heading in aliases:
                    matched_section = canonical
                    break
            if matched_section:
                current = matched_section
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(line.strip())

        return {
            section: cls._clean_text("\n".join(lines))
            for section, lines in sections.items()
            if cls._clean_text("\n".join(lines))
        }

    @staticmethod
    def _source_fragments_from_sections(sections):
        return [
            {"source": section_name, "text": text}
            for section_name, text in (sections or {}).items()
            if text
        ]

    @staticmethod
    def _append_pipeline_step(
        pipeline_steps,
        key,
        label,
        status,
        started,
        message,
        count=None,
        metadata=None,
    ):
        duration_ms = int((time.perf_counter() - started) * 1000)
        pipeline_steps.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "message": message,
                "duration_ms": duration_ms,
                "duration_display": ResumeAnalyticsService._duration_display(
                    duration_ms
                ),
                "count": count,
                "metadata": metadata or {},
            }
        )

    @staticmethod
    def _duration_display(duration_ms):
        total_seconds = max(0, round((duration_ms or 0) / 1000))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _mapped_skills(mapping_result):
        matched = (
            mapping_result.get("matched", [])
            if isinstance(mapping_result, dict)
            else mapping_result.matched
        )
        result = []
        seen = set()
        for item in matched:
            if isinstance(item, dict):
                skillset_id = item["skillset_id"]
                name = item["name"]
            else:
                skillset_id = item.skillset_id
                name = item.name
            if skillset_id in seen:
                continue
            seen.add(skillset_id)
            result.append({"skillset_id": skillset_id, "name": name})
        return result

    @staticmethod
    def _unmapped_skills(mapping_result):
        unmapped = (
            mapping_result.get("unmapped", [])
            if isinstance(mapping_result, dict)
            else mapping_result.unmapped
        )
        result = []
        seen = set()
        for item in unmapped:
            if isinstance(item, dict):
                name = item.get("name", "")
                reason = item.get("reason", "")
            else:
                name = item.name
                reason = item.reason
            key = SkillSet.normalize_name(name)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append({"name": name, "reason": reason})
        return result

    @staticmethod
    def _clean_text(value):
        return "\n".join(
            line.strip() for line in str(value or "").splitlines() if line.strip()
        ).strip()

    def _read_upload_bytes(self, uploaded_file):
        size = getattr(uploaded_file, "size", None)
        if size is not None and size > self.max_attachment_bytes:
            limit_mb = round(self.max_attachment_bytes / (1024 * 1024), 1)
            raise ResumeAnalysisError(
                f"Resume attachment is too large. Maximum size is {limit_mb} MB."
            )

        chunks = []
        total = 0
        if hasattr(uploaded_file, "chunks"):
            iterator = uploaded_file.chunks()
        else:
            iterator = [uploaded_file.read()]

        for chunk in iterator:
            total += len(chunk)
            if total > self.max_attachment_bytes:
                limit_mb = round(self.max_attachment_bytes / (1024 * 1024), 1)
                raise ResumeAnalysisError(
                    f"Resume attachment is too large. Maximum size is {limit_mb} MB."
                )
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _decode_text(content):
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_pdf_text(content):
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ResumeAnalysisError(
                "PDF resume parsing requires pypdf. Rebuild the app dependencies."
            ) from exc

        try:
            reader = PdfReader(BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise ResumeAnalysisError(
                "Could not extract text from the PDF resume attachment."
            ) from exc

    @staticmethod
    def _extract_docx_text(content):
        try:
            from docx import Document
        except ImportError:
            return ResumeAnalyticsService._extract_docx_text_from_xml(content)

        try:
            document = Document(BytesIO(content))
            return "\n".join(
                paragraph.text for paragraph in document.paragraphs if paragraph.text
            )
        except Exception:
            return ResumeAnalyticsService._extract_docx_text_from_xml(content)

    @staticmethod
    def _extract_docx_text_from_xml(content):
        try:
            with ZipFile(BytesIO(content)) as archive:
                xml_content = archive.read("word/document.xml")
        except (BadZipFile, KeyError) as exc:
            raise ResumeAnalysisError(
                "Could not extract text from the DOCX resume attachment."
            ) from exc

        try:
            root = ElementTree.fromstring(xml_content)
        except ElementTree.ParseError as exc:
            raise ResumeAnalysisError(
                "Could not parse the DOCX resume attachment."
            ) from exc

        text_nodes = []
        for node in root.iter():
            if node.tag.endswith("}t") and node.text:
                text_nodes.append(node.text)
        return "\n".join(text_nodes)

    @staticmethod
    def _log_analysis(status, severity, message, metadata, duration_ms):
        logger.info("%s metadata=%s", message, metadata)
        MonitoringService.log_event(
            step_name="resume_analysis",
            status=status,
            severity=severity,
            message=message,
            service_name="ResumeAnalyticsService",
            metadata=metadata,
            duration_ms=duration_ms,
        )
