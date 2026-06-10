import pytest

from apps.imports.services import SkillAttachService
from apps.skills.models import ApplicationSkill, JobPostSkill, SkillSet
from apps.skills.services import (
    MappedSkill,
    ScoredSkill,
    SkillMappingResult,
    SkillScoringResult,
    SkillScoringService,
    SkillVerificationResult,
    VerifiedSkill,
)


@pytest.mark.django_db
def test_score_is_computed_deterministically():
    python = SkillSet.objects.create(name="Python")
    sql = SkillSet.objects.create(name="SQL")
    mapped = SkillMappingResult(
        matched=[
            MappedSkill(name="Python", skillset_id=python.id, created=False),
            MappedSkill(name="SQL", skillset_id=sql.id, created=False),
        ],
        unmapped=[],
    )
    verified = SkillVerificationResult(
        verified_skills=[
            VerifiedSkill(name="Python", reason="explicitly required"),
            VerifiedSkill(name="SQL", reason="verified by model"),
        ],
        rejected_skills=[],
    )
    scorer = SkillScoringService()

    first = scorer.score_mapped_skills(
        mapped_skills=mapped,
        verified_skills=verified,
        title="Senior Python Engineer",
        description="Build Python services.",
        source_fragments=[
            {"source": "requirements", "text": "Python and Django experience."}
        ],
        source_job_identifier="job-1",
    )
    second = scorer.score_mapped_skills(
        mapped_skills=mapped,
        verified_skills=verified,
        title="Senior Python Engineer",
        description="Build Python services.",
        source_fragments=[
            {"source": "requirements", "text": "Python and Django experience."}
        ],
        source_job_identifier="job-1",
    )

    assert first.as_dict() == second.as_dict()


@pytest.mark.django_db
def test_high_evidence_skills_score_higher_than_weak_ones():
    python = SkillSet.objects.create(name="Python")
    sql = SkillSet.objects.create(name="SQL")
    result = SkillScoringService().score_mapped_skills(
        mapped_skills=[
            MappedSkill(name="Python", skillset_id=python.id, created=False),
            MappedSkill(name="SQL", skillset_id=sql.id, created=False),
        ],
        verified_skills=[
            VerifiedSkill(name="Python", reason="explicitly required"),
            VerifiedSkill(name="SQL", reason="accepted by verifier"),
        ],
        title="Python Backend Engineer",
        description="Build APIs with Python.",
        source_fragments=[
            {"source": "requirements", "text": "Python experience required."}
        ],
    )

    scores = {skill.name: skill.score for skill in result.scored_skills}
    assert scores["Python"] > scores["SQL"]
    assert "title match" in result.scored_skills[0].reasons


@pytest.mark.django_db
def test_skills_are_attached_to_jobpost_correctly(job):
    skillset = SkillSet.objects.create(name="Python")
    service = SkillAttachService()
    scored = SkillScoringResult(
        scored_skills=[
            ScoredSkill(
                name="Python",
                skillset_id=skillset.id,
                score=95,
                reasons=["title match", "requirements match"],
            )
        ]
    )

    result = service.attach_to_job_post(
        job_post=job,
        scored_skills=scored,
        extraction_metadata={"pipeline": "test"},
    )

    link = JobPostSkill.objects.get(job_post=job, skill_set=skillset)
    assert result.attached_count == 1
    assert result.created_count == 1
    assert link.score == 95
    assert link.extraction_metadata == {
        "pipeline": "test",
        "skill_name": "Python",
        "reasons": ["title match", "requirements match"],
    }
    assert list(job.skill_links.values_list("skill_set_id", flat=True)) == [
        skillset.id
    ]
    assert job.tags == ""


@pytest.mark.django_db
def test_skills_are_attached_to_application_correctly(application):
    skillset = SkillSet.objects.create(name="Django")
    service = SkillAttachService()

    result = service.attach_to_application(
        application=application,
        scored_skills=[
            {
                "name": "Django",
                "skillset_id": skillset.id,
                "score": 88,
                "reasons": ["description match"],
            }
        ],
    )

    link = ApplicationSkill.objects.get(application=application, skill_set=skillset)
    assert result.attached_count == 1
    assert result.created_count == 1
    assert link.score == 88
    assert list(application.skill_links.values_list("skill_set_id", flat=True)) == [
        skillset.id
    ]


@pytest.mark.django_db
def test_duplicate_skills_are_not_attached_twice(job):
    skillset = SkillSet.objects.create(name="Python")
    service = SkillAttachService()
    first = [
        {"name": "Python", "skillset_id": skillset.id, "score": 90, "reasons": []}
    ]
    second = [
        {"name": "Python", "skillset_id": skillset.id, "score": 80, "reasons": []},
        {"name": "Python", "skillset_id": skillset.id, "score": 70, "reasons": []},
    ]

    first_result = service.attach_to_job_post(job, first)
    second_result = service.attach_to_job_post(job, second)

    link = JobPostSkill.objects.get(job_post=job, skill_set=skillset)
    assert first_result.created_count == 1
    assert second_result.created_count == 0
    assert second_result.updated_count == 1
    assert JobPostSkill.objects.filter(job_post=job, skill_set=skillset).count() == 1
    assert link.score == 80


@pytest.mark.django_db
def test_attach_service_can_be_imported_and_invoked(job):
    skillset = SkillSet.objects.create(name="Python")
    job.title = "Python Backend Engineer"
    job.description = "Build Python services."
    job.save()
    mapping_result = SkillMappingResult(
        matched=[MappedSkill(name="Python", skillset_id=skillset.id, created=False)],
        unmapped=[],
    )
    verification_result = SkillVerificationResult(
        verified_skills=[VerifiedSkill(name="Python", reason="explicitly listed")],
        rejected_skills=[],
    )

    result = SkillAttachService().score_and_attach_job_post(
        job_post=job,
        mapped_skills=mapping_result,
        verified_skills=verification_result,
        source_fragments=[
            {"source": "requirements", "text": "Python experience required."}
        ],
    )

    assert result["attachment"]["attached_count"] == 1
    assert result["attachment"]["skillset_ids"] == [skillset.id]
    assert result["scoring"]["scored_skills"][0]["score"] >= 90
    assert JobPostSkill.objects.filter(job_post=job, skill_set=skillset).exists()
