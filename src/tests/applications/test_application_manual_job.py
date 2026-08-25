import pytest
from django.urls import reverse

from apps.applications.forms import ApplicationForm
from apps.applications.models import Application
from apps.companies.models import Company
from apps.jobs.models import JobPost


def _create_data(user, **overrides):
    data = {
        "user": user.pk,
        "status": Application.Status.SAVED,
        "priority": 3,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_create_page_shows_manual_job_fields(client):
    response = client.get(reverse("application-create"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "New job" in content
    assert 'name="company"' in content
    assert 'name="job_title"' in content
    assert "Type a company name" in content
    assert 'name="priority"' in content
    assert 'class="form-select"' in content
    assert ">1 — Highest<" in content
    assert ">3 — Medium<" in content
    assert ">5 — Lowest<" in content
    assert 'type="number"' not in content
    assert 'name="materials_pack"' in content
    assert ">Select<" in content
    assert 'value="AI"' in content
    assert 'value="INFRA"' in content
    assert "Copies the AI or Infra pack, then tailors the cover letter" in content


@pytest.mark.django_db
def test_priority_field_is_a_dropdown():
    form = ApplicationForm()
    widget = form.fields["priority"].widget

    assert widget.input_type == "select"
    assert list(form.fields["priority"].choices) == list(Application.Priority.choices)


@pytest.mark.django_db
def test_form_rejects_priority_outside_one_to_five(user, job):
    form = ApplicationForm(
        data=_create_data(user, job_post=job.pk, priority=9),
    )

    assert not form.is_valid()
    assert "priority" in form.errors


@pytest.mark.django_db
def test_edit_page_does_not_show_manual_job_fields(client, application):
    response = client.get(reverse("application-update", args=[application.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "New job" not in content
    assert 'name="company"' not in content
    assert 'name="job_title"' not in content


@pytest.mark.django_db
def test_form_creates_company_and_job_when_no_job_post_selected(user):
    form = ApplicationForm(
        data=_create_data(
            user,
            company="Anthropic",
            job_title="Research Engineer",
            location="Remote",
            job_type="Full-time",
            source_url="https://example.com/jobs/research-engineer",
        ),
        allow_manual_job=True,
    )

    assert form.is_valid(), form.errors
    application = form.save()

    assert application.job_post.title == "Research Engineer"
    assert application.job_post.company.name == "Anthropic"
    assert application.job_post.location == "Remote"
    assert application.job_post.job_type == "Full-time"
    assert application.job_post.source_type == JobPost.SourceType.MANUAL
    assert Company.objects.filter(name="Anthropic").exists()


@pytest.mark.django_db
def test_form_reuses_existing_job_by_company_and_title(user, job, company):
    form = ApplicationForm(
        data=_create_data(
            user,
            company=company.name,
            job_title=job.title,
        ),
        allow_manual_job=True,
    )

    assert form.is_valid(), form.errors
    application = form.save()

    assert application.job_post_id == job.id
    assert JobPost.objects.filter(company=company, title=job.title).count() == 1


@pytest.mark.django_db
def test_form_requires_company_and_title_when_job_post_is_blank(user):
    form = ApplicationForm(
        data=_create_data(user),
        allow_manual_job=True,
    )

    assert not form.is_valid()
    assert "company" in form.errors
    assert "job_title" in form.errors


@pytest.mark.django_db
def test_form_rejects_google_drive_url_as_job_url(user):
    form = ApplicationForm(
        data=_create_data(
            user,
            company="OpenAI",
            job_title="Intern",
            source_url="https://drive.google.com/drive/folders/abc123",
        ),
        allow_manual_job=True,
    )

    assert not form.is_valid()
    assert "source_url" in form.errors


@pytest.mark.django_db
def test_create_view_saves_manual_job_application(client, user):
    response = client.post(
        reverse("application-create"),
        data=_create_data(
            user,
            company="Stripe",
            job_title="Software Engineer",
            location="South San Francisco",
        ),
    )

    assert response.status_code == 302
    application = Application.objects.get(user=user)
    assert application.job_post.title == "Software Engineer"
    assert application.job_post.company.name == "Stripe"
    assert application.company_display == "Stripe"
