import json

from django import forms

from .models import JobSource


class JobSourceForm(forms.ModelForm):
    DEFAULT_BASE_URLS = {
        JobSource.ResourceChoices.LINKEDIN: "https://www.linkedin.com/jobs/search/",
        JobSource.ResourceChoices.HANDSHAKE: "https://app.joinhandshake.com/stu/postings",
        JobSource.ResourceChoices.GREENHOUSE: "https://boards.greenhouse.io/",
        JobSource.ResourceChoices.LEVER: "https://jobs.lever.co/",
        JobSource.ResourceChoices.CAREER_SITE: "",
        JobSource.ResourceChoices.RSS: "",
        JobSource.ResourceChoices.API: "",
        JobSource.ResourceChoices.GENERIC_HTML: "",
    }

    class Meta:
        model = JobSource
        fields = [
            "name",
            "resource",
            "base_url",
            "enabled",
            "crawl_interval_minutes",
            "crawl_config",
            "filter_config",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "resource": forms.Select(attrs={"class": "form-select"}),
            "base_url": forms.URLInput(attrs={"class": "form-control"}),
            "enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "crawl_interval_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "crawl_config": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": '{"pages": 3, "delay_seconds": 1}'}),
            "filter_config": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": '{"include_keywords": ["python", "django"]}'}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["resource"].widget.attrs.update(
            {
                "data-default-base-urls": json.dumps(self.DEFAULT_BASE_URLS),
                "data-base-url-target": "id_base_url",
            }
        )

    def clean(self):
        cleaned_data = super().clean()
        resource = cleaned_data.get("resource")
        base_url = cleaned_data.get("base_url")
        if not base_url and resource:
            cleaned_data["base_url"] = self.DEFAULT_BASE_URLS.get(resource, "")
        return cleaned_data
