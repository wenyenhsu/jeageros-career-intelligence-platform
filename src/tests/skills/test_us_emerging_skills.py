import pytest

from apps.skills.models import SkillAlias, SkillCategory, SkillSet
from apps.skills.services import normalize_skill_name
from apps.skills.services.us_emerging_skills import US_EMERGING_SKILLS, UsEmergingSkillsSeeder
from apps.skills.services.us_emerging_skills.seed_data import EmergingSkillSeed


@pytest.mark.django_db
def test_seed_us_emerging_skills_creates_missing_records():
    stats = UsEmergingSkillsSeeder().seed()
    assert stats.skills_created > 0
    assert SkillSet.objects.filter(name="LangChain").exists()
    assert SkillSet.objects.filter(name="Terraform").exists()


@pytest.mark.django_db
def test_seed_us_emerging_skills_is_idempotent():
    UsEmergingSkillsSeeder().seed()
    stats_second = UsEmergingSkillsSeeder().seed()
    assert stats_second.skills_created == 0


@pytest.mark.django_db
def test_seed_us_emerging_skills_assigns_categories():
    UsEmergingSkillsSeeder().seed()

    langchain = SkillSet.objects.get(name="LangChain")
    ai_ml = SkillCategory.objects.get(name="AI / ML")
    assert langchain.categories.filter(id=ai_ml.id).exists()

    snowflake = SkillSet.objects.get(name="Snowflake")
    data_eng = SkillCategory.objects.get(name="Data Engineering")
    assert snowflake.categories.filter(id=data_eng.id).exists()

    terraform = SkillSet.objects.get(name="Terraform")
    cloud = SkillCategory.objects.get(name="Cloud Computing")
    assert terraform.categories.filter(id=cloud.id).exists()

    prometheus = SkillSet.objects.get(name="Prometheus")
    devops = SkillCategory.objects.get(name="DevOps")
    assert prometheus.categories.filter(id=devops.id).exists()


@pytest.mark.django_db
def test_seed_us_emerging_skills_creates_aliases_for_rag():
    UsEmergingSkillsSeeder().seed()

    rag = SkillSet.objects.get(name="RAG")
    assert SkillAlias.objects.filter(
        alias__iexact="Retrieval-Augmented Generation",
        skill=rag,
    ).exists()
    assert normalize_skill_name("Retrieval-Augmented Generation") == rag


@pytest.mark.django_db
def test_seed_us_emerging_skills_does_not_duplicate_existing_skillset():
    existing = SkillSet.objects.create(name="Apache Spark")
    stats = UsEmergingSkillsSeeder().seed()

    assert SkillSet.objects.filter(normalized_name=existing.normalized_name).count() == 1
    assert stats.skills_created >= 0

    spark = SkillSet.objects.get(name="Apache Spark")
    data_eng = SkillCategory.objects.get(name="Data Engineering")
    assert spark.categories.filter(id=data_eng.id).exists()


@pytest.mark.django_db
def test_seed_us_emerging_skills_iac_alias():
    UsEmergingSkillsSeeder().seed()

    iac = SkillSet.objects.get(name="Infrastructure as Code")
    assert SkillAlias.objects.filter(alias__iexact="IaC", skill=iac).exists()


@pytest.mark.django_db
def test_custom_seed_subset():
    subset = [
        EmergingSkillSeed("Test Emerging Skill", "DevOps", aliases=["TES Alias"]),
    ]
    stats = UsEmergingSkillsSeeder().seed(skills=subset)
    assert stats.skills_created == 1
    assert SkillAlias.objects.filter(alias="TES Alias").exists()
