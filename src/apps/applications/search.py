from django.db.models import Q

from apps.jobs.models import JobPost
from apps.jobs.search import clean_search_query
from apps.skills.models import SkillKeyword


def filter_applications_for_search(queryset, query):
    query = clean_search_query(query)
    if not query:
        return queryset
    return queryset.filter(build_application_search_filter(query)).distinct()


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
