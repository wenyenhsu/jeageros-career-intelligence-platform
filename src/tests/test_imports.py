import pytest
from django.urls import reverse

import apps.imports.views as import_views
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
    assert "Run" in content
    assert "Delete" in content
    assert reverse("source-delete", args=[source.id]) in content


@pytest.mark.django_db
def test_source_create_view(client):
    payload = {
        "name": "Greenhouse",
        "resource": JobSource.Resource.GREENHOUSE,
        "base_url": "https://boards.greenhouse.io/",
        "enabled": True,
        "crawl_interval_minutes": 720,
        "crawl_config": '{"pages": 2}',
        "filter_config": '{"include_keywords": ["python"]}',
        "notes": "Test source",
    }

    response = client.post(reverse("source-create"), data=payload)

    assert response.status_code in (302, 303)
    assert JobSource.objects.filter(name="Greenhouse").exists()


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
