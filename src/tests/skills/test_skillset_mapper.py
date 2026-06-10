import pytest

from apps.imports.services import SkillMappingService
from apps.skills.models import SkillSet
from apps.skills.services import (
    RejectedSkill,
    SkillMappingResult,
    SkillSetMapper,
    SkillVerificationResult,
    VerifiedSkill,
)


@pytest.mark.django_db
def test_verified_skill_maps_to_existing_skillset():
    skillset = SkillSet.objects.create(name="Python")
    mapper = SkillSetMapper()

    result = mapper.map_verified_skills(
        [VerifiedSkill(name=" python ", reason="supported")],
        source_job_identifier="job-1",
        model_name="llama3.1",
    )

    assert result.as_dict() == {
        "matched": [
            {
                "name": "Python",
                "skillset_id": skillset.id,
                "created": False,
            }
        ],
        "unmapped": [],
        "metadata": {
            "mapper": "skillset",
            "auto_create": False,
            "source_job_identifier": "job-1",
            "model": "llama3.1",
        },
    }


@pytest.mark.django_db
def test_duplicate_verified_skills_are_removed():
    skillset = SkillSet.objects.create(name="Python")
    mapper = SkillSetMapper()

    result = mapper.map_verified_skills(
        [
            {"name": "Python"},
            {"name": " python "},
            VerifiedSkill(name="PYTHON", reason="duplicate"),
        ]
    )

    assert [skill.skillset_id for skill in result.matched] == [skillset.id]
    assert result.unmapped == []


@pytest.mark.django_db
def test_aliases_resolve_to_existing_skillset():
    skillset = SkillSet.objects.create(
        name="JavaScript",
        aliases=["JS", " ECMAScript "],
    )
    mapper = SkillSetMapper()

    result = mapper.map_verified_skills([{"name": " js "}])

    assert [skill.as_dict() for skill in result.matched] == [
        {
            "name": "JavaScript",
            "skillset_id": skillset.id,
            "created": False,
        }
    ]
    skillset.refresh_from_db()
    assert skillset.aliases == ["JS", "ECMAScript"]


@pytest.mark.django_db
def test_unmapped_skills_are_returned_cleanly_when_auto_create_is_disabled():
    mapper = SkillSetMapper(auto_create=False)

    result = mapper.map_verified_skills(
        verified_skills=[{"name": "Rust"}],
        rejected_skills=[RejectedSkill(name="Communication", reason="generic")],
    )

    assert result.as_dict()["matched"] == []
    assert result.as_dict()["unmapped"] == [
        {"name": "Rust", "reason": "no matching SkillSet"},
        {"name": "Communication", "reason": "rejected during verification"},
    ]
    assert SkillSet.objects.count() == 0


@pytest.mark.django_db
def test_auto_create_path_creates_missing_skillset():
    mapper = SkillSetMapper(auto_create=True)

    result = mapper.map_verified_skills([{"name": "  machine   learning "}])

    created = SkillSet.objects.get(normalized_name="machine learning")
    assert created.name == "Machine Learning"
    assert created.auto_created is True
    assert [skill.as_dict() for skill in result.matched] == [
        {
            "name": "Machine Learning",
            "skillset_id": created.id,
            "created": True,
        }
    ]
    assert result.unmapped == []


@pytest.mark.django_db
def test_mapping_service_can_be_imported_and_invoked():
    skillset = SkillSet.objects.create(name="Django")
    service = SkillMappingService()
    verification_result = SkillVerificationResult(
        verified_skills=[VerifiedSkill(name="Django", reason="supported")],
        rejected_skills=[RejectedSkill(name="Communication", reason="generic")],
        metadata={"model": "llama3.1", "source_job_identifier": "job-7"},
    )

    result = service.map_from_job_data(
        {
            "external_id": "job-7",
            "title": "Backend Engineer",
        },
        verification_result,
    )

    assert isinstance(result, SkillMappingResult)
    assert [skill.skillset_id for skill in result.matched] == [skillset.id]
    assert [skill.as_dict() for skill in result.unmapped] == [
        {"name": "Communication", "reason": "rejected during verification"}
    ]
    assert result.metadata["source_job_identifier"] == "job-7"
    assert result.metadata["model"] == "llama3.1"
