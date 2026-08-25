import pytest
from django.contrib.messages import get_messages
from django.test import override_settings
from django.urls import reverse

from apps.imports.models import PipelineLog
from apps.imports.services import JobUrlRefreshService, ParserRegistry
from apps.imports.services.skill_pipeline_service import SkillPipelineResult
from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill, SkillAttachmentSource, SkillSet


class _FakeParser:
    def __init__(self, raw_job):
        self.raw_job = raw_job

    def extract_single_job(self, url):
        payload = dict(self.raw_job)
        payload.setdefault("absolute_url", url)
        return [payload]


class _EmptyParser:
    def extract_single_job(self, url):
        return []


def _fetched_raw_job(**overrides):
    payload = {
        "title": "Fetched Title",
        "company_name": "Fetched Co",
        "location": "San Francisco, CA",
        "description": "Build Python and SQL services.",
        "employment_type": "Internship",
        "id": "987654",
        "source": "linkedin",
    }
    payload.update(overrides)
    return payload


def _job_form_data(company, **overrides):
    data = {
        "company": company.name,
        "title": "Machine Learning Software Engineer Intern",
        "source_url": "",
        "external_id": "",
        "source_type": JobPost.SourceType.MANUAL,
        "status": JobPost.StatusChoices.ACTIVE,
        "location": "",
        "remote_type": "",
        "employment_type": "",
        "salary_min": "",
        "salary_max": "",
        "description": "",
        "tags": "",
        "skill_keywords": "",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_job_url_import(client):
    response = client.get(reverse("job-url-import"))
    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(CRAWL_SKILL_PIPELINE_ENABLED=True, CRAWL_SKILL_AUTO_CREATE=True)
def test_url_refresh_fills_empty_location_and_attaches_skills(company, monkeypatch):
    job = JobPost.objects.create(
        company=company,
        title="Machine Learning Software Engineer Intern",
        source_url="https://www.linkedin.com/jobs/view/987654/",
    )
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: _FakeParser(_fetched_raw_job()),
    )

    class FakePipeline:
        def process_job_post(self, job_post, canonical_job_payload, auto_create=None):
            skill = SkillSet.objects.create(name="Python")
            JobPostSkill.objects.create(
                job_post=job_post,
                skill_set=skill,
                source_type=SkillAttachmentSource.OLLAMA_PIPELINE,
            )
            return SkillPipelineResult(
                job_id=job_post.id,
                success=True,
                attached_count=1,
            )

    monkeypatch.setattr(
        "apps.imports.services.job_url_refresh_service.SkillPipelineService",
        FakePipeline,
    )

    result = JobUrlRefreshService.refresh(job)

    job.refresh_from_db()
    assert result.error == ""
    assert result.fetched is True
    assert job.location == "San Francisco, CA"
    assert "Python" in job.description
    assert job.job_type == "Internship"
    assert job.company_id == company.id
    assert job.title == "Machine Learning Software Engineer Intern"
    assert list(job.skill_sets.values_list("name", flat=True)) == ["Python"]
    assert result.skills_attached == 1


@pytest.mark.django_db
@override_settings(CRAWL_SKILL_PIPELINE_ENABLED=True, CRAWL_SKILL_AUTO_CREATE=True)
def test_url_refresh_copies_extracted_skills_to_related_application(
    company, user, monkeypatch
):
    from apps.applications.models import Application
    from apps.skills.models import ApplicationSkill

    job = JobPost.objects.create(
        company=company,
        title="Machine Learning Software Engineer Intern",
        source_url="https://www.linkedin.com/jobs/view/987654/",
    )
    application = Application.objects.create(user=user, job_post=job)
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: _FakeParser(_fetched_raw_job()),
    )

    class FakePipeline:
        def process_job_post(self, job_post, canonical_job_payload, auto_create=None):
            skill = SkillSet.objects.create(name="Python")
            JobPostSkill.objects.create(
                job_post=job_post,
                skill_set=skill,
                source_type=SkillAttachmentSource.OLLAMA_PIPELINE,
                score=90,
            )
            return SkillPipelineResult(
                job_id=job_post.id,
                success=True,
                attached_count=1,
            )

    monkeypatch.setattr(
        "apps.imports.services.job_url_refresh_service.SkillPipelineService",
        FakePipeline,
    )

    JobUrlRefreshService.refresh(job)

    copied = ApplicationSkill.objects.get(application=application)
    assert copied.skill_set.name == "Python"
    assert copied.score == 90


@pytest.mark.django_db
@override_settings(CRAWL_SKILL_PIPELINE_ENABLED=True)
def test_url_refresh_does_not_overwrite_typed_location(company, monkeypatch):
    job = JobPost.objects.create(
        company=company,
        title="Intern",
        source_url="https://www.linkedin.com/jobs/view/111/",
        location="Remote",
    )
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: _FakeParser(_fetched_raw_job(location="San Francisco, CA")),
    )
    monkeypatch.setattr(
        "apps.imports.services.job_url_refresh_service.SkillPipelineService",
        lambda: None,
    )

    pipeline_calls = []

    class FakePipeline:
        def process_job_post(self, job_post, canonical_job_payload, auto_create=None):
            pipeline_calls.append(job_post.id)
            return SkillPipelineResult(job_id=job_post.id, success=True)

    monkeypatch.setattr(
        "apps.imports.services.job_url_refresh_service.SkillPipelineService",
        FakePipeline,
    )

    JobUrlRefreshService.refresh(job)

    job.refresh_from_db()
    assert job.location == "Remote"
    assert job.description.startswith("Build Python")
    assert pipeline_calls == [job.id]


@pytest.mark.django_db
@override_settings(CRAWL_SKILL_PIPELINE_ENABLED=True)
def test_url_refresh_replaces_truncated_linkedin_description(company, monkeypatch):
    stub = "Los Angeles, CA | 3 Month Internship | Path to Full Time"
    full_jd = (
        f"{stub}\n\n"
        "Warp is building the agentic development environment. "
        "Interns work with Python, TypeScript, and customer deployments."
    )
    job = JobPost.objects.create(
        company=company,
        title="Forward Deployed Engineering Intern",
        source_url="https://www.linkedin.com/jobs/view/4457171685/",
        location="Los Angeles, CA",
        description=stub,
    )
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: _FakeParser(_fetched_raw_job(description=full_jd)),
    )
    pipeline_payloads = []

    class FakePipeline:
        def process_job_post(self, job_post, canonical_job_payload, auto_create=None):
            pipeline_payloads.append(canonical_job_payload["description"])
            return SkillPipelineResult(job_id=job_post.id, success=True)

    monkeypatch.setattr(
        "apps.imports.services.job_url_refresh_service.SkillPipelineService",
        FakePipeline,
    )

    JobUrlRefreshService.refresh(job)

    job.refresh_from_db()
    assert "agentic development" in job.description
    assert "Python" in job.description
    assert pipeline_payloads
    assert "agentic development" in pipeline_payloads[0]


@pytest.mark.django_db
@override_settings(CRAWL_SKILL_PIPELINE_ENABLED=True)
def test_url_refresh_skips_ollama_when_manual_skills_exist(company, monkeypatch):
    job = JobPost.objects.create(
        company=company,
        title="Intern",
        source_url="https://www.linkedin.com/jobs/view/222/",
    )
    skill = SkillSet.objects.create(name="SQL")
    JobPostSkill.objects.create(
        job_post=job,
        skill_set=skill,
        source_type=SkillAttachmentSource.MANUAL,
    )
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: _FakeParser(_fetched_raw_job()),
    )
    pipeline_calls = []

    class FakePipeline:
        def process_job_post(self, job_post, canonical_job_payload, auto_create=None):
            pipeline_calls.append(job_post.id)
            return SkillPipelineResult(job_id=job_post.id, success=True)

    monkeypatch.setattr(
        "apps.imports.services.job_url_refresh_service.SkillPipelineService",
        FakePipeline,
    )

    result = JobUrlRefreshService.refresh(job)

    job.refresh_from_db()
    assert result.skills_attached == 0
    assert pipeline_calls == []
    assert list(job.skill_sets.values_list("name", flat=True)) == ["SQL"]
    assert job.location == "San Francisco, CA"


@pytest.mark.django_db
def test_url_refresh_skips_job_without_source_url(company, monkeypatch):
    job = JobPost.objects.create(company=company, title="Manual Intern")
    called = []
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: called.append(url) or _EmptyParser(),
    )

    result = JobUrlRefreshService.refresh(job)

    assert result.skipped is True
    assert called == []
    assert JobPost.objects.filter(pk=job.pk).exists()


@pytest.mark.django_db
def test_url_refresh_unsupported_url_keeps_job_and_skips(company, monkeypatch):
    job = JobPost.objects.create(
        company=company,
        title="Intern",
        source_url="https://example.com/jobs/intern-1",
    )
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: _EmptyParser(),
    )

    result = JobUrlRefreshService.refresh(job)

    job.refresh_from_db()
    assert JobPost.objects.filter(pk=job.pk).exists()
    assert result.skipped is True
    assert result.error == ""
    assert job.location == ""
    assert PipelineLog.objects.filter(
        step_name="job_url_refresh",
        status=PipelineLog.StatusChoices.SKIPPED,
        job=job,
    ).exists()


@pytest.mark.django_db
def test_url_refresh_does_not_run_for_google_drive_folder(company):
    job = JobPost.objects.create(
        company=company,
        title="Intern",
        source_url="https://drive.google.com/drive/folders/abc123",
    )

    assert JobUrlRefreshService.needs_refresh(job) is False


@pytest.mark.django_db
def test_job_create_enqueues_url_refresh_when_source_url_is_present(
    client, company, monkeypatch
):
    queued = []
    monkeypatch.setattr(
        "apps.imports.tasks.refresh_job_from_url.delay",
        lambda job_id: queued.append(job_id),
    )

    response = client.post(
        reverse("job-create"),
        data=_job_form_data(
            company,
            source_url="https://www.linkedin.com/jobs/view/987654/",
        ),
    )

    assert response.status_code == 302
    job = JobPost.objects.get(title="Machine Learning Software Engineer Intern")
    assert queued == [job.id]
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert "Fetching location and skills from the job URL." in messages


@pytest.mark.django_db
def test_job_create_does_not_enqueue_url_refresh_without_source_url(
    client, company, monkeypatch
):
    queued = []
    monkeypatch.setattr(
        "apps.imports.tasks.refresh_job_from_url.delay",
        lambda job_id: queued.append(job_id),
    )

    response = client.post(
        reverse("job-create"),
        data=_job_form_data(company),
    )

    assert response.status_code == 302
    assert queued == []


@pytest.mark.django_db
def test_job_create_skips_enqueue_when_location_and_skills_already_present(
    client, company, monkeypatch
):
    queued = []
    monkeypatch.setattr(
        "apps.imports.tasks.refresh_job_from_url.delay",
        lambda job_id: queued.append(job_id),
    )
    SkillSet.objects.create(name="Python")

    response = client.post(
        reverse("job-create"),
        data=_job_form_data(
            company,
            source_url="https://www.linkedin.com/jobs/view/987654/",
            location="Los Angeles, CA",
            skill_keywords="Python",
        ),
    )

    assert response.status_code == 302
    assert queued == []


@pytest.mark.django_db
def test_job_url_preview_returns_form_fields(client, monkeypatch):
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: _FakeParser(_fetched_raw_job()),
    )

    response = client.get(
        reverse("job-url-preview"),
        {"url": "https://www.linkedin.com/jobs/view/987654/"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["company"] == "Fetched Co"
    assert payload["title"] == "Fetched Title"
    assert payload["location"] == "San Francisco, CA"
    assert payload["job_type"] == "Internship"
    assert "Python" in payload["description"]
    assert payload["error"] == ""


@pytest.mark.django_db
def test_job_url_preview_uses_internship_when_title_says_intern(client, monkeypatch):
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: _FakeParser(
            _fetched_raw_job(
                title="Site Digital IT Manager Internship",
                employment_type="Full-time",
            )
        ),
    )

    response = client.get(
        reverse("job-url-preview"),
        {"url": "https://www.linkedin.com/jobs/view/4456520247/"},
    )

    payload = response.json()
    assert payload["ok"] is True
    assert payload["title"] == "Site Digital IT Manager Internship"
    assert payload["job_type"] == "Internship"


@pytest.mark.django_db
def test_job_url_preview_uses_existing_job_when_fetch_fails(
    client, company, monkeypatch
):
    JobPost.objects.create(
        company=company,
        title="Stored Intern",
        source_url="https://www.linkedin.com/jobs/view/4456520247/",
        location="Los Angeles, CA",
        employment_type="Internship",
        description="Stored JD.",
    )
    monkeypatch.setattr(
        ParserRegistry,
        "get_parser_for_url",
        lambda url: _EmptyParser(),
    )

    response = client.get(
        reverse("job-url-preview"),
        {"url": "https://www.linkedin.com/jobs/view/4456520247/"},
    )

    payload = response.json()
    assert payload["ok"] is True
    assert payload["company"] == company.name
    assert payload["title"] == "Stored Intern"
    assert payload["location"] == "Los Angeles, CA"
    assert payload["job_type"] == "Internship"
    assert payload["existing_job_id"]


@pytest.mark.django_db
def test_job_url_preview_rejects_google_drive_folder(client):
    response = client.get(
        reverse("job-url-preview"),
        {"url": "https://drive.google.com/drive/folders/abc123"},
    )

    payload = response.json()
    assert payload["ok"] is False
    assert "Google Drive" in payload["error"]


@pytest.mark.django_db
def test_job_create_page_wires_job_url_preview(client):
    response = client.get(reverse("job-create"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-job-url-preview="true"' in content
    assert reverse("job-url-preview") in content
    assert 'data-preview-title="#id_title"' in content
    assert 'data-preview-job-type="#id_employment_type"' in content
