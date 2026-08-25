from django import forms
from django.db import transaction
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from apps.companies.models import Company
from apps.imports.services.company_upsert_service import CompanyUpsertService
from apps.skills.models import (
    JobPostSkill,
    SkillAttachmentSource,
    SkillKeyword,
    SkillSet,
)

from .models import JobPost
from .identity import JobIdentityService


def attach_job_url_preview_attrs(
    field,
    *,
    title_selector,
    job_type_selector,
    description_selector="",
):
    if field is None:
        return
    attrs = {
        "data-job-url-preview": "true",
        "data-preview-url": reverse("job-url-preview"),
        "data-preview-company": "#id_company",
        "data-preview-title": title_selector,
        "data-preview-location": "#id_location",
        "data-preview-job-type": job_type_selector,
        "autocomplete": "off",
    }
    if description_selector:
        attrs["data-preview-description"] = description_selector
    field.widget.attrs.update(attrs)


class CompanyNameInput(forms.TextInput):
    def __init__(self, attrs=None, company_names=()):
        super().__init__(attrs)
        self.company_names = company_names

    def render(self, name, value, attrs=None, renderer=None):
        attrs = {} if attrs is None else dict(attrs)
        list_id = attrs.get("list") or self.attrs.get("list") or "job-company-options"
        attrs["list"] = list_id
        html = super().render(name, value, attrs=attrs, renderer=renderer)
        options = format_html_join(
            "",
            '<option value="{}"></option>',
            ((company_name,) for company_name in self.company_names),
        )
        return format_html('{}<datalist id="{}">{}</datalist>', html, list_id, options)


class JobPostForm(forms.ModelForm):
    company = forms.CharField(
        label="Company",
        help_text=(
            "Type a company name. Existing companies can be chosen from the list; "
            "a new name creates the company."
        ),
        widget=CompanyNameInput(
            attrs={
                "class": "form-control",
                "list": "job-company-options",
                "placeholder": "Type a company name",
                "autocomplete": "off",
            }
        ),
    )
    employment_type = forms.ChoiceField(
        label="Job Type",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    skill_keywords = forms.CharField(
        label="SkillSet Keywords",
        required=False,
        help_text="Manual SkillSet keywords, separated by commas or new lines.",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Python, Django, SQL",
            }
        ),
    )

    class Meta:
        model = JobPost
        fields = [
            "title",
            "source_url",
            "external_id",
            "source_type",
            "status",
            "location",
            "remote_type",
            "employment_type",
            "starts_on",
            "ends_on",
            "season",
            "duration_weeks",
            "salary_min",
            "salary_max",
            "description",
            "tags",
            "skill_keywords",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "source_url": forms.URLInput(attrs={"class": "form-control"}),
            "external_id": forms.TextInput(attrs={"class": "form-control"}),
            "source_type": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "location": forms.TextInput(attrs={"class": "form-control"}),
            "remote_type": forms.TextInput(attrs={"class": "form-control"}),
            "employment_type": forms.Select(attrs={"class": "form-select"}),
            "starts_on": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "ends_on": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "season": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "winter-2026"}
            ),
            "duration_weeks": forms.NumberInput(
                attrs={"class": "form-control", "min": 1}
            ),
            "salary_min": forms.NumberInput(attrs={"class": "form-control"}),
            "salary_max": forms.NumberInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "tags": forms.TextInput(attrs={"class": "form-control"}),
        }

    field_order = [
        "source_url",
        "company",
        "title",
        "external_id",
        "source_type",
        "status",
        "location",
        "remote_type",
        "employment_type",
        "starts_on",
        "ends_on",
        "season",
        "duration_weeks",
        "salary_min",
        "salary_max",
        "description",
        "tags",
        "skill_keywords",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keyword_analysis = []
        self.fields["company"].widget.company_names = list(
            Company.objects.order_by("name").values_list("name", flat=True)
        )
        if self.instance and getattr(self.instance, "company_id", None):
            self.initial["company"] = self.instance.company.name
        current_value = (
            self.initial.get("employment_type")
            or getattr(self.instance, "employment_type", "")
            or ""
        )
        choices = [("", "---------"), *JobPost.JOB_TYPE_CHOICES]
        known_values = {value for value, _label in choices}
        if current_value and current_value not in known_values:
            choices.append((current_value, current_value))
        self.fields["employment_type"].choices = choices

        if self.instance and self.instance.pk:
            manual_skills = self.instance.skill_links.filter(
                source_type=SkillAttachmentSource.MANUAL,
            ).select_related("skill_set")
            self.fields["skill_keywords"].initial = ", ".join(
                link.skill_set.name for link in manual_skills
            )
        attach_job_url_preview_attrs(
            self.fields["source_url"],
            title_selector="#id_title",
            job_type_selector="#id_employment_type",
            description_selector="#id_description",
        )

    def clean_company(self):
        name = " ".join(str(self.cleaned_data.get("company") or "").split())
        if not name:
            raise forms.ValidationError("This field is required.")
        return name

    def clean_skill_keywords(self):
        value = self.cleaned_data.get("skill_keywords", "")
        self.keyword_analysis = self.analyze_skill_keywords(value)
        return value

    def clean(self):
        cleaned_data = super().clean()
        identity = JobIdentityService.build(
            source_url=cleaned_data.get("source_url", ""),
            external_id=cleaned_data.get("external_id", ""),
            source=getattr(self.instance, "source_key", ""),
            company_name=cleaned_data.get("company", ""),
        )
        queryset = JobPost.objects.all()
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if (
            identity.canonical_source_url
            and queryset.filter(
                canonical_source_url=identity.canonical_source_url
            ).exists()
        ):
            self.add_error(
                "source_url",
                "A job with this canonical source URL already exists.",
            )
        if (
            identity.source_key
            and identity.normalized_external_id
            and queryset.filter(
                source_key=identity.source_key,
                normalized_external_id=identity.normalized_external_id,
            ).exists()
        ):
            self.add_error(
                "external_id",
                "A job with this external ID already exists for the same source.",
            )
        return cleaned_data

    @property
    def existing_keyword_analysis(self):
        return [item for item in self.keyword_analysis if item["exists"]]

    @property
    def new_keyword_analysis(self):
        return [item for item in self.keyword_analysis if not item["exists"]]

    @property
    def existing_keyword_warning(self):
        existing = self.existing_keyword_analysis
        if not existing:
            return ""
        labels = [
            (
                f"{item['raw_text']} ({item['skill_set_name']})"
                if item["skill_set_name"]
                else item["raw_text"]
            )
            for item in existing
        ]
        return "Existing SkillSet keywords reused: " + ", ".join(labels)

    @transaction.atomic
    def save(self, commit=True):
        job = super().save(commit=False)
        job.company = CompanyUpsertService.upsert(self.cleaned_data["company"]).company
        if commit:
            job.save()
            self.save_m2m()
            self._sync_manual_skill_sets(job)
        return job

    def save_m2m(self):
        super().save_m2m()
        if self.instance.pk:
            self._sync_manual_skill_sets(self.instance)

    def _sync_manual_skill_sets(self, job):
        skill_names = self._parse_skill_keywords(
            self.cleaned_data.get("skill_keywords", "")
        )
        manual_links = JobPostSkill.objects.filter(
            job_post=job,
            source_type=SkillAttachmentSource.MANUAL,
        ).select_related("skill_set")

        if not skill_names:
            manual_links.delete()
            return

        linked_normalized_names = set()
        for skill_name in skill_names:
            skill_set = self._get_or_create_skill_set(skill_name)
            SkillKeyword.ensure_for_skillset(
                skill_set,
                skill_name,
                source=SkillKeyword.SourceChoices.MANUAL,
                metadata={"source": "job_form"},
            )
            linked_normalized_names.add(skill_set.normalized_name)
            existing_link = JobPostSkill.objects.filter(
                job_post=job,
                skill_set=skill_set,
            ).first()
            if existing_link:
                if existing_link.source_type == SkillAttachmentSource.MANUAL:
                    existing_link.score = 0
                    existing_link.extraction_metadata = {"source": "job_form"}
                    existing_link.save(
                        update_fields=[
                            "score",
                            "extraction_metadata",
                            "updated_at",
                        ]
                    )
                continue

            JobPostSkill.objects.create(
                job_post=job,
                skill_set=skill_set,
                score=0,
                source_type=SkillAttachmentSource.MANUAL,
                extraction_metadata={"source": "job_form"},
            )

        manual_links.exclude(
            skill_set__normalized_name__in=linked_normalized_names,
        ).delete()

    @staticmethod
    def _parse_skill_keywords(raw_value):
        skill_names = []
        seen = set()
        for value in JobPostForm._split_keyword_input(raw_value):
            skill_name = SkillKeyword.clean_keyword(value)
            normalized_name = SkillKeyword.normalize_keyword(skill_name)
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            skill_names.append(skill_name)
        return skill_names

    @staticmethod
    def _split_keyword_input(raw_value):
        return str(raw_value or "").replace("\n", ",").split(",")

    @staticmethod
    def _get_or_create_skill_set(skill_name):
        normalized_name = SkillSet.normalize_name(skill_name)
        skill_set = (
            SkillSet.objects.filter(
                keywords__normalized_text=normalized_name,
                keywords__status=SkillKeyword.StatusChoices.ACTIVE,
            )
            .distinct()
            .first()
        )
        if skill_set:
            return skill_set
        skill_set = SkillSet.objects.filter(normalized_name=normalized_name).first()
        if skill_set:
            return skill_set
        return SkillSet.objects.create(name=skill_name, auto_created=False)

    @classmethod
    def analyze_skill_keywords(cls, raw_value):
        parsed_keywords = cls._parse_skill_keywords(raw_value)
        normalized_keywords = [
            SkillKeyword.normalize_keyword(keyword) for keyword in parsed_keywords
        ]
        existing_keywords = {
            keyword.normalized_text: keyword
            for keyword in SkillKeyword.objects.filter(
                normalized_text__in=normalized_keywords,
            ).select_related("skill_set")
        }

        analysis = []
        for raw_text, normalized_text in zip(parsed_keywords, normalized_keywords):
            existing_keyword = existing_keywords.get(normalized_text)
            analysis.append(
                {
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                    "exists": existing_keyword is not None,
                    "skill_set_id": (
                        existing_keyword.skill_set_id if existing_keyword else None
                    ),
                    "skill_set_name": (
                        existing_keyword.skill_set.name if existing_keyword else ""
                    ),
                    "status": existing_keyword.status if existing_keyword else "",
                    "source": existing_keyword.source if existing_keyword else "",
                }
            )
        return analysis
