import pytest
from apps.companies.models import Company


@pytest.mark.django_db
def test_create_company():
    company = Company.objects.create(name='OpenAI')
    assert company.name == 'OpenAI'
