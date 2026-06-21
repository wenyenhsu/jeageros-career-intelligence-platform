import logging
from io import BytesIO
from pathlib import Path
import time
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from apps.imports.models import PipelineLog
from apps.imports.services.monitoring_service import MonitoringService
from apps.skills.models import SkillSet
from apps.analytics.models import SkillCandidate
from apps.skills.services.ollama_extractor import OllamaExtractor, SkillExtractionError
from apps.skills.services.ollama_verifier import OllamaVerifier
from apps.skills.services.skill_rag_pipeline import SkillRAGPipeline
from apps.skills.services.skillset_mapper import (
    MappedSkill,
    SkillMappingResult,
    SkillSetMapper,
    UnmappedSkill,
)

from .skill_analytics_service import SkillAnalyticsService
from .skill_candidate_service import SkillCandidateService
from .market_fit_service import MarketFitService, calculate_market_fit
from .resume_gap_service import ResumeGapService
from .skill_demand_service import SkillDemandService

logger = logging.getLogger(__name__)


class ResumeAnalysisError(ValueError):
    pass


class ResumeAnalyticsService:
    default_job_limit = 6
    default_market_limit = 10
    max_attachment_bytes = 5 * 1024 * 1024
    text_extensions = {".txt", ".text", ".md", ".markdown"}
    supported_attachment_extensions = text_extensions | {".pdf", ".docx"}

    def __init__(
        self,
        extractor=None,
        verifier=None,
        mapper=None,
        rag_pipeline=None,
        skill_service=None,
        demand_service=None,
        gap_service=None,
        candidate_service=None,
        market_fit_service=None,
    ):
        self.extractor = extractor or OllamaExtractor()
        self.verifier = verifier or OllamaVerifier()
        self.mapper = mapper or SkillSetMapper(auto_create=False)
        self.rag_pipeline = rag_pipeline or SkillRAGPipeline()
        self.skill_service = skill_service or SkillAnalyticsService()
        self.demand_service = demand_service or SkillDemandService()
        self.gap_service = gap_service or ResumeGapService(self.demand_service)
        self.candidate_service = candidate_service or SkillCandidateService()
        self.market_fit_service = market_fit_service or MarketFitService()

    def analyze_resume(
        self,
        resume_text,
        filters=None,
        job_limit=None,
        market_limit=None,
        run_id=None,
    ):
        started = time.perf_counter()
        pipeline_steps = []
        current_stage = None
        self._analysis_run_id = run_id

        job_limit = job_limit or self.default_job_limit
        market_limit = market_limit or self.default_market_limit
        try:
            stage_started = time.perf_counter()
            current_stage = {
                "key": "text_extraction",
                "label": "Text extraction",
                "started": stage_started,
            }
            self._log_pipeline_step_started(
                current_stage,
                "Preparing resume text for analysis.",
            )
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
            self._log_pipeline_step_started(
                current_stage,
                "Extracting candidate resume skills with Ollama.",
            )
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
            self._log_pipeline_step_started(
                current_stage,
                "Verifying candidate resume skills with Ollama.",
            )
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
            self._log_pipeline_step_started(
                current_stage,
                "Mapping verified resume skills to SkillSet.",
            )
            mapping_result = self.mapper.map_verified_skills(
                verified_keywords,
                auto_create=False,
                source_job_identifier="resume-analysis",
                model_name=getattr(self.verifier, "model", ""),
            )
            mapping_result = self._augment_mapping_with_rag(mapping_result)
            mapped_skills = self._mapped_skills(mapping_result)
            unmapped_keywords = self._unmapped_skills(mapping_result)
            self.candidate_service.record_unmapped_names(
                [item.get("name") for item in unmapped_keywords],
                source=SkillCandidate.SourceChoices.RESUME,
            )
            resume_skill_ids = {skill["skillset_id"] for skill in mapped_skills}
            self._append_pipeline_step(
                pipeline_steps,
                key="skillset_mapping",
                label="SkillSet mapping",
                status="success",
                started=stage_started,
                message="Verified skills mapped to the SkillSet catalog.",
                count=len(mapped_skills),
                metadata={
                    "unmapped_count": len(unmapped_keywords),
                    **(mapping_result.metadata.get("rag_pipeline") or {}),
                },
            )
            current_stage = None

            stage_started = time.perf_counter()
            current_stage = {
                "key": "job_match",
                "label": "Job match",
                "started": stage_started,
            }
            self._log_pipeline_step_started(
                current_stage,
                "Comparing mapped resume skills with tracked jobs.",
            )
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
            self._log_pipeline_step_started(
                current_stage,
                "Comparing mapped resume skills with market demand.",
            )
            market_fit = self._market_fit(
                resume_skill_ids=resume_skill_ids,
                filters=filters,
                limit=market_limit,
            )
            resume_gap = self.gap_service.analyze_resume_gap(
                resume_skill_ids=resume_skill_ids,
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
                "resume_gap": resume_gap,
                "pipeline_steps": pipeline_steps,
                "metadata": {
                    "candidate_count": len(candidate_skills),
                    "verified_count": len(verified_keywords),
                    "rejected_count": len(rejected_keywords),
                    "mapped_count": len(mapped_skills),
                    "unmapped_count": len(unmapped_keywords),
                    "job_match_count": len(job_matches),
                    "market_fit_percent": market_fit.get(
                        "market_fit",
                        market_fit.get("fit_percent", 0),
                    ),
                    "resume_run_id": run_id,
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
                metadata={
                    "pipeline_steps": pipeline_steps,
                    "resume_run_id": run_id,
                },
                duration_ms=duration_ms,
            )
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        self._log_analysis(
            status=PipelineLog.StatusChoices.SUCCESS,
            severity=PipelineLog.SeverityChoices.INFO,
            message="Resume analysis completed.",
            metadata={**result["metadata"], "pipeline_steps": pipeline_steps},
            duration_ms=duration_ms,
        )
        return result

    def analyze_resume_attachment(
        self,
        uploaded_file,
        filters=None,
        job_limit=None,
        market_limit=None,
        run_id=None,
    ):
        attachment_name, resume_text = self.extract_attachment_text(uploaded_file)
        result = self.analyze_resume(
            resume_text,
            filters=filters,
            job_limit=job_limit,
            market_limit=market_limit,
            run_id=run_id,
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
        market_fit = self.market_fit_service.calculate(
            resume_skill_ids,
            top_demand_limit=limit or self.default_market_limit,
        )
        market_fit["market_profile"] = self.demand_service.build_market_profile(
            limit=limit or self.default_market_limit,
        )
        return market_fit

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

    def _append_pipeline_step(
        self,
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
        step = {
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
        pipeline_steps.append(step)
        self._log_pipeline_step_finished(step)
        return step

    def _log_pipeline_step_started(self, stage, message):
        run_id = getattr(self, "_analysis_run_id", None)
        if not run_id:
            return
        MonitoringService.log_event(
            step_name=f"resume_{stage['key']}",
            status=PipelineLog.StatusChoices.STARTED,
            severity=PipelineLog.SeverityChoices.INFO,
            message=message,
            service_name="ResumeAnalyticsService",
            metadata={
                "pipeline_kind": "resume_analysis",
                "resume_run_id": run_id,
                "pipeline_step_key": stage["key"],
                "pipeline_step_label": stage["label"],
            },
        )

    def _log_pipeline_step_finished(self, step):
        run_id = getattr(self, "_analysis_run_id", None)
        if not run_id:
            return
        metadata = {
            **(step.get("metadata") or {}),
            "pipeline_kind": "resume_analysis",
            "resume_run_id": run_id,
            "pipeline_step_key": step["key"],
            "pipeline_step_label": step["label"],
            "count": step.get("count"),
        }
        MonitoringService.log_event(
            step_name=f"resume_{step['key']}",
            status=self._pipeline_log_status(step["status"]),
            severity=(
                PipelineLog.SeverityChoices.ERROR
                if step["status"] == "failed"
                else PipelineLog.SeverityChoices.INFO
            ),
            message=step["message"],
            service_name="ResumeAnalyticsService",
            metadata=metadata,
            duration_ms=step.get("duration_ms"),
        )

    @staticmethod
    def _pipeline_log_status(status):
        if status == "success":
            return PipelineLog.StatusChoices.SUCCESS
        if status == "failed":
            return PipelineLog.StatusChoices.FAILED
        return PipelineLog.StatusChoices.INFO

    @staticmethod
    def _duration_display(duration_ms):
        total_seconds = max(0, round((duration_ms or 0) / 1000))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _augment_mapping_with_rag(self, mapping_result):
        """Give unresolved verified resume skills a RAG mapping pass.

        The existing SkillSetMapper remains the deterministic first pass for
        names, aliases, and SkillKeyword records. RAG only sees verified skills
        that were still unmapped, then may map them back to existing SkillSet
        records. It never creates new canonical skills.
        """
        unresolved = [
            item.name
            for item in mapping_result.unmapped
            if item.reason == "no matching SkillSet"
        ]
        if not unresolved:
            return mapping_result

        rag_results = self.rag_pipeline.map_skills(unresolved)
        matched = list(mapping_result.matched)
        unmapped = list(mapping_result.unmapped)
        keywords = list(mapping_result.keywords)
        metadata = dict(mapping_result.metadata)

        seen_skill_ids = {skill.skillset_id for skill in matched}
        rag_matched_keys = set()
        rag_unmapped = []
        rag_sources = {}

        for result in rag_results:
            source = getattr(result, "source", "") or "rag"
            rag_sources[source] = rag_sources.get(source, 0) + 1
            canonical = getattr(result, "canonical", None)
            original = getattr(result, "original", "")
            if not canonical:
                rag_unmapped.append(
                    UnmappedSkill(
                        name=original,
                        reason=getattr(result, "reason", "") or "RAG unresolved",
                    )
                )
                continue

            skillset = SkillSet.objects.filter(
                normalized_name=SkillSet.normalize_name(canonical)
            ).first()
            if not skillset:
                rag_unmapped.append(
                    UnmappedSkill(
                        name=original,
                        reason=f"RAG suggested {canonical}, but no SkillSet exists.",
                    )
                )
                continue

            rag_matched_keys.add(SkillSet.normalize_name(original))
            if skillset.id in seen_skill_ids:
                continue
            seen_skill_ids.add(skillset.id)
            matched.append(
                MappedSkill(
                    name=skillset.name,
                    skillset_id=skillset.id,
                    created=False,
                )
            )

        unmapped = [
            item
            for item in unmapped
            if SkillSet.normalize_name(item.name) not in rag_matched_keys
        ]
        seen_unmapped = {SkillSet.normalize_name(item.name) for item in unmapped}
        for item in rag_unmapped:
            key = SkillSet.normalize_name(item.name)
            if not key or key in seen_unmapped or key in rag_matched_keys:
                continue
            seen_unmapped.add(key)
            unmapped.append(item)

        metadata["rag_pipeline"] = {
            "rag_attempted_count": len(rag_results),
            "rag_mapped_count": len(rag_matched_keys),
            "rag_unmapped_count": len(rag_unmapped),
            "rag_sources": rag_sources,
        }
        return SkillMappingResult(
            matched=matched,
            unmapped=unmapped,
            keywords=keywords,
            metadata=metadata,
        )

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

    def _log_analysis(self, status, severity, message, metadata, duration_ms):
        run_id = getattr(self, "_analysis_run_id", None)
        metadata = {
            **(metadata or {}),
            "pipeline_kind": "resume_analysis",
            "resume_run_id": run_id,
        }
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
