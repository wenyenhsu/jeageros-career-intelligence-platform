from datetime import UTC, datetime

import pytest
from django.urls import reverse

from apps.companies.models import Company


@pytest.fixture
def searchable_companies():
    data_company = Company.objects.create(
        name="Anthropic",
        website="https://anthropic.com",
        industry="AI Research",
        location="San Francisco",
        notes="Frontier model company",
    )
    finance_company = Company.objects.create(
        name="Stripe",
        website="https://stripe.com",
        industry="Payments",
        location="Remote",
        notes="Financial infrastructure",
    )
    return {
        "data_company": data_company,
        "finance_company": finance_company,
    }


@pytest.mark.django_db
def test_company_search_by_partial_keyword_works(client, searchable_companies):
    response = client.get(reverse("company-list"), {"q": "anth"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Anthropic" in content
    assert "Stripe" not in content


@pytest.mark.django_db
def test_company_search_form_supports_auto_search(client, searchable_companies):
    response = client.get(reverse("company-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "data-auto-search-form" in content
    assert "data-auto-search-input" in content


@pytest.mark.django_db
def test_company_search_by_date_works(client, searchable_companies):
    Company.objects.filter(pk=searchable_companies["data_company"].pk).update(
        created_at=datetime(2026, 6, 18, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 6, 18, 9, 5, tzinfo=UTC),
    )
    Company.objects.filter(pk=searchable_companies["finance_company"].pk).update(
        created_at=datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 10, 9, 5, tzinfo=UTC),
    )

    response = client.get(reverse("company-list"), {"q": "2026-06-18"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Anthropic" in content
    assert "Stripe" not in content


@pytest.mark.django_db
def test_company_search_short_number_does_not_match_dates(client):
    Company.objects.create(name="11:11 Media")
    timestamp_only_company = Company.objects.create(name="Delsys")
    Company.objects.filter(pk=timestamp_only_company.pk).update(
        created_at=datetime(2026, 6, 11, 11, 0, tzinfo=UTC),
        updated_at=datetime(2026, 6, 11, 11, 5, tzinfo=UTC),
    )

    response = client.get(reverse("company-list"), {"q": "11"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "11:11 Media" in content
    assert "Delsys" not in content


@pytest.mark.django_db
def test_company_search_empty_state_is_search_specific(client, searchable_companies):
    response = client.get(reverse("company-list"), {"q": "no-match"})

    assert response.status_code == 200
    content = response.content.decode()
    assert 'No companies match "no-match"' in content
    assert "Create your first company" not in content


@pytest.mark.django_db
def test_company_api_search_matches_list_behavior(client, user, searchable_companies):
    client.force_login(user)

    response = client.get("/api/companies/", {"q": "anth"})

    assert response.status_code == 200
    payload = response.json()
    assert [company["name"] for company in payload] == ["Anthropic"]
