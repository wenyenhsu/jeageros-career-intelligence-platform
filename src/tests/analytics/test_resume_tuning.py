import io
import json

import pytest
from django.core.management import call_command

from apps.analytics.services.resume_tuning_service import ResumeTuningService


class FakeResumeService:
    def __init__(self, results):
        self.results = list(results)

    def extract_attachment_text(self, uploaded_file):
        content = b"".join(uploaded_file.chunks()).decode()
        return uploaded_file.name, content

    def analyze_resume(self, *args, **kwargs):
        if not self.results:
            raise AssertionError("No fake resume result left.")
        return self.results.pop(0)


def fake_result(verified=None, mapped=None, rejected=None, unmapped=None):
    return {
        "candidate_keywords": verified or [],
        "verified_keywords": verified or [],
        "mapped_skills": mapped or [],
        "rejected_keywords": rejected or [],
        "unmapped_keywords": unmapped or [],
        "job_matches": [{"title": "Data Engineer"}],
        "market_fit": {"fit_percent": 50},
    }


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_resume_tuning_passes_when_gold_expectations_are_stable(tmp_path):
    resume_path = tmp_path / "resume.txt"
    gold_path = tmp_path / "gold.json"
    resume_path.write_text("Python SQL MySQL data resume", encoding="utf-8")
    write_json(
        gold_path,
        {
            "expected": ["Python", "SQL", "MySQL"],
            "expected_mapped": ["Python", "SQL"],
            "optional": ["Hadoop", "Tableau"],
            "expected_any_of": {
                "database": ["SQL", "MySQL"],
                "programming": ["Python", "Java"],
            },
            "reject": ["Communication"],
            "normalize": {"Python Programming": "Python"},
            "split": {"SQL (MySQL)": ["SQL", "MySQL"]},
            "minimum": {"mapped_count": 2, "job_match_count": 1},
        },
    )
    results = [
        fake_result(
            verified=[
                {"name": "Python"},
                {"name": "SQL"},
                {"name": "MySQL"},
            ],
            mapped=[
                {"name": "Python", "skillset_id": 1},
                {"name": "SQL", "skillset_id": 2},
            ],
            rejected=[{"name": "Communication"}],
        ),
        fake_result(
            verified=[
                {"name": "Python"},
                {"name": "SQL"},
                {"name": "MySQL"},
            ],
            mapped=[
                {"name": "Python", "skillset_id": 1},
                {"name": "SQL", "skillset_id": 2},
            ],
            rejected=[{"name": "Communication"}],
        ),
    ]

    service = ResumeTuningService(lambda: FakeResumeService(results))
    report = service.run(resume_path, gold_path, runs=2)

    assert report["passed"] is True
    assert report["summary"]["passing_runs"] == 2
    assert report["summary"]["stable_mapped_skills"] == [
        {"name": "Python", "runs": 2},
        {"name": "SQL", "runs": 2},
    ]
    assert report["runs"][0]["optional_found"] == []
    assert report["runs"][0]["optional_missing"] == ["Hadoop", "Tableau"]


def test_resume_tuning_reports_missing_and_unstable_skills(tmp_path):
    resume_path = tmp_path / "resume.txt"
    gold_path = tmp_path / "gold.json"
    resume_path.write_text("Python SQL resume", encoding="utf-8")
    write_json(
        gold_path,
        {
            "expected": ["Python", "SQL", "MySQL"],
            "expected_mapped": ["Python", "SQL"],
            "expected_any_of": {
                "data_stack": ["Hadoop", "Spark"],
            },
            "reject": ["Communication"],
        },
    )
    results = [
        fake_result(
            verified=[{"name": "Python"}, {"name": "SQL"}],
            mapped=[{"name": "Python", "skillset_id": 1}],
        ),
        fake_result(
            verified=[{"name": "Python"}, {"name": "SQL"}],
            mapped=[
                {"name": "Python", "skillset_id": 1},
                {"name": "SQL", "skillset_id": 2},
            ],
        ),
    ]

    service = ResumeTuningService(lambda: FakeResumeService(results))
    report = service.run(resume_path, gold_path, runs=2)

    assert report["passed"] is False
    assert report["runs"][0]["missing_expected"] == ["MySQL"]
    assert report["runs"][0]["missing_mapped"] == ["SQL"]
    assert report["runs"][0]["expected_any_of_failures"] == [
        {"group": "data_stack", "accepted_values": ["Hadoop", "Spark"]}
    ]
    assert report["summary"]["unstable_mapped_skills"] == [
        {"name": "SQL", "runs": 1}
    ]


@pytest.mark.django_db
def test_eval_resume_ollama_command_prints_summary(tmp_path, monkeypatch):
    resume_path = tmp_path / "resume.txt"
    gold_path = tmp_path / "gold.json"
    output_path = tmp_path / "report.json"
    resume_path.write_text("Python SQL resume", encoding="utf-8")
    write_json(gold_path, {"expected": ["Python"]})

    class FakeTuningService:
        def run(self, **kwargs):
            kwargs["progress_callback"](1, kwargs["runs"])
            return {
                "passed": True,
                "runs_completed": kwargs["runs"],
                "summary": {
                    "passing_runs": kwargs["runs"],
                    "stable_mapped_skills": [{"name": "Python", "runs": 1}],
                    "unstable_verified_skills": [],
                },
                "runs": [],
            }

    monkeypatch.setattr(
        "apps.analytics.management.commands.eval_resume_ollama.ResumeTuningService",
        FakeTuningService,
    )
    stdout = io.StringIO()

    call_command(
        "eval_resume_ollama",
        str(resume_path),
        str(gold_path),
        "--runs",
        "1",
        "--output",
        str(output_path),
        stdout=stdout,
    )

    assert "[1/1] Running resume analysis..." in stdout.getvalue()
    assert "PASSED" in stdout.getvalue()
    assert output_path.exists()
