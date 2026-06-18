import pytest

from apps.imports.models import PipelineLog
from apps.imports.services import CanonicalJobPayload, SkillMappingService
from apps.skills.models import SkillKeyword, SkillSet
from apps.skills.services import (
    MappedKeyword,
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
        "keywords": [
            {
                "skillset_id": skillset.id,
                "keyword_id": skillset.keywords.get(normalized_text="python").id,
                "raw_text": "Python",
                "normalized_text": "python",
                "source": SkillKeyword.SourceChoices.CANONICAL,
                "status": SkillKeyword.StatusChoices.ACTIVE,
            }
        ],
        "metadata": {
            "mapper": "skillset",
            "auto_create": False,
            "source_job_identifier": "job-1",
            "model": "llama3.1",
            "created_skillset_ids": [],
            "created_skillset_names": [],
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
def test_normalized_skill_keyword_lookup_resolves_existing_skillset():
    skillset = SkillSet.objects.create(name="Amazon Web Services")
    keyword = SkillKeyword.ensure_for_skillset(
        skill_set=skillset,
        raw_text="AWS",
        source=SkillKeyword.SourceChoices.MANUAL,
    )
    mapper = SkillSetMapper()

    result = mapper.map_verified_skills([{"name": " aws "}])

    assert [skill.as_dict() for skill in result.matched] == [
        {
            "name": "Amazon Web Services",
            "skillset_id": skillset.id,
            "created": False,
        }
    ]
    assert [keyword_result.as_dict() for keyword_result in result.keywords] == [
        {
            "skillset_id": skillset.id,
            "keyword_id": keyword.id,
            "raw_text": "AWS",
            "normalized_text": "aws",
            "source": SkillKeyword.SourceChoices.MANUAL,
            "status": SkillKeyword.StatusChoices.ACTIVE,
        }
    ]


@pytest.mark.django_db
def test_parenthetical_compound_skill_maps_to_separate_skillsets():
    sql = SkillSet.objects.create(name="SQL")
    mysql = SkillSet.objects.create(name="MySQL")
    mapper = SkillSetMapper()

    result = mapper.map_verified_skills(
        [
            {"name": "SQL (MySQL)"},
            {"name": "sql"},
        ]
    )

    assert [skill.as_dict() for skill in result.matched] == [
        {
            "name": "SQL",
            "skillset_id": sql.id,
            "created": False,
        },
        {
            "name": "MySQL",
            "skillset_id": mysql.id,
            "created": False,
        },
    ]
    assert result.unmapped == []


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
    keyword = created.keywords.get(normalized_text="machine learning")
    assert created.name == "Machine Learning"
    assert created.auto_created is True
    assert [skill.as_dict() for skill in result.matched] == [
        {
            "name": "Machine Learning",
            "skillset_id": created.id,
            "created": True,
        }
    ]
    assert [item.as_dict() for item in result.keywords] == [
        {
            "skillset_id": created.id,
            "keyword_id": keyword.id,
            "raw_text": "Machine Learning",
            "normalized_text": "machine learning",
            "source": SkillKeyword.SourceChoices.CANONICAL,
            "status": SkillKeyword.StatusChoices.ACTIVE,
        }
    ]
    assert result.unmapped == []
    assert result.metadata["created_skillset_ids"] == [created.id]
    assert result.metadata["created_skillset_names"] == ["Machine Learning"]


@pytest.mark.django_db
def test_mapping_service_can_be_imported_and_invoked_with_canonical_dict():
    skillset = SkillSet.objects.create(name="Django")
    service = SkillMappingService()
    verification_result = SkillVerificationResult(
        verified_skills=[VerifiedSkill(name="Django", reason="supported")],
        rejected_skills=[RejectedSkill(name="Communication", reason="generic")],
        metadata={"model": "llama3.1", "source_job_identifier": "job-7"},
    )

    result = service.map_from_job_data(
        _canonical_payload_dict(),
        verification_result,
    )

    assert isinstance(result, SkillMappingResult)
    assert [skill.skillset_id for skill in result.matched] == [skillset.id]
    assert all(isinstance(keyword, MappedKeyword) for keyword in result.keywords)
    assert [skill.as_dict() for skill in result.unmapped] == [
        {"name": "Communication", "reason": "rejected during verification"}
    ]
    assert result.metadata["source_job_identifier"] == "job-7"
    assert result.metadata["model"] == "llama3.1"


@pytest.mark.django_db
def test_mapping_service_accepts_canonical_payload_dataclass():
    skillset = SkillSet.objects.create(name="Django")
    service = SkillMappingService()
    verification_result = SkillVerificationResult(
        verified_skills=[VerifiedSkill(name="Django", reason="supported")],
        rejected_skills=[],
        metadata={"model": "llama3.1", "source_job_identifier": "job-7"},
    )

    result = service.map_from_job_data(
        CanonicalJobPayload(**_canonical_payload_dict()),
        verification_result,
    )

    assert [skill.skillset_id for skill in result.matched] == [skillset.id]


def test_mapping_service_rejects_source_specific_payload():
    service = SkillMappingService()

    with pytest.raises(ValueError, match="canonical job payload fields only"):
        service.map_from_job_data(
            {
                "jobTitle": "Backend Engineer",
                "companyName": "OpenAI",
                "jobUrl": "https://www.linkedin.com/jobs/view/123",
                "jobPostingId": "123",
            },
            SkillVerificationResult(verified_skills=[], rejected_skills=[]),
        )


def test_mapping_service_rejects_non_canonical_legacy_payload():
    service = SkillMappingService()

    with pytest.raises(ValueError, match="canonical job payload fields only"):
        service.map_from_job_data(
            {
                "external_id": "job-7",
                "title": "Backend Engineer",
                "raw_text": "Python and Django.",
            },
            SkillVerificationResult(verified_skills=[], rejected_skills=[]),
        )


@pytest.mark.django_db
def test_mapping_service_logs_model_counts_and_created_skillsets():
    service = SkillMappingService(mapper=SkillSetMapper(auto_create=True))
    verification_result = SkillVerificationResult(
        verified_skills=[VerifiedSkill(name="Rust", reason="supported")],
        rejected_skills=[RejectedSkill(name="Communication", reason="generic")],
        metadata={"model": "llama3.1", "source_job_identifier": "job-7"},
    )

    result = service.map_from_job_data(_canonical_payload_dict(), verification_result)

    logs = PipelineLog.objects.filter(step_name="skillset_mapping").order_by(
        "created_at"
    )
    assert [log.status for log in logs] == [
        PipelineLog.StatusChoices.STARTED,
        PipelineLog.StatusChoices.SUCCESS,
    ]
    assert logs[0].metadata["model"] == "llama3.1"
    assert logs[1].metadata["matched_count"] == 1
    assert logs[1].metadata["unmapped_count"] == 1
    assert logs[1].metadata["created_count"] == 1
    assert logs[1].metadata["created_skillset_ids"] == [result.matched[0].skillset_id]


def _canonical_payload_dict():
    return {
        "source": "greenhouse",
        "source_url": "https://boards.greenhouse.io/openai/jobs/job-7",
        "external_id": "job-7",
        "company_name": "OpenAI",
        "title": "Backend Engineer",
        "job_type": "FULL_TIME",
        "employment_type": "FULL_TIME",
        "remote_type": "Remote",
        "location": "Remote",
        "description": "Build Django services.",
        "sections": {
            "requirements": "Python and Django.",
        },
        "posted_at": "2026-06-11",
        "metadata": {},
    }
