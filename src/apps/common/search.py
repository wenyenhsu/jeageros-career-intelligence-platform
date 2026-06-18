import re
from datetime import date

from django.db.models import CharField, Q
from django.db.models.functions import Cast


MONTH_LOOKUP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def clean_search_query(query):
    return " ".join(str(query or "").split()).strip()


def search_tokens(query):
    query = clean_search_query(query)
    if not query:
        return []

    tokens = []
    seen = set()
    for token in re.split(r"[\s,]+", query):
        token = token.strip(" \t\r\n,;()[]{}")
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        tokens.append(token)
        seen.add(key)
    return tokens


def combine_token_filters(tokens, build_filter):
    filters = Q()
    for token in tokens:
        filters &= build_filter(token)
    return filters


def annotate_datetime_search_fields(queryset, field_map):
    annotations = {
        alias: Cast(field_name, output_field=CharField())
        for alias, field_name in field_map.items()
    }
    return queryset.annotate(**annotations) if annotations else queryset


def build_datetime_search_filter(query, field_names, annotation_names=()):
    query = clean_search_query(query)
    if not query or not _looks_like_datetime_query(query):
        return Q()

    filters = Q()
    if _should_search_cast_datetime(query):
        for annotation_name in annotation_names:
            filters |= Q(**{f"{annotation_name}__icontains": query})

    parsed_date = _parse_iso_date(query)
    if parsed_date:
        for field_name in field_names:
            filters |= Q(**{f"{field_name}__date": parsed_date})

    normalized = query.casefold()
    if normalized in MONTH_LOOKUP:
        for field_name in field_names:
            filters |= Q(**{f"{field_name}__month": MONTH_LOOKUP[normalized]})

    if re.fullmatch(r"\d{4}", query):
        for field_name in field_names:
            filters |= Q(**{f"{field_name}__year": int(query)})

    return filters


def _looks_like_datetime_query(value):
    normalized = value.casefold()
    return (
        normalized in MONTH_LOOKUP
        or bool(re.fullmatch(r"\d{4}", value))
        or bool(re.search(r"\d{4}-\d{1,2}-\d{1,2}", value))
        or ":" in value
    )


def _should_search_cast_datetime(value):
    return ":" in value or "-" in value


def _parse_iso_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
