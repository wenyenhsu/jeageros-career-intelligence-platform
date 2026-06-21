import json
from datetime import datetime

import pytest
from django.utils import timezone

from apps.analytics.serialization import make_json_serializable
from apps.analytics.services.skill_demand_service import SkillDemandService
from apps.companies.models import Company
from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill, SkillSet


@pytest.mark.django_db
def test_make_json_serializable_handles_market_profile_datetimes():
    company = Company.objects.create(name="Resume Co")
    skill = SkillSet.objects.create(name="Python")
    job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url="https://example.com/backend",
    )
    JobPostSkill.objects.create(job_post=job, skill_set=skill, score=90)
    SkillDemandService().update_skill_demand()

    profile = SkillDemandService().build_market_profile(limit=3)
    serialized = make_json_serializable(profile)

    json.dumps(serialized)
    assert serialized["top_skills"]
    assert isinstance(serialized["top_skills"][0]["first_seen"], str)


def test_make_json_serializable_converts_datetime():
    payload = {"generated_at": timezone.now()}
    serialized = make_json_serializable(payload)
    json.dumps(serialized)
    assert isinstance(serialized["generated_at"], str)
