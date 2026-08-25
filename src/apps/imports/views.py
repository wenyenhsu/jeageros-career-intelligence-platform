from copy import deepcopy
from urllib.parse import urlencode
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.jobs.models import JobPost
from apps.jobs.search import (
    filter_jobs_for_job_type,
    filter_jobs_for_search,
    filter_jobs_for_start_month,
)

from .forms import JobSourceForm
from .models import CrawlRun, JobArchiveRun, JobSource, PipelineLog
from .search import filter_job_sources_for_search
from .services import JobArchiveService, JobUrlRefreshService, MonitoringService


@login_required
def job_url_import(request):
    return JobSourceListView.as_view()(request)


@login_required
def monitoring_dashboard(request):
    crawl_run_id = request.GET.get("crawl_run_id") or request.GET.get("run")
    resume_run_id = request.GET.get("resume_run_id") or request.session.get(
        "resume_analysis_run_id"
    )
    skill_analysis_run_id = request.GET.get(
        "skill_analysis_run_id"
    ) or request.session.get("skill_analysis_run_id")
    return render(
        request,
        "imports/monitoring_dashboard.html",
        MonitoringService.dashboard_summary(
            crawl_run_id=crawl_run_id,
            resume_run_id=resume_run_id,
            skill_analysis_run_id=skill_analysis_run_id,
        ),
    )


class MissingSkillJobListView(LoginRequiredMixin, ListView):
    model = JobPost
    template_name = "imports/missing_skill_job_list.html"
    context_object_name = "jobs"

    def get_queryset(self):
        return _filtered_missing_skill_jobs(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "").strip()
        context["starts_month"] = self.request.GET.get("starts_month", "").strip()
        context["selected_job_type"] = JobPost.normalize_job_type(
            self.request.GET.get("job_type", "").strip()
        )
        context["job_type_choices"] = JobPost.JOB_TYPE_CHOICES
        context["queued_count"] = sum(
            1 for job in context["jobs"] if JobUrlRefreshService.needs_refresh(job)
        )
        run_id = self.request.GET.get(
            "skill_analysis_run_id"
        ) or self.request.session.get("skill_analysis_run_id")
        context["skill_analysis"] = MonitoringService.job_skill_analysis_status(
            run_id
        )
        context.update(_missing_skill_nav(self.request))
        return context


@login_required
@require_POST
def run_missing_skill_analysis(request):
    from apps.imports.tasks import refresh_job_from_url

    jobs = list(_filtered_missing_skill_jobs(request))
    queued_ids = []
    skipped_without_url = 0
    for job in jobs:
        if JobUrlRefreshService.needs_refresh(job):
            queued_ids.append(job.id)
        elif not (job.source_url or "").strip():
            skipped_without_url += 1

    if queued_ids:
        run_id = MonitoringService.start_job_skill_analysis(queued_ids)
        request.session["skill_analysis_run_id"] = run_id
        for job_id in queued_ids:
            refresh_job_from_url.delay(job_id, analysis_run_id=run_id)
        messages.info(
            request,
            f"Queued analysis for {len(queued_ids)} job(s) with a source URL.",
        )
    if skipped_without_url:
        messages.warning(
            request,
            f"Skipped {skipped_without_url} job(s) without a source URL.",
        )
    if not queued_ids and not skipped_without_url:
        messages.info(request, "No jobs needed skill analysis.")

    query = {}
    for key in ("q", "job_type", "starts_month"):
        value = request.POST.get(key, "").strip()
        if value:
            query[key] = value
    nav = _missing_skill_nav(request)
    url = reverse(nav["list_url_name"])
    if query:
        url = f"{url}?{urlencode(query)}"
    return redirect(url)


@login_required
def job_skill_analysis_status(request):
    run_id = request.GET.get("skill_analysis_run_id") or request.session.get(
        "skill_analysis_run_id"
    )
    status = MonitoringService.job_skill_analysis_status(run_id)
    if not status:
        return JsonResponse(
            {
                "success": False,
                "status": "",
                "progress": 0,
                "detail": "No skill analysis run is active.",
            },
            status=404,
        )

    run_id = status.get("run_id") or run_id
    return JsonResponse(
        {
            "success": status.get("status") != PipelineLog.StatusChoices.FAILED,
            "skill_analysis_run_id": run_id,
            "monitoring_url": (
                f"{reverse('monitoring-dashboard')}?skill_analysis_run_id={run_id}"
                "#job-skill-analysis"
            ),
            **status,
        }
    )


_ANALYTICS_MISSING_SKILL_URLS = {
    "analytics-missing-skills",
    "analytics-missing-skills-run",
}


def _missing_skill_nav(request):
    url_name = getattr(request.resolver_match, "url_name", "")
    if url_name in _ANALYTICS_MISSING_SKILL_URLS:
        return {
            "list_url_name": "analytics-missing-skills",
            "run_url_name": "analytics-missing-skills-run",
            "parent_url_name": "analytics-dashboard",
            "parent_label": "Analytics",
            "section_label": "Analytics",
        }
    return {
        "list_url_name": "monitoring-missing-skills",
        "run_url_name": "monitoring-missing-skills-run",
        "parent_url_name": "monitoring-dashboard",
        "parent_label": "Monitoring",
        "section_label": "Monitoring",
    }


def _filtered_missing_skill_jobs(request):
    queryset = JobUrlRefreshService.jobs_missing_skills()
    params = request.POST if request.method == "POST" else request.GET
    job_type = params.get("job_type", "").strip()
    if job_type:
        queryset = filter_jobs_for_job_type(queryset, job_type)
    starts_month = params.get("starts_month", "").strip()
    if starts_month:
        queryset = filter_jobs_for_start_month(queryset, starts_month)
    query = params.get("q", "").strip()
    if query:
        queryset = filter_jobs_for_search(queryset, query)
    return queryset


@login_required
@require_POST
def archive_jobs(request):
    age_months = request.POST.get("age_months", "3")
    try:
        archive_run = JobArchiveService.archive_old_jobs(age_months=age_months)
    except ValueError as exc:
        if _wants_json(request):
            return JsonResponse({"success": False, "error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect(f"{reverse('monitoring-dashboard')}#job-archive")
    except Exception as exc:
        MonitoringService.log_failure(
            step_name="job_archive",
            message="Job archive failed.",
            service_name=__name__,
            error=exc,
        )
        if _wants_json(request):
            return JsonResponse({"success": False, "error": str(exc)}, status=500)
        messages.error(request, f"Job archive failed: {exc}")
        return redirect(f"{reverse('monitoring-dashboard')}#job-archive")

    payload = {
        "success": True,
        "archive_run_id": archive_run.id,
        "jobs_archived": archive_run.jobs_archived,
        "download_url": reverse("job-archive-download", args=[archive_run.id]),
    }
    if _wants_json(request):
        return JsonResponse(payload, status=201)

    messages.success(
        request,
        (
            f"Archived {archive_run.jobs_archived} jobs created more than "
            f"{archive_run.age_months} months ago."
        ),
    )
    return redirect(f"{reverse('monitoring-dashboard')}#job-archive")


@login_required
@require_POST
def restore_job_archive(request, pk):
    archive_run = get_object_or_404(JobArchiveRun, pk=pk)
    try:
        result = JobArchiveService.restore_archive(archive_run)
    except Exception as exc:
        MonitoringService.log_failure(
            step_name="job_archive_restore",
            message=f"Job archive restore failed for archive run #{archive_run.id}.",
            service_name=__name__,
            error=exc,
            metadata={"archive_run_id": archive_run.id},
        )
        if _wants_json(request):
            return JsonResponse({"success": False, "error": str(exc)}, status=500)
        messages.error(request, f"Job archive restore failed: {exc}")
        return redirect(f"{reverse('monitoring-dashboard')}#job-archive")

    payload = {
        "success": True,
        "archive_run_id": archive_run.id,
        "jobs_restored": result["jobs_restored"],
        "skipped_job_ids": result["skipped_job_ids"],
    }
    if _wants_json(request):
        return JsonResponse(payload)

    messages.success(
        request,
        f"Restored {result['jobs_restored']} archived jobs to active jobs.",
    )
    return redirect(f"{reverse('monitoring-dashboard')}#job-archive")


@login_required
def download_job_archive(request, pk):
    archive_run = get_object_or_404(JobArchiveRun, pk=pk)
    content = json.dumps(archive_run.payload or {}, indent=2, ensure_ascii=False)
    response = HttpResponse(content, content_type="application/json")
    response["Content-Disposition"] = (
        f'attachment; filename="job-archive-{archive_run.id}.json"'
    )
    return response


@login_required
@require_POST
def run_all_sources(request):
    label = "All enabled job sources"
    crawl_run = _start_crawl_run(label)
    error = _enqueue_crawl_task(crawl_run.id)
    return _crawl_started_response(request, label, crawl_run, error=error)


@login_required
@require_POST
def run_source(request, pk):
    source = get_object_or_404(JobSource, pk=pk)
    crawl_run = _start_crawl_run(source.name, total_sources=1)
    error = _enqueue_crawl_task(crawl_run.id, source_ids=[source.id])
    return _crawl_started_response(request, source.name, crawl_run, error=error)


@login_required
@require_POST
def copy_source(request, pk):
    if not request.user.is_staff:
        raise PermissionDenied
    source = get_object_or_404(JobSource, pk=pk)
    copied_source = JobSource.objects.create(
        name=_next_source_copy_name(source.name),
        resource=source.resource,
        base_url=source.base_url,
        enabled=source.enabled,
        crawl_interval_minutes=source.crawl_interval_minutes,
        crawl_config=deepcopy(source.crawl_config or {}),
        filter_config=deepcopy(source.filter_config or {}),
        notes=source.notes,
    )
    MonitoringService.log_event(
        step_name="source_copy",
        status=PipelineLog.StatusChoices.SUCCESS,
        severity=PipelineLog.SeverityChoices.INFO,
        message=f"Copied JobSource {source.name}.",
        service_name=__name__,
        source=copied_source,
        metadata={
            "original_source_id": source.id,
            "copied_source_id": copied_source.id,
        },
    )

    payload = {
        "success": True,
        "source_id": copied_source.id,
        "name": copied_source.name,
        "detail_url": reverse("source-detail", args=[copied_source.id]),
        "edit_url": reverse("source-update", args=[copied_source.id]),
    }
    if _wants_json(request):
        return JsonResponse(payload, status=201)

    messages.success(
        request,
        f'Copied "{source.name}" to "{copied_source.name}".',
    )
    return redirect("source-list")


@login_required
def crawl_run_status(request, pk):
    try:
        payload = MonitoringService.run_status(crawl_run_id=pk, recent_limit=30)
    except CrawlRun.DoesNotExist:
        return JsonResponse({"detail": "Crawl run not found."}, status=404)
    return JsonResponse(payload)


@login_required
@require_POST
def abort_crawl_run(request, pk):
    crawl_run = get_object_or_404(CrawlRun, pk=pk)
    terminal_statuses = {
        CrawlRun.StatusChoices.SUCCESS,
        CrawlRun.StatusChoices.FAILED,
        CrawlRun.StatusChoices.ABORTED,
    }
    changed = crawl_run.status not in terminal_statuses
    if changed:
        crawl_run.status = CrawlRun.StatusChoices.ABORTED
        crawl_run.finished_at = timezone.now()
        crawl_run.current_source = ""
        crawl_run.save(
            update_fields=["status", "finished_at", "current_source"],
        )

    MonitoringService.log_event(
        step_name="crawl_run",
        status=PipelineLog.StatusChoices.FAILED,
        severity=PipelineLog.SeverityChoices.WARNING,
        message=(
            "Crawl run abort requested."
            if changed
            else "Crawl run abort requested after it already finished."
        ),
        service_name=__name__,
        crawl_run=crawl_run,
        metadata={"changed": changed, "status": crawl_run.status},
    )

    payload = {
        "success": True,
        "crawl_run_id": crawl_run.id,
        "status": crawl_run.status,
        "message": "Abort requested." if changed else "Crawl run already finished.",
    }
    if _wants_json(request):
        return JsonResponse(payload)

    if changed:
        messages.warning(request, "Crawl run abort requested.")
    else:
        messages.info(request, "Crawl run was already finished.")
    return redirect(
        f"{reverse('monitoring-dashboard')}?crawl_run_id={crawl_run.id}"
        "#recent-pipeline-logs"
    )


def _start_crawl_run(label, total_sources=0):
    crawl_run = CrawlRun.objects.create(
        status=CrawlRun.StatusChoices.PENDING,
        total_sources=total_sources,
    )
    MonitoringService.log_event(
        step_name="crawl_run",
        status="INFO",
        message=f"{label} crawl queued.",
        service_name=__name__,
        crawl_run=crawl_run,
        metadata={"label": label},
    )
    return crawl_run


def _enqueue_crawl_task(crawl_run_id, source_ids=None):
    try:
        from apps.imports.tasks import crawl_all_sources
    except ModuleNotFoundError as exc:
        if exc.name != "celery":
            raise
        error = (
            "Celery is not installed in this runtime. Rebuild the Docker image "
            "or install project requirements."
        )
        _mark_crawl_enqueue_failed(crawl_run_id, error)
        return error

    try:
        crawl_all_sources.delay(crawl_run_id=crawl_run_id, source_ids=source_ids)
    except Exception as exc:
        _mark_crawl_enqueue_failed(crawl_run_id, str(exc))
        return str(exc)
    return ""


def _mark_crawl_enqueue_failed(crawl_run_id, error):
    CrawlRun.objects.filter(id=crawl_run_id).update(
        status=CrawlRun.StatusChoices.FAILED,
        errors=1,
    )
    MonitoringService.log_event(
        step_name="celery_task",
        status="FAILED",
        severity="ERROR",
        message="Crawl task could not be queued.",
        service_name=__name__,
        crawl_run_id=crawl_run_id,
        metadata={"error": error},
        error_text=error,
    )


def _crawl_started_response(request, label, crawl_run, error=""):
    status_url = reverse("source-run-status", args=[crawl_run.id])
    monitoring_url = (
        f"{reverse('monitoring-dashboard')}?crawl_run_id={crawl_run.id}"
        "#recent-pipeline-logs"
    )
    success = not error
    payload = {
        "success": success,
        "crawl_run_id": crawl_run.id,
        "label": label,
        "status_url": status_url,
        "monitoring_url": monitoring_url,
        "message": (
            f"{label} crawl started."
            if success
            else f"{label} crawl could not be started."
        ),
        "error": error,
    }

    if _wants_json(request):
        return JsonResponse(payload, status=202 if success else 503)

    if success:
        messages.info(
            request,
            format_html(
                '{} crawl started. <a class="alert-link" href="{}">View monitoring logs</a>.',
                label,
                monitoring_url,
            ),
        )
    else:
        messages.error(request, f"{label} crawl could not be started: {error}")

    url = f"{reverse('source-list')}?crawl_run_id={crawl_run.id}"
    return redirect(url)


def _wants_json(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def _next_source_copy_name(name):
    base_name = f"{name} copy"
    if not JobSource.objects.filter(name=base_name).exists():
        return base_name

    index = 2
    while JobSource.objects.filter(name=f"{base_name} {index}").exists():
        index += 1
    return f"{base_name} {index}"


def _add_crawl_message(request, label, summary):
    filtered_count = sum(source.get("jobs_filtered", 0) for source in summary["sources"])
    skill_failures = summary.get("skill_pipeline_failures", 0)
    errors = summary["errors"]
    message = format_html(
        "{} crawl finished. Processed: {}, Created: {}, Updated: {}, Closed: {}, "
        "Filtered: {}, Skill jobs: {}, Skills attached: {}, Skill failures: {}, "
        "Errors: {}.{}",
        label,
        summary["sources_processed"],
        summary["jobs_created"],
        summary["jobs_updated"],
        summary["jobs_closed"],
        filtered_count,
        summary.get("skill_pipeline_jobs_processed", 0),
        summary.get("skills_attached", 0),
        skill_failures,
        errors,
        _monitoring_link(summary) if errors or skill_failures else "",
    )
    if summary.get("success"):
        messages.success(request, message)
    else:
        messages.warning(request, message)


def _monitoring_link(summary):
    crawl_run_id = summary.get("crawl_run_id")
    url = reverse("monitoring-dashboard")
    if crawl_run_id:
        url = f"{url}?crawl_run_id={crawl_run_id}#recent-pipeline-logs"
    else:
        url = f"{url}#recent-pipeline-logs"
    return format_html(
        ' <a class="alert-link" href="{}">View monitoring logs</a>.',
        url,
    )


class JobSourceListView(LoginRequiredMixin, ListView):
    model = JobSource
    template_name = "imports/job_source_list.html"
    context_object_name = "sources"

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get("q", "").strip()
        if not query:
            return queryset
        return filter_job_sources_for_search(queryset, query)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "").strip()
        active_crawl_run_id = self.request.GET.get("crawl_run_id") or ""
        context["active_crawl_run_id"] = active_crawl_run_id
        context["crawl_status_url_template"] = reverse(
            "source-run-status",
            args=[0],
        )
        return context


class JobSourceDetailView(LoginRequiredMixin, DetailView):
    model = JobSource
    template_name = "imports/job_source_detail.html"
    context_object_name = "source"


class JobSourceHelpView(LoginRequiredMixin, TemplateView):
    template_name = "imports/job_source_help.html"


class MonitoringHelpView(LoginRequiredMixin, TemplateView):
    template_name = "imports/monitoring_help.html"


class StaffRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class JobSourceFormUserMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class JobSourceCreateView(
    LoginRequiredMixin,
    StaffRequiredMixin,
    JobSourceFormUserMixin,
    CreateView,
):
    model = JobSource
    form_class = JobSourceForm
    template_name = "imports/job_source_form.html"
    success_url = reverse_lazy("source-list")


class JobSourceUpdateView(LoginRequiredMixin, JobSourceFormUserMixin, UpdateView):
    model = JobSource
    form_class = JobSourceForm
    template_name = "imports/job_source_form.html"
    success_url = reverse_lazy("source-list")


class JobSourceDeleteView(LoginRequiredMixin, StaffRequiredMixin, DeleteView):
    model = JobSource
    template_name = "imports/job_source_confirm_delete.html"
    success_url = reverse_lazy("source-list")
