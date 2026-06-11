import pytest
from django.urls import reverse
from django.utils import timezone

from apps.api.serializers import ApplicationSerializer
from apps.applications.forms import ApplicationForm
from apps.applications.models import Application, StatusHistory
from apps.companies.models import Company
from apps.jobs.models import JobPost
from apps.skills.models import ApplicationSkill, JobPostSkill, SkillSet


@pytest.fixture
def shared_application(user, company):
    job = JobPost.objects.create(
        company=company,
        title="Machine Learning Intern",
        employment_type="Internship",
        location="Remote",
        source_url="https://example.com/jobs/ml-intern",
    )
    application = Application.objects.create(
        user=user,
        job_post=job,
        status=Application.Status.APPLIED,
        applied_at=timezone.now(),
        priority=1,
        referral=True,
    )
    job_skill = SkillSet.objects.create(name="Python", aliases=["Py"])
    application_skill = SkillSet.objects.create(name="Interview Prep")
    JobPostSkill.objects.create(job_post=job, skill_set=job_skill, score=90)
    ApplicationSkill.objects.create(
        application=application,
        skill_set=application_skill,
        score=75,
    )
    return application


@pytest.mark.django_db
def test_application_helpers_return_linked_job_data(shared_application, company):
    application = shared_application

    assert application.job_title_display == "Machine Learning Intern"
    assert application.company_display == company.name
    assert application.job_type == "Internship"
    assert application.job_type_display == "Internship"
    assert application.location_display == "Remote"
    assert application.source_url_display == "https://example.com/jobs/ml-intern"
    assert application.job_skill_set_names == ["Python"]
    assert application.shared_skill_set_names == ["Python"]
    assert application.skill_set_names == ["Interview Prep"]


@pytest.mark.django_db
def test_application_list_displays_linked_job_info_and_job_skills(
    client,
    shared_application,
    company,
):
    response = client.get(reverse("application-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert company.name in content
    assert "Machine Learning Intern" in content
    assert "Internship" in content
    assert "Remote" in content
    assert "Python" in content
    assert "Interview Prep" in content
    assert 'href="https://example.com/jobs/ml-intern"' in content
    assert 'target="_blank"' in content
    assert 'rel="noopener"' in content
    assert "Applied" in content


@pytest.mark.django_db
def test_application_detail_displays_linked_job_info_and_application_fields(
    client,
    shared_application,
    user,
    company,
):
    StatusHistory.objects.create(
        application=shared_application,
        old_status=Application.Status.SAVED,
        new_status=Application.Status.APPLIED,
        changed_by=user,
    )

    response = client.get(reverse("application-detail", args=[shared_application.id]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Linked Job" in content
    assert company.name in content
    assert "Machine Learning Intern" in content
    assert "Remote" in content
    assert "Internship" in content
    assert "https://example.com/jobs/ml-intern" in content
    assert 'href="https://example.com/jobs/ml-intern"' in content
    assert 'target="_blank"' in content
    assert 'rel="noopener"' in content
    assert "Job Skill Sets" in content
    assert "Python" in content
    assert "Application Skill Sets" in content
    assert "Interview Prep" in content
    assert "Status History" in content
    assert "SAVED" in content
    assert "APPLIED" in content


@pytest.mark.django_db
def test_application_search_uses_linked_job_type_location_and_skill_keywords(
    client,
    user,
    company,
):
    other_company = Company.objects.create(name="Anthropic")
    python = SkillSet.objects.create(name="Python", aliases=["Py"])
    react = SkillSet.objects.create(name="React")
    intern_job = JobPost.objects.create(
        company=company,
        title="Research Intern",
        employment_type="Internship",
        location="Remote",
    )
    full_time_job = JobPost.objects.create(
        company=other_company,
        title="Frontend Engineer",
        employment_type="Full-time",
        location="San Francisco",
    )
    Application.objects.create(user=user, job_post=intern_job)
    Application.objects.create(user=user, job_post=full_time_job)
    JobPostSkill.objects.create(job_post=intern_job, skill_set=python)
    JobPostSkill.objects.create(job_post=full_time_job, skill_set=react)

    job_type_response = client.get(reverse("application-list"), {"q": "Internship"})
    location_response = client.get(reverse("application-list"), {"q": "Remote"})
    skill_response = client.get(reverse("application-list"), {"q": "py"})

    for response in [job_type_response, location_response, skill_response]:
        assert response.status_code == 200
        content = response.content.decode()
        assert "Research Intern" in content
        assert "Frontend Engineer" not in content


@pytest.mark.django_db
def test_application_api_exposes_linked_job_fields_and_separate_skill_sets(
    client,
    user,
    shared_application,
    company,
):
    client.force_login(user)

    response = client.get("/api/applications/")

    assert response.status_code == 200
    payload = response.json()
    application_payload = payload[0]
    assert application_payload["job_title"] == "Machine Learning Intern"
    assert application_payload["company_name"] == company.name
    assert application_payload["job_type"] == "Internship"
    assert application_payload["job_type_display"] == "Internship"
    assert application_payload["location"] == "Remote"
    assert application_payload["source_url"] == "https://example.com/jobs/ml-intern"
    assert application_payload["job_skill_set_names"] == ["Python"]
    assert application_payload["shared_skill_set_names"] == ["Python"]
    assert application_payload["skill_set_names"] == ["Interview Prep"]


@pytest.mark.django_db
def test_application_serializer_can_be_invoked_directly(shared_application, company):
    payload = ApplicationSerializer(shared_application).data

    assert payload["job_title"] == "Machine Learning Intern"
    assert payload["company_name"] == company.name
    assert payload["job_skill_set_names"] == ["Python"]
    assert payload["skill_set_names"] == ["Interview Prep"]


@pytest.mark.django_db
def test_application_form_makes_linked_jobpost_relationship_clear(job):
    form = ApplicationForm()

    assert form.fields["job_post"].label == "Linked JobPost"
    assert "Shared job details" in form.fields["job_post"].help_text
    assert form.fields["job_post"].label_from_instance(job) == (
        "OpenAI - Backend Engineer (No job type)"
    )
