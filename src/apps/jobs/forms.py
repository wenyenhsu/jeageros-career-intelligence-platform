from django import forms
from .models import JobPost


class JobPostForm(forms.ModelForm):
    class Meta:
        model = JobPost
        fields = [
            "company",
            "title",
            "source_url",
            "external_id",
            "source_type",
            "status",
            "location",
            "remote_type",
            "employment_type",
            "salary_min",
            "salary_max",
            "description",
            "tags",
        ]
        widgets = {
            "company": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "source_url": forms.URLInput(attrs={"class": "form-control"}),
            "external_id": forms.TextInput(attrs={"class": "form-control"}),
            "source_type": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "location": forms.TextInput(attrs={"class": "form-control"}),
            "remote_type": forms.TextInput(attrs={"class": "form-control"}),
            "employment_type": forms.TextInput(attrs={"class": "form-control"}),
            "salary_min": forms.NumberInput(attrs={"class": "form-control"}),
            "salary_max": forms.NumberInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "tags": forms.TextInput(attrs={"class": "form-control"}),
        }
