import pytest

from apps.imports.services import SkillVerificationService
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
        return {
            "verified_skills": [
                {"name": "TypeScript", "reason": "listed in requirements"},
                {"name": "React", "reason": "listed in requirements"},
            ],
            "rejected_skills": [
                {"name": "Communication", "reason": "too generic"}
            ],
        }

    monkeypatch.setattr(verifier, "_call_ollama", fake_call)

    result = verifier.verify(
        title="Frontend Engineer",
        description="Build React features with TypeScript.",
        candidate_skills=[
            {"name": "typescript", "source": "description"},
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
        lambda prompt: (_ for _ in ()).throw(
            SkillVerificationError("Ollama down")
        ),
    )

    with pytest.raises(SkillVerificationError, match="Ollama down"):
        verifier.verify(
            title="Backend Engineer",
            description="Build APIs.",
            candidate_skills=[{"name": "Python"}],
            source_job_identifier="backend-1",
        )


def test_verification_service_can_be_imported_and_invoked():
    service = SkillVerificationService(verifier=FakeVerifier())
    extraction_result = SkillExtractionResult(
        candidate_skills=[
            CandidateSkill(name="Python", source="description"),
            CandidateSkill(name="Communication", source="description"),
        ]
    )

    result = service.verify_from_job_data(
        {
            "title": "Backend Engineer",
            "description": "Build Django services.",
            "raw_text": "Python, Django, and PostgreSQL.",
            "normalized_text": "Backend Python role.",
            "source_fragments": [{"source": "description", "text": "Python"}],
            "external_id": "backend-1",
        },
        extraction_result,
    )

    assert [skill.name for skill in result.verified_skills] == ["Python"]
    assert [skill.name for skill in result.rejected_skills] == ["Communication"]
    assert result.metadata == {"verifier": "fake"}


class FakeVerifier:
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
        assert "PostgreSQL" in raw_text
        assert normalized_text == "Backend Python role."
        assert source_fragments == [{"source": "description", "text": "Python"}]
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
