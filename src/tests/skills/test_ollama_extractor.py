import pytest

from apps.imports.services import SkillExtractionService
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
        {"name": "SQL", "source": "description"},
    ]
    assert result.metadata["source_job_identifier"] == "job-123"


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


def test_skill_extraction_service_can_be_imported_and_called():
    service = SkillExtractionService(extractor=FakeExtractor())

    result = service.extract_from_job_data(
        {
            "title": "Backend Engineer",
            "description": "Build Django services.",
            "raw_text": "Python, Django, and PostgreSQL.",
            "normalized_text": "Backend Python role.",
            "source_fragments": [{"source": "description", "text": "Python"}],
            "external_id": "backend-1",
        }
    )

    assert [skill.name for skill in result.candidate_skills] == ["Python"]
    assert result.metadata == {"extractor": "fake"}


class FakeExtractor:
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
        assert "PostgreSQL" in raw_text
        assert normalized_text == "Backend Python role."
        assert source_fragments == [{"source": "description", "text": "Python"}]
        assert source_job_identifier == "backend-1"
        return type(
            "FakeResult",
            (),
            {
                "candidate_skills": [CandidateSkill(name="Python")],
                "metadata": {"extractor": "fake"},
            },
        )()
