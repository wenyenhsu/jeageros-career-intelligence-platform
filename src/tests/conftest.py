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
