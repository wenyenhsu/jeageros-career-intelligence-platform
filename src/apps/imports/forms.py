from django import forms

from .models import JobSource


class JobSourceForm(forms.ModelForm):
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
