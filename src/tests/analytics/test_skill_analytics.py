from datetime import UTC, datetime

import pytest

from apps.analytics.services import (
    CompanyAnalyticsService,
    JobAnalyticsService,
    SkillAnalyticsService,
)
from apps.applications.models import Application
from apps.companies.models import Company
from apps.jobs.models import JobPost
from apps.skills.models import ApplicationSkill, JobPostSkill, SkillSet


@pytest.mark.django_db
def test_top_skills_aggregation_works():
    openai = Company.objects.create(name="OpenAI")
    python = SkillSet.objects.create(name="Python")
    django = SkillSet.objects.create(name="Django")
    first = JobPost.objects.create(company=openai, title="Python Engineer")
    second = JobPost.objects.create(company=openai, title="Backend Engineer")
    JobPostSkill.objects.create(job_post=first, skill_set=python, score=95)
    JobPostSkill.objects.create(job_post=second, skill_set=python, score=85)
    JobPostSkill.objects.create(job_post=second, skill_set=django, score=80)

    result = SkillAnalyticsService().top_skills()

    assert result[0]["name"] == "Python"
    assert result[0]["count"] == 2
    assert result[0]["average_score"] == 90
    assert result[1]["name"] == "Django"
    assert list(first.skill_sets.all()) == [python]


@pytest.mark.django_db
def test_time_based_trends_work():
    company = Company.objects.create(name="OpenAI")
    python = SkillSet.objects.create(name="Python")
    job = JobPost.objects.create(company=company, title="Python Engineer")
    january = JobPostSkill.objects.create(job_post=job, skill_set=python, score=90)
    february_job = JobPost.objects.create(company=company, title="Backend Engineer")
    february = JobPostSkill.objects.create(
        job_post=february_job,
        skill_set=python,
        score=80,
    )
    JobPostSkill.objects.filter(id=january.id).update(
        created_at=datetime(2026, 1, 15, tzinfo=UTC)
    )
    JobPostSkill.objects.filter(id=february.id).update(
        created_at=datetime(2026, 2, 15, tzinfo=UTC)
    )

    result = SkillAnalyticsService().skill_trends_by_month(limit=1)

    assert [row["period"] for row in result] == ["2026-01", "2026-02"]
    assert [row["count"] for row in result] == [1, 1]


@pytest.mark.django_db
def test_company_level_analytics_works():
    openai = Company.objects.create(name="OpenAI")
    acme = Company.objects.create(name="Acme")
    python = SkillSet.objects.create(name="Python")
    react = SkillSet.objects.create(name="React")
    JobPostSkill.objects.create(
        job_post=JobPost.objects.create(company=openai, title="Python Engineer"),
        skill_set=python,
        score=90,
    )
    JobPostSkill.objects.create(
        job_post=JobPost.objects.create(company=acme, title="React Engineer"),
        skill_set=react,
        score=88,
    )

    result = CompanyAnalyticsService().company_skill_breakdown(company_id=openai.id)

    assert result == [
        {
            "company_id": openai.id,
            "company": "OpenAI",
            "skillset_id": python.id,
            "name": "Python",
            "count": 1,
            "average_score": 90,
        }
    ]


@pytest.mark.django_db
def test_skill_gap_analysis_works():
    target = Company.objects.create(name="OpenAI")
    benchmark = Company.objects.create(name="Acme")
    python = SkillSet.objects.create(name="Python")
    django = SkillSet.objects.create(name="Django")
    react = SkillSet.objects.create(name="React")
    JobPostSkill.objects.create(
        job_post=JobPost.objects.create(company=target, title="Python Engineer"),
        skill_set=python,
        score=90,
    )
    JobPostSkill.objects.create(
        job_post=JobPost.objects.create(company=benchmark, title="Django Engineer"),
        skill_set=django,
        score=88,
    )
    JobPostSkill.objects.create(
        job_post=JobPost.objects.create(company=benchmark, title="React Engineer"),
        skill_set=react,
        score=80,
    )

    result = CompanyAnalyticsService().skill_gap_analysis(company_id=target.id)

    assert {row["name"] for row in result} == {"Django", "React"}
    assert all(row["target_count"] == 0 for row in result)
    assert all(row["gap"] == 1 for row in result)


@pytest.mark.django_db
def test_filters_by_time_window_and_company_work():
    openai = Company.objects.create(name="OpenAI")
    acme = Company.objects.create(name="Acme")
    python = SkillSet.objects.create(name="Python")
    react = SkillSet.objects.create(name="React")
    openai_link = JobPostSkill.objects.create(
        job_post=JobPost.objects.create(company=openai, title="Python Engineer"),
        skill_set=python,
        score=90,
    )
    acme_link = JobPostSkill.objects.create(
        job_post=JobPost.objects.create(company=acme, title="React Engineer"),
        skill_set=react,
        score=80,
    )
    JobPostSkill.objects.filter(id=openai_link.id).update(
        created_at=datetime(2026, 2, 15, tzinfo=UTC)
    )
    JobPostSkill.objects.filter(id=acme_link.id).update(
        created_at=datetime(2025, 1, 15, tzinfo=UTC)
    )

    result = SkillAnalyticsService().top_skills(
        filters={
            "company_id": str(openai.id),
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        }
    )

    assert [row["name"] for row in result] == ["Python"]


@pytest.mark.django_db
def test_job_category_analytics_works():
    company = Company.objects.create(name="OpenAI")
    python = SkillSet.objects.create(name="Python")
    job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        employment_type="Full-time",
    )
    JobPostSkill.objects.create(job_post=job, skill_set=python, score=91)

    result = JobAnalyticsService().top_skills_by_job_category()

    assert result[0]["category"] == "Full-time"
    assert result[0]["name"] == "Python"


@pytest.mark.django_db
def test_application_skill_comparison_works(user):
    company = Company.objects.create(name="OpenAI")
    python = SkillSet.objects.create(name="Python")
    django = SkillSet.objects.create(name="Django")
    job = JobPost.objects.create(company=company, title="Backend Engineer")
    application = Application.objects.create(user=user, job_post=job)
    JobPostSkill.objects.create(job_post=job, skill_set=python, score=90)
    JobPostSkill.objects.create(job_post=job, skill_set=django, score=85)
    ApplicationSkill.objects.create(application=application, skill_set=python, score=80)

    result = SkillAnalyticsService().application_skill_comparison(application.id)

    assert result["matched"] == [{"skillset_id": python.id, "name": "Python"}]
    assert result["missing_from_application"] == [
        {"skillset_id": django.id, "name": "Django"}
    ]
    assert list(application.skill_sets.all()) == [python]


@pytest.mark.django_db
def test_analytics_api_and_view_return_expected_output(client, user):
    client.force_login(user)
    company = Company.objects.create(name="OpenAI")
    python = SkillSet.objects.create(name="Python")
    job = JobPost.objects.create(company=company, title="Python Engineer")
    JobPostSkill.objects.create(job_post=job, skill_set=python, score=95)

    api_response = client.get("/api/analytics/skills/")
    view_response = client.get("/analytics/skills/")

    assert api_response.status_code == 200
    assert api_response.json()["results"][0]["name"] == "Python"
    assert view_response.status_code == 200
    assert "Python" in view_response.content.decode()
