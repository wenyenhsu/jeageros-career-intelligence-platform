import pytest
from django.db import connection

from apps.analytics.services.market_fit_service import MarketFitService
from apps.companies.models import Company
from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill, SkillSet


def vector(*values):
    return list(values) + [0.0] * (1024 - len(values))


@pytest.mark.django_db
def test_weighted_mean_returns_zero_when_no_demand():
    assert MarketFitService._weighted_mean([]) == 0.0
    assert MarketFitService._weighted_mean([(0, 1.0)]) == 0.0


@pytest.mark.django_db
def test_weighted_mean_formula():
    scores = [(56, 1.0), (23, 0.89), (77, 1.0)]
    expected = (56 * 1.0 + 23 * 0.89 + 77 * 1.0) / (56 + 23 + 77)
    assert abs(MarketFitService._weighted_mean(scores) - expected) < 0.0001


@pytest.mark.django_db
def test_active_market_demand_counts_active_jobpostskill_rows():
    company = Company.objects.create(name="Demand Co")
    python = SkillSet.objects.create(name="Python")
    sql = SkillSet.objects.create(name="SQL")
    active_job = JobPost.objects.create(
        company=company,
        title="Active Job",
        source_url="https://example.com/active",
        status=JobPost.StatusChoices.ACTIVE,
    )
    closed_job = JobPost.objects.create(
        company=company,
        title="Closed Job",
        source_url="https://example.com/closed",
        status=JobPost.StatusChoices.CLOSED,
    )
    active_job_two = JobPost.objects.create(
        company=company,
        title="Active Job Two",
        source_url="https://example.com/active-2",
        status=JobPost.StatusChoices.ACTIVE,
    )
    JobPostSkill.objects.create(job_post=active_job, skill_set=python, score=90)
    JobPostSkill.objects.create(job_post=active_job_two, skill_set=python, score=85)
    JobPostSkill.objects.create(job_post=active_job, skill_set=sql, score=80)
    JobPostSkill.objects.create(job_post=closed_job, skill_set=sql, score=70)

    demand = MarketFitService.active_market_demand()

    assert demand[python.id] == 2
    assert demand[sql.id] == 1


@pytest.mark.django_db
def test_market_fit_exact_match_without_embeddings():
    company = Company.objects.create(name="Fit Co")
    python = SkillSet.objects.create(name="Python")
    sql = SkillSet.objects.create(name="SQL")
    django = SkillSet.objects.create(name="Django")
    job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url="https://example.com/backend",
    )
    JobPostSkill.objects.create(job_post=job, skill_set=python, score=90)
    JobPostSkill.objects.create(job_post=job, skill_set=sql, score=85)
    JobPostSkill.objects.create(job_post=job, skill_set=django, score=80)

    result = MarketFitService().calculate({python.id, sql.id})

    assert result["market_fit"] == 100.0
    assert {skill["name"] for skill in result["matched_skills"]} == {"Python", "SQL"}
    assert any(skill["name"] == "Django" for skill in result["missing_skills"])


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="pgvector required")
def test_market_fit_uses_semantic_similarity_with_embeddings():
    company = Company.objects.create(name="Semantic Co")
    tensorflow = SkillSet.objects.create(
        name="TensorFlow",
        embedding=vector(0.9, 0.1),
    )
    machine_learning = SkillSet.objects.create(
        name="Machine Learning",
        embedding=vector(0.85, 0.15),
    )
    sql = SkillSet.objects.create(
        name="SQL",
        embedding=vector(0.0, 1.0),
    )
    job = JobPost.objects.create(
        company=company,
        title="ML Engineer",
        source_url="https://example.com/ml",
    )
    JobPostSkill.objects.create(job_post=job, skill_set=machine_learning, score=90)
    JobPostSkill.objects.create(job_post=job, skill_set=sql, score=80)

    result = MarketFitService().calculate({tensorflow.id, sql.id})

    assert result["market_fit"] > 0
    tensorflow_row = next(
        row for row in result["debug_rows"] if row["resume_skill"] == "TensorFlow"
    )
    sql_row = next(row for row in result["debug_rows"] if row["resume_skill"] == "SQL")
    assert tensorflow_row["best_match"] == "Machine Learning"
    assert tensorflow_row["similarity"] > 0.8
    assert sql_row["best_match"] == "SQL"
    assert sql_row["similarity"] == 1.0
