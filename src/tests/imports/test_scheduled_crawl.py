import logging
from types import SimpleNamespace
from io import StringIO

import pytest
from django.core.management import call_command
from django.conf import settings
from django.test import override_settings

import apps.imports.services.crawl_service as crawl_service
from config.celery import app as celery_app
from apps.companies.models import Company
from apps.imports.models import CrawlRun, JobSource
from apps.imports.services import CrawlService, ListingPage
from apps.imports.tasks import crawl_all_sources
from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill, SkillSet


def test_celery_loads_successfully():
    assert celery_app.main == "config"
    assert "apps.imports.tasks.crawl_all_sources" in celery_app.tasks


def test_celery_task_can_be_imported():
    assert crawl_all_sources.name == "apps.imports.tasks.crawl_all_sources"
    assert callable(crawl_all_sources.run)


def test_celery_beat_schedule_runs_crawl_task():
    scheduled_task = settings.CELERY_BEAT_SCHEDULE["crawl-enabled-job-sources"]

    assert scheduled_task["task"] == "apps.imports.tasks.crawl_all_sources"
    assert scheduled_task["schedule"] == settings.CRAWL_SCHEDULE_SECONDS
    assert scheduled_task["schedule"] > 0


@pytest.mark.django_db
def test_scheduled_crawl_task_runs_against_mocked_job_source(monkeypatch):
    source = JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=True,
    )
    _patch_parser(monkeypatch)

    summary = crawl_all_sources.run()

    source.refresh_from_db()
    assert summary["success"] is True
    assert summary["sources_processed"] == 1
    assert summary["jobs_created"] == 1
    assert summary["jobs_updated"] == 0
    assert summary["jobs_closed"] == 0
    assert summary["errors"] == 0
    assert summary["progress_percentage"] == 100
    assert source.last_crawled_at is not None
    assert JobPost.objects.filter(external_id=f"{source.id}-backend").exists()

    crawl_run = CrawlRun.objects.get(id=summary["crawl_run_id"])
    assert crawl_run.status == CrawlRun.StatusChoices.SUCCESS
    assert crawl_run.total_sources == 1
    assert crawl_run.processed_sources == 1
    assert crawl_run.success_count == 1
    assert crawl_run.failure_count == 0
    assert crawl_run.jobs_created == 1
    assert crawl_run.jobs_updated == 0
    assert crawl_run.jobs_closed == 0
    assert crawl_run.errors == 0
    assert crawl_run.progress_percentage == 100


@pytest.mark.django_db
def test_scheduled_crawl_normalizes_raw_parser_output_before_sync(monkeypatch):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs",
        enabled=True,
    )
    monkeypatch.setattr(
        crawl_service.ParserRegistry,
        "get_parser",
        staticmethod(lambda parser_type, source=None: RawLinkedInParser(source)),
    )

    summary = crawl_all_sources.run()

    job = JobPost.objects.get(external_id="linkedin-123")
    assert summary["success"] is True
    assert summary["jobs_created"] == 1
    assert job.company.name == "OpenAI"
    assert job.title == "Software Engineer Intern"
    assert job.source_url == "https://www.linkedin.com/jobs/view/123"
    assert job.location == "Remote"
    assert job.remote_type == "Remote"
    assert job.employment_type == "Internship"


@pytest.mark.django_db
def test_scheduled_crawl_skips_disabled_sources(monkeypatch):
    JobSource.objects.create(
        name="Disabled Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=False,
    )

    def fail_if_called(parser_type, source=None):
        raise AssertionError("Disabled sources should not create parsers.")

    monkeypatch.setattr(
        crawl_service.ParserRegistry,
        "get_parser",
        staticmethod(fail_if_called),
    )

    summary = CrawlService.crawl_all_sources()

    assert summary["success"] is True
    assert summary["sources_processed"] == 0
    assert summary["sources_skipped"] == 1
    assert summary["jobs_created"] == 0


@pytest.mark.django_db
def test_scheduled_crawl_processes_enabled_sources(monkeypatch):
    source = JobSource.objects.create(
        name="Lever",
        resource=JobSource.ResourceChoices.LEVER,
        base_url="https://jobs.lever.co/openai",
        enabled=True,
    )
    _patch_parser(monkeypatch)

    summary = CrawlService.crawl_all_sources()

    assert summary["success"] is True
    assert summary["sources_processed"] == 1
    assert summary["sources"][0]["source_id"] == source.id
    assert summary["sources"][0]["status"] == "processed"
    assert summary["sources"][0]["listing_pages"] == 1
    assert summary["sources"][0]["jobs_found"] == 1
    assert summary["progress"]["status"] == CrawlRun.StatusChoices.SUCCESS
    assert summary["progress"]["progress_percentage"] == 100
    assert JobPost.objects.count() == 1


@pytest.mark.django_db
def test_scheduled_crawl_filters_jobs_to_target_companies(monkeypatch):
    source = JobSource.objects.create(
        name="LinkedIn OpenAI",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=backend",
        enabled=True,
        filter_config={"target_companies": ["OpenAI"]},
    )
    monkeypatch.setattr(
        crawl_service.ParserRegistry,
        "get_parser",
        staticmethod(lambda parser_type, source=None: MixedCompanyParser(source)),
    )

    summary = CrawlService.crawl_all_sources([source])

    assert summary["success"] is True
    assert summary["jobs_created"] == 1
    assert summary["sources"][0]["jobs_found"] == 1
    assert summary["sources"][0]["jobs_filtered"] == 1
    assert list(JobPost.objects.values_list("company__name", flat=True)) == ["OpenAI"]


@pytest.mark.django_db
@override_settings(CRAWL_SKILL_PIPELINE_ENABLED=True)
def test_scheduled_crawl_runs_skill_pipeline_after_sync(monkeypatch):
    source = JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=True,
        crawl_config={"auto_create_skills": True},
    )
    _patch_parser(monkeypatch)
    processed = []

    class FakeSkillPipelineService:
        def process_job_post(self, job_post, canonical_job_payload, auto_create=None):
            processed.append((job_post.id, canonical_job_payload["external_id"], auto_create))
            return SimpleNamespace(success=True, attached_count=2)

    monkeypatch.setattr(
        crawl_service,
        "SkillPipelineService",
        FakeSkillPipelineService,
    )

    summary = CrawlService.crawl_all_sources([source])

    assert summary["success"] is True
    assert processed == [(JobPost.objects.get().id, f"{source.id}-backend", True)]
    assert summary["skill_pipeline_jobs_processed"] == 1
    assert summary["skill_pipeline_failures"] == 0
    assert summary["skills_attached"] == 2
    assert summary["sources"][0]["skills_attached"] == 2


@pytest.mark.django_db
@override_settings(CRAWL_SKILL_PIPELINE_ENABLED=True)
def test_scheduled_crawl_runs_skill_pipeline_for_existing_source_jobs(monkeypatch):
    company = Company.objects.create(name="OpenAI")
    existing_job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url="https://www.linkedin.com/jobs/view/123",
        external_id="linkedin-123",
        description="Build Python and Django services.",
    )
    source = JobSource.objects.create(
        name="LinkedIn OpenAI",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        enabled=True,
        filter_config={"target_companies": ["OpenAI"]},
        crawl_config={"auto_create_skills": True},
    )
    monkeypatch.setattr(
        crawl_service.ParserRegistry,
        "get_parser",
        staticmethod(lambda parser_type, source=None: EmptyParser(source)),
    )
    processed = []

    class FakeSkillPipelineService:
        def process_job_post(self, job_post, canonical_job_payload, auto_create=None):
            processed.append(
                (job_post.id, canonical_job_payload["external_id"], auto_create)
            )
            return SimpleNamespace(success=True, attached_count=2)

    monkeypatch.setattr(
        crawl_service,
        "SkillPipelineService",
        FakeSkillPipelineService,
    )

    summary = CrawlService.crawl_all_sources([source])

    assert summary["success"] is True
    assert summary["jobs_created"] == 0
    assert processed == [(existing_job.id, "linkedin-123", True)]
    assert summary["skill_pipeline_jobs_processed"] == 1
    assert summary["skill_pipeline_failures"] == 0
    assert summary["skills_attached"] == 2
    assert summary["sources"][0]["jobs_found"] == 0
    assert summary["sources"][0]["skills_attached"] == 2


@pytest.mark.django_db
@override_settings(CRAWL_SKILL_PIPELINE_ENABLED=True)
def test_scheduled_crawl_skips_ollama_for_jobs_that_already_have_skills(monkeypatch):
    source = JobSource.objects.create(
        name="LinkedIn OpenAI",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        enabled=True,
        crawl_config={"auto_create_skills": True},
    )
    company = Company.objects.create(name="OpenAI")
    existing_job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url=f"{source.base_url}/backend-engineer",
        external_id=f"{source.id}-backend",
        description="Build services.",
    )
    skill_set = SkillSet.objects.create(name="Python")
    JobPostSkill.objects.create(job_post=existing_job, skill_set=skill_set, score=90)
    _patch_parser(monkeypatch)

    class FailIfCalledSkillPipelineService:
        def process_job_post(self, job_post, canonical_job_payload, auto_create=None):
            raise AssertionError("Jobs with existing skills should not rerun Ollama.")

    monkeypatch.setattr(
        crawl_service,
        "SkillPipelineService",
        FailIfCalledSkillPipelineService,
    )

    summary = CrawlService.crawl_all_sources([source])

    assert summary["success"] is True
    assert summary["jobs_created"] == 0
    assert summary["jobs_updated"] == 1
    assert summary["skill_pipeline_jobs_processed"] == 0
    assert summary["skill_pipeline_failures"] == 0
    assert summary["skills_attached"] == 0
    assert existing_job.skill_sets.filter(name="Python").exists()


@pytest.mark.django_db
def test_scheduled_crawl_returns_summary_and_logs_counts(monkeypatch, caplog):
    JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=True,
    )
    _patch_parser(monkeypatch)

    with caplog.at_level(logging.INFO):
        summary = crawl_all_sources.run()

    assert summary["success"] is True
    assert summary["jobs_created"] == 1
    assert "Crawling job source Greenhouse" in caplog.text
    assert "created=1 updated=0 closed=0" in caplog.text
    assert "progress=100.00%" in caplog.text
    assert "Scheduled crawl summary" in caplog.text


@pytest.mark.django_db
def test_progress_values_are_updated_for_multiple_enabled_sources(monkeypatch):
    first = JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=True,
    )
    second = JobSource.objects.create(
        name="Lever",
        resource=JobSource.ResourceChoices.LEVER,
        base_url="https://jobs.lever.co/openai",
        enabled=True,
    )
    _patch_parser(monkeypatch)

    progress_updates = []
    summary = CrawlService.crawl_enabled_sources(
        progress_callback=progress_updates.append
    )

    assert summary["success"] is True
    assert summary["sources_processed"] == 2
    assert summary["progress_percentage"] == 100
    assert [update["processed_sources"] for update in progress_updates] == [1, 2, 2]
    assert [update["progress_percentage"] for update in progress_updates] == [
        50,
        100,
        100,
    ]
    assert progress_updates[0]["current_source"] == first.name
    assert progress_updates[1]["current_source"] == second.name
    assert progress_updates[-1]["status"] == CrawlRun.StatusChoices.SUCCESS


@pytest.mark.django_db
def test_crawl_run_progress_api_returns_latest_run(client, user, monkeypatch):
    client.force_login(user)
    JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=True,
    )
    _patch_parser(monkeypatch)
    summary = CrawlService.crawl_enabled_sources()

    response = client.get("/api/crawl-runs/latest/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == summary["crawl_run_id"]
    assert payload["status"] == CrawlRun.StatusChoices.SUCCESS
    assert payload["progress_percentage"] == 100


@pytest.mark.django_db
def test_crawl_run_api_endpoints_start_and_report_status(client, user, monkeypatch):
    client.force_login(user)
    JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=True,
    )
    _patch_parser(monkeypatch)

    run_response = client.post("/api/crawl/run/")

    assert run_response.status_code == 202
    run_payload = run_response.json()
    assert run_payload["success"] is True
    crawl_run_id = run_payload["crawl_run_id"]

    status_response = client.get(f"/api/crawl/{crawl_run_id}/status/")

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["status"] == CrawlRun.StatusChoices.SUCCESS
    assert status_payload["progress"] == 100
    assert status_payload["jobs_created"] == 1
    assert status_payload["jobs_updated"] == 0
    assert status_payload["jobs_closed"] == 0
    assert status_payload["errors"] == 0


@pytest.mark.django_db
def test_manual_crawl_command_displays_progress_bar(monkeypatch):
    JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=True,
    )
    _patch_parser(monkeypatch)
    stdout = StringIO()

    call_command("crawl_jobs", stdout=stdout)

    output = stdout.getvalue()
    assert "[1/1] Greenhouse (100.00%)" in output
    assert "Done" in output
    assert "Created: 1" in output
    assert "Updated: 0" in output
    assert "Closed: 0" in output
    assert "Filtered: 0" in output
    assert "Skills attached: 0" in output
    assert "Skill pipeline failures: 0" in output
    assert '"jobs_created": 1' in output


def _patch_parser(monkeypatch):
    monkeypatch.setattr(
        crawl_service.ParserRegistry,
        "get_parser",
        staticmethod(lambda parser_type, source=None: FakeParser(source)),
    )


class FakeParser:
    def __init__(self, source):
        self.source = source

    def find_listing_pages(self):
        return [
            ListingPage(
                url=self.source.base_url,
                parser_type=self.source.resource,
                source_name=self.source.name,
            )
        ]

    def extract_jobs(self, listing_page):
        return [
            {
                "title": "Backend Engineer",
                "company_name": "OpenAI",
                "source_url": f"{listing_page.url}/backend-engineer",
                "external_id": f"{self.source.id}-backend",
                "location": "Remote",
                "employment_type": "Full-time",
                "description": "Build services.",
            }
        ]


class RawLinkedInParser(FakeParser):
    def extract_jobs(self, listing_page):
        return [
            {
                "jobTitle": " Software Engineer Intern ",
                "companyName": "OpenAI",
                "jobUrl": "https://www.linkedin.com/jobs/view/123",
                "jobPostingId": "linkedin-123",
                "formattedLocation": "REMOTE",
                "workplaceType": "Remote",
                "employmentType": "Internship",
                "description": "Build reliable systems.",
            }
        ]


class MixedCompanyParser(FakeParser):
    def extract_jobs(self, listing_page):
        return [
            {
                "title": "Backend Engineer",
                "company_name": "OpenAI",
                "source_url": f"{listing_page.url}/openai-backend",
                "external_id": "openai-backend",
                "location": "Remote",
                "employment_type": "Full-time",
                "description": "Build Python services.",
            },
            {
                "title": "Backend Engineer",
                "company_name": "Netflix",
                "source_url": f"{listing_page.url}/netflix-backend",
                "external_id": "netflix-backend",
                "location": "Remote",
                "employment_type": "Full-time",
                "description": "Build Python services.",
            },
        ]


class EmptyParser(FakeParser):
    def extract_jobs(self, listing_page):
        return []
