import pytest

from apps.imports.models import PipelineLog
from apps.imports.services import CanonicalJobPayload, SkillAttachService
from apps.skills.models import (
    ApplicationSkill,
    JobPostSkill,
    SkillAttachmentSource,
    SkillSet,
)
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
def test_score_is_computed_from_canonical_payload():
    python = SkillSet.objects.create(name="Python")
    sql = SkillSet.objects.create(name="SQL")
    payload = _canonical_payload_dict()
    mapped = SkillMappingResult(
        matched=[
            MappedSkill(name="Python", skillset_id=python.id, created=False),
            MappedSkill(name="SQL", skillset_id=sql.id, created=False),
        ],
        unmapped=[],
    )
    verified = SkillVerificationResult(
        verified_skills=[
            VerifiedSkill(name="Python", reason="supported by requirements"),
            VerifiedSkill(name="SQL", reason="weak support"),
        ],
        rejected_skills=[],
    )

    result = SkillScoringService().score_canonical_payload(
        canonical_job_payload=payload,
        mapped_skills=mapped,
        verified_skills=verified,
    )

    assert result.as_dict()["metadata"] == {
        "scorer": "deterministic_evidence_v1",
        "source_job_identifier": "job-8",
    }
    scores = {skill.name: skill.score for skill in result.scored_skills}
    assert scores["Python"] > scores["SQL"]
    assert "requirements match" in result.scored_skills[0].reasons


def test_score_rejects_source_specific_payload():
    with pytest.raises(ValueError, match="canonical job payload fields only"):
        SkillScoringService().score_canonical_payload(
            canonical_job_payload={
                "jobTitle": "Python Backend Engineer",
                "companyName": "OpenAI",
                "jobUrl": "https://www.linkedin.com/jobs/view/8",
            },
            mapped_skills=[],
        )


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
    assert link.source_type == SkillAttachmentSource.OLLAMA_PIPELINE
    assert link.created_at is not None
    assert link.updated_at is not None
    assert link.extraction_metadata == {
        "pipeline": "test",
        "skill_name": "Python",
        "reasons": ["title match", "requirements match"],
    }
    assert list(job.skill_links.values_list("skill_set_id", flat=True)) == [skillset.id]
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
    assert link.source_type == SkillAttachmentSource.OLLAMA_PIPELINE
    assert link.created_at is not None
    assert link.updated_at is not None
    assert list(application.skill_links.values_list("skill_set_id", flat=True)) == [
        skillset.id
    ]


@pytest.mark.django_db
def test_duplicate_skills_are_not_attached_twice(job):
    skillset = SkillSet.objects.create(name="Python")
    service = SkillAttachService()
    first = [{"name": "Python", "skillset_id": skillset.id, "score": 90, "reasons": []}]
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


@pytest.mark.django_db
def test_canonical_payload_skills_are_scored_and_attached_to_jobpost(job):
    skillset = SkillSet.objects.create(name="Python")
    service = SkillAttachService()
    payload = CanonicalJobPayload(**_canonical_payload_dict())
    mapped = SkillMappingResult(
        matched=[MappedSkill(name="Python", skillset_id=skillset.id, created=False)],
        unmapped=[],
    )
    verified = SkillVerificationResult(
        verified_skills=[
            VerifiedSkill(name="Python", reason="supported by requirements")
        ],
        rejected_skills=[],
    )

    result = service.score_and_attach_job_post_from_payload(
        job_post=job,
        canonical_job_payload=payload,
        mapped_skills=mapped,
        verified_skills=verified,
        extraction_metadata={"pipeline": "canonical-test"},
    )

    link = JobPostSkill.objects.get(job_post=job, skill_set=skillset)
    assert result["attachment"]["attached_count"] == 1
    assert result["attachment"]["created_count"] == 1
    assert result["scoring"]["scored_skills"][0]["score"] >= 90
    assert link.score == result["scoring"]["scored_skills"][0]["score"]
    assert link.extraction_metadata["pipeline"] == "canonical-test"
    assert link.extraction_metadata["external_id"] == "job-8"
    assert job.tags == ""


@pytest.mark.django_db
def test_canonical_payload_skills_are_scored_and_attached_to_application(application):
    skillset = SkillSet.objects.create(name="Python")
    service = SkillAttachService()
    mapped = SkillMappingResult(
        matched=[MappedSkill(name="Python", skillset_id=skillset.id, created=False)],
        unmapped=[],
    )
    verified = SkillVerificationResult(
        verified_skills=[
            VerifiedSkill(name="Python", reason="supported by requirements")
        ],
        rejected_skills=[],
    )

    result = service.score_and_attach_application_from_payload(
        application=application,
        canonical_job_payload=_canonical_payload_dict(),
        mapped_skills=mapped,
        verified_skills=verified,
    )

    link = ApplicationSkill.objects.get(application=application, skill_set=skillset)
    assert result["attachment"]["attached_count"] == 1
    assert result["attachment"]["created_count"] == 1
    assert link.score == result["scoring"]["scored_skills"][0]["score"]
    assert list(application.skill_links.values_list("skill_set_id", flat=True)) == [
        skillset.id
    ]


@pytest.mark.django_db
def test_attach_service_rejects_source_specific_payload(job):
    with pytest.raises(ValueError, match="canonical job payload fields only"):
        SkillAttachService().score_and_attach_job_post_from_payload(
            job_post=job,
            canonical_job_payload={
                "jobTitle": "Python Backend Engineer",
                "companyName": "OpenAI",
                "jobUrl": "https://www.linkedin.com/jobs/view/8",
            },
            mapped_skills=[],
        )


@pytest.mark.django_db
def test_canonical_scoring_and_attachment_are_logged(job):
    skillset = SkillSet.objects.create(name="Python")
    mapped = SkillMappingResult(
        matched=[MappedSkill(name="Python", skillset_id=skillset.id, created=False)],
        unmapped=[],
    )

    SkillAttachService().score_and_attach_job_post_from_payload(
        job_post=job,
        canonical_job_payload=_canonical_payload_dict(),
        mapped_skills=mapped,
        verified_skills=[
            VerifiedSkill(name="Python", reason="supported by requirements")
        ],
    )

    scoring_logs = PipelineLog.objects.filter(step_name="skill_scoring").order_by(
        "created_at"
    )
    attach_logs = PipelineLog.objects.filter(step_name="skill_attach").order_by(
        "created_at"
    )
    assert [log.status for log in scoring_logs] == [
        PipelineLog.StatusChoices.STARTED,
        PipelineLog.StatusChoices.SUCCESS,
    ]
    assert scoring_logs[0].metadata["canonical_payload"] is True
    assert scoring_logs[1].metadata["scored_count"] == 1
    assert [log.status for log in attach_logs] == [
        PipelineLog.StatusChoices.STARTED,
        PipelineLog.StatusChoices.SUCCESS,
    ]
    assert attach_logs[1].metadata["attached_count"] == 1


def _canonical_payload_dict():
    return {
        "source": "greenhouse",
        "source_url": "https://boards.greenhouse.io/openai/jobs/job-8",
        "external_id": "job-8",
        "company_name": "OpenAI",
        "title": "Python Backend Engineer",
        "job_type": "FULL_TIME",
        "employment_type": "FULL_TIME",
        "remote_type": "Remote",
        "location": "Remote",
        "description": "Build Python APIs and services.",
        "sections": {
            "requirements": "Python and Django experience required.",
            "preferred_qualifications": "SQL experience is helpful.",
        },
        "posted_at": "2026-06-11",
        "metadata": {},
    }
