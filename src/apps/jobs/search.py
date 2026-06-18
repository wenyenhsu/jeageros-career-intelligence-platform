from django.db.models import Q

from apps.common.search import (
    annotate_datetime_search_fields,
    build_datetime_search_filter,
    clean_search_query,
    combine_token_filters,
    search_tokens,
)
from apps.skills.models import SkillKeyword

from .models import JobPost


JOB_DATETIME_SEARCH_FIELDS = {
    "job_created_at_search": "created_at",
    "job_updated_at_search": "updated_at",
    "job_last_synced_at_search": "last_synced_at",
}


def filter_jobs_for_search(queryset, query):
    query = clean_search_query(query)
    if not query:
        return queryset
    queryset = annotate_datetime_search_fields(queryset, JOB_DATETIME_SEARCH_FIELDS)
    filters = combine_token_filters(search_tokens(query), build_job_search_filter)
    return queryset.filter(filters).distinct()


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
        | Q(status__icontains=query)
        | build_datetime_search_filter(
            query,
            field_names=("created_at", "updated_at", "last_synced_at"),
            annotation_names=JOB_DATETIME_SEARCH_FIELDS.keys(),
        )
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
