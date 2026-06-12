import pytest

from apps.imports.models import PipelineLog
from apps.imports.services import CanonicalJobPayload, SkillVerificationService
from apps.skills.services import (
    CandidateSkill,
    OllamaVerifier,
    SkillExtractionResult,
    SkillVerificationError,
)


def test_valid_verification_response_is_parsed_correctly():
    verifier = OllamaVerifier(model="llama3.1", max_skills=5)

    result = verifier.parse_response(
        {
            "verified_skills": [
                {
                    "name": " python ",
                    "status": "accepted",
                    "reason": "supported by requirements section",
                }
            ],
            "rejected_skills": [
                {
                    "name": " communication ",
                    "reason": "too generic / not a technical skill",
                }
            ],
        },
        source_job_identifier="job-123",
    )

    assert result.as_dict() == {
        "verified_skills": [
            {
                "name": "Python",
                "status": "accepted",
                "reason": "supported by requirements section",
            }
        ],
        "rejected_skills": [
            {
                "name": "Communication",
                "reason": "too generic / not a technical skill",
            }
        ],
        "metadata": {
            "model": "llama3.1",
            "verifier": "ollama",
            "max_skills": 5,
            "source_job_identifier": "job-123",
        },
    }


def test_malformed_json_is_rejected():
    verifier = OllamaVerifier()

    with pytest.raises(SkillVerificationError, match="malformed JSON"):
        verifier.parse_response('{"verified_skills": [')


def test_accepted_and_rejected_separation_works():
    verifier = OllamaVerifier(max_skills=5)

    result = verifier.parse_response(
        {
            "verified_skills": [
                {
                    "name": "Django",
                    "status": "accepted",
                    "reason": "explicitly listed",
                }
            ],
            "rejected_skills": [
                {"name": "Communication", "reason": "not a technical skill"}
            ],
        }
    )

    assert [skill.name for skill in result.verified_skills] == ["Django"]
    assert [skill.name for skill in result.rejected_skills] == ["Communication"]


def test_duplicate_verification_entries_are_removed_and_limited():
    verifier = OllamaVerifier(max_skills=3)

    result = verifier.parse_response(
        {
            "verified_skills": [
                {"name": "Python", "reason": "required"},
                {"name": " python ", "reason": "duplicate"},
                {"name": "Django", "reason": "framework listed"},
            ],
            "rejected_skills": [
                {"name": "Python", "reason": "accepted skill should win"},
                {"name": "Communication", "reason": "generic"},
                {"name": "Leadership", "reason": "over limit"},
            ],
        }
    )

    assert [skill.name for skill in result.verified_skills] == ["Python", "Django"]
    assert [skill.name for skill in result.rejected_skills] == ["Communication"]


def test_empty_verification_output_is_handled():
    verifier = OllamaVerifier()

    with pytest.raises(SkillVerificationError, match="usable results"):
        verifier.parse_response({"verified_skills": [], "rejected_skills": []})


def test_verifier_verify_uses_ollama_response(monkeypatch):
    verifier = OllamaVerifier(model="llama3.1", max_skills=5)

    def fake_call(prompt):
        assert "Candidate skills JSON" in prompt
        assert "TypeScript" in prompt
        assert "Build React features" in prompt
        assert "requirements" in prompt
        return {
            "verified_skills": [
                {"name": "TypeScript", "reason": "listed in requirements"},
                {"name": "React", "reason": "listed in requirements"},
            ],
            "rejected_skills": [{"name": "Communication", "reason": "too generic"}],
        }

    monkeypatch.setattr(verifier, "_call_ollama", fake_call)

    result = verifier.verify(
        title="Frontend Engineer",
        description="Build React features with TypeScript.",
        candidate_skills=[
            {"name": "typescript", "source": "requirements"},
            {"name": "React", "source": "source_fragment"},
            {"name": "Communication", "source": "description"},
        ],
        source_fragments=[{"source": "requirements", "text": "React and TypeScript"}],
        source_job_identifier="frontend-1",
    )

    assert [skill.name for skill in result.verified_skills] == ["TypeScript", "React"]
    assert [skill.name for skill in result.rejected_skills] == ["Communication"]
    assert result.metadata["source_job_identifier"] == "frontend-1"


def test_ollama_failure_is_reported_as_verification_error(monkeypatch):
    verifier = OllamaVerifier()

    monkeypatch.setattr(
        verifier,
        "_call_ollama",
        lambda prompt: (_ for _ in ()).throw(SkillVerificationError("Ollama down")),
    )

    with pytest.raises(SkillVerificationError, match="Ollama down"):
        verifier.verify(
            title="Backend Engineer",
            description="Build APIs.",
            candidate_skills=[{"name": "Python"}],
            source_job_identifier="backend-1",
        )


def test_verification_service_can_be_imported_and_invoked_with_canonical_dict():
    service = SkillVerificationService(verifier=FakeVerifier())
    extraction_result = SkillExtractionResult(
        candidate_skills=[
            CandidateSkill(name="Python", source="requirements"),
            CandidateSkill(name="Communication", source="description"),
        ]
    )

    result = service.verify_from_job_data(
        {
            "source": "greenhouse",
            "source_url": "https://boards.greenhouse.io/openai/jobs/backend-1",
            "external_id": "backend-1",
            "company_name": "OpenAI",
            "title": "Backend Engineer",
            "job_type": "FULL_TIME",
            "employment_type": "FULL_TIME",
            "remote_type": "Remote",
            "location": "Remote",
            "description": "Build Django services.",
            "sections": {
                "requirements": "Python and Django.",
                "preferred_qualifications": "PostgreSQL.",
            },
            "posted_at": "2026-06-11",
            "metadata": {},
        },
        extraction_result,
    )

    assert [skill.name for skill in result.verified_skills] == ["Python"]
    assert [skill.name for skill in result.rejected_skills] == ["Communication"]
    assert result.metadata == {"verifier": "fake"}


def test_verification_service_accepts_canonical_payload_dataclass():
    service = SkillVerificationService(verifier=FakeVerifier())
    payload = CanonicalJobPayload(
        source="lever",
        source_url="https://jobs.lever.co/openai/backend-1",
        external_id="backend-1",
        company_name="OpenAI",
        title="Backend Engineer",
        job_type="FULL_TIME",
        employment_type="FULL_TIME",
        remote_type="Remote",
        location="Remote",
        description="Build Django services.",
        sections={
            "requirements": "Python and Django.",
            "preferred_qualifications": "PostgreSQL.",
        },
        posted_at="2026-06-11",
        metadata={},
    )
    extraction_result = SkillExtractionResult(
        candidate_skills=[
            CandidateSkill(name="Python", source="requirements"),
            CandidateSkill(name="Communication", source="description"),
        ]
    )

    result = service.verify_from_job_data(payload, extraction_result)

    assert [skill.name for skill in result.verified_skills] == ["Python"]
    assert [skill.name for skill in result.rejected_skills] == ["Communication"]


def test_verification_service_rejects_source_specific_payload():
    service = SkillVerificationService(verifier=FakeVerifier())

    with pytest.raises(ValueError, match="canonical job payload fields only"):
        service.verify_from_job_data(
            {
                "jobTitle": "Backend Engineer",
                "companyName": "OpenAI",
                "jobUrl": "https://www.linkedin.com/jobs/view/123",
                "jobPostingId": "123",
            },
            [{"name": "Python"}],
        )


def test_verification_service_rejects_legacy_raw_text_payload():
    service = SkillVerificationService(verifier=FakeVerifier())

    with pytest.raises(ValueError, match="canonical job payload fields only"):
        service.verify_from_job_data(
            {
                "title": "Backend Engineer",
                "company_name": "OpenAI",
                "source_url": "https://jobs.example.com/backend",
                "raw_text": "Python, Django, PostgreSQL.",
            },
            [{"name": "Python"}],
        )


@pytest.mark.django_db
def test_verification_service_logs_model_and_counts():
    service = SkillVerificationService(verifier=FakeVerifier())
    extraction_result = SkillExtractionResult(
        candidate_skills=[
            CandidateSkill(name="Python", source="requirements"),
            CandidateSkill(name="Communication", source="description"),
        ]
    )

    service.verify_from_job_data(_canonical_payload_dict(), extraction_result)

    logs = PipelineLog.objects.filter(step_name="ollama_verify").order_by("created_at")
    assert [log.status for log in logs] == [
        PipelineLog.StatusChoices.STARTED,
        PipelineLog.StatusChoices.SUCCESS,
    ]
    assert logs[0].metadata["source_job_identifier"] == "backend-1"
    assert logs[0].metadata["model"] == "fake-ollama"
    assert logs[1].metadata["accepted_count"] == 1
    assert logs[1].metadata["rejected_count"] == 1


def _canonical_payload_dict():
    return {
        "source": "greenhouse",
        "source_url": "https://boards.greenhouse.io/openai/jobs/backend-1",
        "external_id": "backend-1",
        "company_name": "OpenAI",
        "title": "Backend Engineer",
        "job_type": "FULL_TIME",
        "employment_type": "FULL_TIME",
        "remote_type": "Remote",
        "location": "Remote",
        "description": "Build Django services.",
        "sections": {
            "requirements": "Python and Django.",
            "preferred_qualifications": "PostgreSQL.",
        },
        "posted_at": "2026-06-11",
        "metadata": {},
    }


class FakeVerifier:
    model = "fake-ollama"

    def verify(
        self,
        title,
        description,
        candidate_skills,
        raw_text="",
        normalized_text="",
        source_fragments=None,
        source_job_identifier="",
    ):
        assert title == "Backend Engineer"
        assert "Django" in description
        assert raw_text == ""
        assert normalized_text == ""
        assert source_fragments == [
            {"source": "requirements", "text": "Python and Django."},
            {"source": "preferred_qualifications", "text": "PostgreSQL."},
        ]
        assert source_job_identifier == "backend-1"
        assert isinstance(candidate_skills, SkillExtractionResult)
        return type(
            "FakeResult",
            (),
            {
                "verified_skills": [type("Skill", (), {"name": "Python"})()],
                "rejected_skills": [type("Skill", (), {"name": "Communication"})()],
                "metadata": {"verifier": "fake"},
            },
        )()
