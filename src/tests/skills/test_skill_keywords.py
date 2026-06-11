import pytest
from django.urls import reverse

from apps.applications.models import Application
from apps.jobs.models import JobPost
from apps.skills.models import (
    ApplicationSkill,
    JobPostSkill,
    SkillKeyword,
    SkillSet,
)


@pytest.mark.django_db
def test_skill_keyword_normalization_and_deduplication():
    skillset = SkillSet.objects.create(
        name="JavaScript",
        aliases=[" JS ", "js", "ECMAScript"],
    )

    keywords = {
        keyword.normalized_text: keyword
        for keyword in SkillKeyword.objects.filter(skill_set=skillset)
    }

    assert set(keywords) == {"javascript", "js", "ecmascript"}
    assert keywords["javascript"].raw_text == "JavaScript"
    assert keywords["javascript"].is_primary is True
    assert keywords["js"].raw_text == "JS"
    assert keywords["js"].source == SkillKeyword.SourceChoices.ALIAS


@pytest.mark.django_db
def test_skill_keyword_links_to_skillset():
    skillset = SkillSet.objects.create(name="Python")
    keyword = SkillKeyword.ensure_for_skillset(
        skillset,
        " Py ",
        source=SkillKeyword.SourceChoices.MANUAL,
    )

    assert keyword.skill_set == skillset
    assert keyword.raw_text == "Py"
    assert keyword.normalized_text == "py"
    assert skillset.keywords.filter(normalized_text="py").exists()


@pytest.mark.django_db
def test_job_form_keyword_uses_existing_skill_keyword_alias(company):
    skillset = SkillSet.objects.create(name="Python", aliases=["Py"])

    from apps.jobs.forms import JobPostForm

    form = JobPostForm(
        data={
            "company": company.id,
            "title": "Backend Engineer",
            "source_url": "",
            "external_id": "",
            "source_type": JobPost.SourceType.MANUAL,
            "status": JobPost.StatusChoices.ACTIVE,
            "location": "",
            "remote_type": "",
            "employment_type": "",
            "salary_min": "",
            "salary_max": "",
            "description": "",
            "tags": "",
            "skill_keywords": "py",
        }
    )

    assert form.is_valid(), form.errors
    job = form.save()

    assert list(job.skill_sets.all()) == [skillset]
    assert SkillSet.objects.count() == 1


@pytest.mark.django_db
def test_job_search_uses_normalized_skill_keywords(client, company):
    python = SkillSet.objects.create(name="Python", aliases=["Py"])
    django = SkillSet.objects.create(name="Django")
    matching_job = JobPost.objects.create(company=company, title="Backend Engineer")
    other_job = JobPost.objects.create(company=company, title="Frontend Engineer")
    JobPostSkill.objects.create(job_post=matching_job, skill_set=python)
    JobPostSkill.objects.create(job_post=other_job, skill_set=django)

    response = client.get(reverse("job-list"), {"q": "py"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Backend Engineer" in content
    assert "Frontend Engineer" not in content


@pytest.mark.django_db
def test_application_search_uses_application_and_job_skill_keywords(
    client,
    user,
    company,
):
    python = SkillSet.objects.create(name="Python", aliases=["Py"])
    react = SkillSet.objects.create(name="React", aliases=["React.js"])
    python_job = JobPost.objects.create(company=company, title="Backend Engineer")
    react_job = JobPost.objects.create(company=company, title="Frontend Engineer")
    python_application = Application.objects.create(user=user, job_post=python_job)
    react_application = Application.objects.create(user=user, job_post=react_job)
    JobPostSkill.objects.create(job_post=python_job, skill_set=python)
    ApplicationSkill.objects.create(application=react_application, skill_set=react)

    job_skill_response = client.get(reverse("application-list"), {"q": "py"})
    app_skill_response = client.get(reverse("application-list"), {"q": "react.js"})

    assert job_skill_response.status_code == 200
    assert "Backend Engineer" in job_skill_response.content.decode()
    assert "Frontend Engineer" not in job_skill_response.content.decode()
    assert app_skill_response.status_code == 200
    assert "Frontend Engineer" in app_skill_response.content.decode()
    assert "Backend Engineer" not in app_skill_response.content.decode()
    assert Application.objects.filter(id=python_application.id).exists()


@pytest.mark.django_db
def test_api_job_search_uses_normalized_skill_keywords(client, user, company):
    skillset = SkillSet.objects.create(name="Python", aliases=["Py"])
    job = JobPost.objects.create(company=company, title="Backend Engineer")
    other_job = JobPost.objects.create(company=company, title="Frontend Engineer")
    JobPostSkill.objects.create(job_post=job, skill_set=skillset)
    client.force_login(user)

    response = client.get("/api/jobs/", {"q": "py"})

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [job.id]
    assert payload[0]["skill_keywords"] == ["Python", "Py"]
    assert other_job.id not in [item["id"] for item in payload]


@pytest.mark.django_db
def test_api_skill_keyword_search_uses_normalized_keywords(client, user):
    SkillSet.objects.create(name="Python", aliases=["Py"])
    SkillSet.objects.create(name="Django")
    client.force_login(user)

    response = client.get("/api/skill-keywords/", {"q": "py"})

    assert response.status_code == 200
    payload = response.json()
    normalized_keywords = {item["normalized_text"] for item in payload}
    assert {"python", "py"} == normalized_keywords
    assert "django" not in normalized_keywords
