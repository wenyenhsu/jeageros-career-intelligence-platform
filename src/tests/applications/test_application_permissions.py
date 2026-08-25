import json

import pytest
from django.urls import reverse

from apps.analytics.services.dashboard_service import DashboardService
from apps.applications.models import Application
from apps.companies.models import Company
from apps.jobs.models import JobPost


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name",
    [
        "dashboard",
        "analytics-dashboard",
        "application-list",
        "application-create",
        "job-list",
        "job-create",
        "company-list",
        "company-create",
        "source-list",
        "source-create",
        "monitoring-dashboard",
    ],
)
def test_primary_web_pages_redirect_anonymous_users(anonymous_client, url_name):
    response = anonymous_client.get(reverse(url_name))

    assert response.status_code == 302
    assert response.url.startswith(f"{reverse('login')}?next=")


@pytest.mark.django_db
def test_regular_user_only_sees_owned_applications(
    client,
    user,
    job,
    django_user_model,
):
    own_application = Application.objects.create(user=user, job_post=job)
    other_user = django_user_model.objects.create_user(
        username="other",
        password="pass12345",
    )
    other_job = JobPost.objects.create(
        company=job.company,
        title="Private Role",
    )
    other_application = Application.objects.create(
        user=other_user,
        job_post=other_job,
    )

    list_response = client.get(reverse("application-list"))
    detail_response = client.get(
        reverse("application-detail", args=[other_application.pk])
    )
    delete_response = client.post(
        reverse("application-delete", args=[other_application.pk])
    )

    content = list_response.content.decode()
    assert list_response.status_code == 200
    assert own_application.job_post.title in content
    assert other_application.job_post.title not in content
    assert detail_response.status_code == 404
    assert delete_response.status_code == 404
    assert Application.objects.filter(pk=other_application.pk).exists()


@pytest.mark.django_db
def test_regular_user_cannot_choose_application_owner(
    client,
    user,
    job,
    django_user_model,
):
    other_user = django_user_model.objects.create_user(
        username="other",
        password="pass12345",
    )

    page_response = client.get(reverse("application-create"))
    create_response = client.post(
        reverse("application-create"),
        data={
            "user": other_user.pk,
            "job_post": job.pk,
            "status": Application.Status.SAVED,
            "priority": Application.Priority.MEDIUM,
        },
    )

    assert page_response.status_code == 200
    assert 'name="user"' not in page_response.content.decode()
    assert create_response.status_code == 302
    application = Application.objects.get(job_post=job)
    assert application.user == user


@pytest.mark.django_db
def test_application_api_enforces_owner_on_list_create_and_update(
    client,
    user,
    company,
    django_user_model,
):
    other_user = django_user_model.objects.create_user(
        username="other",
        password="pass12345",
    )
    own_job = JobPost.objects.create(company=company, title="Owned Role")
    other_job = JobPost.objects.create(company=company, title="Other Role")
    new_job = JobPost.objects.create(company=company, title="New Role")
    own_application = Application.objects.create(user=user, job_post=own_job)
    other_application = Application.objects.create(user=other_user, job_post=other_job)

    list_response = client.get("/api/applications/")
    other_detail_response = client.get(
        f"/api/applications/{other_application.pk}/"
    )
    create_response = client.post(
        "/api/applications/",
        data=json.dumps(
            {
                "user": other_user.pk,
                "job_post": new_job.pk,
                "status": Application.Status.SAVED,
                "priority": Application.Priority.MEDIUM,
            }
        ),
        content_type="application/json",
    )
    update_response = client.patch(
        f"/api/applications/{own_application.pk}/",
        data=json.dumps({"user": other_user.pk, "priority": Application.Priority.HIGH}),
        content_type="application/json",
    )

    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [own_application.pk]
    assert other_detail_response.status_code == 404
    assert create_response.status_code == 201
    assert Application.objects.get(job_post=new_job).user == user
    assert update_response.status_code == 200
    own_application.refresh_from_db()
    assert own_application.user == user
    assert own_application.priority == Application.Priority.HIGH


@pytest.mark.django_db
def test_dashboard_application_metrics_are_owner_scoped(
    user,
    job,
    django_user_model,
):
    Application.objects.create(user=user, job_post=job)
    other_user = django_user_model.objects.create_user(
        username="other",
        password="pass12345",
    )
    other_company = Company.objects.create(name="Other Company")
    other_job = JobPost.objects.create(company=other_company, title="Other Role")
    Application.objects.create(user=other_user, job_post=other_job)

    summary = DashboardService().operational_summary(user=user)

    assert summary["kpis"]["total_applications"] == 1
    assert [item.user_id for item in summary["recent_applications"]] == [user.id]

