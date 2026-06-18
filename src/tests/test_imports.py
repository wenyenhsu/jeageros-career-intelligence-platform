import pytest
from django.urls import reverse
from django.utils import timezone

import apps.imports.views as import_views
from apps.imports.forms import JobSourceForm
from apps.imports.models import CrawlRun, JobSource, PipelineLog


@pytest.mark.django_db
def test_job_source_str():
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/",
        enabled=True,
    )

    assert str(source) == "LinkedIn (LinkedIn)"


@pytest.mark.django_db
def test_source_list_view(client):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/",
    )

    response = client.get(reverse("source-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "LinkedIn" in content
    assert "Run all sources" in content
    assert f'action="{reverse("source-run-all")}"' in content
    assert "Live Pipeline Status" in content
    assert "Pipeline Flow" in content
    assert "globalCrawlStatus" in content
    assert "jaegeros.activeCrawlRunId" in content
    assert "Abort" in content
    assert reverse("source-run-abort", args=[0]) in content
    assert "Run" in content
    assert "Copy" in content
    assert reverse("source-copy", args=[source.id]) in content
    assert "Delete" in content
    assert reverse("source-delete", args=[source.id]) in content


@pytest.mark.django_db
def test_source_create_view(client):
    payload = {
        "name": "LinkedIn",
        "resource": JobSource.Resource.LINKEDIN,
        "base_url": "https://www.linkedin.com/jobs/search/",
        "enabled": True,
        "crawl_interval_minutes": 720,
        "max_pages": 2,
        "fetch_details": "new_or_missing",
        "max_search_requests": 5,
        "max_detail_requests": 3,
        "request_delay_seconds": 5,
        "rolling_search": "on",
        "rate_limit_cooldown_minutes": 60,
        "sort_by": "DD",
        "date_posted": "r604800",
        "default_job_type": "",
        "location": "United States, CA",
        "job_types": "Full-time, Internship",
        "workplace_types": "Remote, Hybrid, On-site",
        "search_keywords": "data engineer\nbackend",
        "include_keywords": "python, django",
        "exclude_keywords": "senior",
        "target_companies": "OpenAI, Google",
        "notes": "Test source",
    }

    response = client.post(reverse("source-create"), data=payload)

    assert response.status_code in (302, 303)
    source = JobSource.objects.get(name="LinkedIn")
    assert source.crawl_config["max_pages"] == 2
    assert source.crawl_config["fetch_details"] == "new_or_missing"
    assert source.crawl_config["max_search_requests"] == 5
    assert source.crawl_config["max_detail_requests"] == 3
    assert source.crawl_config["sort_by"] == "DD"
    assert source.crawl_config["date_posted"] == "r604800"
    assert source.filter_config["location"] == ["United States", "CA"]
    assert source.filter_config["job_types"] == ["Full-time", "Internship"]
    assert source.filter_config["include_keywords"] == ["python", "django"]
    assert source.filter_config["target_companies"] == ["OpenAI", "Google"]


@pytest.mark.django_db
def test_source_create_form_exposes_resource_base_url_defaults(client):
    response = client.get(reverse("source-create"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "data-default-base-urls" in content
    assert "data-base-url-target" in content
    assert "id_base_url" in content
    assert "https://www.linkedin.com/jobs/search/" in content
    assert "https://app.joinhandshake.com/stu/postings" not in content
    assert "data-default-config-values" in content
    assert "max_search_requests" in content
    assert "workplace_types" in content
    assert "sort_by" in content
    assert "date_posted" in content
    assert "Parameter guide" in content
    assert reverse("source-help") in content


@pytest.mark.django_db
def test_source_help_view_explains_form_parameters(client):
    response = client.get(reverse("source-help"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Job Source Parameter Guide" in content
    assert "Resource Defaults" in content
    assert "Max pages" in content
    assert "Fetch details" in content
    assert "Request delay seconds" in content
    assert "Max search requests" in content
    assert "Max detail requests" in content
    assert "Rate limit cooldown minutes" in content
    assert "Sort order" in content
    assert "Date posted" in content
    assert "Default job type" in content
    assert "Rolling search" in content
    assert "Location" in content
    assert "Job types" in content
    assert "Workplace types" in content
    assert "Remote only" in content
    assert "Search keywords" in content
    assert "Include keywords" in content
    assert "Exclude keywords" in content
    assert "Target companies" in content
    assert "LinkedIn" in content
    assert "Handshake" not in content
    assert "Generic HTML" not in content


def test_source_form_fills_default_base_url_when_missing():
    form = JobSourceForm(
        data={
            "name": "LinkedIn data",
            "resource": JobSource.Resource.LINKEDIN,
            "base_url": "",
            "enabled": "on",
            "crawl_interval_minutes": 1440,
            "max_pages": 1,
            "fetch_details": "new_or_missing",
            "max_search_requests": 5,
            "max_detail_requests": 5,
            "request_delay_seconds": 5,
            "rolling_search": "on",
            "rate_limit_cooldown_minutes": 60,
            "sort_by": "DD",
            "date_posted": "r604800",
            "default_job_type": "",
            "notes": "",
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["base_url"] == "https://www.linkedin.com/jobs/search/"


def test_source_form_preserves_custom_base_url():
    custom_url = "https://www.linkedin.com/jobs/search/?keywords=data"
    form = JobSourceForm(
        data={
            "name": "LinkedIn custom",
            "resource": JobSource.Resource.LINKEDIN,
            "base_url": custom_url,
            "enabled": "on",
            "crawl_interval_minutes": 1440,
            "max_pages": 1,
            "fetch_details": "new_or_missing",
            "max_search_requests": 5,
            "max_detail_requests": 5,
            "request_delay_seconds": 5,
            "rolling_search": "on",
            "rate_limit_cooldown_minutes": 60,
            "sort_by": "DD",
            "date_posted": "r604800",
            "default_job_type": "",
            "notes": "",
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["base_url"] == custom_url


@pytest.mark.django_db
def test_source_form_standardizes_filter_config_values():
    form = JobSourceForm(
        data={
            "name": "LinkedIn standard config",
            "resource": JobSource.Resource.LINKEDIN,
            "base_url": "",
            "enabled": "on",
            "crawl_interval_minutes": 1440,
            "max_pages": 1,
            "fetch_details": "new_or_missing",
            "max_search_requests": 5,
            "max_detail_requests": 5,
            "request_delay_seconds": 5,
            "rolling_search": "on",
            "rate_limit_cooldown_minutes": 60,
            "sort_by": "DD",
            "date_posted": "r604800",
            "default_job_type": "Full-time",
            "location": "CA\nTX, United States",
            "job_types": "Internship, internship, Full-time",
            "workplace_types": "Remote, Hybrid",
            "remote_only": "",
            "search_keywords": "data engineer, backend",
            "include_keywords": "python\nDjango, python",
            "exclude_keywords": "senior",
            "target_companies": "",
            "notes": "",
        }
    )

    assert form.is_valid(), form.errors
    source = form.save()
    assert source.crawl_config["default_job_type"] == "Full-time"
    assert source.crawl_config["request_delay_seconds"] == 5.0
    assert source.crawl_config["sort_by"] == "DD"
    assert source.crawl_config["date_posted"] == "r604800"
    assert source.filter_config["location"] == ["CA", "TX", "United States"]
    assert source.filter_config["job_types"] == ["Internship", "Full-time"]
    assert source.filter_config["include_keywords"] == ["python", "Django"]
    assert source.filter_config["remote_only"] is False


@pytest.mark.django_db
def test_source_form_preserves_runtime_crawl_config_keys():
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        crawl_config={
            "rolling_state": {"linkedin_search_offset": 25},
            "rate_limited_until": "2026-06-17T12:00:00+00:00",
            "max_pages": 9,
        },
    )
    form = JobSourceForm(
        data={
            "name": "LinkedIn",
            "resource": JobSource.Resource.LINKEDIN,
            "base_url": "https://www.linkedin.com/jobs/search/",
            "enabled": "on",
            "crawl_interval_minutes": 1440,
            "max_pages": 2,
            "fetch_details": "new_or_missing",
            "max_search_requests": 5,
            "max_detail_requests": 5,
            "request_delay_seconds": 5,
            "rolling_search": "on",
            "rate_limit_cooldown_minutes": 60,
            "default_job_type": "",
            "notes": "",
        },
        instance=source,
    )

    assert form.is_valid(), form.errors
    updated = form.save()
    assert updated.crawl_config["max_pages"] == 2
    assert updated.crawl_config["rolling_state"] == {"linkedin_search_offset": 25}
    assert updated.crawl_config["rate_limited_until"] == "2026-06-17T12:00:00+00:00"


@pytest.mark.django_db
def test_source_delete_view(client):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/",
    )

    response = client.post(reverse("source-delete", args=[source.id]))

    assert response.status_code in (302, 303)
    assert not JobSource.objects.filter(id=source.id).exists()


@pytest.mark.django_db
def test_source_copy_view_duplicates_source_without_runtime_state(client):
    source = JobSource.objects.create(
        name="LinkedIn data career",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        enabled=False,
        crawl_interval_minutes=720,
        crawl_config={
            "max_pages": 2,
            "fetch_details": "new_or_missing",
            "rolling_state": {"linkedin_search_offset": 25},
        },
        filter_config={
            "location": ["CA", "TX"],
            "job_types": ["Internship"],
            "include_keywords": ["data engineer"],
        },
        last_crawled_at=timezone.now(),
        notes="Keep this config",
    )

    response = client.post(reverse("source-copy", args=[source.id]), follow=True)

    assert response.status_code == 200
    copied = JobSource.objects.get(name="LinkedIn data career copy")
    assert copied.id != source.id
    assert copied.resource == source.resource
    assert copied.base_url == source.base_url
    assert copied.enabled == source.enabled
    assert copied.crawl_interval_minutes == source.crawl_interval_minutes
    assert copied.crawl_config == source.crawl_config
    assert copied.filter_config == source.filter_config
    assert copied.notes == source.notes
    assert copied.last_crawled_at is None
    assert "Copied &quot;LinkedIn data career&quot;" in response.content.decode()
    assert PipelineLog.objects.filter(
        step_name="source_copy",
        source=copied,
        metadata__original_source_id=source.id,
    ).exists()


@pytest.mark.django_db
def test_source_copy_view_uses_next_available_copy_name(client):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
    )
    JobSource.objects.create(
        name="LinkedIn copy",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
    )

    response = client.post(reverse("source-copy", args=[source.id]))

    assert response.status_code in (302, 303)
    assert JobSource.objects.filter(name="LinkedIn copy 2").exists()


@pytest.mark.django_db
def test_run_all_sources_button_queues_enabled_source_crawl(client, monkeypatch):
    called = {}

    def fake_enqueue(crawl_run_id, source_ids=None):
        called["crawl_run_id"] = crawl_run_id
        called["source_ids"] = source_ids
        return ""

    monkeypatch.setattr(
        import_views,
        "_enqueue_crawl_task",
        fake_enqueue,
    )

    response = client.post(reverse("source-run-all"), follow=True)

    assert response.status_code == 200
    crawl_run = CrawlRun.objects.get(id=called["crawl_run_id"])
    assert called["source_ids"] is None
    assert crawl_run.status == CrawlRun.StatusChoices.PENDING
    content = response.content.decode()
    assert "All enabled job sources crawl started." in content
    assert f'data-active-run-id="{crawl_run.id}"' in content
    assert "View monitoring logs" in content


@pytest.mark.django_db
def test_run_single_source_button_queues_only_that_source(client, monkeypatch):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
    )
    called = {}

    def fake_enqueue(crawl_run_id, source_ids=None):
        called["crawl_run_id"] = crawl_run_id
        called["source_ids"] = source_ids
        return ""

    monkeypatch.setattr(
        import_views,
        "_enqueue_crawl_task",
        fake_enqueue,
    )

    response = client.post(reverse("source-run", args=[source.id]), follow=True)

    assert response.status_code == 200
    assert called["source_ids"] == [source.id]
    crawl_run = CrawlRun.objects.get(id=called["crawl_run_id"])
    content = response.content.decode()
    assert "LinkedIn crawl started." in content
    assert f'data-active-run-id="{crawl_run.id}"' in content


@pytest.mark.django_db
def test_run_single_source_ajax_returns_status_urls(client, monkeypatch):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
    )
    called = {}

    def fake_enqueue(crawl_run_id, source_ids=None):
        called["crawl_run_id"] = crawl_run_id
        called["source_ids"] = source_ids
        return ""

    monkeypatch.setattr(
        import_views,
        "_enqueue_crawl_task",
        fake_enqueue,
    )

    response = client.post(
        reverse("source-run", args=[source.id]),
        HTTP_ACCEPT="application/json",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["success"] is True
    assert payload["crawl_run_id"] == called["crawl_run_id"]
    assert payload["status_url"] == reverse(
        "source-run-status",
        args=[called["crawl_run_id"]],
    )
    assert payload["monitoring_url"].endswith("#recent-pipeline-logs")
    assert called["source_ids"] == [source.id]


@pytest.mark.django_db
def test_source_run_status_endpoint_returns_pipeline_payload(client):
    crawl_run = CrawlRun.objects.create(
        status=CrawlRun.StatusChoices.RUNNING,
        total_sources=1,
        current_source="LinkedIn",
    )
    PipelineLog.objects.create(
        crawl_run=crawl_run,
        step_name="source_detection",
        status=PipelineLog.StatusChoices.SUCCESS,
        severity=PipelineLog.SeverityChoices.INFO,
        message="Detected LinkedIn parser.",
    )

    response = client.get(reverse("source-run-status", args=[crawl_run.id]))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == CrawlRun.StatusChoices.RUNNING
    assert payload["current_step"]["step_name"] == "source_crawl"
    assert payload["recent_logs"][0]["step_name"] == "source_detection"


@pytest.mark.django_db
def test_source_run_abort_endpoint_marks_run_aborted(client):
    crawl_run = CrawlRun.objects.create(
        status=CrawlRun.StatusChoices.RUNNING,
        total_sources=1,
        current_source="LinkedIn",
    )

    response = client.post(
        reverse("source-run-abort", args=[crawl_run.id]),
        HTTP_ACCEPT="application/json",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    crawl_run.refresh_from_db()
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == CrawlRun.StatusChoices.ABORTED
    assert crawl_run.status == CrawlRun.StatusChoices.ABORTED
    assert crawl_run.finished_at is not None
    assert crawl_run.current_source == ""
    assert PipelineLog.objects.filter(
        crawl_run=crawl_run,
        step_name="crawl_run",
        severity=PipelineLog.SeverityChoices.WARNING,
    ).exists()
