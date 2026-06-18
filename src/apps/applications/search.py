from django.db.models import Q

from apps.common.search import (
    annotate_datetime_search_fields,
    build_datetime_search_filter,
    clean_search_query,
    combine_token_filters,
    search_tokens,
)
from apps.jobs.models import JobPost
from apps.skills.models import SkillKeyword


APPLICATION_DATETIME_SEARCH_FIELDS = {
    "application_created_at_search": "created_at",
    "application_updated_at_search": "updated_at",
    "application_last_updated_at_search": "last_updated_at",
    "application_applied_at_search": "applied_at",
    "application_job_created_at_search": "job_post__created_at",
    "application_job_updated_at_search": "job_post__updated_at",
    "application_job_last_synced_at_search": "job_post__last_synced_at",
}


def filter_applications_for_search(queryset, query):
    query = clean_search_query(query)
    if not query:
        return queryset
    queryset = annotate_datetime_search_fields(
        queryset,
        APPLICATION_DATETIME_SEARCH_FIELDS,
    )
    filters = combine_token_filters(
        search_tokens(query),
        build_application_search_filter,
    )
    return queryset.filter(filters).distinct()


def build_application_search_filter(query):
    query = clean_search_query(query)
    normalized_keyword = SkillKeyword.normalize_keyword(query)
    normalized_job_type = JobPost.normalize_job_type(query)

    filters = (
        Q(job_post__title__icontains=query)
        | Q(job_post__company__name__icontains=query)
        | Q(job_post__location__icontains=query)
        | Q(job_post__remote_type__icontains=query)
        | Q(job_post__employment_type__icontains=query)
        | Q(status__icontains=query)
        | build_datetime_search_filter(
            query,
            field_names=(
                "created_at",
                "updated_at",
                "last_updated_at",
                "applied_at",
                "job_post__created_at",
                "job_post__updated_at",
                "job_post__last_synced_at",
            ),
            annotation_names=APPLICATION_DATETIME_SEARCH_FIELDS.keys(),
        )
    )

    if normalized_job_type and normalized_job_type != query:
        filters |= Q(job_post__employment_type__icontains=normalized_job_type)

    if normalized_keyword:
        filters |= (
            Q(skill_sets__name__icontains=query)
            | Q(skill_sets__normalized_name__icontains=normalized_keyword)
            | Q(job_post__skill_sets__name__icontains=query)
            | Q(job_post__skill_sets__normalized_name__icontains=normalized_keyword)
            | Q(
                skill_sets__keywords__raw_text__icontains=query,
                skill_sets__keywords__status=SkillKeyword.StatusChoices.ACTIVE,
            )
            | Q(
                skill_sets__keywords__normalized_text__icontains=normalized_keyword,
                skill_sets__keywords__status=SkillKeyword.StatusChoices.ACTIVE,
            )
            | Q(
                job_post__skill_sets__keywords__raw_text__icontains=query,
                job_post__skill_sets__keywords__status=SkillKeyword.StatusChoices.ACTIVE,
            )
            | Q(
                job_post__skill_sets__keywords__normalized_text__icontains=normalized_keyword,
                job_post__skill_sets__keywords__status=SkillKeyword.StatusChoices.ACTIVE,
            )
        )

    return filters
