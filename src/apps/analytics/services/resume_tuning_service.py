import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

from apps.skills.models import SkillSet

from .resume_analytics_service import ResumeAnalyticsService


class LocalResumeFile:
    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name
        self.size = self.path.stat().st_size

    def chunks(self, chunk_size=64 * 1024):
        with self.path.open("rb") as resume_file:
            while True:
                chunk = resume_file.read(chunk_size)
                if not chunk:
                    break
                yield chunk


class ResumeTuningService:
    """Evaluate resume skill extraction against a small gold skill spec."""

    def __init__(self, resume_service_factory=None):
        self.resume_service_factory = resume_service_factory or ResumeAnalyticsService

    def run(
        self,
        resume_path,
        gold_path,
        runs=3,
        filters=None,
        job_limit=None,
        market_limit=None,
        progress_callback=None,
    ):
        resume_path = Path(resume_path)
        gold_path = Path(gold_path)
        runs = max(1, int(runs or 1))
        gold = self._load_gold(gold_path)

        service = self.resume_service_factory()
        attachment_name, resume_text = service.extract_attachment_text(
            LocalResumeFile(resume_path)
        )

        run_reports = []
        for index in range(1, runs + 1):
            if progress_callback:
                progress_callback(index, runs)
            result = service.analyze_resume(
                resume_text,
                filters=filters,
                job_limit=job_limit,
                market_limit=market_limit,
                run_id=f"resume-tuning-{uuid4()}",
            )
            run_reports.append(self._evaluate_run(index, result, gold))

        summary = self._summarize(run_reports, runs)
        return {
            "passed": summary["passed"],
            "resume": {
                "path": str(resume_path),
                "attachment_name": attachment_name,
                "text_characters": len(resume_text),
            },
            "gold": gold,
            "runs_requested": runs,
            "runs_completed": len(run_reports),
            "summary": summary,
            "runs": run_reports,
        }

    def _evaluate_run(self, index, result, gold):
        candidate_names = self._name_set(result.get("candidate_keywords", []))
        verified_names = self._name_set(result.get("verified_keywords", []))
        mapped_names = self._name_set(result.get("mapped_skills", []))
        rejected_names = self._name_set(result.get("rejected_keywords", []))
        unmapped_names = self._name_set(result.get("unmapped_keywords", []))

        expected = self._normalize_list(gold.get("expected", []))
        expected_mapped = self._normalize_list(gold.get("expected_mapped", []))
        optional = self._normalize_list(
            gold.get("optional", []) or gold.get("expected_optional", [])
        )
        reject = self._normalize_list(gold.get("reject", []))
        minimum = gold.get("minimum", {}) or {}
        accepted_names = verified_names | mapped_names

        missing_expected = self._missing(expected, verified_names)
        missing_mapped = self._missing(expected_mapped, mapped_names)
        unexpected_rejected_present = self._present(
            reject,
            accepted_names,
        )
        optional_found = self._present(optional, accepted_names)
        optional_missing = self._missing(optional, accepted_names)
        expected_any_of_failures = self._expected_any_of_failures(
            gold.get("expected_any_of", {}) or {},
            accepted_names,
        )
        split_failures = self._split_failures(
            gold.get("split", {}) or {},
            verified_names,
        )
        normalize_failures = self._normalize_failures(
            gold.get("normalize", {}) or {},
            accepted_names,
        )
        minimum_failures = self._minimum_failures(
            minimum,
            result,
            verified_names,
            mapped_names,
        )
        passed = not (
            missing_expected
            or missing_mapped
            or unexpected_rejected_present
            or expected_any_of_failures
            or split_failures
            or normalize_failures
            or minimum_failures
        )

        return {
            "index": index,
            "passed": passed,
            "candidate_skills": self._display_names(candidate_names),
            "verified_skills": self._display_names(verified_names),
            "mapped_skills": self._display_names(mapped_names),
            "rejected_skills": self._display_names(rejected_names),
            "unmapped_skills": self._display_names(unmapped_names),
            "job_match_count": len(result.get("job_matches", []) or []),
            "market_fit_percent": (result.get("market_fit") or {}).get(
                "fit_percent", 0
            ),
            "missing_expected": missing_expected,
            "missing_mapped": missing_mapped,
            "unexpected_rejected_present": unexpected_rejected_present,
            "optional_found": optional_found,
            "optional_missing": optional_missing,
            "expected_any_of_failures": expected_any_of_failures,
            "split_failures": split_failures,
            "normalize_failures": normalize_failures,
            "minimum_failures": minimum_failures,
        }

    def _summarize(self, run_reports, runs):
        verified_counter = Counter()
        mapped_counter = Counter()
        for report in run_reports:
            verified_counter.update(
                SkillSet.normalize_name(name) for name in report["verified_skills"]
            )
            mapped_counter.update(
                SkillSet.normalize_name(name) for name in report["mapped_skills"]
            )

        return {
            "passed": all(report["passed"] for report in run_reports),
            "passing_runs": sum(1 for report in run_reports if report["passed"]),
            "failing_runs": sum(1 for report in run_reports if not report["passed"]),
            "stable_verified_skills": self._stable_names(verified_counter, runs),
            "unstable_verified_skills": self._unstable_names(verified_counter, runs),
            "stable_mapped_skills": self._stable_names(mapped_counter, runs),
            "unstable_mapped_skills": self._unstable_names(mapped_counter, runs),
            "average_job_matches": self._average(
                report["job_match_count"] for report in run_reports
            ),
            "average_market_fit_percent": self._average(
                report["market_fit_percent"] for report in run_reports
            ),
        }

    @staticmethod
    def _load_gold(path):
        with Path(path).open(encoding="utf-8") as gold_file:
            payload = json.load(gold_file)
        return {
            "expected": payload.get("expected", []),
            "expected_mapped": payload.get("expected_mapped", []),
            "optional": payload.get("optional", payload.get("expected_optional", [])),
            "expected_any_of": payload.get("expected_any_of", {}),
            "reject": payload.get("reject", []),
            "normalize": payload.get("normalize", {}),
            "split": payload.get("split", {}),
            "minimum": payload.get("minimum", {}),
            "notes": payload.get("notes", ""),
        }

    @classmethod
    def _name_set(cls, rows):
        names = set()
        for row in rows or []:
            if isinstance(row, dict):
                name = row.get("name") or row.get("skill") or ""
            else:
                name = getattr(row, "name", row)
            normalized = SkillSet.normalize_name(name)
            if normalized:
                names.add(normalized)
        return names

    @classmethod
    def _normalize_list(cls, values):
        return {
            SkillSet.normalize_name(value): str(value).strip()
            for value in values or []
            if SkillSet.normalize_name(value)
        }

    @classmethod
    def _missing(cls, expected, actual):
        return sorted(
            display
            for normalized, display in expected.items()
            if normalized not in actual
        )

    @classmethod
    def _present(cls, rejected, actual):
        return sorted(
            display for normalized, display in rejected.items() if normalized in actual
        )

    @classmethod
    def _split_failures(cls, split_spec, actual):
        failures = []
        for raw_name, expected_parts in split_spec.items():
            missing = cls._missing(cls._normalize_list(expected_parts), actual)
            if missing:
                failures.append({"source": raw_name, "missing_parts": missing})
        return failures

    @classmethod
    def _expected_any_of_failures(cls, group_spec, actual):
        failures = []
        for group_name, accepted_values in group_spec.items():
            normalized_values = cls._normalize_list(accepted_values)
            if not normalized_values:
                continue
            if not any(value in actual for value in normalized_values):
                failures.append(
                    {
                        "group": group_name,
                        "accepted_values": sorted(normalized_values.values()),
                    }
                )
        return failures

    @classmethod
    def _normalize_failures(cls, normalize_spec, actual):
        failures = []
        for raw_name, canonical_name in normalize_spec.items():
            raw_key = SkillSet.normalize_name(raw_name)
            canonical_key = SkillSet.normalize_name(canonical_name)
            if canonical_key and canonical_key not in actual:
                failures.append(
                    {
                        "source": raw_name,
                        "expected": canonical_name,
                        "reason": "canonical skill missing",
                    }
                )
            if (
                raw_key
                and canonical_key
                and raw_key != canonical_key
                and raw_key in actual
            ):
                failures.append(
                    {
                        "source": raw_name,
                        "expected": canonical_name,
                        "reason": "raw variant was accepted",
                    }
                )
        return failures

    @staticmethod
    def _minimum_failures(minimum, result, verified_names, mapped_names):
        checks = {
            "verified_count": len(verified_names),
            "mapped_count": len(mapped_names),
            "job_match_count": len(result.get("job_matches", []) or []),
            "market_fit_percent": (result.get("market_fit") or {}).get(
                "fit_percent", 0
            ),
        }
        failures = []
        for key, actual in checks.items():
            expected = minimum.get(key)
            if expected is not None and actual < expected:
                failures.append(
                    {"metric": key, "expected_min": expected, "actual": actual}
                )
        return failures

    @staticmethod
    def _display_names(normalized_names):
        return sorted(
            ResumeTuningService._display_name(name) for name in normalized_names
        )

    @classmethod
    def _stable_names(cls, counter, runs):
        return [
            {"name": cls._display_name(name), "runs": count}
            for name, count in sorted(counter.items())
            if count == runs
        ]

    @classmethod
    def _unstable_names(cls, counter, runs):
        return [
            {"name": cls._display_name(name), "runs": count}
            for name, count in sorted(counter.items())
            if 0 < count < runs
        ]

    @staticmethod
    def _display_name(normalized_name):
        known = {"sql": "SQL", "mysql": "MySQL", "javascript": "JavaScript"}
        return known.get(normalized_name, normalized_name.title())

    @staticmethod
    def _average(values):
        values = list(values)
        if not values:
            return 0
        return round(sum(values) / len(values), 2)
