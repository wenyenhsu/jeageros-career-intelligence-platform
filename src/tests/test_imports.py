import pytest
from django.urls import reverse

import apps.imports.views as import_views
from apps.imports.models import JobSource


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
def test_run_all_sources_button_triggers_enabled_source_crawl(client, monkeypatch):
    called = {}

    def fake_crawl_enabled_sources():
        called["all"] = True
        return _crawl_summary(jobs_created=2, jobs_updated=1)

    monkeypatch.setattr(
        import_views.CrawlService,
        "crawl_enabled_sources",
        staticmethod(fake_crawl_enabled_sources),
    )

    response = client.post(reverse("source-run-all"), follow=True)

    assert response.status_code == 200
    assert called == {"all": True}
    content = response.content.decode()
    assert "All enabled job sources crawl finished." in content
    assert "Created: 2" in content
    assert "Updated: 1" in content


@pytest.mark.django_db
def test_run_single_source_button_triggers_only_that_source(client, monkeypatch):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
    )
    called = {}

    def fake_crawl_all_sources(sources):
        called["source_ids"] = [source.id for source in sources]
        return _crawl_summary(jobs_created=1, filtered=3)

    monkeypatch.setattr(
        import_views.CrawlService,
        "crawl_all_sources",
        staticmethod(fake_crawl_all_sources),
    )

    response = client.post(reverse("source-run", args=[source.id]), follow=True)

    assert response.status_code == 200
    assert called == {"source_ids": [source.id]}
    content = response.content.decode()
    assert "LinkedIn crawl finished." in content
    assert "Created: 1" in content
    assert "Filtered: 3" in content


def _crawl_summary(jobs_created=0, jobs_updated=0, jobs_closed=0, filtered=0):
    return {
        "success": True,
        "sources_processed": 1,
        "jobs_created": jobs_created,
        "jobs_updated": jobs_updated,
        "jobs_closed": jobs_closed,
        "skills_attached": 0,
        "errors": 0,
        "sources": [{"jobs_filtered": filtered}],
    }
