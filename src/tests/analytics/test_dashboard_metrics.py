import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_dashboard_status_code(client):
    response = client.get(reverse('dashboard'))
    assert response.status_code == 200
