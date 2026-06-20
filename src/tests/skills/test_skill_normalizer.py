import pytest
from urllib import error

from apps.skills.models import SkillAlias, SkillSet
from apps.skills.services.normalizer import SkillNormalizer, normalize_skills
from apps.skills.services.ollama_mapper import (
    OllamaSkillMapper,
    OllamaSkillMapping,
    OllamaSkillMappingError,
)


class FakeOllamaMapper:
    def __init__(self, canonical=None, confidence=0.91, reason="mapped by test"):
        self.canonical = canonical
        self.confidence = confidence
        self.reason = reason
        self.calls = []

    def map(self, raw_skill, canonical_options=None):
        self.calls.append(
            {
                "raw_skill": raw_skill,
                "canonical_options": canonical_options or [],
            }
        )
        return OllamaSkillMapping(
            original=raw_skill,
            canonical=self.canonical,
            confidence=self.confidence,
            reason=self.reason,
        )


@pytest.mark.django_db
def test_normalizer_uses_alias_before_other_strategies():
    aws = SkillSet.objects.create(name="AWS")
    SkillSet.objects.create(name="AWS Lambda")
    SkillAlias.objects.create(alias="AWS Lambda", skill=aws)
    mapper = FakeOllamaMapper(canonical="AWS Lambda")

    result = SkillNormalizer(ollama_mapper=mapper).normalize("AWS Lambda")

    assert result.canonical == "AWS"
    assert result.confidence == 1.0
    assert result.source == "alias"
    assert mapper.calls == []


@pytest.mark.django_db
def test_normalizer_uses_exact_skill_match():
    SkillSet.objects.create(name="PostgreSQL")

    result = SkillNormalizer(ollama_mapper=FakeOllamaMapper()).normalize("postgresql")

    assert result.canonical == "PostgreSQL"
    assert result.source == "exact"
    assert result.confidence == 1.0


@pytest.mark.django_db
def test_normalizer_uses_fuzzy_match_above_threshold():
    SkillSet.objects.create(name="Django REST Framework")

    result = SkillNormalizer(
        ollama_mapper=FakeOllamaMapper(),
        fuzzy_threshold=90,
    ).normalize("Django REST Framewrk")

    assert result.canonical == "Django REST Framework"
    assert result.source == "fuzzy"
    assert result.confidence >= 0.9


@pytest.mark.django_db
def test_normalizer_uses_ollama_fallback_when_local_matches_fail():
    SkillSet.objects.create(name="AWS")
    mapper = FakeOllamaMapper(canonical="AWS", confidence=0.82)

    result = SkillNormalizer(
        ollama_mapper=mapper,
        fuzzy_threshold=100,
    ).normalize("cloud function service")

    assert result.canonical == "AWS"
    assert result.source == "ollama"
    assert result.confidence == 0.82
    assert mapper.calls[0]["canonical_options"] == ["AWS"]


@pytest.mark.django_db
def test_normalizer_returns_none_when_ollama_suggests_unknown_skill():
    SkillSet.objects.create(name="Python")
    mapper = FakeOllamaMapper(canonical="Unknown Canonical", confidence=0.75)

    result = SkillNormalizer(ollama_mapper=mapper, fuzzy_threshold=100).normalize(
        "mystery skill"
    )

    assert result.canonical is None
    assert result.source == "ollama"
    assert "no matching SkillSet exists" in result.reason


@pytest.mark.django_db
def test_normalizer_handles_ollama_errors_gracefully():
    class FailingMapper:
        def map(self, raw_skill, canonical_options=None):
            raise OllamaSkillMappingError("timeout")

    result = SkillNormalizer(ollama_mapper=FailingMapper()).normalize("unknown")

    assert result.canonical is None
    assert result.confidence == 0.0
    assert result.source == "ollama_error"
    assert result.reason == "timeout"


@pytest.mark.django_db
def test_batch_api_preserves_input_order():
    python = SkillSet.objects.create(name="Python")
    postgres = SkillSet.objects.create(name="PostgreSQL")
    SkillAlias.objects.create(alias="Postgres", skill=postgres)

    results = normalize_skills(["python", "Postgres", ""])

    assert [result.canonical for result in results] == [
        python.name,
        postgres.name,
        None,
    ]
    assert [result.source for result in results] == ["exact", "alias", "empty"]


def test_ollama_mapper_parses_valid_response():
    mapper = OllamaSkillMapper(model="fake", base_url="http://ollama", timeout=1)

    result = mapper.parse_response(
        '{"original": "drf", "canonical": "Django REST Framework", '
        '"confidence": 0.93, "reason": "common abbreviation"}'
    )

    assert result.original == "drf"
    assert result.canonical == "Django REST Framework"
    assert result.confidence == 0.93


def test_ollama_mapper_rejects_invalid_json():
    mapper = OllamaSkillMapper(model="fake", base_url="http://ollama", timeout=1)

    with pytest.raises(OllamaSkillMappingError, match="malformed JSON"):
        mapper.parse_response("<html>")


def test_ollama_mapper_wraps_network_failures(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise error.URLError("network down")

    monkeypatch.setattr(
        "apps.skills.services.ollama_mapper.request.urlopen",
        fail_urlopen,
    )
    mapper = OllamaSkillMapper(model="fake", base_url="http://ollama", timeout=1)

    with pytest.raises(OllamaSkillMappingError, match="request failed"):
        mapper.map("unknown", canonical_options=["Python"])
