import re

import pytest
from django.contrib.messages import get_messages
from django.utils import timezone
from django.utils.dateformat import format as date_format
from django.urls import reverse

from apps.api.serializers import JobPostSerializer
from apps.applications.models import Application
from apps.jobs.forms import JobPostForm
from apps.jobs.models import JobPost
from apps.skills.models import (
    ApplicationSkill,
    JobPostSkill,
    SkillAttachmentSource,
    SkillKeyword,
    SkillSet,
)


def _title_source_link_count(content, title, source_url):
    return len(
        re.findall(
            rf'<a[^>]+href="{re.escape(source_url)}"[^>]*>\s*{re.escape(title)}\s*</a>',
            content,
        )
    )


def _title_has_any_link(content, title):
    return re.search(rf"<a[^>]*>\s*{re.escape(title)}\s*</a>", content) is not None


def _display_timestamp(value):
    return date_format(timezone.localtime(value), "M j, g:i A")


@pytest.mark.django_db
def test_job_detail_renders_skill_sets_and_job_type(client, company):
    job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        employment_type="Full-time",
    )
    skill = SkillSet.objects.create(name="Python")
    JobPostSkill.objects.create(job_post=job, skill_set=skill, score=95)

    response = client.get(reverse("job-detail", args=[job.id]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Job Type" in content
    assert "Full Time" in content
    assert "Skill Sets" in content
    assert "Python" in content


@pytest.mark.django_db
def test_job_list_title_links_to_source_url_when_present(client, company):
    source_url = "https://example.com/jobs/backend-engineer"
    JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url=source_url,
    )

    response = client.get(reverse("job-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert _title_source_link_count(content, "Backend Engineer", source_url) == 1
    assert 'target="_blank"' in content
    assert 'rel="noopener"' in content


@pytest.mark.django_db
def test_job_list_title_is_plain_text_when_source_url_is_missing(client, company):
    JobPost.objects.create(company=company, title="Manual Backend Engineer")

    response = client.get(reverse("job-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Manual Backend Engineer" in content
    assert not _title_has_any_link(content, "Manual Backend Engineer")


@pytest.mark.django_db
def test_job_list_renders_created_and_updated_columns(client, company):
    job = JobPost.objects.create(company=company, title="Timestamped Job")

    response = client.get(reverse("job-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Created" in content
    assert "Updated" in content
    assert _display_timestamp(job.created_at) in content
    assert _display_timestamp(job.updated_at) in content
    assert "<time" in content


@pytest.mark.django_db
def test_job_list_does_not_render_manual_ollama_skill_actions(client, company):
    job = JobPost.objects.create(company=company, title="Needs Skills")

    response = client.get(reverse("job-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Run Ollama Skills" not in content
    assert "job-skills-run" not in content
    assert "btn-outline-success\">Skills" not in content
    assert reverse("job-detail", args=[job.id]) in content


@pytest.mark.django_db
def test_job_list_renders_delete_action_next_to_view(client, company):
    job = JobPost.objects.create(company=company, title="Deletable Job")

    response = client.get(reverse("job-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert reverse("job-detail", args=[job.id]) in content
    assert f'action="{reverse("job-delete", args=[job.id])}"' in content
    assert "Delete this job?" in content
    assert "btn-outline-danger" in content


@pytest.mark.django_db
def test_job_delete_post_from_list_action_deletes_job(client, company):
    job = JobPost.objects.create(company=company, title="Delete Me")

    response = client.post(reverse("job-delete", args=[job.id]))

    assert response.status_code == 302
    assert response.url == reverse("job-list")
    assert not JobPost.objects.filter(id=job.id).exists()


@pytest.mark.django_db
def test_job_detail_title_links_to_source_url_when_present(client, company):
    source_url = "https://example.com/jobs/data-engineer"
    job = JobPost.objects.create(
        company=company,
        title="Data Engineer",
        source_url=source_url,
    )

    response = client.get(reverse("job-detail", args=[job.id]))

    assert response.status_code == 200
    content = response.content.decode()
    assert _title_source_link_count(content, "Data Engineer", source_url) == 2
    assert 'target="_blank"' in content
    assert 'rel="noopener"' in content


@pytest.mark.django_db
def test_job_detail_title_is_plain_text_when_source_url_is_missing(client, company):
    job = JobPost.objects.create(company=company, title="Manual Data Engineer")

    response = client.get(reverse("job-detail", args=[job.id]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Manual Data Engineer" in content
    assert not _title_has_any_link(content, "Manual Data Engineer")


@pytest.mark.django_db
def test_job_detail_formats_created_and_updated_timestamps(client, company):
    job = JobPost.objects.create(company=company, title="Timestamp Detail Job")

    response = client.get(reverse("job-detail", args=[job.id]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Created At" in content
    assert "Updated At" in content
    assert _display_timestamp(job.created_at) in content
    assert _display_timestamp(job.updated_at) in content
    assert "<time" in content


@pytest.mark.django_db
def test_application_detail_renders_skill_sets_and_job_type(client, user, company):
    job = JobPost.objects.create(
        company=company,
        title="Frontend Engineer",
        employment_type="Internship",
    )
    application = Application.objects.create(user=user, job_post=job)
    job_skill = SkillSet.objects.create(name="React")
    application_skill = SkillSet.objects.create(name="TypeScript")
    JobPostSkill.objects.create(job_post=job, skill_set=job_skill, score=90)
    ApplicationSkill.objects.create(
        application=application,
        skill_set=application_skill,
        score=85,
    )

    response = client.get(reverse("application-detail", args=[application.id]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Job Type" in content
    assert "Internship" in content
    assert "Application Skill Sets" in content
    assert "TypeScript" in content
    assert "Job Skill Sets" in content
    assert "React" in content


@pytest.mark.django_db
def test_job_type_is_present_in_form_and_survives_create_update(company):
    form = JobPostForm(
        data={
            "company": company.id,
            "title": "ML Intern",
            "source_url": "",
            "external_id": "",
            "source_type": JobPost.SourceType.MANUAL,
            "status": JobPost.StatusChoices.ACTIVE,
            "location": "San Francisco",
            "remote_type": "",
            "employment_type": "Internship",
            "salary_min": "",
            "salary_max": "",
            "description": "",
            "tags": "",
        }
    )

    assert form.fields["employment_type"].label == "Job Type"
    assert form.is_valid(), form.errors
    job = form.save()
    assert job.employment_type == "Internship"
    assert job.job_type == "Internship"

    update_form = JobPostForm(
        data={
            "company": company.id,
            "title": "ML Intern",
            "source_url": "",
            "external_id": "",
            "source_type": JobPost.SourceType.MANUAL,
            "status": JobPost.StatusChoices.ACTIVE,
            "location": "San Francisco",
            "remote_type": "",
            "employment_type": "Full-time",
            "salary_min": "",
            "salary_max": "",
            "description": "",
            "tags": "",
        },
        instance=job,
    )

    assert update_form.is_valid(), update_form.errors
    updated_job = update_form.save()
    assert updated_job.employment_type == "Full-time"
    assert updated_job.job_type_display == "Full Time"


@pytest.mark.django_db
def test_job_form_creates_manual_skill_sets_from_keywords(company):
    form = JobPostForm(
        data={
            "company": company.id,
            "title": "Backend Engineer",
            "source_url": "",
            "external_id": "",
            "source_type": JobPost.SourceType.MANUAL,
            "status": JobPost.StatusChoices.ACTIVE,
            "location": "",
            "remote_type": "",
            "employment_type": "Full-time",
            "salary_min": "",
            "salary_max": "",
            "description": "",
            "tags": "",
            "skill_keywords": "Python, Django\nSQL, python",
        }
    )

    assert form.is_valid(), form.errors
    job = form.save()

    assert set(job.skill_sets.values_list("name", flat=True)) == {
        "Python",
        "Django",
        "SQL",
    }
    assert (
        JobPostSkill.objects.filter(
            job_post=job,
            source_type=SkillAttachmentSource.MANUAL,
        ).count()
        == 3
    )
    assert SkillSet.objects.get(name="Python").auto_created is False


@pytest.mark.django_db
def test_job_form_keyword_analysis_marks_existing_and_new_keywords(company):
    SkillSet.objects.create(name="Python", aliases=["Py"])
    form = JobPostForm(
        data={
            "company": company.id,
            "title": "Backend Engineer",
            "source_url": "",
            "external_id": "",
            "source_type": JobPost.SourceType.MANUAL,
            "status": JobPost.StatusChoices.ACTIVE,
            "location": "",
            "remote_type": "",
            "employment_type": "",
            "salary_min": "",
            "salary_max": "",
            "description": "",
            "tags": "",
            "skill_keywords": " py, Rust\nPY ",
        }
    )

    assert form.is_valid(), form.errors
    assert form.keyword_analysis == [
        {
            "raw_text": "py",
            "normalized_text": "py",
            "exists": True,
            "skill_set_id": SkillSet.objects.get(name="Python").id,
            "skill_set_name": "Python",
            "status": SkillKeyword.StatusChoices.ACTIVE,
            "source": SkillKeyword.SourceChoices.ALIAS,
        },
        {
            "raw_text": "Rust",
            "normalized_text": "rust",
            "exists": False,
            "skill_set_id": None,
            "skill_set_name": "",
            "status": "",
            "source": "",
        },
    ]
    assert form.existing_keyword_warning == (
        "Existing SkillSet keywords reused: py (Python)"
    )


@pytest.mark.django_db
def test_job_form_renders_live_keyword_preview_data(client):
    SkillSet.objects.create(name="Python", aliases=["Py"])

    response = client.get(reverse("job-create"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "data-skill-keyword-preview" in content
    assert "skill-keyword-existing-data" in content
    assert "normalized_text" in content
    assert "py" in content
    assert "already exists" in content
    assert "new" in content


@pytest.mark.django_db
def test_job_form_save_warns_for_existing_keywords_and_still_saves(client, company):
    python = SkillSet.objects.create(name="Python", aliases=["Py"])

    response = client.post(
        reverse("job-create"),
        data={
            "company": company.id,
            "title": "Backend Engineer",
            "source_url": "",
            "external_id": "",
            "source_type": JobPost.SourceType.MANUAL,
            "status": JobPost.StatusChoices.ACTIVE,
            "location": "",
            "remote_type": "",
            "employment_type": "",
            "salary_min": "",
            "salary_max": "",
            "description": "",
            "tags": "",
            "skill_keywords": "Py, Rust",
        },
    )

    assert response.status_code == 302
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert messages == ["Existing SkillSet keywords reused: Py (Python)"]
    job = JobPost.objects.get(title="Backend Engineer")
    assert set(job.skill_sets.values_list("name", flat=True)) == {"Python", "Rust"}
    assert JobPostSkill.objects.filter(job_post=job, skill_set=python).exists()


@pytest.mark.django_db
def test_job_form_updates_manual_skill_keywords_without_touching_ollama_links(company):
    job = JobPost.objects.create(company=company, title="Platform Engineer")
    python = SkillSet.objects.create(name="Python")
    django = SkillSet.objects.create(name="Django")
    JobPostSkill.objects.create(
        job_post=job,
        skill_set=python,
        source_type=SkillAttachmentSource.MANUAL,
    )
    JobPostSkill.objects.create(
        job_post=job,
        skill_set=django,
        score=91,
        source_type=SkillAttachmentSource.OLLAMA_PIPELINE,
    )

    form = JobPostForm(
        data={
            "company": company.id,
            "title": "Platform Engineer",
            "source_url": "",
            "external_id": "",
            "source_type": JobPost.SourceType.MANUAL,
            "status": JobPost.StatusChoices.ACTIVE,
            "location": "",
            "remote_type": "",
            "employment_type": "",
            "salary_min": "",
            "salary_max": "",
            "description": "",
            "tags": "",
            "skill_keywords": "Go, Django",
        },
        instance=job,
    )

    assert form.is_valid(), form.errors
    form.save()

    assert set(job.skill_sets.values_list("name", flat=True)) == {"Django", "Go"}
    assert not JobPostSkill.objects.filter(job_post=job, skill_set=python).exists()
    django_link = JobPostSkill.objects.get(job_post=job, skill_set=django)
    assert django_link.source_type == SkillAttachmentSource.OLLAMA_PIPELINE
    assert django_link.score == 91
    assert (
        JobPostSkill.objects.get(
            job_post=job,
            skill_set__name="Go",
        ).source_type
        == SkillAttachmentSource.MANUAL
    )


@pytest.mark.django_db
def test_job_form_prefills_manual_skill_keywords(company):
    job = JobPost.objects.create(company=company, title="Platform Engineer")
    skill = SkillSet.objects.create(name="Python")
    JobPostSkill.objects.create(
        job_post=job,
        skill_set=skill,
        source_type=SkillAttachmentSource.MANUAL,
    )

    form = JobPostForm(instance=job)

    assert form.fields["skill_keywords"].initial == "Python"


@pytest.mark.django_db
def test_job_type_and_skill_sets_are_exposed_in_api_response(client, user, company):
    job = JobPost.objects.create(
        company=company,
        title="Data Engineer",
        employment_type="Full-time",
    )
    skill = SkillSet.objects.create(name="SQL")
    JobPostSkill.objects.create(job_post=job, skill_set=skill, score=92)
    client.force_login(user)

    response = client.get(f"/api/jobs/{job.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["employment_type"] == "Full-time"
    assert payload["job_type"] == "Full-time"
    assert payload["skill_set_names"] == ["SQL"]


@pytest.mark.django_db
def test_job_type_serializer_input_maps_to_employment_type(company):
    serializer = JobPostSerializer(
        data={
            "company": company.id,
            "title": "AI Engineer",
            "job_type": "Full Time",
        }
    )

    assert serializer.is_valid(), serializer.errors
    job = serializer.save()
    assert job.employment_type == "Full-time"
    assert job.job_type == "Full-time"


@pytest.mark.django_db
def test_m2m_skill_sets_access_does_not_break(company):
    job = JobPost.objects.create(company=company, title="Platform Engineer")
    skill = SkillSet.objects.create(name="Django")
    JobPostSkill.objects.create(job_post=job, skill_set=skill, score=88)

    assert list(job.skill_sets.values_list("name", flat=True)) == ["Django"]
    assert job.skill_set_names == ["Django"]
    assert job.skill_set_display == "Django"
