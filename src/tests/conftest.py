import pytest
from django.contrib.auth import get_user_model
from apps.companies.models import Company
from apps.jobs.models import JobPost
from apps.applications.models import Application


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username='tester', password='pass12345')


@pytest.fixture
def company(db):
    return Company.objects.create(name='OpenAI', website='https://openai.com')


@pytest.fixture
def job(db, company):
    return JobPost.objects.create(company=company, title='Backend Engineer')


@pytest.fixture
def application(db, user, job):
    return Application.objects.create(user=user, job_post=job)


@pytest.fixture(autouse=True)
def application_materials_root(settings, tmp_path):
    root = tmp_path / "applications"
    root.mkdir()
    settings.APPLICATION_MATERIALS_ROOT = root
    settings.RESUME_TEMPLATE_ROOT = tmp_path / "resume_golden_template"
    settings.RESUME_TEMPLATE_ROOT.mkdir(exist_ok=True)
    settings.GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE = ""
    settings.GOOGLE_DRIVE_PARENT_FOLDER_ID = ""
    return root
