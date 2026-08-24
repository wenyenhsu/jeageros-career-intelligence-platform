import pytest
from django.urls import reverse
from pathlib import Path

from apps.applications.models import Application
from apps.applications.services.ats_scan_service import AtsScanError, AtsScanService


class FakeExtractor:
    def __init__(self, keywords, draft="tailored draft"):
        self.keywords = keywords
        self.draft = draft
        self.rewrite_calls = []

    def extract_keywords(self, title, description):
        self.title = title
        self.description = description
        return list(self.keywords)

    def rewrite_draft(self, kind, job_title, company, resume_text, unmatched):
        self.rewrite_calls.append(kind)
        return f"{self.draft}\n{kind}\n{', '.join(unmatched)}"


SIMPLIFY_KEYWORDS = [
    "automation tools",
    "ai",
    "KPI",
    "Salesforce",
    "Shadow",
    "content marketing",
    "digital marketing",
    "SEO",
    "cross functional",
    "prioritization",
]


def _write_resume(folder, name="Resume.txt", text=""):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.django_db
def test_keyword_match_uses_word_boundary_for_short_tokens():
    resume = "Used email automation tools and built an AI agent."

    assert AtsScanService.keyword_in_text("ai", resume) is True
    assert AtsScanService.keyword_in_text("automation tools", resume) is True
    assert AtsScanService.keyword_in_text("Salesforce", resume) is False
    assert AtsScanService.keyword_in_text("ai", "detailed email copy") is False
    assert AtsScanService.keyword_in_text("cross functional", "cross-functional intern") is True


@pytest.mark.django_db
def test_ats_scan_scores_literal_keyword_matches(
    application, job, application_materials_root
):
    job.description = (
        "Use automation tools and AI. KPI, Salesforce, Shadow, content marketing, "
        "digital marketing, SEO, cross functional, prioritization."
    )
    job.save(update_fields=["description"])
    folder = Path(application.materials_local_path)
    _write_resume(folder, text="Built AI workflows with automation tools for interns.")

    extractor = FakeExtractor(SIMPLIFY_KEYWORDS)
    result = AtsScanService(extractor=extractor).scan(application)

    assert result["score"] == 20
    assert result["matched_count"] == 2
    assert result["keyword_count"] == 10
    assert result["target"] == 70
    assert result["meets_target"] is False
    assert result["matched"] == ["automation tools", "ai"]
    assert "Salesforce" in result["unmatched"]
    assert result["resume_file"] == "Resume.txt"
    application.refresh_from_db()
    assert application.ats_score == 20
    assert application.ats_meets_target is False
    assert (folder / "ATS-scan.md").is_file()
    assert (folder / "Resume-ats.md").is_file()
    assert (folder / "Cover-Letter-ats.md").is_file()
    assert extractor.rewrite_calls == ["resume", "cover_letter"]


@pytest.mark.django_db
def test_ats_scan_meets_target_when_enough_keywords_match(
    application, application_materials_root
):
    folder = Path(application.materials_local_path)
    _write_resume(
        folder,
        text="Python Django SQL APIs testing documentation collaboration intern.",
    )
    extractor = FakeExtractor(
        ["Python", "Django", "SQL", "APIs", "testing", "documentation", "intern"]
    )

    result = AtsScanService(extractor=extractor).scan(application, write_drafts=False)

    assert result["score"] == 100
    assert result["meets_target"] is True
    assert result["unmatched"] == []
    assert not (folder / "Resume-ats.md").exists()


@pytest.mark.django_db
def test_ats_scan_requires_resume_file(application, application_materials_root):
    extractor = FakeExtractor(["Python"])
    Path(application.materials_local_path).mkdir(parents=True, exist_ok=True)

    with pytest.raises(AtsScanError, match="resume"):
        AtsScanService(extractor=extractor).scan(application)


@pytest.mark.django_db
def test_ats_scan_finds_resume_in_filename(application, application_materials_root):
    folder = Path(application.materials_local_path)
    _write_resume(
        folder,
        name="WenYenHsu_Resume_AI.txt",
        text="Python intern",
    )
    extractor = FakeExtractor(["Python", "Go"])

    result = AtsScanService(extractor=extractor).scan(application, write_drafts=False)

    assert result["resume_file"] == "WenYenHsu_Resume_AI.txt"
    assert result["matched"] == ["Python"]
    assert result["score"] == 50


@pytest.mark.django_db
def test_ats_scan_view_saves_result_and_shows_keywords(
    client, application, job, application_materials_root, monkeypatch
):
    job.description = "Need Python and Salesforce."
    job.save(update_fields=["description"])
    _write_resume(Path(application.materials_local_path), text="Python intern")
    monkeypatch.setattr(
        "apps.applications.views.AtsScanService",
        lambda: AtsScanService(extractor=FakeExtractor(["Python", "Salesforce"])),
    )

    response = client.post(reverse("application-ats-scan", args=[application.pk]))

    assert response.status_code == 302
    application.refresh_from_db()
    assert application.ats_score == 50
    detail = client.get(reverse("application-detail", args=[application.pk]))
    content = detail.content.decode()
    assert "ATS scan" in content
    assert "Python" in content
    assert "Salesforce" in content
    assert "Run ATS scan" in content


@pytest.mark.django_db
def test_ats_scan_service_does_not_import_market_fit():
    from apps.applications.services import ats_keyword_extractor, ats_scan_service

    combined = Path(ats_scan_service.__file__).read_text(
        encoding="utf-8"
    ) + Path(ats_keyword_extractor.__file__).read_text(encoding="utf-8")
    assert "MarketFit" not in combined
    assert "ResumeGap" not in combined
    assert "SkillDemand" not in combined
