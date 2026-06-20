import pytest

from apps.skills.models import SkillAlias, SkillSet
from apps.skills.services import normalize_skill_name


@pytest.mark.django_db
def test_alias_exact_match_resolves_to_canonical_skill():
    postgresql = SkillSet.objects.create(name="PostgreSQL")
    SkillAlias.objects.create(alias="Postgres", skill=postgresql)

    assert normalize_skill_name("Postgres") == postgresql


@pytest.mark.django_db
def test_alias_match_is_case_insensitive():
    drf = SkillSet.objects.create(name="Django REST Framework")
    SkillAlias.objects.create(alias="DRF", skill=drf)

    assert normalize_skill_name("drf") == drf


@pytest.mark.django_db
def test_exact_skillset_name_match_resolves_without_alias():
    aws = SkillSet.objects.create(name="AWS")

    assert normalize_skill_name("AWS") == aws


@pytest.mark.django_db
def test_alias_match_takes_priority_over_skillset_name_match():
    aws = SkillSet.objects.create(name="AWS")
    SkillSet.objects.create(name="AWS Lambda")
    SkillAlias.objects.create(alias="AWS Lambda", skill=aws)

    assert normalize_skill_name("AWS Lambda") == aws


@pytest.mark.django_db
def test_unresolved_skill_returns_none():
    SkillSet.objects.create(name="Python")

    assert normalize_skill_name("Unknown Skill") is None
