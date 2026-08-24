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
    assert "Leave blank to create a Google Drive folder automatically" in content
    assert 'enctype="multipart/form-data"' not in content
    assert 'name="materials_url"' in content
    assert 'type="url"' not in content
    assert 'name="cover_letter"' not in content
    assert 'name="resume"' not in content


@pytest.mark.django_db
def test_application_list_does_not_show_drive_folder_link(client, application):
    application.materials_url = DRIVE_FOLDER_URL
    application.save()

    response = client.get(reverse("application-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Materials" in content
    assert "Drive" not in content
    assert DRIVE_FOLDER_URL not in content


@pytest.mark.django_db
def test_application_create_view_saves_drive_folder_url(
    client, user, job, application_materials_root
):
    response = client.post(
        reverse("application-create"),
        data=_application_form_data(user, job, materials_url=DRIVE_FOLDER_URL),
    )

    assert response.status_code == 302
    created = Application.objects.get(user=user, job_post=job)
    assert created.materials_url == DRIVE_FOLDER_URL
    assert created.has_materials
    assert (application_materials_root / "openai" / "backend-engineer").is_dir()


CREATED_DRIVE_URL = "https://drive.google.com/drive/folders/auto123"


def _mock_drive_create(monkeypatch, create_folder):
    monkeypatch.setattr(
        "apps.applications.services.google_drive_folder_client.GoogleDriveFolderClient.is_configured",
        lambda self: True,
    )
    monkeypatch.setattr(
        "apps.applications.services.google_drive_folder_client.GoogleDriveFolderClient.create_folder",
        create_folder,
    )


@pytest.mark.django_db
def test_form_save_creates_local_and_drive_folders(user, job, monkeypatch, application_materials_root):
    created_names = []

    def create_folder(self, name):
        created_names.append(name)
        return CREATED_DRIVE_URL

    _mock_drive_create(monkeypatch, create_folder)

    form = ApplicationForm(data=_application_form_data(user, job, materials_url=""))
    assert form.is_valid(), form.errors
    application = form.save()

    local_dir = application_materials_root / "openai" / "backend-engineer"
    assert local_dir.is_dir()
    assert application.materials_url == CREATED_DRIVE_URL
    assert created_names == ["OpenAI - Backend Engineer"]


@pytest.mark.django_db
def test_form_save_keeps_pasted_drive_url_and_still_creates_local_folder(
    user, job, monkeypatch, application_materials_root
):
    def create_folder(self, name):
        raise AssertionError("Drive create should not run when a URL is already set")

    _mock_drive_create(monkeypatch, create_folder)

    form = ApplicationForm(
        data=_application_form_data(user, job, materials_url=DRIVE_FOLDER_URL)
    )
    assert form.is_valid(), form.errors
    application = form.save()

    assert application.materials_url == DRIVE_FOLDER_URL
    assert (application_materials_root / "openai" / "backend-engineer").is_dir()


@pytest.mark.django_db
def test_form_save_keeps_application_when_drive_create_fails(
    user, job, monkeypatch, application_materials_root
):
    def create_folder(self, name):
        raise RuntimeError("Drive API unavailable")

    _mock_drive_create(monkeypatch, create_folder)

    form = ApplicationForm(data=_application_form_data(user, job, materials_url=""))
    assert form.is_valid(), form.errors
    application = form.save()

    application.refresh_from_db()
    assert Application.objects.filter(pk=application.pk).exists()
    assert application.materials_url == ""
    assert (application_materials_root / "openai" / "backend-engineer").is_dir()


@pytest.mark.django_db
def test_form_save_skips_drive_when_credentials_are_missing(
    user, job, monkeypatch, application_materials_root
):
    def create_folder(self, name):
        raise AssertionError("Drive create should not run without credentials")

    monkeypatch.setattr(
        "apps.applications.services.google_drive_folder_client.GoogleDriveFolderClient.create_folder",
        create_folder,
    )

    form = ApplicationForm(data=_application_form_data(user, job, materials_url=""))
    assert form.is_valid(), form.errors
    application = form.save()

    assert application.materials_url == ""
    assert (application_materials_root / "openai" / "backend-engineer").is_dir()


@pytest.mark.django_db
def test_materials_folder_slug_strips_unsafe_path_characters(
    user, company, application_materials_root
):
    from apps.jobs.models import JobPost

    job = JobPost.objects.create(
        company=company,
        title="Backend / Intern!",
    )
    form = ApplicationForm(data=_application_form_data(user, job, materials_url=""))
    assert form.is_valid(), form.errors
    application = form.save()

    local_dir = application_materials_root / "openai" / "backend-intern"
    assert local_dir.is_dir()
    assert application.materials_local_path == str(local_dir)
    assert "/" not in local_dir.name


@pytest.mark.django_db
def test_application_detail_shows_local_folder_path(client, application, application_materials_root):
    response = client.get(reverse("application-detail", args=[application.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Local folder" in content
    assert "openai/backend-engineer" in content.replace("\\", "/")


@pytest.mark.django_db
def test_ensure_application_materials_command_backfills_existing_records(
    application, monkeypatch, application_materials_root
):
    from django.core.management import call_command

    def create_folder(self, name):
        return CREATED_DRIVE_URL

    _mock_drive_create(monkeypatch, create_folder)
    assert application.materials_url == ""

    call_command("ensure_application_materials")

    application.refresh_from_db()
    assert application.materials_url == CREATED_DRIVE_URL
    assert (application_materials_root / "openai" / "backend-engineer").is_dir()


@pytest.mark.django_db
def test_ensure_application_materials_command_does_not_replace_existing_url(
    application, monkeypatch, application_materials_root
):
    from django.core.management import call_command

    application.materials_url = DRIVE_FOLDER_URL
    application.save(update_fields=["materials_url"])

    def create_folder(self, name):
        raise AssertionError("Drive create should not replace an existing URL")

    _mock_drive_create(monkeypatch, create_folder)
    call_command("ensure_application_materials")

    application.refresh_from_db()
    assert application.materials_url == DRIVE_FOLDER_URL
    assert (application_materials_root / "openai" / "backend-engineer").is_dir()

