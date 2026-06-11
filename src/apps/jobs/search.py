from django.db.models import Q

from apps.skills.models import SkillKeyword

from .models import JobPost


def filter_jobs_for_search(queryset, query):
    query = clean_search_query(query)
    if not query:
        return queryset
    return queryset.filter(build_job_search_filter(query)).distinct()


def clean_search_query(query):
    return " ".join(str(query or "").split()).strip()


def build_job_search_filter(query):
    query = clean_search_query(query)
    normalized_keyword = SkillKeyword.normalize_keyword(query)
    normalized_job_type = JobPost.normalize_job_type(query)

    filters = (
        Q(title__icontains=query)
        | Q(company__name__icontains=query)
        | Q(location__icontains=query)
        | Q(remote_type__icontains=query)
        | Q(employment_type__icontains=query)
    )

    if normalized_job_type and normalized_job_type != query:
        filters |= Q(employment_type__icontains=normalized_job_type)

    if normalized_keyword:
        filters |= (
            Q(skill_sets__name__icontains=query)
            | Q(skill_sets__normalized_name__icontains=normalized_keyword)
            | Q(
                skill_sets__keywords__raw_text__icontains=query,
                skill_sets__keywords__status=SkillKeyword.StatusChoices.ACTIVE,
            )
            | Q(
                skill_sets__keywords__normalized_text__icontains=normalized_keyword,
                skill_sets__keywords__status=SkillKeyword.StatusChoices.ACTIVE,
            )
        )

    return filters
