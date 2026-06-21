import pytest

from apps.analytics.services.resume_gap_service import ResumeGapService
from apps.analytics.services.resume_profile_service import ResumeProfileService
from apps.analytics.services.skill_demand_service import SkillDemandService
from apps.companies.models import Company
from apps.jobs.models import JobPost
from apps.skills.models import (
    BusinessCategory,
    CategoryMappingSource,
    JobPostSkill,
    MarketCategory,
    SkillAlias,
    SkillBusinessCategory,
    SkillCategory,
    SkillMarketCategory,
    SkillSet,
)
from apps.skills.services.skill_intelligence.business_category_service import (
    BusinessCategoryService,
)
from apps.skills.services.skill_intelligence.market_category_service import (
    MarketCategoryService,
)
from apps.skills.services.skill_intelligence.skill_normalization_validator import (
    SkillNormalizationValidator,
)


@pytest.mark.django_db
def test_seed_business_taxonomy_assigns_python_to_software_engineering():
    python = SkillSet.objects.create(name="Python")
    stats = BusinessCategoryService().seed_taxonomy()

    assert stats.categories_created >= 1
    mapping = SkillBusinessCategory.objects.get(
        skill=python,
        category__slug="software-engineering",
    )
    assert mapping.is_approved is True
    assert mapping.source == CategoryMappingSource.SEED


@pytest.mark.django_db
def test_seed_market_taxonomy_assigns_rag_to_generative_ai():
    rag = SkillSet.objects.create(name="RAG")
    stats = MarketCategoryService().seed_taxonomy()

    assert stats.categories_created >= 1
    mapping = SkillMarketCategory.objects.get(
        skill=rag,
        category__slug="generative-ai",
    )
    assert mapping.is_approved is True


@pytest.mark.django_db
def test_build_resume_profile_returns_percentages():
    python = SkillSet.objects.create(name="Python")
    rag = SkillSet.objects.create(name="RAG")
    ai_ml = BusinessCategory.objects.create(name="AI / ML", slug="ai-ml")
    software = BusinessCategory.objects.create(
        name="Software Engineering",
        slug="software-engineering",
    )
    generative = MarketCategory.objects.create(
        name="Generative AI",
        slug="generative-ai",
    )
    SkillBusinessCategory.objects.create(
        skill=python,
        category=software,
        source=CategoryMappingSource.MANUAL,
        is_approved=True,
    )
    SkillBusinessCategory.objects.create(
        skill=rag,
        category=ai_ml,
        source=CategoryMappingSource.MANUAL,
        is_approved=True,
    )
    SkillMarketCategory.objects.create(
        skill=rag,
        category=generative,
        source=CategoryMappingSource.MANUAL,
        is_approved=True,
    )

    profile = ResumeProfileService().build_resume_profile([python.id, rag.id])

    assert profile["skill_count"] == 2
    assert profile["business_categories"]["Software Engineering"] == 50
    assert profile["business_categories"]["AI / ML"] == 50
    assert profile["market_categories"]["Generative AI"] == 100


@pytest.mark.django_db
def test_build_market_profile_includes_business_and_market_layers():
    company = Company.objects.create(name="Intel Co")
    python = SkillSet.objects.create(name="Python")
    rag = SkillSet.objects.create(name="RAG")
    ai_ml = BusinessCategory.objects.create(name="AI / ML", slug="ai-ml")
    generative = MarketCategory.objects.create(
        name="Generative AI",
        slug="generative-ai",
    )
    SkillBusinessCategory.objects.create(
        skill=rag,
        category=ai_ml,
        source=CategoryMappingSource.MANUAL,
        is_approved=True,
    )
    SkillMarketCategory.objects.create(
        skill=rag,
        category=generative,
        source=CategoryMappingSource.MANUAL,
        is_approved=True,
    )
    job = JobPost.objects.create(
        company=company,
        title="AI Engineer",
        source_url="https://example.com/ai",
    )
    JobPostSkill.objects.create(job_post=job, skill_set=python, score=80)
    JobPostSkill.objects.create(job_post=job, skill_set=rag, score=90)
    SkillDemandService().update_skill_demand()

    profile = SkillDemandService().build_market_profile(limit=5)

    assert profile["business_categories"]["AI / ML"] == 1
    assert profile["market_categories"]["Generative AI"] == 1
    assert profile["top_skills"]
    assert profile["top_business_categories"]
    assert profile["top_market_categories"]


@pytest.mark.django_db
def test_resume_gap_includes_layer_missing_categories():
    company = Company.objects.create(name="Gap Co")
    python = SkillSet.objects.create(name="Python")
    rag = SkillSet.objects.create(name="RAG")
    ai_ml = SkillCategory.objects.create(name="AI / ML")
    business = BusinessCategory.objects.create(name="AI / ML", slug="ai-ml")
    market = MarketCategory.objects.create(name="Generative AI", slug="generative-ai")
    rag.categories.add(ai_ml)
    SkillBusinessCategory.objects.create(
        skill=rag,
        category=business,
        source=CategoryMappingSource.MANUAL,
        is_approved=True,
    )
    SkillMarketCategory.objects.create(
        skill=rag,
        category=market,
        source=CategoryMappingSource.MANUAL,
        is_approved=True,
    )
    job = JobPost.objects.create(
        company=company,
        title="Gap Job",
        source_url="https://example.com/gap",
    )
    JobPostSkill.objects.create(job_post=job, skill_set=rag, score=90)
    SkillDemandService().update_skill_demand()

    gap = ResumeGapService().analyze_resume_gap({python.id}, limit=5)

    assert gap["resume_profile"]["skill_count"] == 1
    assert any(
        item["category"] == "AI / ML" for item in gap["missing_business_categories"]
    )
    assert any(
        item["category"] == "Generative AI"
        for item in gap["missing_market_categories"]
    )


@pytest.mark.django_db
def test_validate_skill_normalization_reports_unresolved_alias():
    python = SkillSet.objects.create(name="Python")
    javascript = SkillSet.objects.create(name="JavaScript")
    SkillAlias.objects.create(alias="Python", skill=javascript)

    report = SkillNormalizationValidator().validate()
    assert any("Python" in entry for entry in report.unresolved_aliases)
    assert report.duplicate_canonical_skills
