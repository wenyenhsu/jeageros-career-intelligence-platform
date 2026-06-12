import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

import apps.imports.services.crawl_service as crawl_service
from apps.imports.models import CrawlRun, JobSource, PipelineLog
from apps.imports.services import CrawlService, ListingPage, MonitoringService
from apps.jobs.models import JobPost


@pytest.mark.django_db
def test_log_entry_is_created_for_successful_events(company):
    log = MonitoringService.log_success(
        step_name="company_upsert",
        message="Company upsert succeeded.",
        service_name="TestService",
        company=company,
        metadata={"created": False},
    )

    assert PipelineLog.objects.count() == 1
    assert log.status == PipelineLog.StatusChoices.SUCCESS
    assert log.severity == PipelineLog.SeverityChoices.INFO
    assert log.company == company
    assert log.metadata == {"created": False}


@pytest.mark.django_db
def test_log_entry_is_created_for_failures(source_factory):
    source = source_factory()
    error = RuntimeError("parser exploded")

    log = MonitoringService.log_failure(
        step_name="source_crawl",
        message="Source crawl failed.",
        service_name="TestService",
        source=source,
        error=error,
    )

    assert log.status == PipelineLog.StatusChoices.FAILED
    assert log.severity == PipelineLog.SeverityChoices.ERROR
    assert log.source == source
    assert "RuntimeError: parser exploded" in log.error_text


@pytest.mark.django_db
def test_status_updates_are_persisted_for_crawl_run(monkeypatch):
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

    summary = CrawlService.crawl_enabled_sources()

    crawl_run = CrawlRun.objects.get(id=summary["crawl_run_id"])
    assert crawl_run.status == CrawlRun.StatusChoices.SUCCESS
    assert crawl_run.processed_sources == 2
    assert (
        PipelineLog.objects.filter(
            crawl_run=crawl_run,
            step_name="crawl_progress",
        ).count()
        == 2
    )
    assert PipelineLog.objects.filter(
        crawl_run=crawl_run,
        source=first,
        step_name="source_crawl",
        status=PipelineLog.StatusChoices.SUCCESS,
    ).exists()
    assert PipelineLog.objects.filter(
        crawl_run=crawl_run,
        source=second,
        step_name="source_crawl",
        status=PipelineLog.StatusChoices.SUCCESS,
    ).exists()


@pytest.mark.django_db
def test_monitoring_service_returns_run_status(monkeypatch):
    source = JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=True,
    )
    _patch_parser(monkeypatch)
    summary = CrawlService.crawl_enabled_sources()

    payload = MonitoringService.run_status(summary["crawl_run_id"])

    assert payload["status"] == CrawlRun.StatusChoices.SUCCESS
    assert payload["progress"] == 100
    assert payload["crawl_run"]["processed_sources"] == 1
    assert payload["current_step"]["step_name"] == "crawl_run"
    assert payload["step_summary"]
    assert any(log["source_id"] == source.id for log in payload["recent_logs"])
    assert payload["error_summary"]["count"] == 0


@pytest.mark.django_db
def test_monitoring_api_returns_expected_log_and_status(
    client, user, monkeypatch, company, job
):
    client.force_login(user)
    JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        enabled=True,
    )
    MonitoringService.log_success(
        step_name="job_upsert",
        message="Job upsert completed.",
        service_name="JobSyncService",
        company=company,
        job=job,
    )
    _patch_parser(monkeypatch)
    summary = CrawlService.crawl_enabled_sources()

    status_response = client.get(f"/api/runs/{summary['crawl_run_id']}/status/")
    logs_response = client.get("/api/logs/?step_name=source_crawl")
    job_logs_response = client.get(
        f"/api/logs/?job_id={job.id}&company_id={company.id}"
    )

    assert status_response.status_code == 200
    assert status_response.json()["progress"] == 100
    assert status_response.json()["recent_logs"]
    assert status_response.json()["step_summary"]
    assert "by_step" in status_response.json()["error_summary"]
    assert logs_response.status_code == 200
    assert any(
        item["step_name"] == "source_crawl" for item in logs_response.json()["results"]
    )
    assert job_logs_response.status_code == 200
    assert job_logs_response.json()["results"][0]["job_id"] == job.id
    assert job_logs_response.json()["results"][0]["company_id"] == company.id


@pytest.mark.django_db
def test_monitoring_admin_list_and_search_work(client):
    admin_user = get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="pass12345",
    )
    MonitoringService.log_success(
        step_name="analytics_query",
        message="Analytics query completed.",
        service_name="SkillAnalyticsService",
    )
    client.force_login(admin_user)

    response = client.get(
        reverse("admin:imports_pipelinelog_changelist"),
        {"q": "analytics"},
    )

    assert response.status_code == 200
    assert "analytics_query" in response.content.decode()


@pytest.mark.django_db
def test_monitoring_page_shows_recent_failures(client):
    MonitoringService.log_failure(
        step_name="celery_task",
        message="Task failed.",
        error=RuntimeError("boom"),
    )

    response = client.get(reverse("monitoring-dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Monitoring" in content
    assert "Pipeline Step Summary" in content
    assert "Task failed." in content


@pytest.mark.django_db
def test_monitoring_service_returns_step_and_error_summaries(source_factory):
    source = source_factory()
    crawl_run = CrawlRun.objects.create(
        status=CrawlRun.StatusChoices.RUNNING,
        total_sources=1,
        current_source=source.name,
    )
    MonitoringService.log_success(
        step_name="source_detection",
        message="Detected source.",
        crawl_run=crawl_run,
        source=source,
        duration_ms=12,
    )
    MonitoringService.log_failure(
        step_name="job_extraction",
        message="Extraction failed.",
        crawl_run=crawl_run,
        source=source,
        error=RuntimeError("bad html"),
        duration_ms=30,
    )

    status = MonitoringService.run_status(crawl_run.id)
    errors = MonitoringService.error_summary(source_id=source.id)

    assert status["current_step"] == {
        "step_name": "source_crawl",
        "message": f"Crawling {source.name}.",
        "source_name": source.name,
    }
    detection_row = next(
        row for row in status["step_summary"] if row["step_name"] == "source_detection"
    )
    assert {
        "step_name": "source_detection",
        "status": PipelineLog.StatusChoices.SUCCESS,
        "severity": PipelineLog.SeverityChoices.INFO,
        "total": 1,
        "average_duration_ms": 12.0,
    }.items() <= detection_row.items()
    assert status["error_summary"]["count"] == 1
    assert errors["by_step"] == [{"step_name": "job_extraction", "total": 1}]
    assert errors["by_source"] == [
        {
            "source_id": source.id,
            "source_name": source.name,
            "total": 1,
        }
    ]


@pytest.mark.django_db
def test_long_running_flow_updates_progress_logs(monkeypatch):
    for index in range(3):
        JobSource.objects.create(
            name=f"Source {index}",
            resource=JobSource.ResourceChoices.GREENHOUSE,
            base_url=f"https://boards.greenhouse.io/source-{index}",
            enabled=True,
        )
    _patch_parser(monkeypatch)

    progress_updates = []
    summary = CrawlService.crawl_enabled_sources(
        progress_callback=progress_updates.append
    )

    assert summary["progress_percentage"] == 100
    assert [update["processed_sources"] for update in progress_updates] == [1, 2, 3, 3]
    assert (
        PipelineLog.objects.filter(
            crawl_run_id=summary["crawl_run_id"],
            step_name="crawl_progress",
        ).count()
        == 3
    )


@pytest.fixture
def source_factory(db):
    def create_source(**kwargs):
        defaults = {
            "name": "Greenhouse",
            "resource": JobSource.ResourceChoices.GREENHOUSE,
            "base_url": "https://boards.greenhouse.io/openai",
            "enabled": True,
        }
        defaults.update(kwargs)
        return JobSource.objects.create(**defaults)

    return create_source


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
