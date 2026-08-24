import logging
import re
from io import BytesIO
from pathlib import Path

from django.utils import timezone

from .ats_document_writer import AtsDocumentWriter
from .ats_keyword_extractor import AtsKeywordError, AtsKeywordExtractor
from .materials_folder_service import MaterialsFolderService

logger = logging.getLogger(__name__)


class AtsScanError(ValueError):
    pass


class AtsScanService:
    target_score = 70
    report_name = "ATS-scan.md"
    resume_draft_name = "Resume-ats.md"
    cover_letter_draft_name = "Cover-Letter-ats.md"
    resume_pdf_name = AtsDocumentWriter.resume_name
    cover_letter_pdf_name = AtsDocumentWriter.cover_letter_name
    resume_extensions = {".pdf", ".docx", ".txt", ".md"}
    cover_extensions = {".pdf", ".docx", ".txt", ".md"}
    generated_names = {
        "ats-scan.md",
        "resume-ats.md",
        "cover-letter-ats.md",
        "resume.pdf",
        "cover-letter.pdf",
        "resume.docx",
        "cover-letter.docx",
        "resume.original.pdf",
        "cover-letter.original.pdf",
    }

    def __init__(self, extractor=None):
        self.extractor = extractor or AtsKeywordExtractor()
        self.document_writer = AtsDocumentWriter()

    def scan(self, application, write_drafts=True):
        MaterialsFolderService().ensure_folders(application)
        job_post = getattr(application, "job_post", None)
        if job_post is None:
            raise AtsScanError("Application is missing a job posting.")

        title = (getattr(job_post, "title", "") or "").strip()
        description = (getattr(job_post, "description", "") or "").strip()
        try:
            keywords = self.extractor.extract_keywords(title, description)
        except AtsKeywordError as exc:
            raise AtsScanError(str(exc)) from exc

        folder = MaterialsFolderService.local_path_for(application)
        resume_path = self.find_resume_file(folder)
        if resume_path is None:
            raise AtsScanError(
                "Add a resume file to the local folder (Resume.pdf or a filename containing resume)."
            )

        resume_text = self.read_document_text(resume_path)
        matched = []
        unmatched = []
        for keyword in keywords:
            if self.keyword_in_text(keyword, resume_text):
                matched.append(keyword)
            else:
                unmatched.append(keyword)

        keyword_count = len(keywords)
        matched_count = len(matched)
        score = round((matched_count / keyword_count) * 100) if keyword_count else 0
        drafts = []
        tailored = {
            "tailored_score": score,
            "tailored_matched": matched,
            "tailored_unmatched": unmatched,
            "tailored_resume_file": "",
            "tailored_cover_letter_file": "",
            "backups": [],
        }
        if write_drafts and folder is not None:
            drafts, tailored = self._write_outputs(
                application,
                folder=folder,
                resume_path=resume_path,
                resume_text=resume_text,
                score=score,
                matched=matched,
                unmatched=unmatched,
                keywords=keywords,
            )

        cover_path = self.find_cover_letter_file(folder)
        payload = {
            "score": score,
            "matched_count": matched_count,
            "keyword_count": keyword_count,
            "target": self.target_score,
            "meets_target": score >= self.target_score,
            "matched": matched,
            "unmatched": unmatched,
            "keywords": keywords,
            "resume_file": resume_path.name,
            "cover_letter_file": cover_path.name if cover_path else "",
            "drafts": drafts,
            "error": "",
            "scanned_at": timezone.now().isoformat(),
            **tailored,
        }
        application.ats_scan = payload
        application.save(update_fields=["ats_scan", "last_updated_at"])
        return payload

    @classmethod
    def keyword_in_text(cls, keyword, text):
        needle = cls._normalize_phrase(keyword)
        haystack = cls._normalize_phrase(text)
        if not needle or not haystack:
            return False
        if len(needle) <= 3:
            return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None
        return needle in haystack

    @classmethod
    def find_resume_file(cls, folder):
        return cls._find_named_file(
            folder,
            exact_stems=("resume",),
            name_contains="resume",
            extensions=cls.resume_extensions,
        )

    @classmethod
    def find_cover_letter_file(cls, folder):
        return cls._find_named_file(
            folder,
            exact_stems=("cover-letter", "cover_letter", "coverletter"),
            name_contains="cover",
            extensions=cls.cover_extensions,
        )

    @classmethod
    def read_document_text(cls, path):
        path = Path(path)
        suffix = path.suffix.casefold()
        content = path.read_bytes()
        if suffix in {".txt", ".md", ".markdown", ".text"}:
            text = content.decode("utf-8", errors="ignore")
        elif suffix == ".pdf":
            text = cls._extract_pdf_text(content)
        elif suffix == ".docx":
            text = cls._extract_docx_text(content)
        else:
            text = ""
        return " ".join(str(text or "").split())

    def _write_outputs(
        self,
        application,
        folder,
        resume_path,
        resume_text,
        score,
        matched,
        unmatched,
        keywords,
    ):
        drafts = []
        report_path = folder / self.report_name
        job_title = application.job_title_display or "the role"
        company = application.company_display or "the company"
        resume_draft = resume_text
        cover_draft = resume_text
        if unmatched:
            resume_draft = self._ensure_keywords(
                self._safe_rewrite(
                    "resume", job_title, company, resume_text, unmatched
                ),
                unmatched,
            )
            cover_draft = self._ensure_keywords(
                self._safe_rewrite(
                    "cover_letter", job_title, company, resume_text, unmatched
                ),
                unmatched,
            )
            (folder / self.resume_draft_name).write_text(resume_draft, encoding="utf-8")
            drafts.append(self.resume_draft_name)
            (folder / self.cover_letter_draft_name).write_text(
                cover_draft, encoding="utf-8"
            )
            drafts.append(self.cover_letter_draft_name)

        cover_source = self.find_cover_letter_file(folder)
        resume_result = self.document_writer.write_resume(
            folder, resume_draft, source_path=resume_path
        )
        cover_result = self.document_writer.write_cover_letter(
            folder, cover_draft, source_path=cover_source
        )
        drafts.extend(
            [
                self.resume_pdf_name,
                self.cover_letter_pdf_name,
                Path(self.resume_pdf_name).with_suffix(".docx").name,
                Path(self.cover_letter_pdf_name).with_suffix(".docx").name,
            ]
        )

        tailored_matched = []
        tailored_unmatched = []
        for keyword in keywords:
            if self.keyword_in_text(keyword, resume_draft):
                tailored_matched.append(keyword)
            else:
                tailored_unmatched.append(keyword)
        tailored_score = (
            round((len(tailored_matched) / len(keywords)) * 100) if keywords else 0
        )
        backups = [
            name
            for name in (resume_result.get("backup"), cover_result.get("backup"))
            if name
        ]
        report_path.write_text(
            self._report_markdown(
                application,
                resume_path=resume_path,
                score=score,
                matched=matched,
                unmatched=unmatched,
                keywords=keywords,
                tailored_score=tailored_score,
            ),
            encoding="utf-8",
        )
        drafts.insert(0, self.report_name)
        return drafts, {
            "tailored_score": tailored_score,
            "tailored_matched": tailored_matched,
            "tailored_unmatched": tailored_unmatched,
            "tailored_resume_file": self.resume_pdf_name,
            "tailored_cover_letter_file": self.cover_letter_pdf_name,
            "backups": backups,
        }

    def _ensure_keywords(self, text, unmatched):
        body = str(text or "").rstrip()
        missing = [
            keyword
            for keyword in unmatched
            if not self.keyword_in_text(keyword, body)
        ]
        if not missing:
            return body + "\n"
        return (
            body
            + "\n\nJob-specific keywords: "
            + ", ".join(missing)
            + "\n"
        )

    def _safe_rewrite(self, kind, job_title, company, resume_text, unmatched):
        try:
            text = self.extractor.rewrite_draft(
                kind, job_title, company, resume_text, unmatched
            )
        except Exception:
            logger.exception("ATS %s draft rewrite failed", kind)
            text = ""
        if text:
            return text
        heading = "Resume draft" if kind == "resume" else "Cover letter draft"
        lines = [
            f"# {heading}",
            "",
            f"Target role: {job_title} at {company}.",
            "",
            "Add these unmatched ATS keywords where they are truthful:",
            "",
        ]
        lines.extend(f"- {keyword}" for keyword in unmatched)
        return "\n".join(lines) + "\n"

    def _report_markdown(
        self,
        application,
        resume_path,
        score,
        matched,
        unmatched,
        keywords,
        tailored_score=None,
    ):
        status = "meets target" if score >= self.target_score else "below target"
        lines = [
            f"# ATS scan — {application.company_display} / {application.job_title_display}",
            "",
            f"Original score: {score} ({len(matched)}/{len(keywords)}) — {status}. Target: {self.target_score}.",
        ]
        if tailored_score is not None:
            lines.append(
                f"Tailored Resume.pdf score: {tailored_score}. Files: {self.resume_pdf_name}, {self.cover_letter_pdf_name}."
            )
        lines.extend(
            [
                f"Source resume: {resume_path.name}",
                "",
                "## Matched",
                "",
            ]
        )
        lines.extend(f"- {keyword}" for keyword in matched or ["(none)"])
        lines.extend(["", "## Unmatched", ""])
        lines.extend(f"- {keyword}" for keyword in unmatched or ["(none)"])
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _normalize_phrase(value):
        return re.sub(r"[\s\-_/]+", " ", str(value or "").casefold()).strip()

    @classmethod
    def _find_named_file(cls, folder, exact_stems, name_contains, extensions):
        if folder is None or not Path(folder).is_dir():
            return None
        files = [
            path
            for path in Path(folder).iterdir()
            if path.is_file() and path.suffix.casefold() in extensions
        ]
        preferred = [
            path for path in files if path.name.casefold() not in cls.generated_names
        ]
        search_order = preferred + [
            path for path in files if path.name.casefold() in cls.generated_names
        ]
        for path in search_order:
            if path.stem.casefold() in exact_stems:
                return path
        contains = str(name_contains or "").casefold()
        matches = [
            path for path in search_order if contains in path.name.casefold()
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda path: (len(path.name), path.name.casefold()))[0]

    @staticmethod
    def _extract_pdf_text(content):
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    @staticmethod
    def _extract_docx_text(content):
        from docx import Document

        document = Document(BytesIO(content))
        return "\n".join(
            paragraph.text for paragraph in document.paragraphs if paragraph.text
        )
