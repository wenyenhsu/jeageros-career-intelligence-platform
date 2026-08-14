from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
@dataclass(frozen=True)
class InternshipSchedule:
    starts_on: date | None = None
    ends_on: date | None = None
    start_precision: str | None = None
    end_precision: str | None = None
    season: str | None = None
    duration_weeks: int | None = None
    schedule_raw: str | None = None

    def as_canonical_fields(self):
        return {
            "starts_on": self.starts_on.isoformat() if self.starts_on else None,
            "ends_on": self.ends_on.isoformat() if self.ends_on else None,
            "start_precision": self.start_precision,
            "end_precision": self.end_precision,
            "season": self.season,
            "duration_weeks": self.duration_weeks,
            "schedule_raw": self.schedule_raw,
        }

    def as_job_fields(self):
        return {
            "starts_on": self.starts_on,
            "ends_on": self.ends_on,
            "start_precision": self.start_precision or "",
            "end_precision": self.end_precision or "",
            "season": self.season or "",
            "duration_weeks": self.duration_weeks,
            "schedule_raw": (self.schedule_raw or "")[:255],
        }

    def matches_window(self, window_start, window_end, keep_unknown=True):
        if self.starts_on is None:
            return keep_unknown
        if self.start_precision == PRECISION_SEASON and self.ends_on:
            return self.starts_on <= window_end and self.ends_on >= window_start
        return window_start <= self.starts_on <= window_end

    @classmethod
    def from_mapping(cls, data):
        data = data or {}
        return cls(
            starts_on=parse_iso_date(data.get("starts_on")),
            ends_on=parse_iso_date(data.get("ends_on")),
            start_precision=_clean_token(data.get("start_precision")),
            end_precision=_clean_token(data.get("end_precision")),
            season=_clean_token(data.get("season")),
            duration_weeks=_coerce_int(data.get("duration_weeks")),
            schedule_raw=_clean_token(data.get("schedule_raw")),
        )


PRECISION_DAY = "day"
PRECISION_MONTH = "month"
PRECISION_SEASON = "season"

MONTH_NUMBERS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
MONTH_PATTERN = "(?:" + "|".join(
    sorted((re.escape(name) for name in MONTH_NUMBERS), key=len, reverse=True)
) + ")"
SEASON_ALIASES = {
    "summer": "summer",
    "fall": "fall",
    "autumn": "fall",
    "winter": "winter",
    "spring": "spring",
}
SEASON_PATTERN = "(?:" + "|".join(SEASON_ALIASES) + ")"
RANGE_SEPARATOR = r"(?:\s*[-–—/]\s*|\s+(?:to|through|until)\s+)"
YEAR_PATTERN = r"(20\d{2})"
SKIP_PATTERN = re.compile(
    r"(?:apply by|application deadline|applications? (?:close|due)|"
    r"deadline|posted(?:\s+on)?|date posted)\s*:?\s*[^\n.]{0,48}",
    re.IGNORECASE,
)
START_PREFIX = (
    r"(?:start(?:ing)?(?:\s+date)?|begins?(?:\s+on)?|available from|"
    r"internship starts?)"
)


class InternshipScheduleExtractor:
    @classmethod
    def extract(cls, title=None, description=None, sections=None):
        title_text = _clean_text(title)
        body_text = cls._body_text(description, sections)
        full_text = " ".join(part for part in (title_text, body_text) if part)
        duration_weeks, duration_raw = cls._extract_duration(full_text)

        matched = (
            cls._extract_explicit_start(full_text)
            or cls._extract_season(title_text)
            or cls._extract_month_range(full_text)
            or cls._extract_season(body_text)
            or cls._extract_month_year(title_text)
        )
        if matched is None:
            return InternshipSchedule(
                duration_weeks=duration_weeks,
                schedule_raw=_clip_raw(duration_raw),
            )

        ends_on = matched.ends_on
        end_precision = matched.end_precision
        if ends_on is None and duration_weeks and matched.starts_on:
            ends_on = matched.starts_on + timedelta(weeks=duration_weeks)
            end_precision = PRECISION_DAY

        raw_parts = [part for part in (matched.schedule_raw, duration_raw) if part]
        return InternshipSchedule(
            starts_on=matched.starts_on,
            ends_on=ends_on,
            start_precision=matched.start_precision,
            end_precision=end_precision,
            season=matched.season,
            duration_weeks=duration_weeks,
            schedule_raw=_clip_raw("; ".join(dict.fromkeys(raw_parts))),
        )

    @classmethod
    def _body_text(cls, description, sections):
        parts = [_clean_text(description)]
        if isinstance(sections, dict):
            parts.extend(_clean_text(value) for value in sections.values())
        return " ".join(part for part in parts if part)

    @classmethod
    def _extract_explicit_start(cls, text):
        if not text:
            return None
        pattern = re.compile(
            rf"{START_PREFIX}\s*:?\s*"
            rf"(?:{cls._day_month_year_pattern()}|{cls._month_year_pattern()}|"
            rf"{cls._iso_date_pattern()}|{cls._iso_month_pattern()})",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            if cls._is_skipped(text, match.start()):
                continue
            parsed = cls._parse_date_groups(match)
            if parsed is None:
                continue
            starts_on, precision = parsed
            return InternshipSchedule(
                starts_on=starts_on,
                start_precision=precision,
                schedule_raw=_clip_raw(match.group(0)),
            )
        return None

    @classmethod
    def _extract_season(cls, text):
        if not text:
            return None
        pattern = re.compile(
            rf"\b({SEASON_PATTERN})\s+(?:intern(?:ship)?\s+)?{YEAR_PATTERN}"
            rf"(?:\s*[/\-–]\s*(?:20)?(\d{{2}}))?\b"
            rf"|\b{YEAR_PATTERN}\s+({SEASON_PATTERN})\b",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            if cls._is_skipped(text, match.start()):
                continue
            if match.group(1):
                season_name = match.group(1)
                year = int(match.group(2))
            else:
                year = int(match.group(4))
                season_name = match.group(5)
            season_key = SEASON_ALIASES[season_name.casefold()]
            starts_on, ends_on = season_date_range(season_key, year)
            return InternshipSchedule(
                starts_on=starts_on,
                ends_on=ends_on,
                start_precision=PRECISION_SEASON,
                end_precision=PRECISION_SEASON,
                season=f"{season_key}-{year}",
                schedule_raw=_clip_raw(match.group(0)),
            )
        return None

    @classmethod
    def _extract_month_range(cls, text):
        if not text:
            return None
        pattern = re.compile(
            rf"\b({MONTH_PATTERN})\.?(?:\s+{YEAR_PATTERN})?{RANGE_SEPARATOR}"
            rf"({MONTH_PATTERN})\.?\s+{YEAR_PATTERN}\b",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            if cls._is_skipped(text, match.start()):
                continue
            start_month = MONTH_NUMBERS[match.group(1).casefold()]
            end_month = MONTH_NUMBERS[match.group(3).casefold()]
            end_year = int(match.group(4))
            start_year = int(match.group(2) or end_year)
            if start_year == end_year and start_month > end_month:
                start_year -= 1
            starts_on = date(start_year, start_month, 1)
            ends_on = date(end_year, end_month, monthrange(end_year, end_month)[1])
            return InternshipSchedule(
                starts_on=starts_on,
                ends_on=ends_on,
                start_precision=PRECISION_MONTH,
                end_precision=PRECISION_MONTH,
                schedule_raw=_clip_raw(match.group(0)),
            )
        return None

    @classmethod
    def _extract_month_year(cls, text):
        if not text:
            return None
        pattern = re.compile(
            rf"\b(?:{cls._day_month_year_pattern()}|{cls._month_year_pattern()})\b",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            if cls._is_skipped(text, match.start()):
                continue
            parsed = cls._parse_date_groups(match)
            if parsed is None:
                continue
            starts_on, precision = parsed
            return InternshipSchedule(
                starts_on=starts_on,
                start_precision=precision,
                schedule_raw=_clip_raw(match.group(0)),
            )
        return None

    @classmethod
    def _extract_duration(cls, text):
        if not text:
            return None, None
        match = re.search(
            r"\b(\d{1,2})\s*[-–]?\s*(weeks?|months?)\b",
            text,
            flags=re.IGNORECASE,
        )
        if match is None:
            return None, None
        amount = int(match.group(1))
        unit = match.group(2).casefold()
        weeks = amount * 4 if unit.startswith("month") else amount
        if weeks < 1 or weeks > 52:
            return None, None
        return weeks, _clip_raw(match.group(0))

    @classmethod
    def _parse_date_groups(cls, match):
        groups = {key: value for key, value in match.groupdict().items() if value}
        if "iso_d_year" in groups:
            return (
                _safe_date(
                    int(groups["iso_d_year"]),
                    int(groups["iso_d_month"]),
                    int(groups["iso_d_day"]),
                ),
                PRECISION_DAY,
            )
        if "iso_m_year" in groups:
            return (
                _safe_date(int(groups["iso_m_year"]), int(groups["iso_m_month"]), 1),
                PRECISION_MONTH,
            )
        month_name = (
            groups.get("md_month")
            or groups.get("dm_month")
            or groups.get("my_month")
        )
        year_value = groups.get("md_year") or groups.get("dm_year") or groups.get("my_year")
        if not month_name or not year_value:
            return None
        day_value = groups.get("md_day") or groups.get("dm_day")
        month = MONTH_NUMBERS[month_name.casefold()]
        precision = PRECISION_DAY if day_value else PRECISION_MONTH
        day = int(day_value) if day_value else 1
        return _safe_date(int(year_value), month, day), precision

    @staticmethod
    def _month_year_pattern():
        return rf"(?P<my_month>{MONTH_PATTERN})\.?\s+(?P<my_year>{YEAR_PATTERN})"

    @staticmethod
    def _day_month_year_pattern():
        return (
            rf"(?:(?P<md_month>{MONTH_PATTERN})\.?\s+(?P<md_day>\d{{1,2}})"
            rf"(?:st|nd|rd|th)?,?\s+(?P<md_year>{YEAR_PATTERN})"
            rf"|(?P<dm_day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<dm_month>{MONTH_PATTERN})"
            rf"\.?\s+(?P<dm_year>{YEAR_PATTERN}))"
        )

    @staticmethod
    def _iso_date_pattern():
        return (
            r"(?P<iso_d_year>20\d{2})-(?P<iso_d_month>0[1-9]|1[0-2])-"
            r"(?P<iso_d_day>0[1-9]|[12]\d|3[01])"
        )

    @staticmethod
    def _iso_month_pattern():
        return r"(?P<iso_m_year>20\d{2})-(?P<iso_m_month>0[1-9]|1[0-2])(?!-\d)"

    @staticmethod
    def _is_skipped(text, index):
        for match in SKIP_PATTERN.finditer(text):
            if match.start() <= index < match.end():
                return True
        return False


def season_date_range(season_key, year):
    if season_key == "spring":
        return date(year, 1, 1), date(year, 4, 30)
    if season_key == "summer":
        return date(year, 5, 1), date(year, 8, 31)
    if season_key == "fall":
        return date(year, 8, 1), date(year, 12, 31)
    last_day = monthrange(year + 1, 2)[1]
    return date(year, 12, 1), date(year + 1, 2, last_day)


def parse_iso_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_year_month(value):
    text = str(value or "").strip()
    match = re.fullmatch(r"(20\d{2})-(\d{2})", text)
    if match is None:
        parsed = parse_iso_date(text)
        if parsed is None:
            return None
        return month_window(parsed.year, parsed.month)
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        return None
    return month_window(year, month)


def month_window(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def start_window_from_config(config):
    config = config or {}
    explicit_from = parse_iso_date(
        config.get("starts_on_from") or config.get("start_date_from")
    )
    explicit_to = parse_iso_date(
        config.get("starts_on_to") or config.get("start_date_to")
    )
    start_month = parse_year_month(config.get("start_month"))
    start_month_to = parse_year_month(config.get("start_month_to"))
    if explicit_from or explicit_to:
        if start_month and explicit_from is None:
            explicit_from = start_month[0]
        if start_month_to and explicit_to is None:
            explicit_to = start_month_to[1]
        elif start_month and explicit_to is None:
            explicit_to = start_month[1]
        if explicit_from is None or explicit_to is None:
            return None
        return explicit_from, explicit_to
    if start_month is None:
        return None
    window_start = start_month[0]
    window_end = start_month_to[1] if start_month_to else start_month[1]
    if window_end < window_start:
        window_start, window_end = window_end, window_start
    return window_start, window_end


def filter_queryset_for_start_window(queryset, window_start, window_end):
    from django.db.models import Q

    same_month = (
        window_start.year == window_end.year
        and window_start.month == window_end.month
    )
    if same_month:
        starts_in_window = Q(
            starts_on__year=window_start.year,
            starts_on__month=window_start.month,
        )
    else:
        starts_in_window = Q(starts_on__gte=window_start, starts_on__lte=window_end)

    season_overlap = Q(
        start_precision=PRECISION_SEASON,
        starts_on__lte=window_end,
        ends_on__gte=window_start,
    )
    return queryset.filter(starts_in_window | season_overlap)


def _safe_date(year, month, day):
    last_day = monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _clean_text(value):
    text = " ".join(str(value or "").split()).strip()
    return text or ""


def _clean_token(value):
    text = str(value or "").strip()
    return text or None


def _clip_raw(value):
    text = _clean_text(value)
    return text[:255] if text else None


def _coerce_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
