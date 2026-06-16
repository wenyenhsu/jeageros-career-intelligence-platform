from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from .forms import JobSourceForm
from .models import JobSource
from .services import CrawlService, MonitoringService


def job_url_import(request):
    return JobSourceListView.as_view()(request)


def monitoring_dashboard(request):
    return render(
        request,
        "imports/monitoring_dashboard.html",
        MonitoringService.dashboard_summary(),
    )


@require_POST
def run_all_sources(request):
    summary = CrawlService.crawl_enabled_sources()
    _add_crawl_message(request, "All enabled job sources", summary)
    return redirect(reverse("source-list"))


@require_POST
def run_source(request, pk):
    source = get_object_or_404(JobSource, pk=pk)
    summary = CrawlService.crawl_all_sources([source])
    _add_crawl_message(request, source.name, summary)
    return redirect(reverse("source-list"))


def _add_crawl_message(request, label, summary):
    filtered_count = sum(source.get("jobs_filtered", 0) for source in summary["sources"])
    message = (
        f"{label} crawl finished. "
        f"Processed: {summary['sources_processed']}, "
        f"Created: {summary['jobs_created']}, "
        f"Updated: {summary['jobs_updated']}, "
        f"Closed: {summary['jobs_closed']}, "
        f"Filtered: {filtered_count}, "
        f"Skill jobs: {summary.get('skill_pipeline_jobs_processed', 0)}, "
        f"Skills attached: {summary.get('skills_attached', 0)}, "
        f"Skill failures: {summary.get('skill_pipeline_failures', 0)}, "
        f"Errors: {summary['errors']}."
    )
    if summary.get("success"):
        messages.success(request, message)
    else:
        messages.warning(request, message)


class JobSourceListView(ListView):
    model = JobSource
    template_name = "imports/job_source_list.html"
    context_object_name = "sources"


class JobSourceDetailView(DetailView):
    model = JobSource
    template_name = "imports/job_source_detail.html"
    context_object_name = "source"


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
