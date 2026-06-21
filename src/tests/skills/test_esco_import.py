from pathlib import Path

import pytest

from apps.skills.models import SkillAlias, SkillCategory, SkillRelationship, SkillSet
from apps.skills.services.esco_import import (
    EscoAliasImporter,
    EscoRelationshipImporter,
    EscoSkillImporter,
    EscoTaxonomyImporter,
    SkillKnowledgeBaseValidator,
)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "esco"


@pytest.mark.django_db
def test_import_esco_skills_is_idempotent():
    stats_first = EscoSkillImporter(FIXTURE_DIR).import_skills()
    assert stats_first.created == 8
    assert stats_first.updated == 0

    stats_second = EscoSkillImporter(FIXTURE_DIR).import_skills()
    assert stats_second.created == 0
    assert stats_second.skipped == 8
    assert SkillSet.objects.count() == 8


@pytest.mark.django_db
def test_import_esco_aliases_creates_skill_aliases():
    EscoSkillImporter(FIXTURE_DIR).import_skills()
    stats = EscoAliasImporter(FIXTURE_DIR).import_aliases()

    assert stats.created >= 5
    assert SkillAlias.objects.filter(alias__iexact="Postgres").exists()
    assert SkillAlias.objects.filter(alias__iexact="DRF").exists()

    postgres = SkillSet.objects.get(name="PostgreSQL")
    assert SkillAlias.objects.get(alias__iexact="Postgres").skill == postgres


@pytest.mark.django_db
def test_import_esco_taxonomy_builds_category_hierarchy():
    EscoSkillImporter(FIXTURE_DIR).import_skills()
    stats = EscoTaxonomyImporter(FIXTURE_DIR).import_taxonomy()

    assert stats.categories_created == 4
    assert SkillCategory.objects.count() == 4

    programming = SkillCategory.objects.get(name="Programming Languages")
    python = SkillSet.objects.get(name="Python")
    assert python.categories.filter(id=programming.id).exists()

    ai_ml = SkillCategory.objects.get(name="AI / ML")
    programming.refresh_from_db()
    assert programming.parent_id == ai_ml.id


@pytest.mark.django_db
def test_import_esco_relationships_creates_skill_links():
    EscoSkillImporter(FIXTURE_DIR).import_skills()
    stats = EscoRelationshipImporter(FIXTURE_DIR).import_relationships()

    assert stats.created >= 2
    nlp = SkillSet.objects.get(name="NLP")
    ml = SkillSet.objects.get(name="Machine Learning")
    assert SkillRelationship.objects.filter(
        source_skill=nlp,
        target_skill=ml,
        relationship_type=SkillRelationship.RelationshipType.RELATED,
    ).exists()


@pytest.mark.django_db
def test_validate_skill_knowledge_base_reports_counts():
    EscoSkillImporter(FIXTURE_DIR).import_skills()
    EscoAliasImporter(FIXTURE_DIR).import_aliases()
    EscoTaxonomyImporter(FIXTURE_DIR).import_taxonomy()
    EscoRelationshipImporter(FIXTURE_DIR).import_relationships()

    report = SkillKnowledgeBaseValidator().validate()
    assert report.skillset_count == 8
    assert report.skill_alias_count >= 5
    assert report.skill_category_count == 4
    assert report.skill_relationship_count >= 2
    assert report.duplicate_aliases == []
