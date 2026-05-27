import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_job_url_import(client):
    response = client.get(reverse('job-url-import'))
    assert response.status_code == 200
