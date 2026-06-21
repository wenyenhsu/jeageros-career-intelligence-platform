from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.analytics.services import ResumeAnalyticsService
from apps.analytics.services.resume_analytics_service import ResumeAnalysisError
from apps.companies.models import Company
from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill, SkillSet
from apps.skills.services.normalizer import SkillMappingResult as RAGMappingResult


class FakeExtractor:
    model = "fake-resume-model"

    def __init__(self, skills):
        self.skills = skills
        self.last_kwargs = {}

    def extract(self, **kwargs):
        self.last_kwargs = kwargs
        return {"skills": self.skills}


class FakeVerifier:
    model = "fake-resume-model"

    def __init__(self, accepted=None, rejected=None, calls=None):
        self.accepted = accepted
        self.rejected = rejected or []
        self.calls = calls
        self.last_kwargs = {}

    def verify(self, **kwargs):
        self.last_kwargs = kwargs
        if self.calls is not None:
            self.calls.append("verify")
        accepted = self.accepted
        if accepted is None:
            accepted = kwargs.get("candidate_skills", [])
        return {
            "verified_skills": accepted,
            "rejected_skills": self.rejected,
        }


class FakeRAGPipeline:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def map_skills(self, raw_skills):
        self.calls.append(list(raw_skills))
        return [
            self.results.get(
                raw_skill,
                RAGMappingResult(
                    original=raw_skill,
                    canonical=None,
                    confidence=0.0,
                    source="unresolved",
                    reason="No test mapping.",
                ),
            )
            for raw_skill in raw_skills
        ]


@pytest.mark.django_db
def test_resume_analysis_matches_jobs_and_market_direction():
    company = Company.objects.create(name="OpenAI")
    python = SkillSet.objects.create(name="Python")
    sql = SkillSet.objects.create(name="SQL")
    django = SkillSet.objects.create(name="Django")
    backend_job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        employment_type="Full-time",
    )
    data_job = JobPost.objects.create(
        company=company,
        title="Data Analyst",
        employment_type="Internship",
    )
    JobPostSkill.objects.create(job_post=backend_job, skill_set=python, score=90)
    JobPostSkill.objects.create(job_post=backend_job, skill_set=django, score=80)
    JobPostSkill.objects.create(job_post=data_job, skill_set=sql, score=85)

    service = ResumeAnalyticsService(
        extractor=FakeExtractor(
            [
                {"name": "python", "source": "resume"},
                {"name": "SQL", "source": "resume"},
                {"name": "Unmapped Tool", "source": "resume"},
            ]
        ),
        verifier=FakeVerifier(),
    )

    result = service.analyze_resume("Python and SQL engineer")

    assert {skill["name"] for skill in result["mapped_skills"]} == {"Python", "SQL"}
    assert result["unmapped_keywords"] == [
        {"name": "Unmapped Tool", "reason": "no matching SkillSet"}
    ]
    assert result["job_matches"][0]["title"] == "Data Analyst"
    assert result["job_matches"][0]["match_percent"] == 100
    assert {skill["name"] for skill in result["market_fit"]["matched_skills"]} == {
        "Python",
        "SQL",
    }
    assert any(
        skill["name"] == "Django"
        for skill in result["market_fit"]["missing_skills"]
    )
    assert [step["key"] for step in result["pipeline_steps"]] == [
        "text_extraction",
        "ollama_extract",
        "ollama_verify",
        "skillset_mapping",
        "job_match",
        "market_fit",
    ]
    assert result["metadata"]["candidate_count"] == 3
    assert result["metadata"]["verified_count"] == 3


@pytest.mark.django_db
def test_resume_analysis_uses_rag_for_unmapped_verified_skills():
    company = Company.objects.create(name="OpenAI")
    machine_learning = SkillSet.objects.create(name="Machine Learning")
    job = JobPost.objects.create(company=company, title="ML Engineer")
    JobPostSkill.objects.create(
        job_post=job,
        skill_set=machine_learning,
        score=90,
    )
    rag_pipeline = FakeRAGPipeline(
        {
            "AI & LLM Engineering": RAGMappingResult(
                original="AI & LLM Engineering",
                canonical="Machine Learning",
                confidence=0.91,
                source="rag",
                reason="Mapped through retrieved catalog candidates.",
            )
        }
    )
    service = ResumeAnalyticsService(
        extractor=FakeExtractor(
            [{"name": "AI & LLM Engineering", "source": "resume"}]
        ),
        verifier=FakeVerifier(),
        rag_pipeline=rag_pipeline,
    )

    result = service.analyze_resume("Built AI and LLM systems")

    assert rag_pipeline.calls == [["AI & LLM Engineering"]]
    assert result["mapped_skills"] == [
        {"skillset_id": machine_learning.id, "name": "Machine Learning"}
    ]
    assert result["unmapped_keywords"] == []
    assert result["job_matches"][0]["title"] == "ML Engineer"
    assert result["metadata"]["mapped_count"] == 1


@pytest.mark.django_db
def test_resume_analysis_respects_company_filter():
    openai = Company.objects.create(name="OpenAI")
    acme = Company.objects.create(name="Acme")
    python = SkillSet.objects.create(name="Python")
    openai_job = JobPost.objects.create(company=openai, title="Python Engineer")
    acme_job = JobPost.objects.create(company=acme, title="Python Developer")
    JobPostSkill.objects.create(job_post=openai_job, skill_set=python, score=90)
    JobPostSkill.objects.create(job_post=acme_job, skill_set=python, score=88)

    service = ResumeAnalyticsService(
        extractor=FakeExtractor([{"name": "Python", "source": "resume"}]),
        verifier=FakeVerifier(),
    )

    result = service.analyze_resume(
        "Python backend resume",
        filters={"company_id": str(openai.id)},
    )

    assert [match["company"] for match in result["job_matches"]] == ["OpenAI"]


@pytest.mark.django_db
def test_resume_analysis_splits_parenthetical_skill_keyword():
    company = Company.objects.create(name="OpenAI")
    sql = SkillSet.objects.create(name="SQL")
    mysql = SkillSet.objects.create(name="MySQL")
    job = JobPost.objects.create(company=company, title="Database Engineer")
    JobPostSkill.objects.create(job_post=job, skill_set=sql, score=90)
    JobPostSkill.objects.create(job_post=job, skill_set=mysql, score=88)

    service = ResumeAnalyticsService(
        extractor=FakeExtractor([{"name": "SQL (MySQL)", "source": "resume"}]),
        verifier=FakeVerifier(),
    )

    result = service.analyze_resume("SQL and MySQL database engineer")

    assert {skill["name"] for skill in result["mapped_skills"]} == {"SQL", "MySQL"}
    assert result["unmapped_keywords"] == []
    assert result["job_matches"][0]["title"] == "Database Engineer"
    assert result["job_matches"][0]["match_percent"] == 100


@pytest.mark.django_db
def test_resume_analysis_accepts_text_attachment():
    python = SkillSet.objects.create(name="Python")
    resume_file = SimpleUploadedFile(
        "resume.txt",
        b"Python backend engineer",
        content_type="text/plain",
    )
    service = ResumeAnalyticsService(
        extractor=FakeExtractor([{"name": "Python", "source": "resume"}]),
        verifier=FakeVerifier(),
    )

    result = service.analyze_resume_attachment(resume_file)

    assert result["metadata"]["attachment_name"] == "resume.txt"
    assert result["mapped_skills"] == [{"skillset_id": python.id, "name": "Python"}]


def test_resume_analysis_rejects_unsupported_attachment_type():
    resume_file = SimpleUploadedFile(
        "resume.png",
        b"not a resume",
        content_type="image/png",
    )
    service = ResumeAnalyticsService(
        extractor=FakeExtractor([{"name": "Python", "source": "resume"}]),
        verifier=FakeVerifier(),
    )

    with pytest.raises(ResumeAnalysisError, match="Unsupported resume file type"):
        service.extract_attachment_text(resume_file)


@pytest.mark.django_db
@override_settings(RESUME_ANALYSIS_RUN_INLINE=True)
def test_analytics_resume_form_runs_in_background_and_results_reach_dashboard(
    client,
    user,
    monkeypatch,
):
    client.force_login(user)

    class FakeResumeService:
        def __init__(self, skill_service=None):
            pass

        def analyze_resume_attachment(self, uploaded_file, filters=None, run_id=None):
            return self._result(uploaded_file.name, run_id)

        def analyze_resume(self, resume_text, filters=None, run_id=None):
            return self._result("", run_id)

        def _result(self, attachment_name, run_id):
            return {
                "candidate_keywords": [{"name": "Python", "source": "resume"}],
                "verified_keywords": [
                    {
                        "name": "Python",
                        "status": "accepted",
                        "reason": "supported by resume",
                    }
                ],
                "rejected_keywords": [
                    {"name": "Communication", "reason": "too generic"}
                ],
                "mapped_skills": [{"skillset_id": 1, "name": "Python"}],
                "unmapped_keywords": [
                    {"name": "PowerShell", "reason": "no matching SkillSet"}
                ],
                "job_matches": [
                    {
                        "title": "Backend Engineer",
                        "company": "OpenAI",
                        "job_type": "Full Time",
                        "location": "Remote",
                        "source_url": "",
                        "match_percent": 80,
                        "matched_skills": ["Python"],
                        "missing_skills": ["Django"],
                    }
                ],
                "market_fit": {
                    "fit_percent": 50,
                    "covered": [{"skillset_id": 1, "name": "Python"}],
                    "missing": [{"skillset_id": 2, "name": "Django"}],
                },
                "pipeline_steps": [
                    {
                        "key": "text_extraction",
                        "label": "Text extraction",
                        "status": "success",
                        "message": "Resume text prepared for analysis.",
                        "duration_display": "0:00",
                        "count": 18,
                    },
                    {
                        "key": "ollama_extract",
                        "label": "Ollama Extract",
                        "status": "success",
                        "message": "Candidate resume skills extracted.",
                        "duration_display": "0:00",
                        "count": 1,
                    },
                ],
                "metadata": {
                    "candidate_count": 1,
                    "verified_count": 1,
                    "rejected_count": 1,
                    "mapped_count": 1,
                    "unmapped_count": 0,
                    "job_match_count": 1,
                    "attachment_name": attachment_name,
                    "resume_run_id": run_id,
                },
            }

    monkeypatch.setattr(
        "apps.analytics.views.ResumeAnalyticsService",
        FakeResumeService,
    )

    response = client.post(
        "/analytics/",
        {
            "action": "resume_analysis",
            "resume_file": SimpleUploadedFile(
                "resume.txt",
                b"Python backend resume",
                content_type="text/plain",
            ),
        },
        HTTP_ACCEPT="application/json",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["success"] is True
    assert payload["status_url"].startswith(reverse("resume-analysis-status"))
    assert payload["dashboard_url"] == f"{reverse('dashboard')}#resume-analysis-results"

    status_response = client.get(payload["status_url"])
    status_payload = status_response.json()
    assert status_response.status_code == 200
    assert status_payload["status"] == "SUCCESS"
    assert status_payload["progress"] == 100
    assert status_payload["analysis_ready"] is True
    assert status_payload["pipeline"]["run_id"] == payload["resume_run_id"]

    analytics_response = client.get(reverse("analytics-dashboard"))
    analytics_content = analytics_response.content.decode()
    assert analytics_response.status_code == 200
    assert "Resume Analysis" in analytics_content
    assert "resumeAnalysisProgress" in analytics_content

    dashboard_response = client.get(reverse("dashboard"))
    content = dashboard_response.content.decode()
    assert dashboard_response.status_code == 200
    assert "Dashboard" in content
    assert "Resume Analysis Results" in content
    assert "Resume attachment" not in content
    assert "Analyze Resume" not in content
    assert "Analyzed attachment: resume.txt" in content
    assert "Python" in content
    assert "Analysis Pipeline" not in content
    assert "Verified by Ollama" in content
    assert "Rejected by Ollama" in content
    assert "Not in SkillSet catalog" in content
    assert "PowerShell" in content
    assert "Backend Engineer" in content
    assert "Market Direction Fit" in content


@pytest.mark.django_db
def test_resume_analysis_form_uses_explicit_submit_url(client):
    response = client.get(reverse("analytics-dashboard"))
    content = response.content.decode()
    template_path = (
        Path(__file__).resolve().parents[2]
        / "templates"
        / "analytics"
        / "dashboard.html"
    )
    template_source = template_path.read_text()

    assert response.status_code == 200
    assert 'id="resumeAnalysisForm"' in content
    assert f'action="{reverse("analytics-dashboard")}"' in content
    assert 'name="action" value="resume_analysis"' in content
    assert "fetch(form.action" not in template_source
    assert 'form.getAttribute("action")' in template_source


@pytest.mark.django_db
def test_resume_analysis_verifies_before_mapping_and_keeps_rejected_separate():
    SkillSet.objects.create(name="Python")
    SkillSet.objects.create(name="SQL")
    calls = []

    class OrderedExtractor(FakeExtractor):
        def extract(self, **kwargs):
            calls.append("extract")
            return super().extract(**kwargs)

    extractor = OrderedExtractor(
        [
            {"name": "Python", "source": "experience"},
            {"name": "SQL", "source": "skills"},
            {"name": "Communication", "source": "summary"},
        ]
    )
    verifier = FakeVerifier(
        accepted=[{"name": "Python", "status": "accepted", "reason": "used"}],
        rejected=[{"name": "Communication", "reason": "not technical"}],
        calls=calls,
    )
    service = ResumeAnalyticsService(
        extractor=extractor,
        verifier=verifier,
    )

    result = service.analyze_resume("Python SQL communication")

    assert calls == ["extract", "verify"]
    assert extractor.last_kwargs["content_kind"] == "resume"
    assert verifier.last_kwargs["content_kind"] == "resume"
    assert result["mapped_skills"] == [
        {"skillset_id": SkillSet.objects.get(name="Python").id, "name": "Python"}
    ]
    assert result["rejected_keywords"] == [
        {"name": "Communication", "reason": "not technical"}
    ]
    assert result["unmapped_keywords"] == []
    assert result["metadata"]["candidate_count"] == 3
    assert result["metadata"]["verified_count"] == 1
    assert result["metadata"]["rejected_count"] == 1


@pytest.mark.django_db
def test_resume_analysis_maps_only_verified_skills():
    SkillSet.objects.create(name="Python")
    SkillSet.objects.create(name="SQL")

    service = ResumeAnalyticsService(
        extractor=FakeExtractor(
            [
                {"name": "Python", "source": "experience"},
                {"name": "SQL", "source": "skills"},
            ]
        ),
        verifier=FakeVerifier(
            accepted=[{"name": "SQL", "status": "accepted", "reason": "used"}],
            rejected=[{"name": "Python", "reason": "listed without evidence"}],
        ),
    )

    result = service.analyze_resume("Python SQL")

    assert result["mapped_skills"] == [
        {"skillset_id": SkillSet.objects.get(name="SQL").id, "name": "SQL"}
    ]
    assert result["rejected_keywords"] == [
        {"name": "Python", "reason": "listed without evidence"}
    ]
    assert result["unmapped_keywords"] == []
    assert result["metadata"]["candidate_count"] == 2
    assert result["metadata"]["verified_count"] == 1
    assert result["metadata"]["rejected_count"] == 1
