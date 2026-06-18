from copy import deepcopy

from django.contrib import messages
from django.http import JsonResponse
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

from .forms import JobSourceForm
from .models import CrawlRun, JobSource, PipelineLog
from .services import MonitoringService


def job_url_import(request):
    return JobSourceListView.as_view()(request)


def monitoring_dashboard(request):
    crawl_run_id = request.GET.get("crawl_run_id") or request.GET.get("run")
    return render(
        request,
        "imports/monitoring_dashboard.html",
        MonitoringService.dashboard_summary(crawl_run_id=crawl_run_id),
    )


@require_POST
def run_all_sources(request):
    label = "All enabled job sources"
    crawl_run = _start_crawl_run(label)
    error = _enqueue_crawl_task(crawl_run.id)
    return _crawl_started_response(request, label, crawl_run, error=error)


@require_POST
def run_source(request, pk):
    source = get_object_or_404(JobSource, pk=pk)
    crawl_run = _start_crawl_run(source.name, total_sources=1)
    error = _enqueue_crawl_task(crawl_run.id, source_ids=[source.id])
    return _crawl_started_response(request, source.name, crawl_run, error=error)


@require_POST
def copy_source(request, pk):
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


def crawl_run_status(request, pk):
    try:
        payload = MonitoringService.run_status(crawl_run_id=pk, recent_limit=30)
    except CrawlRun.DoesNotExist:
        return JsonResponse({"detail": "Crawl run not found."}, status=404)
    return JsonResponse(payload)


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


class JobSourceListView(ListView):
    model = JobSource
    template_name = "imports/job_source_list.html"
    context_object_name = "sources"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_crawl_run_id = self.request.GET.get("crawl_run_id") or ""
        context["active_crawl_run_id"] = active_crawl_run_id
        context["crawl_status_url_template"] = reverse(
            "source-run-status",
            args=[0],
        )
        return context


class JobSourceDetailView(DetailView):
    model = JobSource
    template_name = "imports/job_source_detail.html"
    context_object_name = "source"


class JobSourceHelpView(TemplateView):
    template_name = "imports/job_source_help.html"


class MonitoringHelpView(TemplateView):
    template_name = "imports/monitoring_help.html"


class JobSourceCreateView(CreateView):
    model = JobSource
    form_class = JobSourceForm
    template_name = "imports/job_source_form.html"
    success_url = reverse_lazy("source-list")


class JobSourceUpdateView(UpdateView):
    model = JobSource
    form_class = JobSourceForm
    template_name = "imports/job_source_form.html"
    success_url = reverse_lazy("source-list")


class JobSourceDeleteView(DeleteView):
    model = JobSource
    template_name = "imports/job_source_confirm_delete.html"
    success_url = reverse_lazy("source-list")
