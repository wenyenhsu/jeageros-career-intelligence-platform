import pytest
from django.urls import reverse

from apps.applications.forms import ApplicationForm
from apps.applications.models import Application

DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/abc123xyz"


def _application_form_data(user, job, **overrides):
    data = {
        "user": user.pk,
        "job_post": job.pk,
        "status": Application.Status.SAVED,
        "priority": 3,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_application_saves_google_drive_folder_url(application):
    application.materials_url = DRIVE_FOLDER_URL
    application.save()
    application.refresh_from_db()

    assert application.has_materials
    assert application.materials_url_display == DRIVE_FOLDER_URL


@pytest.mark.django_db
def test_form_accepts_google_drive_folder_url(user, job):
    form = ApplicationForm(
        data=_application_form_data(user, job, materials_url=DRIVE_FOLDER_URL)
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["materials_url"] == DRIVE_FOLDER_URL


@pytest.mark.django_db
def test_form_normalizes_pasted_drive_url(user, job):
    form = ApplicationForm(
        data=_application_form_data(
            user,
            job,
            materials_url="  drive.google.com/drive/folders/abc123xyz  ",
        )
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["materials_url"] == DRIVE_FOLDER_URL


@pytest.mark.django_db
def test_form_accepts_google_docs_url(user, job):
    docs_url = "https://docs.google.com/document/d/abc123/edit"
    form = ApplicationForm(
        data=_application_form_data(user, job, materials_url=docs_url)
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["materials_url"] == docs_url


@pytest.mark.django_db
def test_form_accepts_blank_materials_url(user, job):
    form = ApplicationForm(data=_application_form_data(user, job, materials_url=""))

    assert form.is_valid(), form.errors
    assert form.cleaned_data["materials_url"] == ""


@pytest.mark.django_db
def test_form_rejects_non_google_drive_url(user, job):
    form = ApplicationForm(
        data=_application_form_data(
            user,
            job,
            materials_url="https://example.com/resume.pdf",
        )
    )

    assert not form.is_valid()
    assert "materials_url" in form.errors


@pytest.mark.django_db
def test_application_detail_links_to_drive_folder(client, application):
    application.materials_url = DRIVE_FOLDER_URL
    application.save()

    response = client.get(reverse("application-detail", args=[application.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Materials" in content
    assert "Open folder" in content
    assert DRIVE_FOLDER_URL in content


@pytest.mark.django_db
def test_application_form_page_uses_drive_url_field(client, application):
    response = client.get(reverse("application-update", args=[application.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Google Drive folder" in content
    assert 'enctype="multipart/form-data"' not in content
    assert 'name="materials_url"' in content
    assert 'type="url"' not in content
    assert 'name="cover_letter"' not in content
    assert 'name="resume"' not in content


@pytest.mark.django_db
def test_application_list_shows_drive_folder_link(client, application):
    application.materials_url = DRIVE_FOLDER_URL
    application.save()

    response = client.get(reverse("application-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Materials" in content
    assert "Drive" in content
    assert f'href="{DRIVE_FOLDER_URL}"' in content


@pytest.mark.django_db
def test_application_create_view_saves_drive_folder_url(client, user, job):
    response = client.post(
        reverse("application-create"),
        data=_application_form_data(user, job, materials_url=DRIVE_FOLDER_URL),
    )

    assert response.status_code == 302
    created = Application.objects.get(user=user, job_post=job)
    assert created.materials_url == DRIVE_FOLDER_URL
    assert created.has_materials
