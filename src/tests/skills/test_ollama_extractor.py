import pytest

from apps.imports.models import PipelineLog
from apps.imports.services import CanonicalJobPayload, SkillExtractionService
from apps.skills.services import CandidateSkill, OllamaExtractor, SkillExtractionError


def test_valid_extraction_response_is_parsed_correctly():
    extractor = OllamaExtractor(model="llama3.1", max_skills=5)

    result = extractor.parse_response(
        {
            "candidate_skills": [
                {
                    "name": " python ",
                    "source": "description",
                    "confidence": 0.91,
                    "source_fragment": "Python and Django experience required.",
                },
                {"name": "django", "source": "raw_text", "confidence": "0.82"},
            ]
        }
    )

    assert [skill.as_dict() for skill in result.candidate_skills] == [
        {
            "name": "Python",
            "source": "description",
            "confidence": 0.91,
            "source_fragment": "Python and Django experience required.",
        },
        {"name": "Django", "source": "raw_text", "confidence": 0.82},
    ]
    assert result.as_dict() == {
        "skills": [
            {
                "name": "Python",
                "source": "description",
                "confidence": 0.91,
                "source_fragment": "Python and Django experience required.",
            },
            {"name": "Django", "source": "raw_text", "confidence": 0.82},
        ],
        "metadata": {
            "extractor": "ollama",
            "max_skills": 5,
            "model": "llama3.1",
            "source_job_identifier": "",
        },
    }
    assert result.metadata["extractor"] == "ollama"


def test_malformed_json_is_rejected():
    extractor = OllamaExtractor()

    with pytest.raises(SkillExtractionError, match="malformed JSON"):
        extractor.parse_response('{"candidate_skills": [')


def test_duplicate_skills_are_removed_and_limited():
    extractor = OllamaExtractor(max_skills=2)

    result = extractor.parse_response(
        {
            "candidate_skills": [
                {"name": "Python"},
                {"name": " python "},
                {"name": "Django"},
                {"name": "PostgreSQL"},
            ]
        }
    )

    assert [skill.name for skill in result.candidate_skills] == ["Python", "Django"]


def test_skill_names_and_sources_are_normalized():
    extractor = OllamaExtractor(max_skills=5)

    result = extractor.parse_response(
        {
            "skills": [
                {"name": "  machine   learning ", "source": "Normalized Text"},
                {"name": "sql", "source": "requirements"},
            ]
        },
        source_job_identifier="job-123",
    )

    assert [skill.as_dict() for skill in result.candidate_skills] == [
        {"name": "Machine Learning", "source": "normalized_text"},
        {"name": "SQL", "source": "requirements"},
    ]
    assert result.metadata["source_job_identifier"] == "job-123"


def test_confidence_labels_are_normalized():
    extractor = OllamaExtractor(max_skills=5)

    result = extractor.parse_response(
        {
            "skills": [
                {"name": "Python", "confidence": "high"},
                {"name": "Django", "confidence": "medium"},
                {"name": "SQL", "confidence": "low"},
            ]
        }
    )

    assert [skill.confidence for skill in result.candidate_skills] == [
        0.9,
        0.6,
        0.3,
    ]


def test_empty_extraction_output_is_handled():
    extractor = OllamaExtractor()

    with pytest.raises(SkillExtractionError, match="candidate skills"):
        extractor.parse_response({"candidate_skills": []})


def test_extractor_extract_uses_ollama_response(monkeypatch):
    extractor = OllamaExtractor(max_skills=5)

    monkeypatch.setattr(
        extractor,
        "_call_ollama",
        lambda prompt: {
            "skills": [
                {"name": "TypeScript", "source": "description"},
                {"name": "React", "source": "source_fragment"},
            ]
        },
    )

    result = extractor.extract(
        title="Frontend Engineer",
        description="Build React features with TypeScript.",
        source_fragments=[{"source": "requirements", "text": "React and TypeScript"}],
        source_job_identifier="frontend-1",
    )

    assert [skill.name for skill in result.candidate_skills] == ["TypeScript", "React"]
    assert result.metadata["source_job_identifier"] == "frontend-1"


def test_ollama_failure_is_reported_as_extraction_error(monkeypatch):
    extractor = OllamaExtractor()

    monkeypatch.setattr(
        extractor,
        "_call_ollama",
        lambda prompt: (_ for _ in ()).throw(SkillExtractionError("Ollama down")),
    )

    with pytest.raises(SkillExtractionError, match="Ollama down"):
        extractor.extract(
            title="Backend Engineer",
            description="Build APIs.",
            source_job_identifier="backend-1",
        )


def test_skill_extraction_service_can_be_imported_and_called_with_canonical_dict():
    service = SkillExtractionService(extractor=FakeExtractor())

    result = service.extract_from_job_data(
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
        }
    )

    assert [skill.name for skill in result.candidate_skills] == ["Python"]
    assert result.metadata == {"extractor": "fake"}


def test_skill_extraction_service_accepts_canonical_payload_dataclass():
    service = SkillExtractionService(extractor=FakeExtractor())
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

    result = service.extract_from_job_data(payload)

    assert [skill.name for skill in result.candidate_skills] == ["Python"]


def test_skill_extraction_service_rejects_source_specific_payload():
    service = SkillExtractionService(extractor=FakeExtractor())

    with pytest.raises(ValueError, match="canonical job payload fields only"):
        service.extract_from_job_data(
            {
                "jobTitle": "Backend Engineer",
                "companyName": "OpenAI",
                "jobUrl": "https://www.linkedin.com/jobs/view/123",
                "jobPostingId": "123",
            }
        )


def test_skill_extraction_service_rejects_legacy_raw_text_payload():
    service = SkillExtractionService(extractor=FakeExtractor())

    with pytest.raises(ValueError, match="canonical job payload fields only"):
        service.extract_from_job_data(
            {
                "title": "Backend Engineer",
                "company_name": "OpenAI",
                "source_url": "https://jobs.example.com/backend",
                "raw_text": "Python, Django, PostgreSQL.",
            }
        )


@pytest.mark.django_db
def test_skill_extraction_service_logs_model_and_job_identifier():
    service = SkillExtractionService(extractor=FakeExtractor())

    service.extract_from_job_data(_canonical_payload_dict())

    logs = PipelineLog.objects.filter(step_name="ollama_extract").order_by("created_at")
    assert [log.status for log in logs] == [
        PipelineLog.StatusChoices.STARTED,
        PipelineLog.StatusChoices.SUCCESS,
    ]
    assert logs[0].metadata["source_job_identifier"] == "backend-1"
    assert logs[0].metadata["model"] == "fake-ollama"
    assert logs[1].metadata["candidate_skill_count"] == 1


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


class FakeExtractor:
    model = "fake-ollama"

    def extract(
        self,
        title,
        description,
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
        return type(
            "FakeResult",
            (),
            {
                "candidate_skills": [CandidateSkill(name="Python")],
                "metadata": {"extractor": "fake"},
            },
        )()
