from django.db.models import Q

from apps.common.search import (
    annotate_datetime_search_fields,
    build_datetime_search_filter,
    clean_search_query,
    combine_token_filters,
    search_tokens,
)


COMPANY_DATETIME_SEARCH_FIELDS = {
    "company_created_at_search": "created_at",
    "company_updated_at_search": "updated_at",
}


def filter_companies_for_search(queryset, query):
    query = clean_search_query(query)
    if not query:
        return queryset
    queryset = annotate_datetime_search_fields(queryset, COMPANY_DATETIME_SEARCH_FIELDS)
    filters = combine_token_filters(search_tokens(query), build_company_search_filter)
    return queryset.filter(filters).distinct()


def build_company_search_filter(query):
    query = clean_search_query(query)
    return (
        Q(name__icontains=query)
        | Q(website__icontains=query)
        | Q(industry__icontains=query)
        | Q(location__icontains=query)
        | Q(notes__icontains=query)
        | build_datetime_search_filter(
            query,
            field_names=("created_at", "updated_at"),
            annotation_names=COMPANY_DATETIME_SEARCH_FIELDS.keys(),
        )
    )
