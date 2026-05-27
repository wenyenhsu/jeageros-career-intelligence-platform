import pytest
from apps.jobs.models import JobPost


@pytest.mark.django_db
def test_job_post_str(company):
    job = JobPost.objects.create(company=company, title='Backend Engineer')
    assert str(job) == 'OpenAI - Backend Engineer'
