from urllib.parse import urlparse

from django import forms
from django.db import transaction

from apps.companies.models import Company
from apps.imports.services.company_upsert_service import CompanyUpsertService
from apps.jobs.forms import CompanyNameInput, attach_job_url_preview_attrs
from apps.jobs.models import JobPost

from .models import Application, GOOGLE_DRIVE_HOSTS, normalize_materials_url
from .services.materials_folder_service import MaterialsFolderService
from .services.materials_pack_service import MaterialsPackService


class ApplicationForm(forms.ModelForm):
    materials_url = forms.CharField(
        required=False,
        max_length=500,
        label="Google Drive folder",
        help_text=(
            "Leave blank to create a Google Drive folder automatically. "
            "Contains this job's cover letter and resume."
        ),
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "https://drive.google.com/drive/folders/...",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:
        model = Application
        fields = [
            "user",
            "job_post",
            "status",
            "applied_at",
            "priority",
            "referral",
            "materials_pack",
            "materials_url",
        ]
        widgets = {
            "user": forms.Select(attrs={"class": "form-select"}),
            "job_post": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "applied_at": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"},
                format="%Y-%m-%dT%H:%M",
            ),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "referral": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "materials_pack": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "materials_pack": "Materials",
        }
        help_texts = {
            "materials_pack": "Copies the AI or Infra pack, then tailors the cover letter to the job URL.",
        }

    def __init__(self, *args, allow_manual_job=False, acting_user=None, **kwargs):
        self.allow_manual_job = allow_manual_job
        self.acting_user = acting_user
        self.lock_user = bool(
            acting_user
            and acting_user.is_authenticated
            and not acting_user.is_staff
        )
        super().__init__(*args, **kwargs)
        self._original_pack = (
            self.instance.materials_pack if self.instance.pk else ""
        ) or ""
        self.copied_pack = False
        self.cover_letter_tailor_result = None

        if self.lock_user:
            self.fields.pop("user", None)

        pack_field = self.fields["materials_pack"]
        pack_field.required = False
        pack_field.choices = [("", "Select"), *Application.MaterialsPack.choices]

        job_post_field = self.fields["job_post"]
        job_post_field.label = "Linked JobPost"
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

        if self.allow_manual_job:
            job_post_field.required = False
            job_post_field.help_text = (
                "Optional. Leave blank and enter a company and job title below "
                "to add a new job."
            )
            self._add_manual_job_fields()
        else:
            job_post_field.help_text = (
                "Shared job details come from the selected JobPost."
            )

        if self.instance and self.instance.applied_at:
            self.initial["applied_at"] = self.instance.applied_at.strftime(
                "%Y-%m-%dT%H:%M"
            )

    def _add_manual_job_fields(self):
        self.fields["company"] = forms.CharField(
            required=False,
            label="Company",
            help_text="Type a company name. A new name creates the company.",
            widget=CompanyNameInput(
                attrs={
                    "class": "form-control",
                    "list": "application-company-options",
                    "placeholder": "Type a company name",
                    "autocomplete": "off",
                }
            ),
        )
        self.fields["company"].widget.company_names = list(
            Company.objects.order_by("name").values_list("name", flat=True)
        )
        self.fields["job_title"] = forms.CharField(
            required=False,
            label="Job title",
            widget=forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Backend Engineer",
                }
            ),
        )
        self.fields["source_url"] = forms.URLField(
            required=False,
            assume_scheme="https",
            label="Job URL",
            help_text=(
                "Paste a public job posting URL to fill company, title, location, "
                "and job type. LinkedIn, Greenhouse, or a career site page. "
                "Do not paste a Google Drive folder here."
            ),
            widget=forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://www.linkedin.com/jobs/view/...",
                }
            ),
        )
        attach_job_url_preview_attrs(
            self.fields["source_url"],
            title_selector="#id_job_title",
            job_type_selector="#id_job_type",
        )
        self.fields["location"] = forms.CharField(
            required=False,
            label="Location",
            widget=forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Remote",
                }
            ),
        )
        self.fields["job_type"] = forms.ChoiceField(
            required=False,
            label="Job type",
            choices=[("", "---------"), *JobPost.JOB_TYPE_CHOICES],
            widget=forms.Select(attrs={"class": "form-select"}),
        )

    def clean_company(self):
        return " ".join(str(self.cleaned_data.get("company") or "").split())

    def clean_job_title(self):
        return " ".join(str(self.cleaned_data.get("job_title") or "").split())

    def clean_source_url(self):
        url = (self.cleaned_data.get("source_url") or "").strip()
        if not url:
            return ""
        host = urlparse(url).netloc.casefold()
        if host.startswith("www."):
            host = host[4:]
        if host in GOOGLE_DRIVE_HOSTS:
            raise forms.ValidationError(
                "Use the Google Drive folder field for cover letter and resume."
            )
        return url

    def clean_materials_url(self):
        return normalize_materials_url(self.cleaned_data.get("materials_url"))

    def clean_materials_pack(self):
        pack = (self.cleaned_data.get("materials_pack") or "").strip()
        if not pack:
            return ""
        pack_key = MaterialsPackService.normalize_pack(pack)
        if not pack_key:
            raise forms.ValidationError("Choose AI or Infra.")
        if pack_key != self._original_pack:
            source_dir = MaterialsPackService.template_root()
            if source_dir is None or not source_dir.is_dir():
                raise forms.ValidationError("Resume template folder was not found.")
        return pack_key

    def clean(self):
        cleaned_data = super().clean()
        job_post = cleaned_data.get("job_post")
        if self.allow_manual_job and not job_post:
            company = cleaned_data.get("company")
            job_title = cleaned_data.get("job_title")
            if not company:
                self.add_error("company", "Enter a company name or select a job.")
            if not job_title:
                self.add_error("job_title", "Enter a job title or select a job.")
            if company and job_title:
                existing_job = self._find_existing_job(cleaned_data)
                if existing_job is not None:
                    cleaned_data["job_post"] = existing_job
                    job_post = existing_job

        user = self.acting_user if self.lock_user else cleaned_data.get("user")
        if self.lock_user:
            cleaned_data["user"] = user
        if user and job_post:
            existing_application = Application.objects.filter(
                user=user,
                job_post=job_post,
            )
            if self.instance.pk:
                existing_application = existing_application.exclude(pk=self.instance.pk)
            if existing_application.exists():
                raise forms.ValidationError(
                    "An application for this job already exists."
                )
        return cleaned_data

    def save(self, commit=True):
        copied_pack = False
        with transaction.atomic():
            application = super().save(commit=False)
            if self.lock_user:
                application.user = self.acting_user
            if not application.job_post_id:
                application.job_post = self._create_job_post()
            if commit:
                application.save()
                self.save_m2m()
                MaterialsFolderService().ensure_folders(application)
                copied_pack = self._copy_selected_materials_pack(application)
        self.copied_pack = copied_pack
        return application

    def _copy_selected_materials_pack(self, application):
        pack = (self.cleaned_data.get("materials_pack") or "").strip()
        if not pack or pack == self._original_pack:
            return False
        MaterialsPackService().apply_pack(application, pack)
        return True

    def _find_existing_job(self, cleaned_data):
        source_url = (cleaned_data.get("source_url") or "").strip()
        if source_url:
            job = JobPost.objects.filter(source_url=source_url).first()
            if job is not None:
                return job
        company_name = cleaned_data.get("company")
        job_title = cleaned_data.get("job_title")
        if not company_name or not job_title:
            return None
        return (
            JobPost.objects.filter(
                company__name__iexact=company_name,
                title__iexact=job_title,
            )
            .select_related("company")
            .first()
        )

    def _create_job_post(self):
        company = CompanyUpsertService.upsert(self.cleaned_data["company"]).company
        job_type = JobPost.normalize_job_type(self.cleaned_data.get("job_type") or "")
        return JobPost.objects.create(
            company=company,
            title=self.cleaned_data["job_title"],
            source_url=(self.cleaned_data.get("source_url") or "").strip(),
            location=(self.cleaned_data.get("location") or "").strip(),
            source_type=JobPost.SourceType.MANUAL,
            employment_type=job_type,
            job_type=job_type,
        )
