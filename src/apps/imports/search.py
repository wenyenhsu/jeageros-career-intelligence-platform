from django.db.models import Case, CharField, Q, TextField, Value, When
from django.db.models.functions import Cast

from apps.common.search import (
    annotate_datetime_search_fields,
    build_datetime_search_filter,
    clean_search_query,
    combine_token_filters,
    search_tokens,
)

from .models import JobSource

SOURCE_DATETIME_SEARCH_FIELDS = {
    "source_last_crawled_at_search": "last_crawled_at",
}


def filter_job_sources_for_search(queryset, query):
    query = clean_search_query(query)
    if not query:
        return queryset

    queryset = annotate_datetime_search_fields(queryset, SOURCE_DATETIME_SEARCH_FIELDS)
    queryset = queryset.annotate(
        filter_config_search=Cast("filter_config", output_field=TextField()),
        crawl_config_search=Cast("crawl_config", output_field=TextField()),
        status_search=Case(
            When(enabled=True, then=Value("Enabled")),
            default=Value("Disabled"),
            output_field=CharField(),
        ),
    )
    filters = combine_token_filters(
        search_tokens(query),
        build_job_source_search_filter,
    )
    return queryset.filter(filters).distinct()


def build_job_source_search_filter(query):
    query = clean_search_query(query)
    normalized = query.casefold()

    filters = (
        Q(name__icontains=query)
        | Q(base_url__icontains=query)
        | Q(notes__icontains=query)
        | Q(resource__icontains=query)
        | Q(status_search__icontains=query)
        | Q(filter_config_search__icontains=query)
        | Q(crawl_config_search__icontains=query)
        | build_datetime_search_filter(
            query,
            field_names=("last_crawled_at",),
            annotation_names=SOURCE_DATETIME_SEARCH_FIELDS.keys(),
        )
    )

    for value, label in JobSource.Resource.choices:
        if normalized in label.casefold():
            filters |= Q(resource=value)

    return filters
