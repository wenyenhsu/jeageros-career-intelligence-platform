from django import forms
from .models import Application


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ["user", "job_post", "status", "applied_at", "priority", "referral"]
        widgets = {
            "user": forms.Select(attrs={"class": "form-select"}),
            "job_post": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "applied_at": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"},
                format="%Y-%m-%dT%H:%M",
            ),
            "priority": forms.NumberInput(attrs={"class": "form-control"}),
            "referral": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        job_post_field = self.fields["job_post"]
        job_post_field.label = "Linked JobPost"
        job_post_field.help_text = "Shared job details come from the selected JobPost."
        job_post_field.queryset = job_post_field.queryset.select_related(
            "company",
        ).order_by(
            "company__name",
            "title",
        )

        def job_post_label(job_post):
            job_type = job_post.job_type_display or "No job type"
            company = job_post.company.name if job_post.company_id else "No company"
            return f"{company} - {job_post.title} ({job_type})"

        job_post_field.label_from_instance = job_post_label

        if self.instance and self.instance.applied_at:
            self.initial["applied_at"] = self.instance.applied_at.strftime(
                "%Y-%m-%dT%H:%M"
            )
