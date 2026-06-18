import pytest
from django.urls import reverse
from django.utils import timezone

from apps.applications.models import Application
from apps.companies.models import Company
from apps.imports.models import CrawlRun, JobSource, PipelineLog
from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill, SkillSet


@pytest.mark.django_db
def test_dashboard_page_renders_operational_overview(client, user):
    company = Company.objects.create(name="OpenAI")
    job = JobPost.objects.create(
        company=company,
        title="Platform Engineer",
        status=JobPost.StatusChoices.ACTIVE,
        employment_type="Full-time",
        location="San Francisco, CA",
        source_type=JobPost.SourceType.URL,
    )
    skill = SkillSet.objects.create(name="Python")
    JobPostSkill.objects.create(job_post=job, skill_set=skill, score=90)
    Application.objects.create(
        user=user,
        job_post=job,
        status=Application.Status.APPLIED,
        applied_at=timezone.now(),
    )
    JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        enabled=True,
    )
    CrawlRun.objects.create(
        total_sources=1,
        processed_sources=1,
        jobs_created=1,
        jobs_updated=0,
        jobs_closed=0,
        status=CrawlRun.StatusChoices.SUCCESS,
    )
    PipelineLog.objects.create(
        step_name="source_crawl",
        status=PipelineLog.StatusChoices.SUCCESS,
        message="Finished crawling LinkedIn.",
    )

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Operational status, recent work, and crawl health." in content
    assert "Total Jobs" in content
    assert "Active Jobs" not in content
    assert "Applications" in content
    assert "Applied Today" in content
    assert "Recent Jobs" in content
    assert "Platform Engineer" in content
    assert "Recent Applications" in content
    assert "Skill Coverage Snapshot" in content
    assert "Required Skill Snapshot" in content
    assert "Job Mix" in content
    assert "Fast read on job type and location spread." in content
    assert "Fast read on job type, source, and location spread." not in content
    assert "URL" not in content
    assert "Active ·" not in content
    assert "Closed ·" not in content
    assert "Python" in content
    assert "Full Time" in content
    assert "Crawl / Sync Health" in content
    assert "Pipeline Status" in content


@pytest.mark.django_db
def test_dashboard_does_not_contain_analytics_only_sections(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Top Skill Demand" not in content
    assert "Skill Demand Trends" not in content
    assert "Company Skill Breakdown" not in content
    assert "Skill Gaps" not in content
    assert "Job-Market Signals by Category" not in content
    assert "Analysis Filters" not in content


@pytest.mark.django_db
def test_analytics_page_keeps_filters_and_market_analysis_sections(client):
    company = Company.objects.create(name="OpenAI")
    skill = SkillSet.objects.create(name="Python")
    job = JobPost.objects.create(
        company=company,
        title="Python Engineer",
        employment_type="Full-time",
    )
    JobPostSkill.objects.create(job_post=job, skill_set=skill, score=95)

    response = client.get(reverse("analytics-dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Market signals, skill demand, company trends, and gap analysis." in content
    assert "Analysis Filters" in content
    assert "Top Skill Demand" in content
    assert "Skill Demand Trends" in content
    assert "Company Skill Breakdown" in content
    assert "Job-Market Signals by Category" in content
    assert "Skill Coverage" in content
    assert "High-confidence links" not in content
    assert "Average score" not in content
    assert "Python" in content
    assert "Crawl / Sync Health" not in content
    assert "Recent Jobs" not in content


@pytest.mark.django_db
def test_dashboard_and_analytics_navbar_links_resolve(client):
    dashboard_response = client.get(reverse("dashboard"))
    analytics_response = client.get(reverse("analytics-dashboard"))

    assert dashboard_response.status_code == 200
    assert analytics_response.status_code == 200
    dashboard_content = dashboard_response.content.decode()
    analytics_content = analytics_response.content.decode()
    assert f'href="{reverse("dashboard")}"' in dashboard_content
    assert f'href="{reverse("analytics-dashboard")}"' in dashboard_content
    assert f'href="{reverse("dashboard")}"' in analytics_content
    assert f'href="{reverse("analytics-dashboard")}"' in analytics_content
