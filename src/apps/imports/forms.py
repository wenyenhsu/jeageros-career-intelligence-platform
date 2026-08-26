import json

from django import forms

from .models import JobSource
from .services.internship_schedule_extractor import parse_year_month

GENERIC_CRAWL_DEFAULTS = {
    "max_pages": 1,
    "fetch_details": "new_or_missing",
    "max_search_requests": 3,
    "max_detail_requests": 3,
    "request_delay_seconds": 2,
    "rolling_search": True,
    "rate_limit_cooldown_minutes": 60,
    "default_job_type": "",
}

GENERIC_FILTER_DEFAULTS = {
    "location": [],
    "remote_only": False,
    "workplace_types": [],
    "job_types": [],
    "search_keywords": [],
    "include_keywords": [],
    "exclude_keywords": [],
    "target_companies": [],
    "location_aliases": [],
}


class JobSourceForm(forms.ModelForm):
    DEFAULT_BASE_URLS = {
        JobSource.ResourceChoices.LINKEDIN: "https://www.linkedin.com/jobs/search/",
        JobSource.ResourceChoices.GREENHOUSE: "https://my.greenhouse.io/",
        JobSource.ResourceChoices.HANDSHAKE: "https://app.joinhandshake.com/stu/postings",
        JobSource.ResourceChoices.LEVER: "https://jobs.lever.co/",
        JobSource.ResourceChoices.INTERSTRIDE: "https://student.interstride.com/",
        JobSource.ResourceChoices.CAREER_SITE: "",
        JobSource.ResourceChoices.RSS: "",
        JobSource.ResourceChoices.API: "",
        JobSource.ResourceChoices.GENERIC_HTML: "",
    }

    DEFAULT_CRAWL_CONFIGS = {
        JobSource.ResourceChoices.LINKEDIN: {
            "max_pages": 1,
            "fetch_details": "new_or_missing",
            "max_search_requests": 5,
            "max_detail_requests": 5,
            "request_delay_seconds": 5,
            "rolling_search": True,
            "rate_limit_cooldown_minutes": 60,
            "sort_by": "DD",
            "date_posted": "r604800",
            "default_job_type": "",
        },
        JobSource.ResourceChoices.GREENHOUSE: {
            "max_pages": 1,
            "fetch_details": "new_or_missing",
            "max_search_requests": 8,
            "max_detail_requests": 5,
            "request_delay_seconds": 2,
            "rolling_search": True,
            "rate_limit_cooldown_minutes": 60,
            "date_posted": "r604800",
            "default_job_type": "",
        },
        JobSource.ResourceChoices.HANDSHAKE: dict(GENERIC_CRAWL_DEFAULTS),
        JobSource.ResourceChoices.LEVER: {
            **GENERIC_CRAWL_DEFAULTS,
            "max_pages": 5,
            "max_search_requests": 5,
            "fetch_details": "false",
            "request_delay_seconds": 1,
        },
        JobSource.ResourceChoices.INTERSTRIDE: {
            **GENERIC_CRAWL_DEFAULTS,
            "max_pages": 3,
            "max_search_requests": 3,
            "max_detail_requests": 3,
            "request_delay_seconds": 2,
        },
        JobSource.ResourceChoices.CAREER_SITE: dict(GENERIC_CRAWL_DEFAULTS),
        JobSource.ResourceChoices.RSS: {
            **GENERIC_CRAWL_DEFAULTS,
            "fetch_details": "false",
        },
        JobSource.ResourceChoices.API: {
            **GENERIC_CRAWL_DEFAULTS,
            "fetch_details": "false",
        },
        JobSource.ResourceChoices.GENERIC_HTML: dict(GENERIC_CRAWL_DEFAULTS),
    }

    DEFAULT_FILTER_CONFIGS = {
        JobSource.ResourceChoices.LINKEDIN: {
            "location": ["United States"],
            "remote_only": False,
            "workplace_types": ["Remote", "Hybrid", "On-site"],
            "job_types": [],
            "search_keywords": [],
            "include_keywords": [],
            "exclude_keywords": [],
            "target_companies": [],
            "location_aliases": [],
        },
        JobSource.ResourceChoices.GREENHOUSE: {
            "location": ["United States"],
            "remote_only": False,
            "workplace_types": ["Remote", "Hybrid", "On-site"],
            "job_types": [],
            "search_keywords": [],
            "include_keywords": [],
            "exclude_keywords": ["intern", "internship", "co-op"],
            "target_companies": [],
            "board_tokens": [],
            "location_aliases": [],
        },
        JobSource.ResourceChoices.HANDSHAKE: dict(GENERIC_FILTER_DEFAULTS),
        JobSource.ResourceChoices.LEVER: dict(GENERIC_FILTER_DEFAULTS),
        JobSource.ResourceChoices.INTERSTRIDE: {
            **GENERIC_FILTER_DEFAULTS,
            "location": ["United States"],
        },
        JobSource.ResourceChoices.CAREER_SITE: dict(GENERIC_FILTER_DEFAULTS),
        JobSource.ResourceChoices.RSS: dict(GENERIC_FILTER_DEFAULTS),
        JobSource.ResourceChoices.API: dict(GENERIC_FILTER_DEFAULTS),
        JobSource.ResourceChoices.GENERIC_HTML: dict(GENERIC_FILTER_DEFAULTS),
    }

    MANAGED_CRAWL_CONFIG_KEYS = {
        "max_pages",
        "fetch_details",
        "max_search_requests",
        "max_detail_requests",
        "request_delay_seconds",
        "rolling_search",
        "rate_limit_cooldown_minutes",
        "sort_by",
        "date_posted",
        "default_job_type",
    }
    MANAGED_FILTER_CONFIG_KEYS = {
        "location",
        "locations",
        "remote_only",
        "workplace_types",
        "job_types",
        "search_keywords",
        "include_keywords",
        "exclude_keywords",
        "target_companies",
        "board_tokens",
        "location_aliases",
        "start_month",
        "start_month_to",
    }

    FETCH_DETAIL_CHOICES = (
        ("all", "All jobs"),
        ("new_or_missing", "New or missing descriptions"),
        ("new_only", "New jobs only"),
        ("false", "Do not fetch details"),
    )
    JOB_TYPE_CHOICES = (
        ("", "Any job type"),
        ("Full-time", "Full-time"),
        ("Part-time", "Part-time"),
        ("Internship", "Internship"),
        ("Contract", "Contract"),
        ("Temporary", "Temporary"),
    )
    SORT_BY_CHOICES = (
        ("DD", "Newest first"),
        ("R", "Most relevant"),
    )
    DATE_POSTED_CHOICES = (
        ("", "Any time"),
        ("r86400", "Past 24 hours"),
        ("r604800", "Past week"),
        ("r2592000", "Past month"),
    )

    max_pages = forms.IntegerField(
        min_value=1,
        required=False,
        label="Max pages",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    fetch_details = forms.ChoiceField(
        choices=FETCH_DETAIL_CHOICES,
        required=False,
        label="Fetch details",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    max_search_requests = forms.IntegerField(
        min_value=1,
        required=False,
        label="Max search requests",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    max_detail_requests = forms.IntegerField(
        min_value=1,
        required=False,
        label="Max detail requests",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    request_delay_seconds = forms.DecimalField(
        min_value=0,
        required=False,
        decimal_places=2,
        max_digits=6,
        label="Request delay seconds",
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": 0, "step": "0.5"}
        ),
    )
    rolling_search = forms.BooleanField(
        required=False,
        label="Rolling search",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    rate_limit_cooldown_minutes = forms.IntegerField(
        min_value=1,
        required=False,
        label="Rate limit cooldown minutes",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    sort_by = forms.ChoiceField(
        choices=SORT_BY_CHOICES,
        required=False,
        label="Sort order",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    date_posted = forms.ChoiceField(
        choices=DATE_POSTED_CHOICES,
        required=False,
        label="Date posted",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    default_job_type = forms.ChoiceField(
        choices=JOB_TYPE_CHOICES,
        required=False,
        label="Default job type",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    location = forms.CharField(
        required=False,
        label="Location",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "United States, CA, TX",
            }
        ),
    )
    location_aliases = forms.CharField(
        required=False,
        label="Nearby cities",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Burbank, Santa Monica, Anaheim, Irvine",
            }
        ),
        help_text=(
            "City names kept after crawl. These are not extra LinkedIn search "
            "locations, so nearby jobs from a metro search are not dropped."
        ),
    )
    job_types = forms.CharField(
        required=False,
        label="Job types",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Full-time, Internship",
            }
        ),
    )
    workplace_types = forms.CharField(
        required=False,
        label="Workplace types",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Remote, Hybrid, On-site",
            }
        ),
    )
    remote_only = forms.BooleanField(
        required=False,
        label="Remote only",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    search_keywords = forms.CharField(
        required=False,
        label="Search keywords",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "data engineer, backend, internship",
            }
        ),
    )
    include_keywords = forms.CharField(
        required=False,
        label="Include keywords",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 2, "placeholder": "python, django"}
        ),
    )
    exclude_keywords = forms.CharField(
        required=False,
        label="Exclude keywords",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 2, "placeholder": "senior, staff"}
        ),
    )
    target_companies = forms.CharField(
        required=False,
        label="Target companies",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 2, "placeholder": "OpenAI, Google"}
        ),
    )
    board_tokens = forms.CharField(
        required=False,
        label="Board tokens",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "stripe, databricks, anthropic",
            }
        ),
        help_text="Greenhouse board tokens to query. Leave empty to use the default tech-company list.",
    )
    start_month = forms.CharField(
        required=False,
        label="Internship start month",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "type": "month",
            }
        ),
        help_text=(
            "Keep jobs that start in this month, including seasons that cover it "
            "(Winter 2026 and Fall 2026 both match December). Jobs with no extracted "
            "start date are still saved."
        ),
    )
    start_month_to = forms.CharField(
        required=False,
        label="Internship start month to",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "type": "month",
            }
        ),
        help_text="Optional end of the start-month window.",
    )

    class Meta:
        model = JobSource
        fields = [
            "name",
            "resource",
            "base_url",
            "enabled",
            "crawl_interval_minutes",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "resource": forms.Select(attrs={"class": "form-select"}),
            "base_url": forms.URLInput(attrs={"class": "form-control"}),
            "enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "crawl_interval_minutes": forms.NumberInput(
                attrs={"class": "form-control", "min": 1}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.user_can_manage_resource = user is None or user.is_staff
        self._normalized_crawl_config = {}
        self._normalized_filter_config = {}
        self.fields["resource"].widget.attrs.update(
            {
                "data-default-base-urls": json.dumps(self.DEFAULT_BASE_URLS),
                "data-default-config-values": json.dumps(
                    self._default_form_values_by_resource()
                ),
                "data-base-url-target": "id_base_url",
            }
        )
        if not self.user_can_manage_resource:
            resource_attrs = dict(self.fields["resource"].widget.attrs)
            self.fields["resource"].widget = forms.HiddenInput(attrs=resource_attrs)
            self.fields["resource"].disabled = True
        if not self.is_bound:
            self._set_initial_config_values()

    @property
    def resource_display(self):
        resource = self.initial.get("resource") or getattr(
            self.instance, "resource", ""
        )
        return dict(JobSource.ResourceChoices.choices).get(resource, resource)

    def clean(self):
        cleaned_data = super().clean()
        resource = cleaned_data.get("resource")
        base_url = cleaned_data.get("base_url")
        if not base_url and resource:
            cleaned_data["base_url"] = self.DEFAULT_BASE_URLS.get(resource, "")

        self._normalized_crawl_config = self._build_crawl_config(cleaned_data)
        self._normalized_filter_config = self._build_filter_config(cleaned_data)
        return cleaned_data

    def clean_start_month(self):
        return self._clean_month_value(self.cleaned_data.get("start_month"))

    def clean_start_month_to(self):
        return self._clean_month_value(self.cleaned_data.get("start_month_to"))

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.crawl_config = self._merged_config(
            instance.crawl_config,
            self._normalized_crawl_config,
            self.MANAGED_CRAWL_CONFIG_KEYS,
        )
        instance.filter_config = self._merged_config(
            instance.filter_config,
            self._normalized_filter_config,
            self.MANAGED_FILTER_CONFIG_KEYS,
        )
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def _set_initial_config_values(self):
        resource = self.initial.get("resource") or getattr(self.instance, "resource", "")
        crawl_config = {
            **self.DEFAULT_CRAWL_CONFIGS.get(resource, {}),
            **(getattr(self.instance, "crawl_config", None) or {}),
        }
        filter_config = {
            **self.DEFAULT_FILTER_CONFIGS.get(resource, {}),
            **(getattr(self.instance, "filter_config", None) or {}),
        }
        for field_name in self.MANAGED_CRAWL_CONFIG_KEYS:
            if field_name in self.fields:
                self.fields[field_name].initial = self._field_value(
                    crawl_config.get(field_name)
                )
        for field_name in self.MANAGED_FILTER_CONFIG_KEYS:
            if field_name in self.fields:
                self.fields[field_name].initial = self._field_value(
                    filter_config.get(field_name)
                )

    def _build_crawl_config(self, cleaned_data):
        config = {}
        for key in self.MANAGED_CRAWL_CONFIG_KEYS:
            value = cleaned_data.get(key)
            if key == "rolling_search":
                config[key] = bool(value)
            elif value not in (None, "", [], {}):
                config[key] = float(value) if key == "request_delay_seconds" else value
        return config

    def _build_filter_config(self, cleaned_data):
        config = {
            "remote_only": bool(cleaned_data.get("remote_only")),
        }
        for key in (
            "location",
            "location_aliases",
            "job_types",
            "workplace_types",
            "search_keywords",
            "include_keywords",
            "exclude_keywords",
            "target_companies",
            "board_tokens",
        ):
            values = self._split_values(cleaned_data.get(key))
            if values:
                config[key] = values
        for key in ("start_month", "start_month_to"):
            value = cleaned_data.get(key)
            if value:
                config[key] = value
        return config

    @staticmethod
    def _clean_month_value(value):
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        if parse_year_month(text) is None:
            raise forms.ValidationError("Use YYYY-MM, for example 2026-12.")
        return text

    @classmethod
    def _merged_config(cls, existing_config, normalized_config, managed_keys):
        config = dict(existing_config or {})
        for key in managed_keys:
            config.pop(key, None)
        config.update(normalized_config)
        return config

    @classmethod
    def _default_form_values_by_resource(cls):
        values = {}
        resources = set(cls.DEFAULT_CRAWL_CONFIGS) | set(cls.DEFAULT_FILTER_CONFIGS)
        for resource in resources:
            field_values = {}
            for key, value in cls.DEFAULT_CRAWL_CONFIGS.get(resource, {}).items():
                field_values[key] = cls._field_value(value)
            for key, value in cls.DEFAULT_FILTER_CONFIGS.get(resource, {}).items():
                field_values[key] = cls._field_value(value)
            values[resource] = field_values
        return values

    @staticmethod
    def _field_value(value):
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        if value is None:
            return ""
        return value

    @staticmethod
    def _split_values(value):
        if value in (None, "", [], {}):
            return []
        if isinstance(value, str):
            raw_values = value.replace("\n", ",").split(",")
        elif isinstance(value, (list, tuple, set)):
            raw_values = value
        else:
            raw_values = [value]

        values = []
        seen = set()
        for raw_value in raw_values:
            text = " ".join(str(raw_value or "").split()).strip()
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            values.append(text)
        return values
