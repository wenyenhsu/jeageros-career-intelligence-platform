import pytest

from apps.skills.models import SkillAlias, SkillSet
from apps.skills.services.skillset_mapper import SkillSetMapper


@pytest.mark.django_db
def test_skillset_mapper_resolves_skill_alias_records():
    postgresql = SkillSet.objects.create(name="PostgreSQL")
    SkillAlias.objects.create(alias="Postgres", skill=postgresql)

    result = SkillSetMapper().map_verified_skills(["Postgres"])
    assert len(result.matched) == 1
    assert result.matched[0].skillset_id == postgresql.id
