from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

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
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        enabled=True,
    )
    second = JobSource.objects.create(
        name="Lever",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
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
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
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
def test_monitoring_service_returns_estimated_progress_for_running_pipeline():
    crawl_run = CrawlRun.objects.create(
        status=CrawlRun.StatusChoices.RUNNING,
        total_sources=1,
        processed_sources=0,
        current_source="LinkedIn",
    )
    PipelineLog.objects.create(
        crawl_run=crawl_run,
        step_name="source_detection",
        status=PipelineLog.StatusChoices.SUCCESS,
        severity=PipelineLog.SeverityChoices.INFO,
        message="Detected parser type LINKEDIN.",
    )

    payload = MonitoringService.run_status(crawl_run.id)

    assert payload["progress"] == 0
    assert payload["display_progress"] == 30
    assert payload["display_progress_label"] == "30% estimated pipeline progress"


@pytest.mark.django_db
def test_monitoring_api_returns_expected_log_and_status(
    client, user, monkeypatch, company, job
):
    client.force_login(user)
    JobSource.objects.create(
        name="Greenhouse",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
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
    log = MonitoringService.log_failure(
        step_name="celery_task",
        message="Task failed.",
        error=RuntimeError("boom"),
    )
    timestamp = MonitoringService.log_to_dict(log)

    response = client.get(reverse("monitoring-dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Monitoring" in content
    assert "Pipeline Flow" in content
    assert "Pipeline Step Summary" not in content
    assert "Pipeline step summary" not in content
    assert "<th>Counts</th>" not in content
    assert "Task failed." in content
    assert "RuntimeError: boom" in content
    assert "<time" in content
    assert "datetime=" in content
    assert timestamp["created_at_display"] in content
    assert timestamp["created_at_title"] in content
    assert "+00:00" not in content
    assert content.index("Latest Crawl Run") < content.index("Pipeline Flow")
    assert content.index("Pipeline Flow") < content.index("Analysis Pipeline")
    assert content.index("Analysis Pipeline") < content.index("Top Error Sources")
    assert content.index("Top Error Sources") < content.index("Recent Failures")


@pytest.mark.django_db
def test_monitoring_page_shows_resume_analysis_pipeline(client):
    resume_run_id = "resume-run-1"
    MonitoringService.log_event(
        step_name="resume_text_extraction",
        status=PipelineLog.StatusChoices.SUCCESS,
        message="Resume text prepared for analysis.",
        metadata={
            "pipeline_kind": "resume_analysis",
            "resume_run_id": resume_run_id,
            "pipeline_step_key": "text_extraction",
            "pipeline_step_label": "Text extraction",
            "count": 1200,
        },
        duration_ms=250,
    )
    MonitoringService.log_event(
        step_name="resume_ollama_extract",
        status=PipelineLog.StatusChoices.SUCCESS,
        message="Candidate resume skills extracted.",
        metadata={
            "pipeline_kind": "resume_analysis",
            "resume_run_id": resume_run_id,
            "pipeline_step_key": "ollama_extract",
            "pipeline_step_label": "Ollama Extract",
            "count": 8,
        },
        duration_ms=1500,
    )
    MonitoringService.log_event(
        step_name="resume_analysis",
        status=PipelineLog.StatusChoices.SUCCESS,
        message="Resume analysis completed.",
        metadata={
            "pipeline_kind": "resume_analysis",
            "resume_run_id": resume_run_id,
            "candidate_count": 8,
            "verified_count": 6,
            "mapped_count": 5,
            "unmapped_count": 1,
            "job_match_count": 4,
            "market_fit_percent": 50,
        },
    )

    payload = MonitoringService.dashboard_summary(resume_run_id=resume_run_id)
    response = client.get(
        reverse("monitoring-dashboard"),
        {"resume_run_id": resume_run_id},
    )

    assert payload["analysis_pipeline"]["status"] == PipelineLog.StatusChoices.SUCCESS
    assert payload["analysis_pipeline"]["summary"]["candidate_count"] == 8
    assert response.status_code == 200
    content = response.content.decode()
    assert "Analysis Pipeline" in content
    assert "Resume run resume-r" in content
    assert "Candidates" in content
    assert "Verified" in content
    assert "Mapped" in content
    assert "Market fit" in content
    assert "Text extraction" in content
    assert "Ollama Extract" in content
    assert "Candidate resume skills extracted." in content
    assert content.index("Pipeline Flow") < content.index("Analysis Pipeline")
    assert content.index("Analysis Pipeline") < content.index("Top Error Sources")


@pytest.mark.django_db
def test_monitoring_page_links_to_parameter_guide(client):
    response = client.get(reverse("monitoring-dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Parameter guide" in content
    assert reverse("monitoring-help") in content


@pytest.mark.django_db
def test_monitoring_help_view_explains_dashboard_parameters(client):
    response = client.get(reverse("monitoring-help"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Monitoring Parameter Guide" in content
    assert "Latest Crawl Run" in content
    assert "Pipeline Flow" in content
    assert "Job Archive" in content
    assert "Top Error Sources" in content
    assert "Recent Failures" in content
    assert "Started" in content
    assert "Finished" in content
    assert "Created" in content
    assert "Updated" in content
    assert "Closed" in content
    assert "Errors" in content
    assert "crawl_run_id" in content
    assert "source_detection" in content
    assert "ollama_extract" in content
    assert "skill_pipeline" in content
    assert "HTTP 429" in content
    assert "Created before" in content
    assert "JobArchiveRun" in content


@pytest.mark.django_db
def test_monitoring_page_shows_crawl_run_counts(client):
    crawl_run = CrawlRun.objects.create(
        status=CrawlRun.StatusChoices.SUCCESS,
        total_sources=1,
        processed_sources=1,
        jobs_created=2,
        jobs_updated=3,
        jobs_closed=4,
        errors=5,
    )
    finished_at = timezone.now()
    started_at = finished_at - timedelta(minutes=7)
    CrawlRun.objects.filter(id=crawl_run.id).update(
        started_at=started_at,
        finished_at=finished_at,
    )
    latest_run = MonitoringService.dashboard_summary()["latest_run"]

    response = client.get(reverse("monitoring-dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Started" in content
    assert "Finished" in content
    assert latest_run["started_at_display"] in content
    assert latest_run["finished_at_display"] in content
    assert latest_run["started_at_title"] in content
    assert latest_run["finished_at_title"] in content
    assert "Created" in content
    assert "Updated" in content
    assert "Closed" in content
    assert "Processed" in content
    assert "Latest crawl run progress" in content
    assert ">2<" in content
    assert ">3<" in content
    assert ">4<" in content
    assert ">5<" in content


@pytest.mark.django_db
def test_monitoring_page_shows_summary_failure_reason(client):
    crawl_run = CrawlRun.objects.create(status=CrawlRun.StatusChoices.FAILED)
    MonitoringService.log_event(
        step_name="crawl_run",
        status=PipelineLog.StatusChoices.FAILED,
        severity=PipelineLog.SeverityChoices.ERROR,
        message="Crawl run finished.",
        crawl_run=crawl_run,
        metadata={
            "failures": [
                {
                    "source_name": "LinkedIn",
                    "error": "HTTP Error 429: Too Many Requests",
                }
            ]
        },
    )

    response = client.get(
        reverse("monitoring-dashboard"),
        {"crawl_run_id": crawl_run.id},
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Reason" in content
    assert "HTTP Error 429: Too Many Requests" in content


@pytest.mark.django_db
def test_monitoring_page_filters_logs_by_crawl_run(client):
    first_run = CrawlRun.objects.create(status=CrawlRun.StatusChoices.FAILED)
    second_run = CrawlRun.objects.create(status=CrawlRun.StatusChoices.SUCCESS)
    MonitoringService.log_failure(
        step_name="source_crawl",
        message="Selected run failed.",
        crawl_run=first_run,
        error=RuntimeError("selected"),
    )
    MonitoringService.log_success(
        step_name="source_crawl",
        message="Other run succeeded.",
        crawl_run=second_run,
    )

    response = client.get(
        reverse("monitoring-dashboard"),
        {"crawl_run_id": first_run.id},
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert f"Showing logs for crawl run #{first_run.id}" in content
    assert "Selected run failed." in content
    assert "Other run succeeded." not in content
    assert 'id="recent-pipeline-logs"' in content


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
    assert detection_row["average_duration_display"] == "0:00"
    failure_log = next(
        log for log in status["recent_logs"] if log["step_name"] == "job_extraction"
    )
    assert failure_log["flow_duration_display"] == "0:00"
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
def test_monitoring_service_formats_flow_counts_and_duration():
    crawl_run = CrawlRun.objects.create(
        status=CrawlRun.StatusChoices.SUCCESS,
        total_sources=1,
        processed_sources=1,
        jobs_created=2,
        jobs_updated=3,
        jobs_closed=4,
        errors=1,
    )
    MonitoringService.log_success(
        step_name="source_crawl",
        message="Finished crawling LinkedIn.",
        crawl_run=crawl_run,
        metadata={
            "jobs_created": 2,
            "jobs_updated": 3,
            "jobs_closed": 4,
            "errors": 1,
        },
        duration_ms=65_000,
    )

    payload = MonitoringService.run_status(crawl_run.id)
    log = payload["recent_logs"][0]
    summary = payload["step_summary"][0]

    assert log["duration_display"] == "1:05"
    assert log["flow_duration_display"] == "1:05"
    assert log["metric_summary_text"] == (
        "Created: 2, Updated: 3, Closed: 4, Errors: 1"
    )
    assert [metric["label"] for metric in log["metric_summary"][:4]] == [
        "Created",
        "Updated",
        "Closed",
        "Errors",
    ]
    assert summary["average_duration_display"] == "1:05"


@pytest.mark.django_db
def test_long_running_flow_updates_progress_logs(monkeypatch):
    for index in range(3):
        JobSource.objects.create(
            name=f"Source {index}",
            resource=JobSource.ResourceChoices.LINKEDIN,
            base_url="https://www.linkedin.com/jobs/search/",
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
            "resource": JobSource.ResourceChoices.LINKEDIN,
            "base_url": "https://www.linkedin.com/jobs/search/",
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
