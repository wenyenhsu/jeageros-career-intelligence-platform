from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from .models import Company
from .forms import CompanyForm
from .search import filter_companies_for_search
from apps.imports.services import CompanyJobRefreshService


@login_required
@require_POST
def company_sync_jobs(request, pk):
    company = get_object_or_404(Company, pk=pk)
    result = CompanyJobRefreshService.queue(company)

    if result.queued_jobs:
        add_message = messages.warning if result.failed_jobs else messages.success
        add_message(
            request,
            (
                f"Queued {result.queued_jobs} job refresh task(s). "
                f"Skipped {result.skipped_without_url} without a source URL, "
                f"{result.skipped_unsupported_url} unsupported, "
                f"and {result.skipped_archived} archived. "
                f"Failed to queue {result.failed_jobs}."
            ),
        )
    elif result.failed_jobs:
        messages.error(
            request,
            f"No jobs were queued; {result.failed_jobs} refresh task(s) failed to queue.",
        )
    else:
        messages.info(
            request,
            "No refreshable jobs found. Add a supported source URL to a non-archived job.",
        )
    return redirect("company-detail", pk=company.pk)


class CompanyListView(LoginRequiredMixin, ListView):
    model = Company
    template_name = "companies/company_list.html"
    context_object_name = "companies"

    def get_queryset(self):
        queryset = Company.objects.all()
        query = self.request.GET.get("q", "").strip()
        if not query:
            return queryset
        return filter_companies_for_search(queryset, query)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "").strip()
        return context


class CompanyDetailView(LoginRequiredMixin, DetailView):
    model = Company
    template_name = "companies/company_detail.html"
    context_object_name = "company"


class CompanyCreateView(LoginRequiredMixin, CreateView):
    model = Company
    form_class = CompanyForm
    template_name = "companies/company_form.html"
    success_url = reverse_lazy("company-list")


class CompanyUpdateView(LoginRequiredMixin, UpdateView):
    model = Company
    form_class = CompanyForm
    template_name = "companies/company_form.html"
    success_url = reverse_lazy("company-list")


class CompanyDeleteView(LoginRequiredMixin, DeleteView):
    model = Company
    template_name = "companies/company_confirm_delete.html"
    success_url = reverse_lazy("company-list")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        return super().post(request, *args, **kwargs)
