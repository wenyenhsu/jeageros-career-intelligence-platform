from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
    DeleteView,
)
from apps.applications.models import Application
from apps.applications.services import record_status_transition
from apps.skills.models import SkillKeyword
from apps.skills.models import ApplicationSkill
from .forms import JobPostForm
from .models import JobPost
from .search import filter_jobs_for_search


class JobListView(ListView):
    model = JobPost
    template_name = "jobs/job_list.html"
    context_object_name = "jobs"

    def get_queryset(self):
        queryset = JobPost.objects.select_related("company").prefetch_related(
            "skill_sets",
            "skill_sets__keywords",
        )
        query = self.request.GET.get("q", "").strip()
        if not query:
            return queryset

        return filter_jobs_for_search(queryset, query)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "").strip()
        return context


class JobDetailView(DetailView):
    model = JobPost
    template_name = "jobs/job_detail.html"
    context_object_name = "job"
    queryset = JobPost.objects.select_related("company").prefetch_related(
        "skill_sets",
        "skill_sets__keywords",
    )


class JobCreateView(CreateView):
    model = JobPost
    form_class = JobPostForm
    template_name = "jobs/job_form.html"
    success_url = reverse_lazy("job-list")

    def form_valid(self, form):
        response = super().form_valid(form)
        _add_existing_keyword_warning(self.request, form)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["skill_keyword_lookup"] = _skill_keyword_lookup()
        return context


class JobUpdateView(UpdateView):
    model = JobPost
    form_class = JobPostForm
    template_name = "jobs/job_form.html"
    success_url = reverse_lazy("job-list")

    def form_valid(self, form):
        response = super().form_valid(form)
        _add_existing_keyword_warning(self.request, form)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["skill_keyword_lookup"] = _skill_keyword_lookup()
        return context


class JobDeleteView(DeleteView):
    model = JobPost
    success_url = reverse_lazy("job-list")


@login_required
@require_POST
def apply_to_job(request, pk):
    job = get_object_or_404(
        JobPost.objects.select_related("company").prefetch_related(
            "skill_links",
            "skill_links__skill_set",
        ),
        pk=pk,
    )
    now = timezone.now()
    application, created = Application.objects.get_or_create(
        user=request.user,
        job_post=job,
        defaults={
            "status": Application.Status.APPLIED,
            "applied_at": now,
        },
    )

    if created:
        _copy_job_skills_to_application(job, application)
        messages.success(
            request,
            f"Added {job.title_display} to Applications.",
        )
    else:
        updated_fields = []
        old_status = application.status
        if application.status == Application.Status.SAVED:
            application.status = Application.Status.APPLIED
            updated_fields.append("status")
        if application.applied_at is None:
            application.applied_at = now
            updated_fields.append("applied_at")
        if updated_fields:
            updated_fields.append("last_updated_at")
            application.save(update_fields=updated_fields)
            if old_status != application.status:
                record_status_transition(
                    application,
                    old_status,
                    application.status,
                    user=request.user,
                )

        copied = _copy_job_skills_to_application(job, application)
        if copied:
            messages.success(
                request,
                f"Updated existing application for {job.title_display}.",
            )
        else:
            messages.info(
                request,
                f"Application for {job.title_display} already exists.",
            )

    return redirect("application-list")


def _copy_job_skills_to_application(job, application):
    copied = 0
    for job_skill in job.skill_links.all():
        _, created = ApplicationSkill.objects.get_or_create(
            application=application,
            skill_set=job_skill.skill_set,
            defaults={
                "score": job_skill.score,
                "source_type": job_skill.source_type,
                "extraction_metadata": dict(job_skill.extraction_metadata or {}),
            },
        )
        if created:
            copied += 1
    return copied


def _skill_keyword_lookup():
    lookup = []
    for keyword in SkillKeyword.objects.select_related("skill_set").order_by(
        "normalized_text",
        "skill_set__name",
    ):
        lookup.append(
            {
                "raw_text": keyword.raw_text,
                "normalized_text": keyword.normalized_text,
                "skill_set_id": keyword.skill_set_id,
                "skill_set_name": keyword.skill_set.name,
                "status": keyword.status,
                "source": keyword.source,
            }
        )
    return lookup


def _add_existing_keyword_warning(request, form):
    warning = form.existing_keyword_warning
    if warning:
        messages.warning(request, warning)
