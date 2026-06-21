from datetime import timedelta

import pytest
from django.utils import timezone

from apps.analytics.models import SkillCandidate, SkillDemand, SkillTrend
from apps.analytics.services.resume_gap_service import ResumeGapService
from apps.analytics.services.skill_candidate_service import SkillCandidateService
from apps.analytics.services.skill_demand_service import SkillDemandService
from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill, SkillCategory, SkillSet


@pytest.mark.django_db
def test_update_skill_demand_aggregates_job_post_skills():
    company = __import__("apps.companies.models", fromlist=["Company"]).Company.objects.create(
        name="Test Co"
    )
    python = SkillSet.objects.create(name="Python")
    aws = SkillSet.objects.create(name="AWS")
    job_old = JobPost.objects.create(
        company=company,
        title="Old Job",
        source_url="https://example.com/old",
    )
    job_new = JobPost.objects.create(
        company=company,
        title="New Job",
        source_url="https://example.com/new",
    )
    now = timezone.now()
    JobPostSkill.objects.create(job_post=job_old, skill_set=python, score=80)
    JobPostSkill.objects.create(job_post=job_new, skill_set=python, score=90)
    JobPostSkill.objects.create(job_post=job_new, skill_set=aws, score=70)
    JobPostSkill.objects.filter(job_post=job_old).update(
        created_at=now - timedelta(days=45)
    )

    stats = SkillDemandService().update_skill_demand()
    assert stats["demand_records"] == 2

    python_demand = SkillDemand.objects.get(skill=python)
    assert python_demand.total_occurrences == 2
    assert python_demand.unique_jobs == 2
    assert python_demand.rolling_30_day_count == 1
    assert python_demand.demand_score > 0

    python_trend = SkillTrend.objects.get(skill=python)
    assert python_trend.trend_type in SkillTrend.TrendType.values


@pytest.mark.django_db
def test_build_market_profile_counts_jobs_per_category():
    ai_ml = SkillCategory.objects.create(name="AI / ML")
    cloud = SkillCategory.objects.create(name="Cloud Computing")
    company = __import__("apps.companies.models", fromlist=["Company"]).Company.objects.create(
        name="Cat Co"
    )
    langchain = SkillSet.objects.create(name="LangChain")
    terraform = SkillSet.objects.create(name="Terraform")
    langchain.categories.add(ai_ml)
    terraform.categories.add(cloud)

    job = JobPost.objects.create(
        company=company,
        title="ML Job",
        source_url="https://example.com/ml",
    )
    JobPostSkill.objects.create(job_post=job, skill_set=langchain, score=85)
    JobPostSkill.objects.create(job_post=job, skill_set=terraform, score=75)

    profile = SkillDemandService().build_market_profile()
    assert profile["esco_categories"]["AI / ML"] == 1
    assert profile["esco_categories"]["Cloud Computing"] == 1


@pytest.mark.django_db
def test_skill_candidate_records_unmapped_and_flags_threshold():
    service = SkillCandidateService()
    service.review_threshold = 3
    for index in range(3):
        service.record_unmapped_names([f"Novel Skill {index}"])

    candidate = SkillCandidate.objects.get(normalized_name=SkillSet.normalize_name("Novel Skill 0"))
    assert candidate.occurrence_count == 1
    assert candidate.flagged_for_review is False

    service.record_unmapped_names(["Novel Skill 0", "Novel Skill 0", "Novel Skill 0"])
    candidate.refresh_from_db()
    assert candidate.occurrence_count == 4
    assert candidate.flagged_for_review is True


@pytest.mark.django_db
def test_skill_candidate_skips_existing_skillset_names():
    SkillSet.objects.create(name="Python")
    created = SkillCandidateService().record_unmapped_names(["Python", "python"])
    assert created == 0
    assert SkillCandidate.objects.count() == 0


@pytest.mark.django_db
def test_resume_gap_analysis_returns_market_profile_and_recommendations():
    ai_ml = SkillCategory.objects.create(name="AI / ML")
    company = __import__("apps.companies.models", fromlist=["Company"]).Company.objects.create(
        name="Gap Co"
    )
    python = SkillSet.objects.create(name="Python")
    langchain = SkillSet.objects.create(name="LangChain")
    python.categories.add(ai_ml)
    langchain.categories.add(ai_ml)

    job = JobPost.objects.create(
        company=company,
        title="Gap Job",
        source_url="https://example.com/gap",
    )
    JobPostSkill.objects.create(job_post=job, skill_set=langchain, score=90)
    SkillDemandService().update_skill_demand()

    gap = ResumeGapService().analyze_resume_gap({python.id}, limit=5)
    assert "AI / ML" in gap["market_profile"]["esco_categories"]
    assert any(
        item["name"] == "LangChain"
        for item in gap["missing_high_demand_skills"]
    )
    assert gap["recommended_skills"]
